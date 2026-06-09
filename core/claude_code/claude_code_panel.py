# -*- coding: utf-8 -*-
"""Claude Code 集成管理面板 - 主面板容器，提供连接模式切换和功能 Tab 管理"""

import logging

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                               QTabWidget, QComboBox, QLabel, QPushButton)

logger = logging.getLogger(__name__)


class ClaudeCodePanel(QWidget):
    """Claude Code 管理面板"""

    # 信号：请求在终端中打开 claude（参数为会话名/命令）
    open_terminal_requested = Signal(str)

    def __init__(self, main_dialog=None, parent=None):
        """
        Args:
            main_dialog: 主窗口引用，用于获取 SSH 连接列表（远程模式）
            parent: 父 widget
        """
        super().__init__(parent)
        self._main_dialog = main_dialog
        self._backend = None
        self._initialized = False
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # 顶部：连接模式选择
        top_layout = QHBoxLayout()
        top_layout.addWidget(QLabel(self.tr("连接模式：")))
        self._mode_combo = QComboBox()
        self._mode_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self._mode_combo.setMinimumWidth(200)
        self._mode_combo.addItem(self.tr("本地"), "local")
        # 远程连接项会动态添加（从 main_dialog.ssh_clients 获取）
        top_layout.addWidget(self._mode_combo)
        top_layout.addStretch()
        layout.addLayout(top_layout)

        # 主体：QTabWidget 切换各功能模块
        self._tab_widget = QTabWidget()
        layout.addWidget(self._tab_widget)

        # 添加各功能 Tab（部分模块可能尚未创建，用 try/except 保护）
        self._add_tabs()

        # 连接 Tab 切换信号 — 切换时懒加载当前 Tab 数据
        self._tab_widget.currentChanged.connect(self._on_tab_changed)

        # 连接模式切换信号 — 用户手动切换时才触发
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)

        # 刷新远程连接列表（不触发加载）
        self._refresh_connections()

        # 设置鼠标样式：默认箭头，按钮/Tab/下拉框为手指
        self._setup_cursors()

    def _add_tabs(self):
        """添加各功能 Tab，尚未实现的模块静默跳过"""
        # 状态 Tab
        try:
            from core.claude_code.status_widget import StatusWidget
            self._status_widget = StatusWidget(self)
            self._status_widget.open_terminal_requested.connect(
                self._on_open_terminal_requested
            )
            self._tab_widget.addTab(self._status_widget, self.tr("状态"))
        except ImportError:
            logger.debug("StatusWidget 尚未实现，跳过")

        # 会话 Tab
        try:
            from core.claude_code.session_widget import SessionWidget
            self._session_widget = SessionWidget(self)
            self._tab_widget.addTab(self._session_widget, self.tr("会话"))
        except ImportError:
            logger.debug("SessionWidget 尚未实现，跳过")

        # 设置 Tab
        try:
            from core.claude_code.settings_widget import SettingsWidget
            self._settings_widget = SettingsWidget(self)
            self._tab_widget.addTab(self._settings_widget, self.tr("设置"))
        except ImportError:
            logger.debug("SettingsWidget 尚未实现，跳过")

        # MCP Tab
        try:
            from core.claude_code.mcp_widget import McpWidget
            self._mcp_widget = McpWidget(self)
            self._tab_widget.addTab(self._mcp_widget, self.tr("MCP"))
        except ImportError:
            logger.debug("McpWidget 尚未实现，跳过")

    def _refresh_connections(self):
        """刷新远程连接列表"""
        # 保留第一项"本地"
        while self._mode_combo.count() > 1:
            self._mode_combo.removeItem(1)
        # 添加所有活跃的 SSH 连接
        if self._main_dialog and hasattr(self._main_dialog, 'ssh_clients'):
            for conn_id, ssh_conn in self._main_dialog.ssh_clients.items():
                label = f"远程: {getattr(ssh_conn, 'hostname', conn_id)}"
                self._mode_combo.addItem(label, conn_id)

    def showEvent(self, event):
        """面板首次显示时初始化 backend 并加载第一个 Tab"""
        super().showEvent(event)
        if not self._initialized:
            self._initialized = True
            self._on_mode_changed(self._mode_combo.currentIndex())

    def _on_mode_changed(self, index: int):
        """切换连接模式：创建 backend，通知子 widget 更新引用，刷新当前 Tab"""
        from core.claude_code.backend import LocalBackend, RemoteBackend

        mode_data = self._mode_combo.itemData(index)
        if mode_data == "local":
            self._backend = LocalBackend()
        else:
            # 远程模式
            ssh_conn = None
            if self._main_dialog and hasattr(self._main_dialog, 'ssh_clients'):
                ssh_conn = self._main_dialog.ssh_clients.get(mode_data)
            if ssh_conn:
                self._backend = RemoteBackend(ssh_conn)
            else:
                self._backend = LocalBackend()  # fallback
                logger.warning(f"找不到 SSH 连接 {mode_data}，回退到本地模式")

        # 通知所有子 widget 更新 backend 引用（不触发加载）
        self._notify_backend_changed()
        # 只刷新当前可见的 Tab
        current_widget = self._tab_widget.currentWidget()
        if current_widget and hasattr(current_widget, 'refresh'):
            current_widget.refresh()

    def _on_tab_changed(self, index: int):
        """Tab 切换时，懒加载对应 Tab 的数据"""
        widget = self._tab_widget.widget(index)
        if widget and hasattr(widget, 'refresh'):
            widget.refresh()

    def _notify_backend_changed(self):
        """通知所有子模块 backend 变更（只更新引用，不触发加载）"""
        for i in range(self._tab_widget.count()):
            widget = self._tab_widget.widget(i)
            if hasattr(widget, 'set_backend'):
                widget.set_backend(self._backend)

    @property
    def backend(self):
        """获取当前 backend 实例"""
        return self._backend

    def _on_open_terminal_requested(self, command: str):
        """子 widget 请求打开终端，向外传递信号"""
        self.open_terminal_requested.emit(command)

    def _setup_cursors(self):
        """设置鼠标样式：整体默认箭头，可点击元素为手指"""
        self.setCursor(Qt.CursorShape.ArrowCursor)
        # Tab 栏设置手指光标
        self._tab_widget.tabBar().setCursor(Qt.CursorShape.PointingHandCursor)
        # 下拉框设置手指光标
        self._mode_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        # 递归设置所有 QPushButton 为手指光标
        for btn in self.findChildren(QPushButton):
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
