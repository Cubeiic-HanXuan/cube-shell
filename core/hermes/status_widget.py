# -*- coding: utf-8 -*-
"""Hermes Agent 部署状态模块 - 显示版本、安装和运行状态，提供快速操作按钮"""

import subprocess
import sys

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
                                QLabel, QPushButton, QTextEdit, QFrame)
from PySide6.QtCore import Qt, QThread, Signal, QDateTime
from PySide6.QtGui import QFont


class CommandWorker(QThread):
    """后台线程执行 CLI 命令，避免阻塞 UI"""
    finished = Signal(str, str)  # (command_description, output)

    def __init__(self, backend, args):
        super().__init__()
        self._backend = backend
        self._args = args

    def run(self):
        try:
            result = self._backend.exec_cli(self._args)
        except Exception as e:
            result = f"[错误] {e}"
        self.finished.emit(' '.join(self._args), result)


class PipInstallWorker(QThread):
    """后台线程执行 pip 安装/升级 hermes-agent。

    upgrade=True  -> pip install --upgrade hermes-agent（更新已装的 Hermes）
    upgrade=False -> pip install hermes-agent（首次安装）
    """
    finished = Signal(str)  # output
    error = Signal(str)

    def __init__(self, upgrade: bool = True):
        super().__init__()
        self._upgrade = upgrade

    def run(self):
        try:
            kwargs = dict(
                capture_output=True, text=True, timeout=120
            )
            # Windows GUI 应用下防止弹出控制台黑窗口
            import os
            if os.name == 'nt':
                import subprocess as _sp
                kwargs['creationflags'] = _sp.CREATE_NO_WINDOW
            args = [sys.executable, "-m", "pip", "install"]
            if self._upgrade:
                args.append("--upgrade")
            args.append("hermes-agent")
            result = subprocess.run(args, **kwargs)
            output = result.stdout or result.stderr or ""
            self.finished.emit(output.strip())
        except Exception as e:
            self.error.emit(str(e))


class StatusWidget(QWidget):
    """部署状态模块：显示 Hermes 版本、安装状态、网关和 API Server 运行状态"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._backend = None
        self._workers = []  # 持有 worker 引用，防止 GC
        self._update_worker: PipInstallWorker | None = None
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)

        # ─── 状态卡片区域 (2x2 网格) ───
        cards_layout = QGridLayout()
        cards_layout.setSpacing(10)

        self._card_version = self._create_card(self.tr("版本信息"), "--")
        self._card_install = self._create_card(self.tr("安装状态"), self.tr("检测中..."))
        self._card_gateway = self._create_card(self.tr("网关状态"), self.tr("检测中..."))
        self._card_api = self._create_card(self.tr("API Server"), self.tr("检测中..."))

        cards_layout.addWidget(self._card_version["frame"], 0, 0)
        cards_layout.addWidget(self._card_install["frame"], 0, 1)
        cards_layout.addWidget(self._card_gateway["frame"], 1, 0)
        cards_layout.addWidget(self._card_api["frame"], 1, 1)

        main_layout.addLayout(cards_layout)

        # ─── 快速操作按钮区域 ───
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self._btn_refresh = QPushButton(self.tr("刷新状态"))
        self._btn_start_gw = QPushButton(self.tr("启动网关"))
        self._btn_stop_gw = QPushButton(self.tr("停止网关"))
        self._btn_doctor = QPushButton(self.tr("检查修复"))
        self._btn_update = QPushButton(self.tr("更新 Hermes"))
        # 安装按钮：仅在检测到未安装 Hermes 时显示（见 _update_install_button_visibility）
        self._btn_install = QPushButton(self.tr("安装 Hermes"))
        self._btn_install.setVisible(False)

        self._btn_refresh.clicked.connect(self.refresh_status)
        self._btn_start_gw.clicked.connect(self._start_gateway)
        self._btn_stop_gw.clicked.connect(self._stop_gateway)
        self._btn_doctor.clicked.connect(self._run_doctor)
        self._btn_update.clicked.connect(self._on_update)
        self._btn_install.clicked.connect(self._on_install)

        btn_layout.addWidget(self._btn_refresh)
        btn_layout.addWidget(self._btn_start_gw)
        btn_layout.addWidget(self._btn_stop_gw)
        btn_layout.addWidget(self._btn_doctor)
        btn_layout.addWidget(self._btn_update)
        btn_layout.addWidget(self._btn_install)
        btn_layout.addStretch()

        main_layout.addLayout(btn_layout)

        # ─── 日志输出区域 ───
        log_label = QLabel(self.tr("操作日志"))
        log_label.setFont(self._bold_font())
        main_layout.addWidget(log_label)

        self._log_output = QTextEdit()
        self._log_output.setReadOnly(True)
        self._log_output.setMaximumHeight(200)
        self._log_output.setPlaceholderText(self.tr("命令输出将显示在此处..."))
        main_layout.addWidget(self._log_output)

        main_layout.addStretch()

    # ─── 公共方法 ───

    def set_backend(self, backend):
        """设置后端引用（不触发加载）"""
        self._backend = backend

    def refresh(self):
        """当 Tab 被选中时调用，触发数据加载"""
        self.refresh_status()

    def refresh_status(self):
        """调用 CLI 获取各项状态信息"""
        if not self._backend:
            return
        self._set_buttons_enabled(False)
        # 获取版本
        self._run_command(["--version"], self.tr("获取版本"), self._on_version_result)
        # 获取整体状态
        self._run_command(["status"], self.tr("获取状态"), self._on_status_result)

    # ─── 按钮操作 ───

    def _start_gateway(self):
        """启动网关"""
        if not self._backend:
            return
        self._run_command(["gateway", "start"], self.tr("启动网关"), self._on_command_done)

    def _stop_gateway(self):
        """停止网关"""
        if not self._backend:
            return
        self._run_command(["gateway", "stop"], self.tr("停止网关"), self._on_command_done)

    def _run_doctor(self):
        """执行检查修复"""
        if not self._backend:
            return
        self._run_command(["doctor", "--fix"], self.tr("检查修复"), self._on_command_done)

    def _on_update(self):
        """执行 pip install --upgrade hermes-agent"""
        if not self._backend:
            return
        if self._update_worker and self._update_worker.isRunning():
            return
        self._set_buttons_enabled(False)
        timestamp = QDateTime.currentDateTime().toString("HH:mm:ss")
        self._log_output.append(f"[{timestamp}] {self.tr('正在更新 Hermes...')}")

        self._update_worker = PipInstallWorker(upgrade=True)
        self._update_worker.finished.connect(self._on_update_finished)
        self._update_worker.error.connect(self._on_update_error)
        self._update_worker.start()

    def _on_install(self):
        """执行 pip install hermes-agent 安装 Hermes Agent。

        安装不依赖 backend（未安装时正是 backend 可能不可用的时刻），
        直接用当前 Python 环境的 pip 安装，与"更新 Hermes"走同一套环境。
        """
        if self._update_worker and self._update_worker.isRunning():
            return
        self._set_buttons_enabled(False)
        timestamp = QDateTime.currentDateTime().toString("HH:mm:ss")
        self._log_output.append(f"[{timestamp}] {self.tr('正在安装 Hermes...')}")

        self._update_worker = PipInstallWorker(upgrade=False)
        self._update_worker.finished.connect(self._on_update_finished)
        self._update_worker.error.connect(self._on_update_error)
        self._update_worker.start()

    def _on_update_finished(self, output: str):
        """更新命令完成"""
        timestamp = QDateTime.currentDateTime().toString("HH:mm:ss")
        self._log_output.append(f"[{timestamp}] {self.tr('更新完成')}")
        if output:
            self._log_output.append(output)
        self._log_output.append("")
        self._set_buttons_enabled(True)
        # 更新完成后自动刷新状态
        self.refresh_status()

    def _on_update_error(self, error_msg: str):
        """更新命令失败"""
        timestamp = QDateTime.currentDateTime().toString("HH:mm:ss")
        self._log_output.append(f"[{timestamp}] {self.tr('更新失败')}: {error_msg}")
        self._log_output.append("")
        self._set_buttons_enabled(True)

    # ─── 后台命令执行 ───

    def _run_command(self, args, description, callback):
        """在后台线程运行命令并在完成后回调"""
        worker = CommandWorker(self._backend, args)
        worker.finished.connect(lambda desc, output: self._on_worker_finished(desc, output, callback, worker))
        self._workers.append(worker)
        worker.start()

    def _on_worker_finished(self, description, output, callback, worker):
        """Worker 完成后处理"""
        # 写入日志
        timestamp = QDateTime.currentDateTime().toString("HH:mm:ss")
        self._log_output.append(f"[{timestamp}] hermes {description}")
        if output and output.strip():
            self._log_output.append(output.strip())
        self._log_output.append("")
        # 回调处理结果
        callback(description, output)
        # 清理 worker 引用
        if worker in self._workers:
            self._workers.remove(worker)

    # ─── 结果回调 ───

    def _on_version_result(self, description, output):
        """处理版本查询结果"""
        version = output.strip() if output and output.strip() else self.tr("未安装")
        self._card_version["value"].setText(version)
        # 判断安装状态
        installed = bool(output and output.strip() and "not found" not in output.lower())
        if installed:
            self._set_card_status(self._card_install, self.tr("已安装"), "#27ae60")
        else:
            self._set_card_status(self._card_install, self.tr("未安装"), "#e74c3c")
        # 未安装时显示"安装 Hermes"按钮，已安装则隐藏
        self._update_install_button_visibility(installed)

    def _on_status_result(self, description, output):
        """解析 status 命令输出，判断网关和 API Server 状态"""
        text = output.lower() if output else ""
        # 解析网关状态
        if "gateway" in text and "running" in text:
            self._set_card_status(self._card_gateway, self.tr("运行中"), "#27ae60")
        elif "gateway" in text and ("stopped" in text or "inactive" in text):
            self._set_card_status(self._card_gateway, self.tr("已停止"), "#e74c3c")
        else:
            self._set_card_status(self._card_gateway, self.tr("未知"), "#7f8c8d")

        # 解析 API Server 状态
        if "api" in text and "running" in text:
            self._set_card_status(self._card_api, self.tr("运行中"), "#27ae60")
        elif "api" in text and ("stopped" in text or "inactive" in text):
            self._set_card_status(self._card_api, self.tr("已停止"), "#e74c3c")
        else:
            self._set_card_status(self._card_api, self.tr("未知"), "#7f8c8d")

        self._set_buttons_enabled(True)

    def _on_command_done(self, description, output):
        """通用命令完成后自动刷新状态"""
        self.refresh_status()

    # ─── UI 辅助方法 ───

    def _create_card(self, title_text, value_text):
        """创建一个状态卡片：QFrame 内含标题和值标签"""
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        card_layout = QVBoxLayout(frame)
        card_layout.setContentsMargins(12, 10, 12, 10)
        card_layout.setSpacing(6)

        title_label = QLabel(title_text)
        title_label.setFont(self._bold_font())
        #title_label.setStyleSheet("color: palette(text); border: none;")

        value_label = QLabel(value_text)
        value_label.setStyleSheet("font-size: 14px; border: none;")
        value_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        card_layout.addWidget(title_label)
        card_layout.addWidget(value_label)
        card_layout.addStretch()

        return {"frame": frame, "title": title_label, "value": value_label}

    def _set_card_status(self, card, text, color):
        """设置卡片值标签的文本和颜色"""
        card["value"].setText(text)
        card["value"].setStyleSheet(f"color: {color}; font-size: 14px; font-weight: bold; border: none;")

    def _bold_font(self):
        """返回粗体字体"""
        font = QFont()
        font.setBold(True)
        return font

    def _set_buttons_enabled(self, enabled):
        """启用或禁用操作按钮"""
        self._btn_refresh.setEnabled(enabled)
        self._btn_start_gw.setEnabled(enabled)
        self._btn_stop_gw.setEnabled(enabled)
        self._btn_doctor.setEnabled(enabled)
        self._btn_update.setEnabled(enabled)
        self._btn_install.setEnabled(enabled)

    def _update_install_button_visibility(self, installed: bool):
        """根据是否已安装 Hermes 切换按钮显隐。

        已安装：隐藏"安装 Hermes"、显示"更新 Hermes"；
        未安装：显示"安装 Hermes"、隐藏"更新 Hermes"（未装无从更新）。
        """
        self._btn_install.setVisible(not installed)
        self._btn_update.setVisible(installed)
