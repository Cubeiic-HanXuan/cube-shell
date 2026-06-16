# -*- coding: utf-8 -*-
"""Claude Code 状态面板 - 显示版本、认证、守护进程和安装路径等状态信息"""

import logging
import os

from PySide6.QtCore import Qt, QThread, Signal, QDateTime
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
                               QLabel, QPushButton, QTextEdit, QFrame, QFileDialog)

logger = logging.getLogger(__name__)


class UpdateWorker(QThread):
    """后台线程执行更新命令"""
    finished = Signal(str)  # output
    error = Signal(str)

    def __init__(self, backend):
        super().__init__()
        self._backend = backend

    def run(self):
        try:
            returncode, stdout, stderr = self._backend.run_command(["update"])
            output = stdout or stderr or ""
            self.finished.emit(output.strip())
        except Exception as e:
            logger.error(f"更新 Claude Code 失败: {e}")
            self.error.emit(str(e))


class StatusWorker(QThread):
    """后台线程加载状态信息，避免阻塞 UI"""
    finished = Signal(dict)  # {version, auth_status, daemon_status, bin_path}
    error = Signal(str)

    def __init__(self, backend):
        super().__init__()
        self._backend = backend

    def run(self):
        try:
            result = {}
            # 获取版本
            result["version"] = self._backend.get_version()
            # 获取认证状态
            result["auth_status"] = self._backend.get_auth_status()
            # 获取守护进程状态
            result["daemon_status"] = self._backend.get_daemon_status()
            # 获取 claude 二进制路径
            if hasattr(self._backend, '_claude_bin'):
                result["bin_path"] = self._backend._claude_bin
            else:
                # 远程模式：通过 which 获取路径
                returncode, stdout, stderr = self._backend.run_command(
                    ["--version"]
                )
                result["bin_path"] = "claude (远程)"
            self.finished.emit(result)
        except Exception as e:
            logger.error(f"获取 Claude Code 状态失败: {e}")
            self.error.emit(str(e))


class StatusWidget(QWidget):
    """Claude Code 状态面板：显示版本、认证、守护进程状态和安装路径"""

    # 信号：请求打开终端
    open_terminal_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._backend = None
        self._worker: StatusWorker | None = None
        self._update_worker: UpdateWorker | None = None
        self._last_dir: str = ""  # 记住上次选择的项目文件夹
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)

        # ─── 状态卡片区域 (2x2 网格) ───
        cards_layout = QGridLayout()
        cards_layout.setSpacing(10)

        self._card_version = self._create_card(self.tr("版本信息"), "--")
        self._card_auth = self._create_card(self.tr("认证状态"), self.tr("检测中..."))
        self._card_daemon = self._create_card(self.tr("守护进程"), self.tr("检测中..."))
        self._card_path = self._create_card(self.tr("安装路径"), self.tr("检测中..."))

        cards_layout.addWidget(self._card_version["frame"], 0, 0)
        cards_layout.addWidget(self._card_auth["frame"], 0, 1)
        cards_layout.addWidget(self._card_daemon["frame"], 1, 0)
        cards_layout.addWidget(self._card_path["frame"], 1, 1)

        main_layout.addLayout(cards_layout)

        # ─── 快速操作按钮区域 ───
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self._btn_refresh = QPushButton(self.tr("刷新状态"))
        self._btn_open_terminal = QPushButton(self.tr("打开终端"))
        self._btn_agent_view = QPushButton(self.tr("Agent View"))
        self._btn_update = QPushButton(self.tr("更新 Claude"))

        self._btn_refresh.clicked.connect(self.refresh)
        self._btn_open_terminal.clicked.connect(self._on_open_terminal)
        self._btn_agent_view.clicked.connect(self._on_agent_view)
        self._btn_update.clicked.connect(self._on_update)

        btn_layout.addWidget(self._btn_refresh)
        btn_layout.addWidget(self._btn_open_terminal)
        btn_layout.addWidget(self._btn_agent_view)
        btn_layout.addWidget(self._btn_update)
        btn_layout.addStretch()

        main_layout.addLayout(btn_layout)

        # ─── 日志输出区域 ───
        log_label = QLabel(self.tr("操作日志"))
        log_label.setFont(self._bold_font())
        main_layout.addWidget(log_label)

        self._log_output = QTextEdit()
        self._log_output.setReadOnly(True)
        self._log_output.setMaximumHeight(200)
        self._log_output.setPlaceholderText(self.tr("状态信息将显示在此处..."))
        main_layout.addWidget(self._log_output)

        main_layout.addStretch()

    # ─── 公共方法 ───

    def set_backend(self, backend):
        """由 Panel 调用，设置当前 Backend（不触发加载）"""
        self._backend = backend

    def refresh(self):
        """刷新状态信息，使用 QThread Worker 异步加载"""
        if not self._backend:
            return
        # 避免重复启动
        if self._worker and self._worker.isRunning():
            return
        self._set_buttons_enabled(False)
        self._log_append(self.tr("正在获取 Claude Code 状态..."))

        self._worker = StatusWorker(self._backend)
        self._worker.finished.connect(self._on_status_loaded)
        self._worker.error.connect(self._on_status_error)
        self._worker.start()

    # ─── 按钮操作 ───

    def _on_open_terminal(self):
        """先选择项目文件夹，再在该目录打开终端运行 claude"""
        self._open_in_selected_dir("claude", self.tr("选择项目文件夹"))

    def _on_agent_view(self):
        """先选择项目文件夹，再在该目录打开 Agent View"""
        self._open_in_selected_dir("claude agents", self.tr("选择项目文件夹"))

    def _open_in_selected_dir(self, claude_cmd: str, caption: str):
        """弹出文件夹选择对话框，选定后 cd 到该目录再执行 claude 命令。"""
        directory = QFileDialog.getExistingDirectory(
            self, caption, self._last_dir or os.path.expanduser("~")
        )
        if not directory:
            return  # 用户取消
        self._last_dir = directory
        from core.claude_code.backend import build_cd_command
        cmd = build_cd_command(directory, claude_cmd)
        self.open_terminal_requested.emit(cmd)

    def _on_update(self):
        """执行 claude update 命令"""
        if not self._backend:
            return
        if self._update_worker and self._update_worker.isRunning():
            return
        self._set_buttons_enabled(False)
        self._log_append(self.tr("正在更新 Claude Code..."))

        self._update_worker = UpdateWorker(self._backend)
        self._update_worker.finished.connect(self._on_update_finished)
        self._update_worker.error.connect(self._on_update_error)
        self._update_worker.start()

    def _on_update_finished(self, output: str):
        """更新命令完成"""
        timestamp = QDateTime.currentDateTime().toString("HH:mm:ss")
        self._log_append(f"[{timestamp}] {self.tr('更新完成')}")
        if output:
            self._log_append(output)
        self._set_buttons_enabled(True)
        # 更新完成后自动刷新状态
        self.refresh()

    def _on_update_error(self, error_msg: str):
        """更新命令失败"""
        timestamp = QDateTime.currentDateTime().toString("HH:mm:ss")
        self._log_append(f"[{timestamp}] {self.tr('更新失败')}: {error_msg}")
        self._set_buttons_enabled(True)

    # ─── Worker 回调 ───

    def _on_status_loaded(self, data: dict):
        """状态加载完成，更新 UI 卡片"""
        timestamp = QDateTime.currentDateTime().toString("HH:mm:ss")

        # 版本信息
        version = data.get("version", "")
        if version:
            self._card_version["value"].setText(version)
            self._set_card_status(self._card_version, version, "#27ae60")
        else:
            self._set_card_status(self._card_version, self.tr("未安装"), "#e74c3c")

        # 认证状态
        # 真实 JSON 形如：{"loggedIn": true, "authMethod": "oauth_token",
        #                  "apiProvider": "firstParty"}
        auth = data.get("auth_status", {})
        if auth:
            is_authed = auth.get(
                "loggedIn",
                auth.get("authenticated", auth.get("logged_in", False)),
            )
            account = (
                auth.get("account")
                or auth.get("email")
                or auth.get("organization")
                or ""
            )
            method = auth.get("authMethod", auth.get("auth_method", ""))
            if is_authed:
                if account:
                    status_text = account
                elif method:
                    status_text = f"{self.tr('已登录')} ({method})"
                else:
                    status_text = self.tr("已登录")
                self._set_card_status(self._card_auth, status_text, "#27ae60")
            elif account:
                self._set_card_status(self._card_auth, account, "#27ae60")
            else:
                self._set_card_status(self._card_auth, self.tr("未登录"), "#e74c3c")
        else:
            self._set_card_status(self._card_auth, self.tr("未知"), "#7f8c8d")

        # 守护进程状态
        daemon = data.get("daemon_status", {})
        if daemon.get("running", False):
            workers = daemon.get("workers", daemon.get("num_workers", ""))
            status_text = self.tr("运行中")
            if workers:
                status_text += f" ({workers} workers)"
            self._set_card_status(self._card_daemon, status_text, "#27ae60")
        else:
            self._set_card_status(self._card_daemon, self.tr("未运行"), "#e74c3c")

        # 安装路径
        bin_path = data.get("bin_path", "")
        if bin_path:
            self._card_path["value"].setText(bin_path)
            self._card_path["value"].setStyleSheet(
                "font-size: 12px; border: none; color: #27ae60;"
            )
        else:
            self._set_card_status(self._card_path, self.tr("未找到"), "#e74c3c")

        self._log_append(f"[{timestamp}] {self.tr('状态刷新完成')}")
        self._set_buttons_enabled(True)

    def _on_status_error(self, error_msg: str):
        """状态加载失败"""
        timestamp = QDateTime.currentDateTime().toString("HH:mm:ss")
        self._log_append(f"[{timestamp}] {self.tr('错误')}: {error_msg}")

        self._set_card_status(self._card_version, self.tr("获取失败"), "#e74c3c")
        self._set_card_status(self._card_auth, self.tr("获取失败"), "#e74c3c")
        self._set_card_status(self._card_daemon, self.tr("获取失败"), "#e74c3c")
        self._set_card_status(self._card_path, self.tr("获取失败"), "#e74c3c")

        self._set_buttons_enabled(True)

    # ─── UI 辅助方法 ───

    def _create_card(self, title_text: str, value_text: str) -> dict:
        """创建一个状态卡片：QFrame 内含标题和值标签"""
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        card_layout = QVBoxLayout(frame)
        card_layout.setContentsMargins(12, 10, 12, 10)
        card_layout.setSpacing(6)

        title_label = QLabel(title_text)
        title_label.setFont(self._bold_font())

        value_label = QLabel(value_text)
        value_label.setStyleSheet("font-size: 14px; border: none;")
        value_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        value_label.setWordWrap(True)

        card_layout.addWidget(title_label)
        card_layout.addWidget(value_label)
        card_layout.addStretch()

        return {"frame": frame, "title": title_label, "value": value_label}

    def _set_card_status(self, card: dict, text: str, color: str):
        """设置卡片值标签的文本和颜色"""
        card["value"].setText(text)
        card["value"].setStyleSheet(
            f"color: {color}; font-size: 14px; font-weight: bold; border: none;"
        )

    def _bold_font(self) -> QFont:
        """返回粗体字体"""
        font = QFont()
        font.setBold(True)
        return font

    def _set_buttons_enabled(self, enabled: bool):
        """启用或禁用操作按钮"""
        self._btn_refresh.setEnabled(enabled)
        self._btn_open_terminal.setEnabled(enabled)
        self._btn_agent_view.setEnabled(enabled)
        self._btn_update.setEnabled(enabled)

    def _log_append(self, message: str):
        """追加日志到日志区域"""
        self._log_output.append(message)
