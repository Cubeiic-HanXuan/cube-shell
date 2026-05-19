"""
命令执行历史面板组件

提供历史记录浏览、全文搜索、收藏管理等功能。
"""

import time
from datetime import datetime, timedelta

from PySide6.QtCore import Signal, Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

# 风险等级显示映射
_RISK_LABELS = {
    "safe": ("安全", "#4caf50"),
    "low": ("低", "#8bc34a"),
    "medium": ("中", "#ff9800"),
    "high": ("高", "#f44336"),
}

# 退出码图标
_EXIT_ICON = {True: "✓", False: "✗", None: "…"}


def _format_time(timestamp: float) -> str:
    """将 Unix 时间戳格式化为可读的时间字符串。"""
    dt = datetime.fromtimestamp(timestamp)
    return dt.strftime("%H:%M")


def _date_label(timestamp: float) -> str:
    """根据时间戳返回日期分组标签（今天/昨天/具体日期）。"""
    dt = datetime.fromtimestamp(timestamp)
    today = datetime.now().date()
    delta = today - dt.date()
    if delta == timedelta(0):
        return "📅 今天"
    elif delta == timedelta(days=1):
        return "📅 昨天"
    else:
        return f"📅 {dt.strftime('%Y-%m-%d')}"


class HistoryPanel(QWidget):
    """命令执行历史面板"""

    # 信号
    command_selected = Signal(str)  # 用户选择了某条命令（用于重新执行）
    command_copied = Signal(str)    # 命令被复制

    def __init__(self, audit_logger, parent=None):
        """
        Args:
            audit_logger: AuditLogger 实例
        """
        super().__init__(parent)
        self._logger = audit_logger
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self._do_search)
        self._init_ui()

    def _init_ui(self):
        """初始化 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # ---------- 顶部标题栏 ----------
        header = QHBoxLayout()
        title_label = QLabel("历史记录")
        title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        header.addWidget(title_label)
        header.addStretch()

        self._clear_btn = QPushButton("清空")
        self._clear_btn.setFixedWidth(50)
        self._clear_btn.clicked.connect(self._on_clear)
        header.addWidget(self._clear_btn)
        layout.addLayout(header)

        # ---------- 搜索栏 ----------
        search_layout = QHBoxLayout()
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("搜索命令历史...")
        self._search_input.setClearButtonEnabled(True)
        self._search_input.textChanged.connect(self._on_search_text_changed)
        search_layout.addWidget(self._search_input)
        layout.addLayout(search_layout)

        # ---------- Tab 切换 ----------
        self._tabs = QTabWidget()

        # 最近历史 Tab
        self._recent_list = QListWidget()
        self._recent_list.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._recent_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._recent_list.customContextMenuRequested.connect(
            lambda pos: self._show_context_menu(self._recent_list, pos)
        )
        self._tabs.addTab(self._recent_list, "最近")

        # 收藏 Tab
        self._favorites_list = QListWidget()
        self._favorites_list.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._favorites_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._favorites_list.customContextMenuRequested.connect(
            lambda pos: self._show_context_menu(self._favorites_list, pos)
        )
        self._tabs.addTab(self._favorites_list, "收藏")

        layout.addWidget(self._tabs)

    # ------------------------------------------------------------------ #
    #  公共接口
    # ------------------------------------------------------------------ #

    def refresh(self):
        """刷新历史列表和收藏列表"""
        self._load_recent()
        self._load_favorites()

    # ------------------------------------------------------------------ #
    #  内部方法 — 数据加载
    # ------------------------------------------------------------------ #

    def _load_recent(self):
        """加载最近的命令历史"""
        self._recent_list.clear()
        records = self._logger.query_history(limit=200)
        self._populate_history_list(self._recent_list, records)

    def _load_favorites(self):
        """加载收藏列表"""
        self._favorites_list.clear()
        favorites = self._logger.get_favorites()
        for fav in favorites:
            text = fav["command"]
            if fav.get("description"):
                text = f"{fav['command']}  — {fav['description']}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, {"type": "favorite", **fav})
            self._favorites_list.addItem(item)

    def _populate_history_list(self, list_widget: QListWidget, records: list[dict]):
        """将审计记录填充到 QListWidget 中，按日期分组。"""
        current_date_label = None
        for record in records:
            # 日期分组标题
            dl = _date_label(record["timestamp"])
            if dl != current_date_label:
                current_date_label = dl
                header_item = QListWidgetItem(dl)
                header_item.setFlags(Qt.ItemFlag.NoItemFlags)
                header_item.setData(Qt.ItemDataRole.UserRole, {"type": "header"})
                font = header_item.font()
                font.setBold(True)
                header_item.setFont(font)
                list_widget.addItem(header_item)

            # 命令条目
            risk_label, risk_color = _RISK_LABELS.get(
                record.get("risk_level", "safe"), ("?", "#999")
            )
            exit_ok = (
                record.get("exit_code") == 0
                if record.get("exit_code") is not None
                else None
            )
            exit_icon = _EXIT_ICON[exit_ok]
            time_str = _format_time(record["timestamp"])

            cmd_display = record["command"]
            if len(cmd_display) > 50:
                cmd_display = cmd_display[:47] + "..."

            text = f"  {cmd_display}    [{risk_label}] {exit_icon}  {time_str}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, {"type": "record", **record})
            item.setToolTip(record["command"])
            list_widget.addItem(item)

    # ------------------------------------------------------------------ #
    #  搜索
    # ------------------------------------------------------------------ #

    def _on_search_text_changed(self, text: str):
        """搜索文本变化时启动延迟搜索。"""
        self._search_timer.start()

    def _do_search(self):
        """执行搜索"""
        text = self._search_input.text().strip()
        if not text:
            self._load_recent()
            return

        self._recent_list.clear()
        results = self._logger.search(text, limit=100)
        self._populate_history_list(self._recent_list, results)

    # ------------------------------------------------------------------ #
    #  交互事件
    # ------------------------------------------------------------------ #

    def _on_item_double_clicked(self, item: QListWidgetItem):
        """双击条目重新执行"""
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data or data.get("type") == "header":
            return
        command = data.get("command", "")
        if command:
            self.command_selected.emit(command)

    def _show_context_menu(self, list_widget: QListWidget, pos):
        """右键菜单：复制/收藏/在终端执行"""
        item = list_widget.itemAt(pos)
        if not item:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data or data.get("type") == "header":
            return

        command = data.get("command", "")
        menu = QMenu(self)

        # 复制命令
        copy_action = QAction("复制命令", self)
        copy_action.triggered.connect(lambda: self._copy_command(command))
        menu.addAction(copy_action)

        # 在终端执行
        exec_action = QAction("在终端执行", self)
        exec_action.triggered.connect(lambda: self.command_selected.emit(command))
        menu.addAction(exec_action)

        menu.addSeparator()

        if data.get("type") == "record":
            # 添加到收藏
            fav_action = QAction("添加到收藏", self)
            fav_action.triggered.connect(lambda: self._add_to_favorites(command))
            menu.addAction(fav_action)
        elif data.get("type") == "favorite":
            # 从收藏删除
            remove_action = QAction("取消收藏", self)
            remove_action.triggered.connect(
                lambda: self._remove_from_favorites(data.get("id"))
            )
            menu.addAction(remove_action)

        menu.exec(list_widget.viewport().mapToGlobal(pos))

    def _copy_command(self, command: str):
        """复制命令到剪贴板"""
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(command)
        self.command_copied.emit(command)

    def _add_to_favorites(self, command: str):
        """将命令添加到收藏"""
        desc, ok = QInputDialog.getText(self, "添加收藏", "备注说明（可选）：")
        if ok:
            self._logger.add_favorite(command, description=desc)
            self._load_favorites()

    def _remove_from_favorites(self, favorite_id: int):
        """从收藏中删除"""
        if favorite_id is None:
            return
        self._logger.remove_favorite(favorite_id)
        self._load_favorites()

    def _on_clear(self):
        """清空历史"""
        reply = QMessageBox.question(
            self,
            "确认清空",
            "确定要清空所有历史记录吗？\n此操作不可撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._logger.cleanup(
                retention_days={"safe": 0, "low": 0, "medium": 0, "high": 0}
            )
            self.refresh()
