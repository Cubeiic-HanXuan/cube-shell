from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                                QTabWidget, QComboBox, QLabel, QPushButton)
from PySide6.QtCore import Signal, Qt

from function.util import logger


class HermesPanel(QWidget):
    """Hermes Agent 可视化管理面板"""

    def __init__(self, main_dialog, parent=None):
        super().__init__(parent)
        self._main_dialog = main_dialog
        self._backend = None
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

        # 添加各功能 Tab
        from core.hermes.agent_widget import AgentWidget
        from core.hermes.status_widget import StatusWidget
        from core.hermes.config_widget import ConfigWidget
        from core.hermes.memory_widget import MemoryWidget
        from core.hermes.cron_widget import CronWidget
        from core.hermes.skills_widget import SkillsWidget
        from core.hermes.gateway_widget import GatewayWidget

        self._agent_widget = AgentWidget(self)
        self._status_widget = StatusWidget(self)
        self._config_widget = ConfigWidget(self)
        self._memory_widget = MemoryWidget(self)
        self._cron_widget = CronWidget(self)
        self._skills_widget = SkillsWidget(self)
        self._gateway_widget = GatewayWidget(self)

        self._tab_widget.addTab(self._agent_widget, self.tr("Agent 管理"))
        self._tab_widget.addTab(self._status_widget, self.tr("部署状态"))
        self._tab_widget.addTab(self._config_widget, self.tr("配置管理"))
        self._tab_widget.addTab(self._memory_widget, self.tr("Memory 浏览"))
        self._tab_widget.addTab(self._cron_widget, self.tr("定时任务"))
        self._tab_widget.addTab(self._skills_widget, self.tr("Skills 管理"))
        self._tab_widget.addTab(self._gateway_widget, self.tr("消息网关"))

        # 连接 Agent 管理的"在终端中打开"信号
        self._agent_widget.open_terminal_requested.connect(self._on_open_terminal_requested)

        # 连接 Tab 切换信号 — 切换时懒加载当前 Tab 数据
        self._tab_widget.currentChanged.connect(self._on_tab_changed)

        # 连接模式切换信号 — 用户手动切换时才触发
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)

        # 刷新远程连接列表（不触发加载）
        self._refresh_connections()

        # 设置鼠标样式：默认箭头，按钮/Tab/下拉框为手指
        self._setup_cursors()

    def _refresh_connections(self):
        """刷新远程连接列表"""
        # 保留第一项"本地"
        while self._mode_combo.count() > 1:
            self._mode_combo.removeItem(1)
        # 添加所有活跃的 SSH 连接
        if hasattr(self._main_dialog, 'ssh_clients'):
            for conn_id, ssh_conn in self._main_dialog.ssh_clients.items():
                label = f"远程: {getattr(ssh_conn, 'hostname', conn_id)}"
                self._mode_combo.addItem(label, conn_id)

    def showEvent(self, event):
        """面板首次显示时初始化 backend 并加载第一个 Tab"""
        super().showEvent(event)
        if self._backend is None:
            self._on_mode_changed(self._mode_combo.currentIndex())

    def _on_mode_changed(self, index):
        """切换连接模式：创建 backend，通知子 widget 更新引用，刷新当前 Tab"""
        from core.hermes.backend import LocalBackend, RemoteBackend
        mode_data = self._mode_combo.itemData(index)
        if mode_data == "local":
            self._backend = LocalBackend()
        else:
            # 远程模式
            ssh_conn = self._main_dialog.ssh_clients.get(mode_data)
            if ssh_conn:
                self._backend = RemoteBackend(ssh_conn)
            else:
                self._backend = LocalBackend()  # fallback
        # 通知所有子 widget 更新 backend 引用（不触发加载）
        self._notify_backend_changed()
        # 只刷新当前可见的 Tab
        current_widget = self._tab_widget.currentWidget()
        if current_widget and hasattr(current_widget, 'refresh'):
            current_widget.refresh()

    def _on_tab_changed(self, index):
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
        return self._backend

    def _on_open_terminal_requested(self, profile_name):
        """Agent 管理请求打开终端"""
        if self._main_dialog:
            self._main_dialog.open_agent_terminal(profile_name)

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
