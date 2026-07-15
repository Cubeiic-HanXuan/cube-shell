"""带有紧邻式新建本机终端按钮的终端标签组件。"""

from PySide6.QtCore import QEvent, QPoint, QTimer, Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QTabWidget, QToolButton


class TerminalTabWidget(QTabWidget):
    """让 ``+`` 按钮始终紧跟最后一个真实标签的标签组件。

    ``QTabWidget.setCornerWidget`` 会将控件固定在组件最右侧，标签较少时
    会在最后一个标签和按钮之间留下较大空隙。本组件改为根据最后一个
    标签的矩形位置放置按钮，并限制标签栏宽度，确保标签溢出时滚动控件
    仍然可用。
    """

    newLocalTerminalRequested = Signal()

    _BUTTON_WIDTH = 28
    _BUTTON_GAP = 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self._position_update_pending = False

        self.new_local_terminal_button = QToolButton(self)
        self.new_local_terminal_button.setObjectName("newLocalTerminalButton")
        self.new_local_terminal_button.setText("+")
        self.new_local_terminal_button.setToolTip(self.tr("新建本机终端"))
        self.new_local_terminal_button.setAccessibleName(self.tr("新建本机终端"))
        self.new_local_terminal_button.setCursor(QCursor(Qt.PointingHandCursor))
        self.new_local_terminal_button.setFocusPolicy(Qt.StrongFocus)
        self.new_local_terminal_button.setAutoRaise(True)
        self.new_local_terminal_button.setStyleSheet("""
            QToolButton#newLocalTerminalButton {
                padding: 0;
                margin: 0;
                border-bottom: 0;
                border-radius: 2px;
                font-size: 20px;
                font-weight: 400;
            }
            QToolButton#newLocalTerminalButton:pressed {
                background-color: palette(mid);
            }
            QToolButton#newLocalTerminalButton:focus {
                border-color: palette(highlight);
            }
        """)
        self.new_local_terminal_button.clicked.connect(self.newLocalTerminalRequested)

        tab_bar = self.tabBar()
        tab_bar.tabMoved.connect(self._schedule_new_terminal_button_position)
        tab_bar.installEventFilter(self)
        self._schedule_new_terminal_button_position()

    def tabInserted(self, index):
        super().tabInserted(index)
        self._schedule_new_terminal_button_position()

    def tabRemoved(self, index):
        super().tabRemoved(index)
        self._schedule_new_terminal_button_position()

    def takeTab(self, index):
        """从标签栏摘除并返回指定页面，但不删除该页面。

        此方法返回后，调用方可以安全停止子进程：任何同步触发的完成信号
        都无法再从标签栏中找到已摘除的页面，因此不会递归删除占据相同
        索引的其他标签。
        """
        page = self.widget(index)
        if page is not None:
            self.removeTab(index)
        return page

    def beginTabClose(self, page):
        """将 ``page`` 标记为正在关闭，并拒绝重入的关闭请求。"""
        if page is None or self.indexOf(page) < 0:
            return False
        if bool(page.property("cubeShellTabClosing")):
            return False
        page.setProperty("cubeShellTabClosing", True)
        return True

    def finishTabClose(self, page):
        """仅当关闭失败且页面仍在标签栏中时，清除关闭标记。"""
        if page is not None and self.indexOf(page) >= 0:
            page.setProperty("cubeShellTabClosing", False)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._schedule_new_terminal_button_position()

    def showEvent(self, event):
        super().showEvent(event)
        self._schedule_new_terminal_button_position()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.StyleChange, QEvent.FontChange, QEvent.PaletteChange):
            self._schedule_new_terminal_button_position()

    def eventFilter(self, watched, event):
        if watched is self.tabBar() and event.type() in (
            QEvent.Resize,
            QEvent.Move,
            QEvent.Show,
            QEvent.LayoutRequest,
        ):
            self._schedule_new_terminal_button_position()
        return super().eventFilter(watched, event)

    def _schedule_new_terminal_button_position(self, *_args):
        if self._position_update_pending:
            return
        self._position_update_pending = True
        QTimer.singleShot(0, self._position_new_terminal_button)

    def _position_new_terminal_button(self):
        self._position_update_pending = False
        tab_bar = self.tabBar()
        tab_count = tab_bar.count()

        # 在右侧为按钮预留紧凑空间。标签无法全部显示时，QTabBar 会将自身的
        # 滚动按钮限制在此最大宽度内，因此悬浮按钮不会遮挡滚动按钮。
        max_tab_bar_width = max(0, self.width() - self._BUTTON_WIDTH - self._BUTTON_GAP - 2)
        if tab_bar.maximumWidth() != max_tab_bar_width:
            tab_bar.setMaximumWidth(max_tab_bar_width)
            self._schedule_new_terminal_button_position()

        if tab_count:
            last_tab_rect = tab_bar.tabRect(tab_count - 1)
            tab_height = max(20, last_tab_rect.height())
            tab_bar_origin = tab_bar.mapTo(self, QPoint(0, 0))
            desired_x = tab_bar_origin.x() + last_tab_rect.right() + 1 + self._BUTTON_GAP
            desired_y = tab_bar_origin.y() + last_tab_rect.y()
        else:
            tab_height = max(20, tab_bar.sizeHint().height())
            tab_bar_origin = tab_bar.mapTo(self, QPoint(0, 0))
            desired_x = tab_bar_origin.x()
            desired_y = tab_bar_origin.y()

        button_size = (self._BUTTON_WIDTH, tab_height)
        if (self.new_local_terminal_button.width(), self.new_local_terminal_button.height()) != button_size:
            self.new_local_terminal_button.setFixedSize(*button_size)

        # 标签溢出时，tabRect(last) 可能位于标签栏可见区域之外。
        # 将按钮限制在预留空间内，确保按钮始终可以点击。
        max_x = max(0, self.rect().right() - self.new_local_terminal_button.width())
        button_x = max(0, min(desired_x, max_x))
        self.new_local_terminal_button.move(button_x, max(0, desired_y))
        self.new_local_terminal_button.show()
        self.new_local_terminal_button.raise_()
