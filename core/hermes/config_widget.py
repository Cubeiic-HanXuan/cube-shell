# -*- coding: utf-8 -*-
"""Hermes Agent 配置管理模块

两个子 Tab：
  - 常用设置：分组结构化表单，覆盖高频字段，仅对改动项调用 `hermes config set`
    （由 Hermes 安全改写文件、保留结构与注释、自动推断类型）。
  - 原始配置：config.yaml / .env 纯文本编辑器兜底全部字段，YAML 保存前做语法校验。
"""

import re

import yaml
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
                                QLabel, QPushButton, QLineEdit, QComboBox,
                                QTableWidget, QTableWidgetItem, QHeaderView,
                                QGroupBox, QCheckBox, QMessageBox, QSpinBox,
                                QTabWidget, QScrollArea, QPlainTextEdit,
                                QInputDialog, QDialog, QDialogButtonBox,
                                QGridLayout, QFrame, QSizePolicy)

from function.util import logger
from core.hermes.config_highlighter import YamlHighlighter, DotenvHighlighter


class ConfigLoader(QThread):
    """后台加载 hermes 配置，避免阻塞 UI"""
    # (config_data, env_data, raw_config, raw_env)
    loaded = Signal(dict, dict, str, str)
    error = Signal(str)

    def __init__(self, backend):
        super().__init__()
        self._backend = backend

    def run(self):
        try:
            hermes_home = self._backend.get_hermes_home()
            config_content = self._backend.read_file(f"{hermes_home}/config.yaml")
            env_content = self._backend.read_file(f"{hermes_home}/.env")
            config_data = yaml.safe_load(config_content) if config_content else {}
            env_data = self._parse_env(env_content)
            self.loaded.emit(
                config_data or {}, env_data,
                config_content or "", env_content or ""
            )
        except Exception as e:
            self.error.emit(str(e))

    @staticmethod
    def _parse_env(content):
        env = {}
        if not content:
            return env
        for line in content.strip().split('\n'):
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                env[key.strip()] = value.strip()
        return env


class SaveWorker(QThread):
    """后台执行配置保存：

    - scalar 改动逐项走 `hermes config set <key.path> <value>`
    - .env 改动就地更新（保留注释与未改动行）后写回文件
    """
    # (ok_keys, failed_keys, env_saved)
    finished = Signal(list, list, bool)
    error = Signal(str)

    def __init__(self, backend, scalar_changes, env_changes, raw_env):
        super().__init__()
        self._backend = backend
        self._scalar_changes = scalar_changes  # [(key_path, value_str)]
        self._env_changes = env_changes        # {KEY: value}
        self._raw_env = raw_env

    def run(self):
        try:
            ok_keys, failed_keys = [], []
            for key_path, value_str in self._scalar_changes:
                output = self._backend.exec_cli(
                    ["config", "set", key_path, value_str]
                ) or ""
                # hermes 成功时输出包含 "✓ Set"，失败/异常则无
                if "Set" in output and "✓" in output:
                    ok_keys.append(key_path)
                else:
                    failed_keys.append(key_path)
                    logger.warning(f"hermes config set {key_path} 失败: {output!r}")

            env_saved = False
            if self._env_changes:
                new_content = ConfigWidget._update_env_content(
                    self._raw_env, self._env_changes
                )
                hermes_home = self._backend.get_hermes_home()
                self._backend.write_file(f"{hermes_home}/.env", new_content)
                env_saved = True

            self.finished.emit(ok_keys, failed_keys, env_saved)
        except Exception as e:
            logger.error(f"保存 hermes 配置失败: {e}")
            self.error.emit(str(e))


class CheckWorker(QThread):
    """后台执行 `hermes config check`"""
    finished = Signal(str)

    def __init__(self, backend):
        super().__init__()
        self._backend = backend

    def run(self):
        output = self._backend.exec_cli(["config", "check"]) or ""
        self.finished.emit(output.strip() or "(无输出)")


class ConfigWidget(QWidget):
    """Hermes Agent 配置管理模块"""

    # reasoning_effort / terminal.backend 的候选项
    _REASONING_CHOICES = ["low", "medium", "high"]
    _TOOL_ENFORCE_CHOICES = ["auto", "required", "none"]
    _TERMINAL_CHOICES = ["local", "docker", "ssh", "modal"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._backend = None
        self._config_data = {}
        self._env_data = {}
        self._raw_config = ""
        self._raw_env = ""
        self._loader = None
        self._save_worker = None
        self._check_worker = None
        # 记录每个表单字段：{widget_key: (key_path, kind, widget, loaded_value)}
        self._fields = {}
        self._init_ui()

    # ─────────────────────────── UI 构建 ───────────────────────────

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_form_tab(), self.tr("常用设置"))
        self._tabs.addTab(self._build_raw_tab(), self.tr("原始配置"))
        layout.addWidget(self._tabs)

    def _build_form_tab(self) -> QWidget:
        """常用设置：分组表单，放进滚动区"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        # 去掉滚动区自带的边框，避免与 tab 边框、GroupBox 边框叠成多层线框
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(12)

        # --- 三个紧凑表单分两列并排，压缩纵向占用，给 API Keys 表格腾空间 ---
        # 左列：模型配置(3行) + Terminal(3行)；右列：Agent 行为(6行)。两列高度平衡。

        # 模型配置
        model_group = QGroupBox(self.tr("模型配置"))
        model_form = QFormLayout(model_group)
        model_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self._add_line(model_form, "model.default", self.tr("模型 (default):"))
        self._add_line(model_form, "model.provider", self.tr("Provider:"))
        self._add_line(model_form, "model.base_url", self.tr("Base URL:"))

        # Agent 行为
        agent_group = QGroupBox(self.tr("Agent 行为"))
        agent_form = QFormLayout(agent_group)
        agent_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self._add_spin(agent_form, "agent.max_turns", self.tr("最大轮数:"), 1, 999)
        self._add_combo(agent_form, "agent.reasoning_effort",
                        self.tr("推理强度:"), self._REASONING_CHOICES, editable=True)
        self._add_combo(agent_form, "agent.tool_use_enforcement",
                        self.tr("工具调用约束:"), self._TOOL_ENFORCE_CHOICES, editable=True)
        self._add_check(agent_form, "agent.verbose", self.tr("详细输出 (verbose):"))
        self._add_check(agent_form, "agent.environment_probe", self.tr("环境探测:"))
        self._add_check(agent_form, "agent.task_completion_guidance",
                        self.tr("任务完成引导:"))

        # Terminal
        term_group = QGroupBox(self.tr("Terminal"))
        term_form = QFormLayout(term_group)
        term_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self._add_combo(term_form, "terminal.backend",
                        self.tr("Backend:"), self._TERMINAL_CHOICES, editable=False)
        self._add_spin(term_form, "terminal.timeout", self.tr("超时(秒):"), 0, 36000)
        self._add_line(term_form, "terminal.cwd", self.tr("工作目录:"))

        # 统一三个表单的标签列宽度：标签同宽 + 列同宽 → 所有输入框/下拉框宽度一致
        self._normalize_label_widths([model_form, agent_form, term_form])

        # 用网格让 Agent 跨两行，其高度自动等于左列(模型+Terminal)之和，
        # 底边对齐、无尾部空隙；同时比嵌套 VBox 少一层结构。
        grid = QGridLayout()
        grid.setSpacing(12)
        grid.addWidget(model_group, 0, 0)       # 左上：模型配置
        grid.addWidget(term_group, 1, 0)        # 左下：Terminal
        grid.addWidget(agent_group, 0, 1, 2, 1)  # 右侧跨 2 行：Agent 行为
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        # Terminal 行可伸展以吸收左列多余空间，使 Agent 底边与其对齐
        grid.setRowStretch(1, 1)
        v.addLayout(grid)

        # --- API Keys (.env) ---
        key_group = QGroupBox(self.tr("API Keys (.env)"))
        key_layout = QVBoxLayout(key_group)
        self._provider_table = QTableWidget()
        self._provider_table.setColumnCount(3)
        self._provider_table.setMinimumHeight(180)
        self._provider_table.setHorizontalHeaderLabels(
            [self.tr("环境变量"), self.tr("值"), self.tr("操作")]
        )
        self._provider_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self._provider_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self._provider_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents)
        self._provider_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._provider_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows)
        self._provider_table.verticalHeader().setVisible(False)
        key_layout.addWidget(self._provider_table)
        add_key_btn = QPushButton(self.tr("新增环境变量"))
        add_key_btn.clicked.connect(self._on_add_env_key)
        key_row = QHBoxLayout()
        key_row.addStretch()
        key_row.addWidget(add_key_btn)
        key_layout.addLayout(key_row)
        # API Keys 占据剩余纵向空间（stretch=1），不再让尾部空白抢占
        v.addWidget(key_group, 1)

        # --- 底部操作按钮 ---
        btn_row = QHBoxLayout()
        self._check_btn = QPushButton(self.tr("配置检查"))
        self._check_btn.clicked.connect(self._on_check)
        btn_row.addWidget(self._check_btn)
        btn_row.addStretch()
        self._refresh_btn = QPushButton(self.tr("刷新配置"))
        self._refresh_btn.clicked.connect(self._on_refresh)
        btn_row.addWidget(self._refresh_btn)
        self._save_btn = QPushButton(self.tr("保存配置"))
        self._save_btn.clicked.connect(self._on_save_form)
        btn_row.addWidget(self._save_btn)
        v.addLayout(btn_row)

        scroll.setWidget(container)
        return scroll

    def _build_raw_tab(self) -> QWidget:
        """原始配置：config.yaml / .env 文本编辑器（带语法高亮）"""
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(8)

        mono = self._mono_font()

        # config.yaml
        v.addWidget(QLabel("config.yaml"))
        self._raw_config_edit = QPlainTextEdit()
        self._raw_config_edit.setPlaceholderText(self.tr("config.yaml 内容..."))
        self._raw_config_edit.setFont(mono)
        self._raw_config_edit.setTabStopDistance(
            self._raw_config_edit.fontMetrics().horizontalAdvance(' ') * 2)
        # 语法高亮器需持有引用，否则会被 GC 回收；配色随 util.THEME 主题
        self._yaml_highlighter = YamlHighlighter(
            self._raw_config_edit.document())
        v.addWidget(self._raw_config_edit, stretch=3)
        yaml_row = QHBoxLayout()
        yaml_row.addStretch()
        save_yaml_btn = QPushButton(self.tr("保存 config.yaml"))
        save_yaml_btn.clicked.connect(self._on_save_raw_yaml)
        yaml_row.addWidget(save_yaml_btn)
        v.addLayout(yaml_row)

        # .env
        v.addWidget(QLabel(".env"))
        self._raw_env_edit = QPlainTextEdit()
        self._raw_env_edit.setPlaceholderText(self.tr(".env 内容..."))
        self._raw_env_edit.setFont(mono)
        self._env_highlighter = DotenvHighlighter(
            self._raw_env_edit.document())
        v.addWidget(self._raw_env_edit, stretch=2)
        env_row = QHBoxLayout()
        env_row.addStretch()
        save_env_btn = QPushButton(self.tr("保存 .env"))
        save_env_btn.clicked.connect(self._on_save_raw_env)
        env_row.addWidget(save_env_btn)
        v.addLayout(env_row)

        return w

    # ── 表单控件添加助手（登记 key_path 供保存时 diff） ──

    def _add_line(self, form, key_path, label):
        w = QLineEdit()
        w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        form.addRow(label, w)
        self._fields[key_path] = {"path": key_path, "kind": "line",
                                  "widget": w, "loaded": None}

    def _add_spin(self, form, key_path, label, lo, hi):
        w = QSpinBox()
        w.setRange(lo, hi)
        w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        form.addRow(label, w)
        self._fields[key_path] = {"path": key_path, "kind": "spin",
                                  "widget": w, "loaded": None}

    def _add_combo(self, form, key_path, label, items, editable=False):
        w = QComboBox()
        w.setEditable(editable)
        w.addItems(items)
        w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        form.addRow(label, w)
        self._fields[key_path] = {"path": key_path, "kind": "combo",
                                  "widget": w, "loaded": None}

    def _add_check(self, form, key_path, label):
        w = QCheckBox()
        form.addRow(label, w)
        self._fields[key_path] = {"path": key_path, "kind": "check",
                                  "widget": w, "loaded": None}

    @staticmethod
    def _normalize_label_widths(forms):
        """把多个 QFormLayout 的标签列统一到相同宽度。

        标签同宽 + 各列同宽 → 所有字段控件宽度一致、左边缘对齐，
        避免输入框一长一短参差不齐。
        """
        labels = []
        for form in forms:
            for r in range(form.rowCount()):
                item = form.itemAt(r, QFormLayout.ItemRole.LabelRole)
                if item and item.widget():
                    labels.append(item.widget())
        if not labels:
            return
        max_w = max(lbl.sizeHint().width() for lbl in labels)
        for lbl in labels:
            lbl.setMinimumWidth(max_w)

    # ─────────────────────────── 公共方法 ───────────────────────────

    def set_backend(self, backend):
        """设置后端引用（不触发加载）"""
        self._backend = backend

    def refresh(self):
        """当 Tab 被选中时调用，触发数据加载"""
        self._load_config()

    # ─────────────────────────── 加载 ───────────────────────────

    def _load_config(self):
        if not self._backend:
            return
        if self._loader and self._loader.isRunning():
            return
        self._loader = ConfigLoader(self._backend)
        self._loader.loaded.connect(self._on_config_loaded)
        self._loader.error.connect(self._on_config_error)
        self._loader.start()

    def _on_config_loaded(self, config_data, env_data, raw_config, raw_env):
        try:
            self._config_data = config_data
            self._env_data = env_data
            self._raw_config = raw_config
            self._raw_env = raw_env
            self._populate_form()
            self._populate_env_table()
            self._raw_config_edit.setPlainText(raw_config)
            self._raw_env_edit.setPlainText(raw_env)
        except Exception as e:
            logger.error(f"填充配置 UI 失败: {e}")

    def _on_config_error(self, error_msg):
        logger.error(f"加载 hermes 配置失败: {error_msg}")
        self._config_data = {}
        self._env_data = {}
        self._raw_config = ""
        self._raw_env = ""
        try:
            self._populate_form()
            self._populate_env_table()
            self._raw_config_edit.setPlainText("")
            self._raw_env_edit.setPlainText("")
        except Exception as e:
            logger.error(f"重置配置 UI 失败: {e}")

    def _populate_form(self):
        """按 key_path 从 config_data 取值填充各控件，并记录加载值供 diff"""
        for info in self._fields.values():
            raw = self._get_nested(self._config_data, info["path"], None)
            w = info["widget"]
            kind = info["kind"]
            if kind == "line":
                text = "" if raw is None else str(raw)
                w.setText(text)
                info["loaded"] = text
            elif kind == "spin":
                val = self._to_int(raw, w.minimum())
                w.setValue(val)
                info["loaded"] = val
            elif kind == "combo":
                text = "" if raw is None else str(raw)
                if w.isEditable():
                    w.setCurrentText(text)
                else:
                    idx = w.findText(text)
                    if idx >= 0:
                        w.setCurrentIndex(idx)
                    elif text:
                        w.addItem(text)
                        w.setCurrentText(text)
                info["loaded"] = w.currentText()
            elif kind == "check":
                val = bool(raw) if raw is not None else False
                w.setChecked(val)
                info["loaded"] = val

    def _populate_env_table(self):
        """列出 .env 中的环境变量（值遮蔽显示）"""
        self._provider_table.setRowCount(0)
        if not self._env_data:
            self._provider_table.setRowCount(1)
            self._provider_table.setItem(0, 0, QTableWidgetItem(self.tr("未配置")))
            self._provider_table.setItem(0, 1, QTableWidgetItem(""))
            return
        keys = sorted(self._env_data.keys())
        self._provider_table.setRowCount(len(keys))
        for row, key in enumerate(keys):
            value = self._env_data.get(key, "")
            self._provider_table.setItem(row, 0, QTableWidgetItem(key))
            # 敏感值（含 KEY/SECRET/TOKEN/PASSWORD）遮蔽，其余明文
            display = self._mask_key(value) if self._is_secret(key) else value
            self._provider_table.setItem(row, 1, QTableWidgetItem(display))
            edit_btn = QPushButton(self.tr("编辑"))
            edit_btn.clicked.connect(
                lambda checked, k=key: self._on_edit_env_key(k))
            self._provider_table.setCellWidget(row, 2, edit_btn)

    # ─────────────────────────── .env 编辑 ───────────────────────────

    def _on_add_env_key(self):
        key, ok = QInputDialog.getText(
            self, self.tr("新增环境变量"), self.tr("变量名 (如 OPENAI_API_KEY):"))
        if not ok or not key.strip():
            return
        key = key.strip()
        value, ok = QInputDialog.getText(
            self, self.tr("新增环境变量"),
            self.tr("{} 的值:").format(key))
        if not ok:
            return
        self._env_data[key] = value.strip()
        self._populate_env_table()

    def _on_edit_env_key(self, key):
        current = self._env_data.get(key, "")
        new_value, ok = QInputDialog.getText(
            self, self.tr("编辑环境变量"),
            self.tr("{} 的值:").format(key),
            QLineEdit.EchoMode.Normal, current)
        if ok:
            self._env_data[key] = new_value.strip()
            self._populate_env_table()

    # ─────────────────────────── 保存（常用设置） ───────────────────────────

    def _on_refresh(self):
        self._load_config()

    def _on_save_form(self):
        if not self._backend:
            QMessageBox.warning(self, self.tr("警告"), self.tr("未连接后端"))
            return
        if self._save_worker and self._save_worker.isRunning():
            return

        scalar_changes = self._collect_scalar_changes()
        env_changes = self._collect_env_changes()

        if not scalar_changes and not env_changes:
            QMessageBox.information(self, self.tr("提示"), self.tr("没有需要保存的改动"))
            return

        self._save_btn.setEnabled(False)
        self._save_worker = SaveWorker(
            self._backend, scalar_changes, env_changes, self._raw_env)
        self._save_worker.finished.connect(self._on_save_finished)
        self._save_worker.error.connect(self._on_save_error)
        self._save_worker.start()

    def _collect_scalar_changes(self):
        """对比 loaded 与当前值，收集改动项 [(key_path, value_str)]"""
        changes = []
        for info in self._fields.values():
            w, kind, loaded = info["widget"], info["kind"], info["loaded"]
            if kind == "line":
                cur = w.text().strip()
                if cur != (loaded or "") and cur != "":
                    changes.append((info["path"], cur))
            elif kind == "spin":
                cur = w.value()
                if cur != loaded:
                    changes.append((info["path"], str(cur)))
            elif kind == "combo":
                cur = w.currentText().strip()
                if cur != (loaded or "") and cur != "":
                    changes.append((info["path"], cur))
            elif kind == "check":
                cur = w.isChecked()
                if cur != loaded:
                    changes.append((info["path"], "true" if cur else "false"))
        return changes

    def _collect_env_changes(self):
        """收集相对原始 .env 有增改的键"""
        original = ConfigLoader._parse_env(self._raw_env)
        changes = {}
        for key, value in self._env_data.items():
            if original.get(key) != value:
                changes[key] = value
        return changes

    def _on_save_finished(self, ok_keys, failed_keys, env_saved):
        self._save_btn.setEnabled(True)
        parts = []
        if ok_keys:
            parts.append(self.tr("已保存 {} 项配置").format(len(ok_keys)))
        if env_saved:
            parts.append(self.tr(".env 已更新"))
        if failed_keys:
            parts.append(
                self.tr("以下项保存失败，请改用「原始配置」手动编辑：\n{}")
                .format("\n".join(failed_keys)))
            QMessageBox.warning(self, self.tr("部分失败"), "\n".join(parts))
        else:
            QMessageBox.information(
                self, self.tr("成功"), "\n".join(parts) or self.tr("配置已保存"))
        # 重新加载以刷新 loaded 基准值和原始文本
        self._load_config()

    def _on_save_error(self, error_msg):
        self._save_btn.setEnabled(True)
        QMessageBox.critical(self, self.tr("错误"),
                             self.tr("保存配置失败: {}").format(error_msg))

    # ─────────────────────────── 保存（原始配置） ───────────────────────────

    def _on_save_raw_yaml(self):
        if not self._backend:
            QMessageBox.warning(self, self.tr("警告"), self.tr("未连接后端"))
            return
        content = self._raw_config_edit.toPlainText()
        # 语法校验：解析失败则拒绝写入
        try:
            yaml.safe_load(content)
        except yaml.YAMLError as e:
            QMessageBox.critical(
                self, self.tr("YAML 语法错误"),
                self.tr("无法保存，请修正后重试：\n{}").format(str(e)))
            return
        try:
            hermes_home = self._backend.get_hermes_home()
            self._backend.write_file(f"{hermes_home}/config.yaml", content)
            QMessageBox.information(self, self.tr("成功"), self.tr("config.yaml 已保存"))
            self._load_config()
        except Exception as e:
            QMessageBox.critical(self, self.tr("错误"),
                                 self.tr("保存失败: {}").format(str(e)))

    def _on_save_raw_env(self):
        if not self._backend:
            QMessageBox.warning(self, self.tr("警告"), self.tr("未连接后端"))
            return
        content = self._raw_env_edit.toPlainText()
        try:
            hermes_home = self._backend.get_hermes_home()
            self._backend.write_file(f"{hermes_home}/.env", content)
            QMessageBox.information(self, self.tr("成功"), self.tr(".env 已保存"))
            self._load_config()
        except Exception as e:
            QMessageBox.critical(self, self.tr("错误"),
                                 self.tr("保存失败: {}").format(str(e)))

    # ─────────────────────────── 配置检查 ───────────────────────────

    def _on_check(self):
        if not self._backend:
            QMessageBox.warning(self, self.tr("警告"), self.tr("未连接后端"))
            return
        if self._check_worker and self._check_worker.isRunning():
            return
        self._check_btn.setEnabled(False)
        self._check_worker = CheckWorker(self._backend)
        self._check_worker.finished.connect(self._on_check_finished)
        self._check_worker.start()

    def _on_check_finished(self, output):
        self._check_btn.setEnabled(True)
        dlg = QDialog(self)
        dlg.setWindowTitle(self.tr("配置检查 (hermes config check)"))
        dlg.resize(560, 480)
        v = QVBoxLayout(dlg)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(output)
        v.addWidget(text)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        box.accepted.connect(dlg.accept)
        v.addWidget(box)
        dlg.exec()

    # ─────────────────────────── 辅助方法 ───────────────────────────
    @staticmethod
    def _mono_font():
        """返回等宽字体，跨平台回退"""
        font = QFont()
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setFamilies(["Consolas", "Menlo", "DejaVu Sans Mono",
                          "Courier New", "monospace"])
        font.setFixedPitch(True)
        font.setPointSize(15)
        return font

    @staticmethod
    def _get_nested(data, dotted_path, default=None):
        """按 'a.b.c' 点号路径从嵌套 dict 安全取值"""
        cur = data
        for part in dotted_path.split('.'):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return default
        return cur

    @staticmethod
    def _to_int(value, default):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _is_secret(key):
        return bool(re.search(r"KEY|SECRET|TOKEN|PASSWORD", key, re.IGNORECASE))

    @staticmethod
    def _mask_key(key):
        """将敏感值遮蔽为 '前4****后4' 格式"""
        if not key:
            return ""
        if len(key) <= 8:
            return key[:2] + "****" + key[-2:] if len(key) > 4 else "****"
        return key[:4] + "****" + key[-4:]

    @staticmethod
    def _update_env_content(raw, changes):
        """就地更新 .env 内容：匹配 KEY= 行替换值，新键追加末尾，保留注释与空行。

        Args:
            raw: 原始 .env 文本
            changes: {KEY: value} 需增改的键值
        Returns:
            更新后的 .env 文本
        """
        if not changes:
            return raw
        remaining = dict(changes)
        out_lines = []
        for line in raw.splitlines():
            stripped = line.strip()
            matched = False
            if stripped and not stripped.startswith('#') and '=' in stripped:
                key = stripped.split('=', 1)[0].strip()
                if key in remaining:
                    out_lines.append(f"{key}={remaining.pop(key)}")
                    matched = True
            if not matched:
                out_lines.append(line)
        # 追加新键
        for key, value in remaining.items():
            out_lines.append(f"{key}={value}")
        content = '\n'.join(out_lines)
        if not content.endswith('\n'):
            content += '\n'
        return content
