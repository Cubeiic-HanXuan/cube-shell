"""
Hermes Agent Cron 定时任务管理模块
提供任务列表、创建/编辑/删除、暂停/恢复、立即执行、输出日志查看等功能。
"""

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                                QLabel, QPushButton, QTableWidget,
                                QTableWidgetItem, QHeaderView, QDialog,
                                QFormLayout, QLineEdit, QTextEdit,
                                QComboBox, QMessageBox, QGroupBox,
                                QSplitter, QTextBrowser, QTabWidget)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor
import json

from function.util import logger


class CronWorker(QThread):
    """后台执行 Cron 相关操作，避免阻塞 UI"""
    jobs_loaded = Signal(list)        # jobs 列表
    command_done = Signal(str, str)   # (description, output)
    output_loaded = Signal(str)       # 日志内容
    error = Signal(str)

    def __init__(self, backend, action, **kwargs):
        super().__init__()
        self._backend = backend
        self._action = action
        self._kwargs = kwargs

    def run(self):
        try:
            if self._action == "load_jobs":
                self._do_load_jobs()
            elif self._action == "create_job":
                self._do_create_job()
            elif self._action == "delete_job":
                self._do_delete_job()
            elif self._action == "pause_job":
                self._do_pause_resume("pause")
            elif self._action == "resume_job":
                self._do_pause_resume("resume")
            elif self._action == "run_job":
                self._do_run_job()
            elif self._action == "load_output":
                self._do_load_output()
            elif self._action == "clear_output":
                self._do_clear_output()
        except Exception as e:
            logger.error(f"CronWorker 执行失败 [{self._action}]: {e}")
            self.error.emit(str(e))

    def _do_load_jobs(self):
        hermes_home = self._backend.get_hermes_home()
        all_jobs = []

        # 扫描所有 profile 目录下的 cron/jobs.json
        profiles_dir = f"{hermes_home}/profiles"
        if self._backend.file_exists(profiles_dir):
            profiles = self._backend.list_dir(profiles_dir)
            for profile_name in (profiles or []):
                jobs_path = f"{profiles_dir}/{profile_name}/cron/jobs.json"
                if self._backend.file_exists(jobs_path):
                    content = self._backend.read_file(jobs_path)
                    jobs = self._parse_jobs_file(content, profile_name)
                    all_jobs.extend(jobs)

        # 也检查顶层 cron/jobs.json（default profile 可能存此处）
        default_jobs_path = f"{hermes_home}/cron/jobs.json"
        if self._backend.file_exists(default_jobs_path):
            content = self._backend.read_file(default_jobs_path)
            jobs = self._parse_jobs_file(content, "default")
            all_jobs.extend(jobs)

        self.jobs_loaded.emit(all_jobs)

    def _parse_jobs_file(self, content: str, profile_name: str) -> list:
        """解析 jobs.json 文件内容，兼容 {jobs:[...]} 和 [...] 两种格式"""
        if not content or not content.strip():
            return []
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            return []
        # 兼容两种格式
        if isinstance(data, dict):
            jobs = data.get("jobs", [])
        elif isinstance(data, list):
            jobs = data
        else:
            return []
        # 标记来源 profile
        for job in jobs:
            if "profile_source" not in job:
                job["profile_source"] = profile_name
        return jobs

    def _do_create_job(self):
        schedule = self._kwargs.get("schedule", "")
        prompt = self._kwargs.get("prompt", "")
        name = self._kwargs.get("name", "")
        skills = self._kwargs.get("skills", "")
        deliver_to = self._kwargs.get("deliver_to", "none")

        args = ["cron", "create", schedule, prompt]
        if name:
            args += ["--name", name]
        if skills:
            args += ["--skills", skills]
        if deliver_to and deliver_to != "none":
            args += ["--deliver", deliver_to]

        output = self._backend.exec_cli(args)
        self.command_done.emit(self.tr("创建任务"), output)

    def _do_delete_job(self):
        job_id = self._kwargs.get("job_id", "")
        profile = self._kwargs.get("profile", "")
        args = []
        if profile:
            args += ["-p", profile]
        args += ["cron", "remove", job_id]
        output = self._backend.exec_cli(args)
        self.command_done.emit(self.tr("删除任务"), output)

    def _do_pause_resume(self, action):
        job_id = self._kwargs.get("job_id", "")
        profile = self._kwargs.get("profile", "")
        args = []
        if profile:
            args += ["-p", profile]
        args += ["cron", action, job_id]
        output = self._backend.exec_cli(args)
        desc = self.tr("暂停任务") if action == "pause" else self.tr("恢复任务")
        self.command_done.emit(desc, output)

    def _do_run_job(self):
        job_id = self._kwargs.get("job_id", "")
        profile = self._kwargs.get("profile", "")
        # 1. 标记任务为立即触发
        args = []
        if profile:
            args += ["-p", profile]
        args += ["cron", "run", job_id]
        output = self._backend.exec_cli(args)
        # 2. 强制执行一次 tick，确保任务立即运行（不等 gateway 60s 轮询）
        tick_args = []
        if profile:
            tick_args += ["-p", profile]
        tick_args += ["cron", "tick", "--accept-hooks"]
        self._backend.exec_cli(tick_args, timeout=120)
        self.command_done.emit(self.tr("立即执行"), output)

    def _do_load_output(self):
        job_id = self._kwargs.get("job_id", "")
        profile = self._kwargs.get("profile", "")
        hermes_home = self._backend.get_hermes_home()

        # 优先在 profile 目录下查找输出
        if profile:
            output_dir = f"{hermes_home}/profiles/{profile}/cron/output/{job_id}"
        else:
            output_dir = f"{hermes_home}/cron/output/{job_id}"

        if not self._backend.file_exists(output_dir):
            # fallback: 尝试顶层目录
            output_dir = f"{hermes_home}/cron/output/{job_id}"
            if not self._backend.file_exists(output_dir):
                self.output_loaded.emit(self.tr("暂无执行日志"))
                return

        files = self._backend.list_dir(output_dir)
        if not files:
            self.output_loaded.emit(self.tr("暂无执行日志"))
            return

        # 按文件名排序取最近的日志（假设文件名包含时间戳）
        files.sort(reverse=True)
        recent_files = files[:5]

        log_content = ""
        for fname in recent_files:
            file_path = f"{output_dir}/{fname}"
            content = self._backend.read_file(file_path)
            log_content += f"━━━ {fname} ━━━\n{content}\n\n"

        self.output_loaded.emit(log_content if log_content else self.tr("暂无执行日志"))

    def _do_clear_output(self):
        """清除指定任务的所有执行日志"""
        job_id = self._kwargs.get("job_id", "")
        profile = self._kwargs.get("profile", "")
        hermes_home = self._backend.get_hermes_home()

        if profile:
            output_dir = f"{hermes_home}/profiles/{profile}/cron/output/{job_id}"
        else:
            output_dir = f"{hermes_home}/cron/output/{job_id}"

        if not self._backend.file_exists(output_dir):
            self.command_done.emit(self.tr("清除日志"), self.tr("无日志可清除"))
            return

        files = self._backend.list_dir(output_dir)
        count = 0
        for fname in (files or []):
            file_path = f"{output_dir}/{fname}"
            try:
                self._backend.delete_file(file_path)
                count += 1
            except Exception:
                pass
        self.command_done.emit(self.tr("清除日志"),
                              self.tr("已清除 {} 条日志").format(count))


class CronJobDialog(QDialog):
    """Cron 任务创建/编辑对话框"""

    def __init__(self, parent=None, job_data=None):
        super().__init__(parent)
        self._job_data = job_data
        self._is_edit = job_data is not None
        self.setWindowTitle(self.tr("编辑定时任务") if self._is_edit else self.tr("新建定时任务"))
        self.setMinimumWidth(480)
        self._init_ui()
        if self._is_edit:
            self._populate_data()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        form = QFormLayout()
        form.setSpacing(8)

        # 任务名称
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText(self.tr("例如: Daily Summary"))
        form.addRow(self.tr("任务名称:"), self._name_edit)

        # Cron 表达式
        self._schedule_edit = QLineEdit()
        self._schedule_edit.setPlaceholderText("*/5 * * * *")
        form.addRow(self.tr("计划表达式:"), self._schedule_edit)

        # Prompt
        self._prompt_edit = QTextEdit()
        self._prompt_edit.setPlaceholderText(self.tr("Agent 执行的 prompt"))
        self._prompt_edit.setMaximumHeight(120)
        form.addRow(self.tr("Prompt:"), self._prompt_edit)

        # Skills
        self._skills_edit = QLineEdit()
        self._skills_edit.setPlaceholderText(self.tr("可用 skills，逗号分隔，例如: web_search,file_read"))
        form.addRow(self.tr("Skills:"), self._skills_edit)

        # 投递目标
        self._deliver_combo = QComboBox()
        self._deliver_combo.addItems(["none", "telegram", "discord", "slack", "飞书"])
        form.addRow(self.tr("投递目标:"), self._deliver_combo)

        layout.addLayout(form)

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = QPushButton(self.tr("取消"))
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        ok_btn = QPushButton(self.tr("确定"))
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._on_accept)
        btn_layout.addWidget(ok_btn)
        layout.addLayout(btn_layout)

    def _populate_data(self):
        """编辑模式下填充已有数据"""
        if not self._job_data:
            return
        self._name_edit.setText(self._job_data.get("name", ""))
        # schedule 可能是对象 {"expr": "...", "display": "..."} 或字符串
        schedule = self._job_data.get("schedule", "")
        if isinstance(schedule, dict):
            self._schedule_edit.setText(schedule.get("display", schedule.get("expr", "")))
        else:
            self._schedule_edit.setText(str(schedule))
        self._prompt_edit.setPlainText(self._job_data.get("prompt", ""))
        skills = self._job_data.get("skills", [])
        if isinstance(skills, list):
            self._skills_edit.setText(", ".join(skills))
        else:
            self._skills_edit.setText(str(skills))
        deliver = self._job_data.get("deliver", self._job_data.get("deliver_to", "none"))
        idx = self._deliver_combo.findText(str(deliver))
        if idx >= 0:
            self._deliver_combo.setCurrentIndex(idx)

    def _on_accept(self):
        """确认按钮校验"""
        if not self._schedule_edit.text().strip():
            QMessageBox.warning(self, self.tr("警告"), self.tr("计划表达式不能为空"))
            return
        if not self._prompt_edit.toPlainText().strip():
            QMessageBox.warning(self, self.tr("警告"), self.tr("Prompt 不能为空"))
            return
        self.accept()

    def get_data(self) -> dict:
        """获取表单数据"""
        return {
            "name": self._name_edit.text().strip(),
            "schedule": self._schedule_edit.text().strip(),
            "prompt": self._prompt_edit.toPlainText().strip(),
            "skills": self._skills_edit.text().strip(),
            "deliver_to": self._deliver_combo.currentText(),
        }


class CronWidget(QWidget):
    """Hermes Agent Cron 定时任务管理模块"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._backend = None
        self._jobs = []
        self._worker = None
        self._selected_job_id = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(0)

        # 使用 QSplitter 上下分割
        splitter = QSplitter(Qt.Orientation.Vertical)
        layout.addWidget(splitter)

        # ========== 上方：任务列表区域 ==========
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)

        # 工具栏
        toolbar = QHBoxLayout()
        self._create_btn = QPushButton(self.tr("新建任务"))
        self._create_btn.clicked.connect(self._on_create_job)
        toolbar.addWidget(self._create_btn)

        self._refresh_btn = QPushButton(self.tr("刷新列表"))
        self._refresh_btn.clicked.connect(self._on_refresh)
        toolbar.addWidget(self._refresh_btn)

        self._run_btn = QPushButton(self.tr("立即执行"))
        self._run_btn.clicked.connect(self._on_run_job)
        toolbar.addWidget(self._run_btn)

        self._pause_btn = QPushButton(self.tr("暂停/恢复"))
        self._pause_btn.clicked.connect(self._on_pause_resume)
        toolbar.addWidget(self._pause_btn)

        self._delete_btn = QPushButton(self.tr("删除"))
        self._delete_btn.clicked.connect(self._on_delete_job)
        toolbar.addWidget(self._delete_btn)

        toolbar.addStretch()
        top_layout.addLayout(toolbar)

        # 任务表格
        self._table = QTableWidget()
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels([
            self.tr("名称"), self.tr("计划表达式"), self.tr("状态"),
            self.tr("上次运行"), self.tr("投递目标"), self.tr("Prompt")
        ])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.currentCellChanged.connect(self._on_row_changed)
        self._table.doubleClicked.connect(self._on_row_double_clicked)
        top_layout.addWidget(self._table)

        # 空状态提示
        self._empty_label = QLabel(self.tr("暂无定时任务"))
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet("color: #888; font-size: 14px; padding: 20px;")
        self._empty_label.setVisible(False)
        top_layout.addWidget(self._empty_label)

        splitter.addWidget(top_widget)

        # ========== 下方：任务详情和输出 ==========
        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)

        self._detail_tabs = QTabWidget()

        # 任务详情 Tab
        self._detail_browser = QTextBrowser()
        self._detail_browser.setPlaceholderText(self.tr("选择一个任务查看详情"))
        self._detail_tabs.addTab(self._detail_browser, self.tr("任务详情"))

        # 执行日志 Tab（含清除按钮）
        log_widget = QWidget()
        log_layout = QVBoxLayout(log_widget)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(4)

        log_toolbar = QHBoxLayout()
        log_toolbar.addStretch()
        self._clear_log_btn = QPushButton(self.tr("清除日志"))
        self._clear_log_btn.clicked.connect(self._on_clear_log)
        log_toolbar.addWidget(self._clear_log_btn)
        log_layout.addLayout(log_toolbar)

        self._log_browser = QTextBrowser()
        self._log_browser.setPlaceholderText(self.tr("选择一个任务查看执行日志"))
        log_layout.addWidget(self._log_browser)

        self._detail_tabs.addTab(log_widget, self.tr("执行日志"))

        bottom_layout.addWidget(self._detail_tabs)
        splitter.addWidget(bottom_widget)

        # 设置 splitter 初始比例
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

    def set_backend(self, backend):
        """设置后端引用（不触发加载）"""
        self._backend = backend

    def refresh(self):
        """当 Tab 被选中时调用，触发数据加载"""
        self._load_jobs()

    def _load_jobs(self):
        """后台加载任务列表"""
        if not self._backend:
            return
        if self._worker and self._worker.isRunning():
            return
        self._worker = CronWorker(self._backend, "load_jobs")
        self._worker.jobs_loaded.connect(self._on_jobs_loaded)
        self._worker.error.connect(self._on_worker_error)
        self._worker.start()

    def _on_jobs_loaded(self, jobs):
        """任务列表加载完成"""
        self._jobs = jobs
        self._populate_table()

    def _populate_table(self):
        """填充任务表格"""
        self._table.setRowCount(0)

        if not self._jobs:
            self._table.setVisible(False)
            self._empty_label.setVisible(True)
            return

        self._table.setVisible(True)
        self._empty_label.setVisible(False)
        self._table.setRowCount(len(self._jobs))

        for row, job in enumerate(self._jobs):
            # 名称（附加来源 profile）
            name = job.get("name", self.tr("未命名"))
            profile_source = job.get("profile_source", "")
            if profile_source:
                name = f"{name}  [{profile_source}]"
            name_item = QTableWidgetItem(name)
            self._table.setItem(row, 0, name_item)

            # 计划表达式（兼容 schedule 为对象或字符串）
            schedule = job.get("schedule", "")
            if isinstance(schedule, dict):
                schedule_text = schedule.get("display", schedule.get("expr", ""))
            else:
                schedule_text = str(schedule)
            schedule_item = QTableWidgetItem(schedule_text)
            self._table.setItem(row, 1, schedule_item)

            # 状态（兼容 state/status/enabled 字段）
            status = job.get("state", job.get("status", "unknown"))
            if not job.get("enabled", True):
                status = "paused"
            status_item = QTableWidgetItem(status)
            if status in ("active", "scheduled"):
                status_item.setForeground(QColor("#2ecc71"))
            elif status == "paused":
                status_item.setForeground(QColor("#f39c12"))
            elif status in ("error", "failed"):
                status_item.setForeground(QColor("#e74c3c"))
            self._table.setItem(row, 2, status_item)

            # 上次运行（兼容 last_run_at/last_run）
            last_run = job.get("last_run_at", job.get("last_run", None))
            last_run_text = last_run if last_run else self.tr("从未")
            last_run_item = QTableWidgetItem(last_run_text)
            self._table.setItem(row, 3, last_run_item)

            # 投递目标（兼容 deliver/deliver_to）
            deliver = job.get("deliver", job.get("deliver_to", "none"))
            deliver_item = QTableWidgetItem(str(deliver))
            self._table.setItem(row, 4, deliver_item)

            # Prompt（截断显示）
            prompt = job.get("prompt", "")
            truncated = prompt[:50] + "..." if len(prompt) > 50 else prompt
            prompt_item = QTableWidgetItem(truncated)
            prompt_item.setToolTip(prompt)
            self._table.setItem(row, 5, prompt_item)

    def _get_selected_job(self):
        """获取当前选中的任务"""
        row = self._table.currentRow()
        if row < 0 or row >= len(self._jobs):
            return None, -1
        return self._jobs[row], row

    def _on_row_changed(self, current_row, current_col, prev_row, prev_col):
        """表格行选中变化时显示详情"""
        if current_row < 0 or current_row >= len(self._jobs):
            return
        job = self._jobs[current_row]
        self._selected_job_id = job.get("id")
        self._show_job_detail(job)
        self._load_job_output(job.get("id", ""), job.get("profile_source", ""))

    def _on_row_double_clicked(self, index):
        """双击行编辑任务"""
        job, row = self._get_selected_job()
        if job:
            self._edit_job(job)

    def _show_job_detail(self, job):
        """显示任务详情（JSON 格式化）"""
        formatted = json.dumps(job, indent=2, ensure_ascii=False)
        self._detail_browser.setPlainText(formatted)

    def _load_job_output(self, job_id, profile=""):
        """后台加载任务执行日志"""
        if not self._backend or not job_id:
            self._log_browser.setPlainText(self.tr("暂无执行日志"))
            return
        if self._worker and self._worker.isRunning():
            return
        self._worker = CronWorker(self._backend, "load_output", job_id=job_id, profile=profile)
        self._worker.output_loaded.connect(self._on_output_loaded)
        self._worker.error.connect(self._on_worker_error)
        self._worker.start()

    def _on_output_loaded(self, content):
        """日志加载完成"""
        self._log_browser.setPlainText(content)

    def _on_clear_log(self):
        """清除当前选中任务的执行日志"""
        job, row = self._get_selected_job()
        if not job:
            QMessageBox.warning(self, self.tr("警告"), self.tr("请先选择一个任务"))
            return
        job_id = job.get("id", "")
        job_name = job.get("name", job_id)
        reply = QMessageBox.question(
            self, self.tr("确认清除"),
            self.tr("确定要清除任务「{}」的所有执行日志吗？").format(job_name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            profile = job.get("profile_source", "")
            self._exec_command("clear_output", self.tr("清除日志"),
                              job_id=job_id, profile=profile)

    def _on_create_job(self):
        """新建任务按钮点击"""
        dialog = CronJobDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.get_data()
            self._exec_command("create_job", self.tr("创建任务"), **data)

    def _edit_job(self, job):
        """编辑任务"""
        dialog = CronJobDialog(self, job_data=job)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.get_data()
            # 先删除再创建（hermes CLI 通常不支持 update）
            job_id = job.get("id", "")
            if job_id:
                self._backend.exec_cli(["cron", "remove", job_id])
            self._exec_command("create_job", self.tr("更新任务"), **data)

    def _on_delete_job(self):
        """删除按钮点击"""
        job, row = self._get_selected_job()
        if not job:
            QMessageBox.warning(self, self.tr("警告"), self.tr("请先选择一个任务"))
            return
        job_id = job.get("id", "")
        job_name = job.get("name", job_id)
        profile = job.get("profile_source", "")
        reply = QMessageBox.question(
            self, self.tr("确认删除"),
            self.tr("确定要删除任务「{}」吗？").format(job_name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._exec_command("delete_job", self.tr("删除任务"), job_id=job_id, profile=profile)

    def _on_pause_resume(self):
        """暂停/恢复按钮点击"""
        job, row = self._get_selected_job()
        if not job:
            QMessageBox.warning(self, self.tr("警告"), self.tr("请先选择一个任务"))
            return
        job_id = job.get("id", "")
        profile = job.get("profile_source", "")
        status = job.get("state", job.get("status", ""))
        if status == "paused" or not job.get("enabled", True):
            self._exec_command("resume_job", self.tr("恢复任务"), job_id=job_id, profile=profile)
        else:
            self._exec_command("pause_job", self.tr("暂停任务"), job_id=job_id, profile=profile)

    def _on_run_job(self):
        """立即执行按钮点击"""
        job, row = self._get_selected_job()
        if not job:
            QMessageBox.warning(self, self.tr("警告"), self.tr("请先选择一个任务"))
            return
        job_id = job.get("id", "")
        profile = job.get("profile_source", "")
        self._exec_command("run_job", self.tr("立即执行"), job_id=job_id, profile=profile)

    def _on_refresh(self):
        """刷新列表按钮点击"""
        self._load_jobs()

    def _exec_command(self, action, description, **kwargs):
        """执行后台命令"""
        if not self._backend:
            QMessageBox.warning(self, self.tr("警告"), self.tr("未连接后端"))
            return
        if self._worker and self._worker.isRunning():
            QMessageBox.information(self, self.tr("提示"), self.tr("请等待当前操作完成"))
            return
        self._worker = CronWorker(self._backend, action, **kwargs)
        self._worker.command_done.connect(self._on_command_done)
        self._worker.error.connect(self._on_worker_error)
        self._worker.start()

    def _on_command_done(self, description, output):
        """命令执行完成"""
        logger.info(f"Cron 操作完成 [{description}]: {output}")
        # 显示操作结果
        QMessageBox.information(self, description, output if output.strip() else self.tr("操作成功"))
        # 刷新列表
        self._load_jobs()

    def _on_worker_error(self, error_msg):
        """Worker 出错"""
        logger.error(f"Cron Worker 错误: {error_msg}")
        QMessageBox.critical(self, self.tr("错误"),
                             self.tr("操作失败: {}").format(error_msg))
