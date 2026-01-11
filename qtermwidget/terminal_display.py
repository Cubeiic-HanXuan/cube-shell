#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
TerminalDisplay Widget for Python PySide6
Converted from Konsole's TerminalDisplay.cpp/h

Copyright 2006-2008 by Robert Knight <robertknight@gmail.com>
Copyright 1997,1998 by Lars Doelle <lars.doelle@on-line.de>

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.
"""

from enum import Enum
from typing import Optional, List, Tuple
from typing import TYPE_CHECKING

from PySide6.QtCore import (
    Qt, QTimer, QPoint, QRect, QSize, QPointF, QRectF,
    Signal, Slot, QObject, QEvent, QMimeData
)
from PySide6.QtGui import (
    QPainter, QPaintEvent, QResizeEvent, QMouseEvent, QKeyEvent,
    QFocusEvent, QShowEvent, QHideEvent, QWheelEvent, QDragEnterEvent,
    QDropEvent, QFont, QFontMetrics, QColor, QPalette, QPen, QBrush,
    QPixmap, QCursor, QInputMethodEvent, QEnterEvent, QFontInfo,
    QClipboard, QRegion, QDrag
)
from PySide6.QtWidgets import (
    QWidget, QScrollBar, QGridLayout, QLabel, QMessageBox, QStyle, QSizePolicy, QSpacerItem, QApplication
)

from qtermwidget.character import (
    Character, ColorEntry, CharacterColor,
    RE_BOLD, RE_BLINK, RE_UNDERLINE, RE_REVERSE,
    RE_ITALIC, RE_CURSOR,
    RE_STRIKEOUT, RE_CONCEAL, RE_OVERLINE,
    DEFAULT_FORE_COLOR, DEFAULT_BACK_COLOR
)
from qtermwidget.character_color import TABLE_COLORS  # Character color definitions
# Import the already implemented modules
from qtermwidget.filter import FilterChain, Filter, TerminalImageFilterChain  # Filter.h implementation
from qtermwidget.screen_window import ScreenWindow  # ScreenWindow implementation
from qtermwidget.wcwidth import konsole_wcwidth

# 避免循环导入 - QTermWidget将在需要时动态导入
# from .qtermwidget import QTermWidget  # LineFont.h
if TYPE_CHECKING:
    pass

# Constants
REPCHAR = "ABCDEFGHIJKLMNOPQRSTUVWXYZ" + "abcdefgjijklmnopqrstuvwxyz" + "0123456789./+@"

DEFAULT_FORE_COLOR = 0
DEFAULT_BACK_COLOR = 1
TEXT_BLINK_DELAY = 500

# Line drawing characters mapping
VT100_GRAPHICS = [
    0x0020, 0x25C6, 0x2592, 0x2409, 0x240c, 0x240d, 0x240a, 0x00b0,
    0x00b1, 0x2424, 0x240b, 0x2518, 0x2510, 0x250c, 0x2514, 0x253c,
    0xF800, 0xF801, 0x2500, 0xF803, 0xF804, 0x251c, 0x2524, 0x2534,
    0x252c, 0x2502, 0x2264, 0x2265, 0x03C0, 0x2260, 0x00A3, 0x00b7
]

# LTR override character for forcing text direction
LTR_OVERRIDE_CHAR = chr(0x202D)


# Line encoding constants for drawing line characters
class LineEncode:
    TopL = (1 << 1)
    TopC = (1 << 2)
    TopR = (1 << 3)

    LeftT = (1 << 5)
    Int11 = (1 << 6)
    Int12 = (1 << 7)
    Int13 = (1 << 8)
    RightT = (1 << 9)

    LeftC = (1 << 10)
    Int21 = (1 << 11)
    Int22 = (1 << 12)
    Int23 = (1 << 13)
    RightC = (1 << 14)

    LeftB = (1 << 15)
    Int31 = (1 << 16)
    Int32 = (1 << 17)
    Int33 = (1 << 18)
    RightB = (1 << 19)

    BotL = (1 << 21)
    BotC = (1 << 22)
    BotR = (1 << 23)


# LineFont character mappings - CORRECT VALUES from LineFont.h
LINE_CHARS = [
                 0x00007c00, 0x000fffe0, 0x00421084, 0x00e739ce, 0x00000000, 0x00000000, 0x00000000, 0x00000000,
                 0x00000000, 0x00000000, 0x00000000, 0x00000000, 0x00427000, 0x004e7380, 0x00e77800, 0x00ef7bc0,
                 0x00421c00, 0x00439ce0, 0x00e73c00, 0x00e7bde0, 0x00007084, 0x000e7384, 0x000079ce, 0x000f7bce,
                 0x00001c84, 0x00039ce4, 0x00003dce, 0x0007bdee, 0x00427084, 0x004e7384, 0x004279ce, 0x00e77884,
                 0x00e779ce, 0x004f7bce, 0x00ef7bc4, 0x00ef7bce, 0x00421c84, 0x00439ce4, 0x00423dce, 0x00e73c84,
                 0x00e73dce, 0x0047bdee, 0x00e7bde4, 0x00e7bdee, 0x00427c00, 0x0043fce0, 0x004e7f80, 0x004fffe0,
                 0x004fffe0, 0x00e7fde0, 0x006f7fc0, 0x00efffe0, 0x00007c84, 0x0003fce4, 0x000e7f84, 0x000fffe4,
                 0x00007dce, 0x0007fdee, 0x000f7fce, 0x000fffee, 0x00427c84, 0x0043fce4, 0x004e7f84, 0x004fffe4,
                 0x00427dce, 0x00e77c84, 0x00e77dce, 0x0047fdee, 0x004e7fce, 0x00e7fde4, 0x00ef7f84, 0x004fffee,
                 0x00efffe4, 0x00e7fdee, 0x00ef7fce, 0x00efffee, 0x00000000, 0x00000000, 0x00000000, 0x00000000,
                 0x000f83e0, 0x00a5294a, 0x004e1380, 0x00a57800, 0x00ad0bc0, 0x004390e0, 0x00a53c00, 0x00a5a1e0,
                 0x000e1384, 0x0000794a, 0x000f0b4a, 0x000390e4, 0x00003d4a, 0x0007a16a, 0x004e1384, 0x00a5694a,
                 0x00ad2b4a, 0x004390e4, 0x00a52d4a, 0x00a5a16a, 0x004f83e0, 0x00a57c00, 0x00ad83e0, 0x000f83e4,
                 0x00007d4a, 0x000f836a, 0x004f93e4, 0x00a57d4a, 0x00ad836a, 0x00000000, 0x00000000, 0x00000000,
                 0x00000000, 0x00000000, 0x00000000, 0x00000000, 0x00001c00, 0x00001084, 0x00007000, 0x00421000,
                 0x00039ce0, 0x000039ce, 0x000e7380, 0x00e73800, 0x000e7f80, 0x00e73884, 0x0003fce0, 0x004239ce
             ] + [0] * 128  # Extend to 256 elements with zeros for unused entries

# Global variables for mouse handling (equivalent to C++ static variables)
_gs_dead_spot = QPoint(-1, -1)
_gs_future_dead_spot = QPoint()


# Helper functions for drawing line characters
def draw_line_char(painter: QPainter, x: int, y: int, w: int, h: int, code: int):
    """Draw a line character using the given code"""
    if code >= len(LINE_CHARS):
        return

    # Calculate cell midpoints and endpoints
    cx = x + w // 2
    cy = y + h // 2
    ex = x + w - 1
    ey = y + h - 1

    to_draw = LINE_CHARS[code]

    # Top lines
    if to_draw & LineEncode.TopL:
        painter.drawLine(cx - 1, y, cx - 1, cy - 2)
    if to_draw & LineEncode.TopC:
        painter.drawLine(cx, y, cx, cy - 2)
    if to_draw & LineEncode.TopR:
        painter.drawLine(cx + 1, y, cx + 1, cy - 2)

    # Bottom lines
    if to_draw & LineEncode.BotL:
        painter.drawLine(cx - 1, cy + 2, cx - 1, ey)
    if to_draw & LineEncode.BotC:
        painter.drawLine(cx, cy + 2, cx, ey)
    if to_draw & LineEncode.BotR:
        painter.drawLine(cx + 1, cy + 2, cx + 1, ey)

    # Left lines
    if to_draw & LineEncode.LeftT:
        painter.drawLine(x, cy - 1, cx - 2, cy - 1)
    if to_draw & LineEncode.LeftC:
        painter.drawLine(x, cy, cx - 2, cy)
    if to_draw & LineEncode.LeftB:
        painter.drawLine(x, cy + 1, cx - 2, cy + 1)

    # Right lines
    if to_draw & LineEncode.RightT:
        painter.drawLine(cx + 2, cy - 1, ex, cy - 1)
    if to_draw & LineEncode.RightC:
        painter.drawLine(cx + 2, cy, ex, cy)
    if to_draw & LineEncode.RightB:
        painter.drawLine(cx + 2, cy + 1, ex, cy + 1)

    # Intersection points
    if to_draw & LineEncode.Int11:
        painter.drawPoint(cx - 1, cy - 1)
    if to_draw & LineEncode.Int12:
        painter.drawPoint(cx, cy - 1)
    if to_draw & LineEncode.Int13:
        painter.drawPoint(cx + 1, cy - 1)

    if to_draw & LineEncode.Int21:
        painter.drawPoint(cx - 1, cy)
    if to_draw & LineEncode.Int22:
        painter.drawPoint(cx, cy)
    if to_draw & LineEncode.Int23:
        painter.drawPoint(cx + 1, cy)

    if to_draw & LineEncode.Int31:
        painter.drawPoint(cx - 1, cy + 1)
    if to_draw & LineEncode.Int32:
        painter.drawPoint(cx, cy + 1)
    if to_draw & LineEncode.Int33:
        painter.drawPoint(cx + 1, cy + 1)


def draw_other_char(painter: QPainter, x: int, y: int, w: int, h: int, code: int):
    """Draw special characters like double dashes, rounded corners, diagonals"""
    # Calculate cell midpoints and endpoints
    cx = x + w // 2
    cy = y + h // 2
    ex = x + w - 1
    ey = y + h - 1

    # Double dashes
    if 0x4C <= code <= 0x4F:
        x_half_gap = max(w // 15, 1)
        y_half_gap = max(h // 15, 1)

        if code == 0x4D:  # BOX DRAWINGS HEAVY DOUBLE DASH HORIZONTAL
            painter.drawLine(x, cy - 1, cx - x_half_gap - 1, cy - 1)
            painter.drawLine(x, cy + 1, cx - x_half_gap - 1, cy + 1)
            painter.drawLine(cx + x_half_gap, cy - 1, ex, cy - 1)
            painter.drawLine(cx + x_half_gap, cy + 1, ex, cy + 1)
            # Falls through to 0x4C case
        if code == 0x4C or code == 0x4D:  # BOX DRAWINGS LIGHT DOUBLE DASH HORIZONTAL
            painter.drawLine(x, cy, cx - x_half_gap - 1, cy)
            painter.drawLine(cx + x_half_gap, cy, ex, cy)
        elif code == 0x4F:  # BOX DRAWINGS HEAVY DOUBLE DASH VERTICAL
            painter.drawLine(cx - 1, y, cx - 1, cy - y_half_gap - 1)
            painter.drawLine(cx + 1, y, cx + 1, cy - y_half_gap - 1)
            painter.drawLine(cx - 1, cy + y_half_gap, cx - 1, ey)
            painter.drawLine(cx + 1, cy + y_half_gap, cx + 1, ey)
            # Falls through to 0x4E case
        if code == 0x4E or code == 0x4F:  # BOX DRAWINGS LIGHT DOUBLE DASH VERTICAL
            painter.drawLine(cx, y, cx, cy - y_half_gap - 1)
            painter.drawLine(cx, cy + y_half_gap, cx, ey)

    # Rounded corner characters
    elif 0x6D <= code <= 0x70:
        r = w * 3 // 8
        d = 2 * r

        if code == 0x6D:  # BOX DRAWINGS LIGHT ARC DOWN AND RIGHT
            painter.drawLine(cx, cy + r, cx, ey)
            painter.drawLine(cx + r, cy, ex, cy)
            painter.drawArc(cx, cy, d, d, 90 * 16, 90 * 16)
        elif code == 0x6E:  # BOX DRAWINGS LIGHT ARC DOWN AND LEFT
            painter.drawLine(cx, cy + r, cx, ey)
            painter.drawLine(x, cy, cx - r, cy)
            painter.drawArc(cx - d, cy, d, d, 0 * 16, 90 * 16)
        elif code == 0x6F:  # BOX DRAWINGS LIGHT ARC UP AND LEFT
            painter.drawLine(cx, y, cx, cy - r)
            painter.drawLine(x, cy, cx - r, cy)
            painter.drawArc(cx - d, cy - d, d, d, 270 * 16, 90 * 16)
        elif code == 0x70:  # BOX DRAWINGS LIGHT ARC UP AND RIGHT
            painter.drawLine(cx, y, cx, cy - r)
            painter.drawLine(cx + r, cy, ex, cy)
            painter.drawArc(cx, cy - d, d, d, 180 * 16, 90 * 16)

    # Diagonals
    elif 0x71 <= code <= 0x73:
        if code == 0x71:  # BOX DRAWINGS LIGHT DIAGONAL UPPER RIGHT TO LOWER LEFT
            painter.drawLine(ex, y, x, ey)
        elif code == 0x72:  # BOX DRAWINGS LIGHT DIAGONAL UPPER LEFT TO LOWER RIGHT
            painter.drawLine(x, y, ex, ey)
        elif code == 0x73:  # BOX DRAWINGS LIGHT DIAGONAL CROSS
            painter.drawLine(ex, y, x, ey)
            painter.drawLine(x, y, ex, ey)


# Base color table
BASE_COLOR_TABLE = [
    # normal - 修复前景色和背景色对比度问题
    ColorEntry(QColor(0xFF, 0xFF, 0xFF), False), ColorEntry(QColor(0x00, 0x00, 0x00), True),  # 白色前景, 黑色背景
    ColorEntry(QColor(0xFF, 0xFF, 0xFF), False), ColorEntry(QColor(0xB2, 0x18, 0x18), False),  # Black, Red
    ColorEntry(QColor(0x18, 0xB2, 0x18), False), ColorEntry(QColor(0xB2, 0x68, 0x18), False),  # Green, Yellow
    ColorEntry(QColor(0x18, 0x18, 0xB2), False), ColorEntry(QColor(0xB2, 0x18, 0xB2), False),  # Blue, Magenta
    ColorEntry(QColor(0x18, 0xB2, 0xB2), False), ColorEntry(QColor(0xB2, 0xB2, 0xB2), False),  # Cyan, White
    # intensive
    ColorEntry(QColor(0x80, 0x80, 0x80), False), ColorEntry(QColor(0xFF, 0xFF, 0xFF), True),
    ColorEntry(QColor(0x68, 0x68, 0x68), False), ColorEntry(QColor(0xFF, 0x54, 0x54), False),
    ColorEntry(QColor(0x54, 0xFF, 0x54), False), ColorEntry(QColor(0xFF, 0xFF, 0x54), False),
    ColorEntry(QColor(0x54, 0x54, 0xFF), False), ColorEntry(QColor(0xFF, 0x54, 0xFF), False),
    ColorEntry(QColor(0x54, 0xFF, 0xFF), False), ColorEntry(QColor(0xFF, 0xFF, 0xFF), False)
]


class MotionAfterPasting(Enum):
    NoMoveScreenWindow = 0
    MoveStartScreenWindow = 1
    MoveEndScreenWindow = 2


class BackgroundMode(Enum):
    NONE = 0
    STRETCH = 1
    ZOOM = 2
    FIT = 3
    CENTER = 4


class BellMode(Enum):
    SystemBeepBell = 0
    NotifyBell = 1
    VisualBell = 2
    NoBell = 3


class TripleClickMode(Enum):
    SelectWholeLine = 0
    SelectForwardsFromCursor = 1


class DragState(Enum):
    diNone = 0
    diPending = 1
    diDragging = 2


# 本地枚举定义 - 避免循环导入，与QTermWidget中的枚举保持一致
class ScrollBarPosition(Enum):
    """滚动条位置枚举 - 本地副本"""
    NoScrollBar = 0
    ScrollBarLeft = 1
    ScrollBarRight = 2


class KeyboardCursorShape(Enum):
    """键盘光标形状枚举 - 本地副本"""
    BlockCursor = 0
    UnderlineCursor = 1
    IBeamCursor = 2


class ScrollBar(QScrollBar):
    """Custom ScrollBar with mouse handling"""

    def __init__(self, parent=None):
        super().__init__(parent)

    def enterEvent(self, event):
        # Show the mouse cursor that was auto-hidden
        # Implementation for mouse cursor handling
        super().enterEvent(event)


class AutoScrollHandler(QObject):
    """Handles auto-scrolling when dragging outside widget boundaries"""

    def __init__(self, parent):
        super().__init__(parent)
        self._timer_id = 0
        parent.installEventFilter(self)

    def timerEvent(self, event):
        if event.timerId() != self._timer_id:
            return

        widget = self.parent()
        mouse_event = QMouseEvent(
            QEvent.Type.MouseMove,
            widget.mapFromGlobal(QCursor.pos()),
            QCursor.pos(),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier
        )
        QApplication.sendEvent(widget, mouse_event)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseMove:
            mouse_event = event
            mouse_in_widget = self.parent().rect().contains(mouse_event.pos())

            if mouse_in_widget:
                if self._timer_id:
                    self.killTimer(self._timer_id)
                self._timer_id = 0
            else:
                if not self._timer_id and (mouse_event.buttons() & Qt.MouseButton.LeftButton):
                    self._timer_id = self.startTimer(100)

        elif event.type() == QEvent.Type.MouseButtonRelease:
            mouse_event = event
            if self._timer_id and (mouse_event.buttons() & ~Qt.MouseButton.LeftButton):
                self.killTimer(self._timer_id)
                self._timer_id = 0

        return False


class TerminalDisplay(QWidget):
    """
    A widget which displays output from a terminal emulation and sends input
    keypresses and mouse activity to the terminal.
    """

    # Signals
    keyPressedSignal = Signal(QKeyEvent, bool)  # keyEvent, fromPaste
    mouseSignal = Signal(int, int, int, int)  # button, column, line, eventType
    changedFontMetricSignal = Signal(int, int)  # height, width
    changedContentSizeSignal = Signal(int, int)  # height, width
    configureRequest = Signal(QPoint)  # position
    overrideShortcutCheck = Signal(QKeyEvent, bool)  # keyEvent, override
    isBusySelecting = Signal(bool)
    sendStringToEmu = Signal(bytes)
    copyAvailable = Signal(bool)
    termGetFocus = Signal()
    termLostFocus = Signal()
    notifyBell = Signal(str)
    usesMouseChanged = Signal()

    # Class variables - C++ style naming
    _antialiasText = True
    HAVE_TRANSPARENCY = True
    _hideMouseTimer = None

    def __init__(self, parent=None):
        """Initialize the TerminalDisplay widget"""
        super().__init__(parent)

        # 修复：添加缺失的核心变量
        self._screenWindow = None  # 关键：终端屏幕窗口

        # Basic variables
        self._image = None
        self._size = QSize()
        self._lines = 24
        self._columns = 80
        self._usedLines = 0
        self._usedColumns = 0
        self._contentHeight = 0
        self._contentWidth = 0
        self._fontHeight = 15
        self._fontWidth = 7
        self._fontAscent = 13
        self._boldIntense = True
        self._line_properties = []

        # Color and drawing
        # 修复：正确初始化颜色表大小
        from .character_color import ColorEntry
        self._color_table = [ColorEntry() for _ in range(TABLE_COLORS)]
        # 使用默认颜色表填充前16个条目
        default_colors = self._default_color_table()
        for i in range(min(len(default_colors), len(self._color_table))):
            self._color_table[i] = default_colors[i]
        self._randomSeed = 0
        self._margin = 1
        self._topMargin = 1
        self._leftMargin = 1
        self._drawTextTestFlag = False
        self._drawTextAdditionHeight = 0

        # Layout
        self._grid_layout = None
        self._resizing = False
        self._terminal_size_hint = False
        self._terminal_size_startup = True
        self._bidi_enabled = True
        self._mouse_marks = False
        self._bracketed_paste_mode = False
        self._disabled_bracketed_paste_mode = False

        # Selection
        self._i_pnt_sel = QPoint()  # Initial selection point
        self._pnt_sel = QPoint()  # Current selection point
        self._triple_sel_begin = QPoint()  # Help avoid flicker
        self._act_sel = 0
        self._word_selection_mode = False
        self._line_selection_mode = False
        self._preserve_line_breaks = False
        self._column_selection_mode = False

        # Scrollbar
        self._scrollbar_location = ScrollBarPosition.NoScrollBar
        self._scroll_bar = None
        self._scroll_bar_connected = False  # 跟踪滚动条连接状态

        # Other settings
        self._word_characters = ":@-./_~"
        self._bell_mode = BellMode.SystemBeepBell
        self._allowBell = True  # 修复：初始化bell允许标志

        # Blinking - 修复：与C++一致的光标闪烁初始化
        self._blinking = False
        self._has_blinker = False
        self._cursor_blinking = False  # 修复：初始化为False，表示光标应该显示
        self._has_blinking_cursor = False  # 修复：默认禁用光标闪烁
        self._allow_blinking_text = True
        self._ctrl_drag = False
        self._triple_click_mode = TripleClickMode.SelectWholeLine
        self._is_fixed_size = False

        # Timers
        self._blink_timer = None
        self._blink_cursor_timer = None

        # UI elements
        self._possible_triple_click = False
        self._resize_widget = None
        self._resize_timer = None
        self._flow_control_warning_enabled = False
        self._output_suspended_label = None

        # Display settings
        self._line_spacing = 0
        self._colors_inverted = False
        self._opacity = 1.0
        self._background_image = QPixmap()
        self._background_mode = BackgroundMode.NONE

        # Filter chain
        self._filter_chain = TerminalImageFilterChain()
        self._mouse_over_hotspot_area = QRegion()

        # Cursor - 修复：与C++一致的光标设置
        self._cursor_shape = KeyboardCursorShape.BlockCursor
        self._cursor_color = QColor()  # 修复：初始化为无效颜色，使用前景色

        # Paste settings
        self._motion_after_pasting = MotionAfterPasting.NoMoveScreenWindow
        self._confirm_multiline_paste = False
        self._trim_pasted_trailing_newlines = False

        # Input method
        self._input_method_data = {
            'preedit_string': '',
            'previous_preedit_rect': QRect()
        }

        # Font settings
        self._fixed_font = True
        self._fixed_font_original = True
        self._left_base_margin = 1
        self._top_base_margin = 1
        self._draw_line_chars = True
        self._mouse_autohide_delay = -1

        # Drag info
        self._drag_info = {
            'state': DragState.diNone,
            'start': QPoint(),
            'drag_object': None
        }

        # Initialize the widget
        self._init_widget()

    def _init_widget(self):
        """正确的初始化顺序 - 修复版本"""

        # 1. 设置基本属性
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)

        # 2. 创建滚动条
        self._scroll_bar = ScrollBar(self)
        self._scroll_bar.hide()

        # 3. 设置布局
        self._grid_layout = QGridLayout(self)
        self._grid_layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(self._grid_layout)

        # 4. 连接信号
        self._setup_timers()

        # 5. 设置颜色表（关键修复）
        # 颜色表已在构造函数中正确初始化，无需额外设置

        # 6. 设置焦点和其他属性
        self.setFocusPolicy(Qt.FocusPolicy.WheelFocus)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)

        # 7. 确保图像初始化
        self._make_image()

        # 8. 修复：正确设置默认鼠标选择状态（与C++版本保持一致）
        # C++版本默认启用鼠标选择，除非终端程序特别请求鼠标事件
        self._mouse_marks = True  # 直接设置变量，避免过早的信号发送
        cursor = Qt.CursorShape.IBeamCursor if self._mouse_marks else Qt.CursorShape.ArrowCursor
        self.setCursor(cursor)

    def _default_color_table(self):
        """默认颜色表"""
        from .character_color import ColorEntry
        from PySide6.QtGui import QColor
        return [
            ColorEntry(QColor(0, 0, 0)),  # Black
            ColorEntry(QColor(178, 24, 24)),  # Red
            ColorEntry(QColor(24, 178, 24)),  # Green
            ColorEntry(QColor(178, 104, 24)),  # Yellow
            ColorEntry(QColor(24, 24, 178)),  # Blue
            ColorEntry(QColor(178, 24, 178)),  # Magenta
            ColorEntry(QColor(24, 178, 178)),  # Cyan
            ColorEntry(QColor(178, 178, 178)),  # White
            # 重复明亮版本
            ColorEntry(QColor(104, 104, 104)),  # Bright Black
            ColorEntry(QColor(255, 84, 84)),  # Bright Red
            ColorEntry(QColor(84, 255, 84)),  # Bright Green
            ColorEntry(QColor(255, 255, 84)),  # Bright Yellow
            ColorEntry(QColor(84, 84, 255)),  # Bright Blue
            ColorEntry(QColor(255, 84, 255)),  # Bright Magenta
            ColorEntry(QColor(84, 255, 255)),  # Bright Cyan
            ColorEntry(QColor(255, 255, 255)),  # Bright White
        ]

    def _setup_timers(self):
        """设置定时器"""
        # 闪烁定时器
        self._blink_timer = QTimer(self)
        self._blink_timer.timeout.connect(self._blink_event)

        # 光标闪烁定时器
        self._blink_cursor_timer = QTimer(self)
        self._blink_cursor_timer.timeout.connect(self._blink_cursor_event)

    def _blink_event(self):
        """闪烁事件处理"""
        self._blinking = not self._blinking
        # 更新显示
        self.update()

    def _blink_cursor_event(self):
        """光标闪烁事件处理"""
        self._cursor_blinking = not self._cursor_blinking
        # 更新光标区域
        self.update()

    def screenWindow(self) -> Optional[ScreenWindow]:
        """Returns the terminal screen section displayed in this widget"""
        return self._screenWindow

    def setScreenWindow(self, window: Optional[ScreenWindow]):
        """Sets the terminal screen section displayed in this widget"""
        # Disconnect existing screen window
        if self._screenWindow:
            self._screenWindow.outputChanged.disconnect()
            self._screenWindow.scrolled.disconnect()
            self._screenWindow.scrollToEnd.disconnect()

        self._screenWindow = window

        if window:
            window.outputChanged.connect(self.updateLineProperties)
            window.outputChanged.connect(self.updateImage)
            window.outputChanged.connect(self.updateFilters)
            window.selectionChanged.connect(self.updateImage)
            window.scrolled.connect(self.updateFilters)
            window.scrollToEnd.connect(self.scrollToEnd)

            # 设置窗口行数
            if hasattr(window, 'set_window_lines'):
                window.set_window_lines(self._lines)
            elif hasattr(window, 'setWindowLines'):
                window.setWindowLines(self._lines)

    def colorTable(self) -> List[ColorEntry]:
        """Returns the terminal color palette used by the display"""
        return self._color_table

    def setColorTable(self, table: List[ColorEntry]):
        """Sets the terminal color palette used by the display"""
        for i in range(min(len(table), TABLE_COLORS)):
            self._color_table[i] = table[i]

        self.setBackgroundColor(self._color_table[DEFAULT_BACK_COLOR].color)

    def setBackgroundColor(self, color: QColor):
        """Sets the background color of the terminal display"""
        self._color_table[DEFAULT_BACK_COLOR].color = color
        palette = self.palette()
        palette.setColor(self.backgroundRole(), color)
        self.setPalette(palette)

        # Avoid propagating palette change to scroll bar
        self._scroll_bar.setPalette(QApplication.palette())

        self.update()

    def setForegroundColor(self, color: QColor):
        """Sets the foreground color of the terminal display"""
        self._color_table[DEFAULT_FORE_COLOR].color = color
        self.update()

    def setRandomSeed(self, seed: int):
        """Sets the seed for random color generation"""
        self._random_seed = seed

    def randomSeed(self) -> int:
        """Returns the seed for random color generation"""
        return self._random_seed

    def setOpacity(self, opacity: float):
        """Sets the opacity of the terminal display"""
        self._opacity = max(0.0, min(opacity, 1.0))

    def setBackgroundImage(self, background_image: str):
        """Sets the background image"""
        if background_image:
            self._background_image.load(background_image)
            self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        else:
            self._background_image = QPixmap()
            self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)

    def setBackgroundMode(self, mode: BackgroundMode):
        """Sets the background image mode"""
        self._background_mode = mode

    def setScrollBarPosition(self, position: ScrollBarPosition):
        """Set scrollbar position"""
        self._scrollbar_location = position
        if position == ScrollBarPosition.NoScrollBar:
            self._scroll_bar.hide()
        else:
            self._scroll_bar.show()

        self._propagate_size()
        self.update()

    def _set_scroll(self, cursor: int, lines: int):
        """Sets scroll bar range and value"""
        # Avoid unnecessary updates
        if (self._scroll_bar.minimum() == 0 and
                self._scroll_bar.maximum() == (lines - self._lines) and
                self._scroll_bar.value() == cursor):
            return

        # 静默重新连接滚动条 - 避免警告
        # self._scroll_bar.valueChanged.disconnect()  # 断开所有连接，然后重新连接

        self._scroll_bar.setRange(0, lines - self._lines)
        self._scroll_bar.setSingleStep(1)
        self._scroll_bar.setPageStep(self._lines)
        self._scroll_bar.setValue(cursor)
        self._scroll_bar.valueChanged.connect(self.scrollBarPositionChanged)

    @Slot()
    def scrollToEnd(self):
        """Scrolls to the end of the terminal output"""
        try:
            # 断开特定的连接而不是所有连接，避免警告
            # 静默断开连接 - 使用blockSignals代替disconnect避免警告
            pass
        except (TypeError, RuntimeError):
            pass  # Signal was not connected

        self._scroll_bar.setValue(self._scroll_bar.maximum())
        self._scroll_bar.valueChanged.connect(self.scrollBarPositionChanged)

        if self._screenWindow:
            self._screenWindow.scrollTo(self._scroll_bar.value() + 1)
            self._screenWindow.setTrackOutput(self._screenWindow.atEndOfOutput())

    @Slot(int)
    def scrollBarPositionChanged(self, value: int):
        """Handles scroll bar position changes - 优化版本"""
        if not self._screenWindow:
            return

        # 节流滚动更新 - 避免频繁的updateImage调用
        if not hasattr(self, '_scroll_update_timer'):
            from PySide6.QtCore import QTimer
            self._scroll_update_timer = QTimer()
            self._scroll_update_timer.setSingleShot(True)
            self._scroll_update_timer.timeout.connect(self._delayed_scroll_update)

        # 设置目标滚动位置
        self._pending_scroll_value = value

        # 延迟更新，避免频繁调用
        if not self._scroll_update_timer.isActive():
            self._scroll_update_timer.start(16)  # 约60fps的更新率

    def _delayed_scroll_update(self):
        """延迟的滚动更新 - 减少重复计算"""
        if not self._screenWindow:
            return

        self._screenWindow.scrollTo(self._pending_scroll_value)

        # Enable auto-tracking if at end
        at_end = self._pending_scroll_value == self._scroll_bar.maximum()
        self._screenWindow.setTrackOutput(at_end)

        self.updateImage()

    # NEW METHOD: Set scroll - missing public method from C++
    def setScroll(self, cursor: int, lines: int):
        """Sets scroll bar range and value - C++ style public method"""
        # Avoid unnecessary updates
        if (self._scroll_bar.minimum() == 0 and
                self._scroll_bar.maximum() == (lines - self._lines) and
                self._scroll_bar.value() == cursor):
            return

        # 重新配置滚动条而不断开连接，避免警告
        self._scroll_bar.setRange(0, lines - self._lines)
        self._scroll_bar.setSingleStep(1)
        self._scroll_bar.setPageStep(self._lines)
        self._scroll_bar.setValue(cursor)
        self._scroll_bar.valueChanged.connect(self.scrollBarPositionChanged)

    def filterChain(self) -> FilterChain:
        """Returns the display's filter chain"""
        return self._filter_chain

    def processFilters(self):
        """Updates the filters in the display's filter chain"""
        if not self._screenWindow:
            return

        try:
            pre_update_hotspots = self._hot_spot_region()

            # 获取图像数据 - 兼容性处理
            image = self._screenWindow.getImage()
            if hasattr(self._screenWindow, 'window_lines'):
                lines = self._screenWindow.window_lines()
                columns = self._screenWindow.window_columns()
            else:
                lines = self._screenWindow.windowLines()
                columns = self._screenWindow.windowColumns()

            # 获取行属性 - 兼容性处理
            if hasattr(self._screenWindow, 'get_line_properties'):
                line_properties = self._screenWindow.get_line_properties()
            elif hasattr(self._screenWindow, 'getLineProperties'):
                line_properties = self._screenWindow.getLineProperties()
            else:
                line_properties = []

            # 设置过滤器图像
            if hasattr(self._filter_chain, 'set_image'):
                self._filter_chain.set_image(image, lines, columns, line_properties)
            elif hasattr(self._filter_chain, 'setImage'):
                self._filter_chain.setImage(image, lines, columns, line_properties)

            self._filter_chain.process()

            post_update_hotspots = self._hot_spot_region()
            self.update(pre_update_hotspots | post_update_hotspots)

        except Exception as e:
            print(f"Warning: Could not process filters: {e}")

    def _hot_spot_region(self) -> QRegion:
        """Returns region covering hotspots"""
        region = QRegion()

        try:
            # 兼容性处理
            if hasattr(self._filter_chain, 'hot_spots'):
                hotspots = self._filter_chain.hot_spots()
            elif hasattr(self._filter_chain, 'hotSpots'):
                hotspots = self._filter_chain.hotSpots()
            else:
                return region

            for hotspot in hotspots:
                if hotspot.startLine() == hotspot.endLine():
                    r = QRect()
                    r.setLeft(hotspot.startColumn())
                    r.setTop(hotspot.startLine())
                    r.setRight(hotspot.endColumn())
                    r.setBottom(hotspot.endLine())
                    region |= self._image_to_widget(r)
                else:
                    # Multi-line hotspot
                    # First line
                    r = QRect()
                    r.setLeft(hotspot.startColumn())
                    r.setTop(hotspot.startLine())
                    r.setRight(self._columns)
                    r.setBottom(hotspot.startLine())
                    region |= self._image_to_widget(r)

                    # Middle lines
                    for line in range(hotspot.startLine() + 1, hotspot.endLine()):
                        r.setLeft(0)
                        r.setTop(line)
                        r.setRight(self._columns)
                        r.setBottom(line)
                        region |= self._image_to_widget(r)

                    # Last line
                    r.setLeft(0)
                    r.setTop(hotspot.endLine())
                    r.setRight(hotspot.endColumn())
                    r.setBottom(hotspot.endLine())
                    region |= self._image_to_widget(r)
        except Exception as e:
            print(f"Warning: Could not get hotspot region: {e}")

        return region

    def filterActions(self, position: QPoint) -> List:
        """Returns filter actions for position"""
        char_line, char_column = self.getCharacterPosition(position)
        hotspot = self._filter_chain.hotSpotAt(char_line, char_column)
        return hotspot.actions() if hotspot else []

    # Cursor methods
    def setKeyboardCursorShape(self, shape: KeyboardCursorShape):
        """Set the shape of the keyboard cursor"""
        self._cursor_shape = shape

    def keyboardCursorShape(self) -> KeyboardCursorShape:
        """Get the shape of the keyboard cursor"""
        return self._cursor_shape

    def setKeyboardCursorColor(self, use_foreground: bool, color: QColor = QColor()):
        """Sets the keyboard cursor color"""
        if use_foreground:
            self._cursor_color = QColor()  # Invalid color means use foreground
        else:
            self._cursor_color = color

    def keyboardCursorColor(self) -> QColor:
        """Returns the keyboard cursor color"""
        return self._cursor_color

    def setBlinkingCursor(self, blink: bool):
        """Sets whether the cursor blinks - 修复：与C++一致的逻辑"""
        self._has_blinking_cursor = blink

        if blink and not self._blink_cursor_timer.isActive() and self.hasFocus():
            # 修复：与C++一致的闪烁时间计算
            flash_time = max(QApplication.cursorFlashTime(), 1000)
            self._blink_cursor_timer.start(flash_time // 2)

        if not blink and self._blink_cursor_timer.isActive():
            self._blink_cursor_timer.stop()
            # 修复：与C++一致的状态重置
            if self._cursor_blinking:
                self._blink_cursor_event()  # 确保光标可见
            else:
                self._cursor_blinking = False

    def blinkingCursor(self) -> bool:
        """Returns whether the cursor blinks"""
        return self._has_blinking_cursor

    def setBlinkingTextEnabled(self, blink: bool):
        """Sets whether text can blink"""
        self._allow_blinking_text = blink

        if blink and not self._blink_timer.isActive() and self.hasFocus():
            self._blink_timer.start(TEXT_BLINK_DELAY)

        if not blink and self._blink_timer.isActive():
            self._blink_timer.stop()
            self._blinking = False

    @Slot()
    def _blink_event(self):
        """Handles text blinking"""
        if not self._allow_blinking_text:
            return

        self._blinking = not self._blinking
        self.update()

    @Slot()
    def _blink_cursor_event(self):
        """Handles cursor blinking"""
        self._cursor_blinking = not self._cursor_blinking
        self._update_cursor()

    def _update_cursor(self):
        """Updates the cursor display"""
        cursor_rect = self._image_to_widget(QRect(self._cursor_position(), QSize(1, 1)))
        self.update(cursor_rect)

    def _cursor_position(self) -> QPoint:
        """Returns the cursor position"""
        if self._screenWindow:
            return self._screenWindow.cursorPosition()
        else:
            return QPoint(0, 0)

    # Font methods
    def setVTFont(self, font: QFont):
        """Sets the terminal font"""
        if not QFontInfo(font).fixedPitch():
            print("Warning: Using variable-width font may cause display issues")

        if not TerminalDisplay._antialiasText:
            font.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
            # else:
            # 修复：强制使用整数度量，确保网格对齐
            # 注意：PySide6中 ForceIntegerMetrics 可能不可用或名称不同，
            # 如果报错 AttributeError: ForceIntegerMetrics，请尝试使用其他策略或注释掉
            # font.setStyleStrategy(QFont.StyleStrategy.ForceIntegerMetrics)
            pass

        font.setKerning(False)
        font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
        font.setStyleName("")

        super().setFont(font)
        self._font_change(font)

    def setFont(self, font: QFont):
        """Override setFont to ignore external font changes"""
        pass  # Ignore font changes not from VTFont

    def _font_change(self, font: QFont):
        """Handles font changes"""
        fm = QFontMetrics(font)
        self._fontHeight = fm.height() + self._line_spacing

        # 修复：使用整数度量后，horizontalAdvance应该返回整数
        # 使用 'W' 作为标准宽度，这是终端模拟器的标准做法
        # self._fontWidth = fm.horizontalAdvance('W')

        # 优化：字符间距过大是因为 'W' 太宽了
        # 尝试使用 'x' 或平均宽度来获得更紧凑的布局
        # 或者直接使用 averageCharWidth() 如果可用且合理

        # 方法1: 使用平均宽度 (通常更紧凑)
        # self._fontWidth = round(fm.averageCharWidth())

        # 方法2: 复刻C++逻辑 - 计算REPCHAR的平均宽度
        # REPCHAR包含了各种宽度的字符，取平均值通常是最平衡的
        char_widths = [fm.horizontalAdvance(c) for c in REPCHAR]
        self._fontWidth = round(sum(char_widths) / len(char_widths))

        # 方法3: 检查 'W' 和 'i' 的宽度差异，如果太大说明不是严格等宽或测量有问题
        # w_width = fm.horizontalAdvance('W')
        # i_width = fm.horizontalAdvance('i')

        # 如果两者差异不大，说明是等宽字体，可以使用 W 的宽度
        # if abs(w_width - i_width) < 1:
        #      self._fontWidth = round(w_width)

        # 验证是否为等宽字体（可选，仅用于日志或状态）
        # char_widths = [fm.horizontalAdvance(c) for c in REPCHAR]
        # self._fixed_font = len(set(char_widths)) == 1
        self._fixed_font = True  # 强制假设为等宽字体处理，以启用优化的绘制路径
        self._fixed_font_original = self._fixed_font

        if self._fontWidth < 1:
            self._fontWidth = 1

        self._fontAscent = fm.ascent()

        self.changedFontMetricSignal.emit(self._fontHeight, self._fontWidth)
        self._propagate_size()

        # Test draw text
        self._drawTextTestFlag = True
        self.update()

    def getVTFont(self) -> QFont:
        """Returns the terminal font"""
        return self.font()

    # Size and layout methods
    def lines(self) -> int:
        """Returns number of lines that can be displayed"""
        return self._lines

    def columns(self) -> int:
        """Returns number of columns that can be displayed"""
        return self._columns

    def fontHeight(self) -> int:
        """Returns character height in pixels"""
        return self._fontHeight

    def fontWidth(self) -> int:
        """Returns character width in pixels"""
        return self._fontWidth

    def fontAscent(self) -> int:
        """Returns font ascent in pixels"""
        return self._fontAscent

    def setSize(self, cols: int, lins: int):
        """Sets the terminal size"""
        # Update internal dimensions first
        self._columns = max(1, cols)
        self._lines = max(1, lins)
        self._usedColumns = min(self._usedColumns, self._columns)
        self._usedLines = min(self._usedLines, self._lines)

        # Calculate widget size
        scroll_bar_width = 0 if (self._scroll_bar.isHidden() or
                                 self._scroll_bar.style().styleHint(
                                     QStyle.StyleHint.SH_ScrollBar_Transient)) else self._scroll_bar.sizeHint().width()

        horizontal_margin = 2 * self._left_base_margin
        vertical_margin = 2 * self._top_base_margin

        new_size = QSize(
            horizontal_margin + scroll_bar_width + (cols * self._fontWidth),
            vertical_margin + (lins * self._fontHeight)
        )

        if new_size != self.size():
            self._size = new_size
            self.updateGeometry()

        # Recreate image array if needed
        if self._image:
            self._make_image()

    def setFixedSize(self, cols: int, lins: int):
        """Sets fixed terminal size"""
        self._is_fixed_size = True
        self._columns = max(1, cols)
        self._lines = max(1, lins)
        self._usedColumns = min(self._usedColumns, self._columns)
        self._usedLines = min(self._usedLines, self._lines)

        if self._image:
            self._image = None
            self._make_image()

        self.setSize(cols, lins)
        super().setFixedSize(self._size)

    def sizeHint(self) -> QSize:
        """Returns size hint"""
        return getattr(self, '_size', QSize(800, 600))

    # Word selection
    def setWordCharacters(self, wc: str):
        """Sets characters considered part of a word"""
        self._word_characters = wc

    def wordCharacters(self) -> str:
        """Returns word characters"""
        return self._word_characters

    def setTripleClickMode(self, mode: TripleClickMode):
        """Sets triple-click selection mode"""
        self._triple_click_mode = mode

    def tripleClickMode(self) -> TripleClickMode:
        """Returns triple-click selection mode"""
        return self._triple_click_mode

    # Bell methods
    def setBellMode(self, mode: int):
        """Sets bell mode"""
        self._bell_mode = BellMode(mode)

    def bellMode(self) -> int:
        """Returns bell mode"""
        return self._bell_mode.value

    @Slot(str)
    def bell(self, message: str = ""):
        """Triggers bell effect"""
        if self._bell_mode == BellMode.NoBell:
            return

        if self._allowBell:
            self._allowBell = False
            QTimer.singleShot(500, self._enable_bell)

            if self._bell_mode == BellMode.SystemBeepBell:
                QApplication.beep()
            elif self._bell_mode == BellMode.NotifyBell:
                self.notifyBell.emit(message)
            elif self._bell_mode == BellMode.VisualBell:
                self._swap_color_table()
                QTimer.singleShot(200, self._swap_color_table)

    @Slot()
    def _enable_bell(self):
        """Re-enables bell after delay"""
        self._allowBell = True

    @Slot()
    def _swap_color_table(self):
        """Swaps foreground/background colors for visual bell"""
        color = self._color_table[1]
        self._color_table[1] = self._color_table[0]
        self._color_table[0] = color
        self._colors_inverted = not self._colors_inverted
        self.update()

    # Line spacing and margins
    def setLineSpacing(self, spacing: int):
        """Sets line spacing"""
        self._line_spacing = spacing
        self.setVTFont(self.font())  # Trigger update

    def lineSpacing(self) -> int:
        """Returns line spacing"""
        return self._line_spacing

    def setMargin(self, margin: int):
        """Sets display margins"""
        self._top_base_margin = margin
        self._left_base_margin = margin

    def margin(self) -> int:
        """Returns display margin"""
        return self._top_base_margin

    # Mouse and selection methods
    def setUsesMouse(self, uses_mouse: bool):
        """Sets whether terminal uses mouse"""
        if self._mouse_marks != uses_mouse:
            self._mouse_marks = uses_mouse
            # 修复：正确设置光标 - 与C++版本保持一致
            # 当鼠标选择启用时使用IBeamCursor，禁用时使用ArrowCursor
            cursor = Qt.CursorShape.IBeamCursor if self._mouse_marks else Qt.CursorShape.ArrowCursor
            self.setCursor(cursor)
            self.usesMouseChanged.emit()

    def usesMouse(self) -> bool:
        """Returns whether terminal uses mouse"""
        return self._mouse_marks

    def setBracketedPasteMode(self, enabled: bool):
        """Sets bracketed paste mode"""
        self._bracketed_paste_mode = enabled

    def bracketedPasteMode(self) -> bool:
        """Returns bracketed paste mode"""
        return self._bracketed_paste_mode

    def disableBracketedPasteMode(self, disable: bool):
        """Disables bracketed paste mode"""
        self._disabled_bracketed_paste_mode = disable

    def bracketedPasteModeIsDisabled(self) -> bool:
        """Returns if bracketed paste mode is disabled"""
        return self._disabled_bracketed_paste_mode

    def setCtrlDrag(self, enabled: bool):
        """Sets whether Ctrl is required for dragging"""
        self._ctrl_drag = enabled

    def ctrlDrag(self) -> bool:
        """Returns whether Ctrl is required for dragging"""
        return self._ctrl_drag

    # NEW METHOD: Calculate text area - missing from Python version
    def calculateTextArea(self, topLeftX: int, topLeftY: int, startColumn: int, line: int, length: int) -> QRect:
        """Calculate the area that encloses a series of characters - C++ style method name"""
        left = self._fontWidth * startColumn if self._fixed_font else self._text_width(0, startColumn, line)
        top = self._fontHeight * line
        width = self._fontWidth * length if self._fixed_font else self._text_width(startColumn, length, line)

        return QRect(
            self._leftMargin + topLeftX + left,
            self._topMargin + topLeftY + top,
            width,
            self._fontHeight
        )

    # NEW METHOD: Enable bell - missing public method
    def enableBell(self):
        """Re-enables bell after delay - C++ style method name"""
        self._allowBell = True

    # NEW METHOD: Swap color table - missing public method
    def swapColorTable(self):
        """Swaps foreground/background colors for visual bell - C++ style method name"""
        color = self._colorTable[1]
        self._colorTable[1] = self._colorTable[0]
        self._colorTable[0] = color
        self._colorsInverted = not self._colorsInverted
        self.update()

    # NEW METHOD: Character classification for word selection
    def charClass(self, ch: Character) -> str:
        """Classify character for word selection - C++ style method name"""
        if hasattr(ch, 'rendition') and (ch.rendition & 0x40000000):  # RE_EXTENDED_CHAR
            # Handle extended characters
            if hasattr(ch, 'character'):
                char_str = chr(ch.character)
                if self._wordCharacters and char_str in self._wordCharacters:
                    return 'a'
                elif char_str.isalnum():
                    return 'a'
                elif char_str.isspace():
                    return ' '
                else:
                    return char_str
        else:
            # Single character
            if hasattr(ch, 'character'):
                qchar = chr(ch.character)
                if qchar.isspace():
                    return ' '
                elif qchar.isalnum() or (self._wordCharacters and qchar in self._wordCharacters):
                    return 'a'
                else:
                    return qchar
        return ' '

    # Event handling methods
    def paintEvent(self, event: QPaintEvent):
        """绘制事件处理"""
        # 关键修复：使用 begin/end 模式代替直接构造 QPainter(self)
        # 这能更好地处理复杂的绘制状态和多重调用
        painter = QPainter()
        if not painter.begin(self):
            # 如果无法开始绘制（例如已经在绘制中），则直接返回
            return

        try:
            # 再次检查活动状态
            if not painter.isActive():
                return

            cr = self.contentsRect()

            # Draw background image if present
            if not self._background_image.isNull():
                background = self._color_table[DEFAULT_BACK_COLOR].color
                if self._opacity < 1.0:
                    background.setAlphaF(self._opacity)
                    painter.save()
                    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
                    painter.fillRect(cr, background)
                    painter.restore()
                else:
                    painter.fillRect(cr, background)

                painter.save()
                painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)

                # Draw background image according to mode
                if self._background_mode == BackgroundMode.STRETCH:
                    painter.drawPixmap(cr, self._background_image, self._background_image.rect())
                elif self._background_mode == BackgroundMode.ZOOM:
                    self._draw_background_zoom(painter, cr)
                elif self._background_mode == BackgroundMode.FIT:
                    self._draw_background_fit(painter, cr)
                elif self._background_mode == BackgroundMode.CENTER:
                    self._draw_background_center(painter, cr)
                else:  # NONE
                    painter.drawPixmap(0, 0, self._background_image)

                painter.restore()

            # Test draw text if needed - 修复：增加安全检查
            if hasattr(self, '_drawTextTestFlag') and self._drawTextTestFlag:
                self._calc_draw_text_addition_height(painter)

            # Draw contents
            region_to_draw = event.region() & cr
            for rect in region_to_draw:
                self._draw_background(painter, rect, self.palette().window().color(), True)
                self._draw_contents(painter, rect)

            # Draw filters (在内容之后绘制，确保覆盖)
            self._paint_filters(painter)

            # Draw input method preedit string
            self._draw_input_method_preedit_string(painter, self._preedit_rect())

        except Exception as e:
            print(f"Warning: Paint event failed: {e}")
        finally:
            # 确保结束绘制
            painter.end()

    def _draw_background_zoom(self, painter: QPainter, cr: QRect):
        """Draw background image in zoom mode"""
        r = self._background_image.rect()
        w_ratio = cr.width() / r.width()
        h_ratio = cr.height() / r.height()

        if w_ratio > h_ratio:
            r.setWidth(round(r.width() * h_ratio))
            r.setHeight(cr.height())
        else:
            r.setHeight(round(r.height() * w_ratio))
            r.setWidth(cr.width())

        r.moveCenter(cr.center())
        painter.drawPixmap(r, self._background_image, self._background_image.rect())

    def _draw_background_fit(self, painter: QPainter, cr: QRect):
        """Draw background image in fit mode"""
        r = self._background_image.rect()
        w_ratio = cr.width() / r.width()
        h_ratio = cr.height() / r.height()

        if r.width() > cr.width():
            if w_ratio <= h_ratio:
                r.setHeight(round(r.height() * w_ratio))
                r.setWidth(cr.width())
            else:
                r.setWidth(round(r.width() * h_ratio))
                r.setHeight(cr.height())
        elif r.height() > cr.height():
            r.setWidth(round(r.width() * h_ratio))
            r.setHeight(cr.height())

        r.moveCenter(cr.center())
        painter.drawPixmap(r.topLeft(), self._background_image)

    def _draw_background_center(self, painter: QPainter, cr: QRect):
        """Draw background image in center mode"""
        r = self._background_image.rect()
        r.moveCenter(cr.center())
        painter.drawPixmap(r.topLeft(), self._background_image)

    def _calc_draw_text_addition_height(self, painter: QPainter):
        """
        计算文本绘制附加高度

        Args:
            painter: 绘制器

        对应C++: void TerminalDisplay::calDrawTextAdditionHeight(QPainter& painter)
        """
        test_rect = QRect(0, 0, 100, 100)

        # 创建反馈矩形以获取实际绘制尺寸
        # 在PySide6中，QPainter.drawText不支持feedback参数
        # 我们改用其他方法获取文本尺寸

        # 使用fontMetrics获取文本高度
        font_metrics = painter.fontMetrics()
        text = "\u202D" + "Mq"

        # 先绘制文本
        painter.drawText(test_rect, Qt.AlignmentFlag.AlignBottom, text)

        # 使用fontMetrics计算高度差
        text_height = font_metrics.height()
        font_height = self._fontHeight

        # 计算附加高度
        self._draw_text_addition_height = max(0, (text_height - font_height) // 2)

    def _draw_background(self, painter: QPainter, rect: QRect, background_color: QColor, use_opacity: bool):
        """Draw background color"""
        if use_opacity:
            if self._background_image.isNull():
                color = QColor(background_color)
                color.setAlphaF(self._opacity)
                painter.save()
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
                painter.fillRect(rect, color)
                painter.restore()
        else:
            painter.fillRect(rect, background_color)

    def _draw_contents(self, painter: QPainter, rect: QRect):
        """Draw terminal contents"""
        if not self._image:
            return

        tl = self.contentsRect().topLeft()
        tlx, tly = tl.x(), tl.y()

        # Calculate visible character range
        lux = min(self._usedColumns - 1, max(0, (rect.left() - tlx - self._leftMargin) // self._fontWidth))
        luy = min(self._usedLines - 1, max(0, (rect.top() - tly - self._topMargin) // self._fontHeight))
        rlx = min(self._usedColumns - 1, max(0, (rect.right() - tlx - self._leftMargin) // self._fontWidth))
        rly = min(self._usedLines - 1, max(0, (rect.bottom() - tly - self._topMargin) // self._fontHeight))

        fm = QFontMetrics(self.font())

        for y in range(luy, rly + 1):
            self._draw_line(painter, y, lux, rlx, tlx, tly, fm)

    def _draw_line(self, painter: QPainter, y: int, lux: int, rlx: int, tlx: int, tly: int, fm: QFontMetrics):
        """Draw a single line of text - FIXED VERSION"""
        if y >= len(self._image) // self._columns:
            return

        line_start = y * self._columns
        x = lux

        while x <= rlx:
            if line_start + x >= len(self._image):
                break

            char = self._image[line_start + x]
            if char.character == 0 and x > 0:
                x -= 1  # Search for start of multi-column character
                char = self._image[line_start + x]

            # Group consecutive characters with same attributes
            text = ""
            text_width = 0
            current_attrs = char
            start_x = x

            while x <= rlx and line_start + x < len(self._image):
                char = self._image[line_start + x]

                # 修复：更严格的属性比较
                # Ignore attribute check for continuation characters (char.character == 0)
                if char.character != 0:
                    if (hasattr(char, 'foregroundColor') and hasattr(current_attrs, 'foregroundColor') and
                            char.foregroundColor != current_attrs.foregroundColor):
                        break
                    if (hasattr(char, 'backgroundColor') and hasattr(current_attrs, 'backgroundColor') and
                            char.backgroundColor != current_attrs.backgroundColor):
                        break
                    if (hasattr(char, 'rendition') and hasattr(current_attrs, 'rendition') and
                            char.rendition != current_attrs.rendition):
                        break

                # 修复：更安全的字符处理
                if char.character and char.character != 0:
                    try:
                        char_str = chr(char.character)
                        # 过滤掉控制字符
                        if ord(char_str) >= 32 or char_str in ['\t']:  # 可打印字符或制表符
                            text += char_str
                            if self._fixed_font:
                                # 使用 konsole_wcwidth 计算字符宽度
                                w = konsole_wcwidth(ord(char_str))
                                if w <= 0: w = 1  # 默认至少1个宽度
                                text_width += w * self._fontWidth
                            else:
                                text_width += fm.horizontalAdvance(char_str)
                    except (ValueError, OverflowError):
                        # 跳过无效字符
                        pass

                x += 1

            if text:  # 修复：绘制所有文本（包括空格）
                # Calculate text area
                text_area = QRect(
                    self._leftMargin + tlx + start_x * self._fontWidth,
                    self._topMargin + tly + y * self._fontHeight,
                    text_width,
                    self._fontHeight
                )

                self._draw_text_fragment(painter, text_area, text, current_attrs, False)

    def _draw_text_fragment(self, painter: QPainter, rect: QRect, text: str, style: Character,
                            invert_colors: bool = False):
        """Draw text and cursor fragment - 彻底简化版本，避免选择相关的复杂颜色处理"""
        painter.save()

        # 基础前景/背景色
        fg_color = style.foregroundColor.color(self._color_table)
        bg_color = style.backgroundColor.color(self._color_table)

        # 选择反色：当字符带有RE_REVERSE并且控件拥有焦点时，交换前景/背景
        is_reverse = bool(getattr(style, 'rendition', 0) & RE_REVERSE)
        apply_reverse = (invert_colors or is_reverse) and self.hasFocus()

        # 这里要区分“属性里的前景/背景色”和“最终显示出来的前景/背景色”：
        # - 当开启 RE_REVERSE（反显）或上层要求 invert_colors 时，实际显示需要交换前景/背景
        # - 后续绘制背景、光标、文字都必须基于 effective_*，否则就会出现：
        #   - 背景按反显画成绿色
        #   - 光标仍然用原始 fg_color 填充
        #   - 两者同色导致光标看起来“被背景盖住/消失”
        effective_fg, effective_bg = (bg_color, fg_color) if apply_reverse else (fg_color, bg_color)

        # 绘制背景：仅在需要时填充，避免整行/整屏闪烁
        fill_color = effective_bg
        default_bg = self._color_table[DEFAULT_BACK_COLOR].color
        if apply_reverse or fill_color != default_bg:
            self._draw_background(painter, rect, fill_color, False)

        # 处理光标（简化版本）
        # 绘制文本（简化版本）
        text_color = effective_fg
        if hasattr(style, 'rendition') and (style.rendition & RE_CURSOR) and self.hasFocus() and (not self._cursor_blinking):
            # 终端模拟层会在“光标所在的单元格”打上 RE_CURSOR 标记。
            # 该单元格的绘制顺序通常是：背景 -> 光标 -> 文本。
            #
            # 这里使用 _cursor_paint_colors() 计算“光标填充色”和“光标上的文字颜色”，保证：
            # - 不会因为反显、同色前景/背景等情况导致光标不可见
            # - 如果用户配置了固定光标颜色，则优先使用用户配置
            #
            # 注意：这里一定要用 effective_fg/effective_bg 来计算，而不是原始 fg_color/bg_color。
            cursor_fill, cursor_text = self._cursor_paint_colors(effective_fg, effective_bg, self._cursor_color)
            painter.fillRect(rect, cursor_fill)
            text_color = cursor_text

        painter.setPen(text_color)

        # 设置字体样式
        font = painter.font()
        if hasattr(style, 'rendition'):
            font.setBold(bool(style.rendition & RE_BOLD))
            font.setItalic(bool(style.rendition & RE_ITALIC))
            font.setUnderline(bool(style.rendition & RE_UNDERLINE))
            painter.setFont(font)

        # 绘制文本
        if self._fixed_font:
            # 对于等宽字体，强制逐字符绘制，确保对齐
            # 使用 QFontMetricsF 获取精确的字符宽度（虽然我们这里用的是整数网格）
            # 但为了视觉上的一致性，我们让字符在其网格内左对齐或居中

            fm = QFontMetrics(painter.font())
            current_x = rect.x()
            for char in text:
                # 计算字符实际宽度
                char_width = fm.horizontalAdvance(char)

                # 使用 konsole_wcwidth 计算字符应占用的网格宽度
                w = konsole_wcwidth(ord(char))
                if w <= 0: w = 1  # 默认至少1个宽度

                target_width = w * self._fontWidth

                # 居中绘制（无论是单宽还是双宽）
                # 如果字符实际宽度小于目标宽度，则居中
                # 如果字符实际宽度大于目标宽度，也居中（允许两边溢出）
                offset = (target_width - char_width) / 2

                painter.drawText(current_x + offset, rect.y() + self._fontAscent + self._line_spacing, char)

                current_x += target_width
        else:
            painter.drawText(rect.x(), rect.y() + self._fontAscent + self._line_spacing, text)

        painter.restore()

    @staticmethod
    def _brightness(color: QColor) -> float:
        # 亮度估计（0~255），使用人眼感知权重：
        # 绿色权重最高，其次红色，再到蓝色。
        # 这不是严格的 sRGB 相对亮度公式，但足够用来做“光标可见性”的快速判断。
        return 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()

    @staticmethod
    def _best_bw_for_bg(bg: QColor) -> QColor:
        # 给定背景色，选择“更显眼”的黑/白文本色：
        # - 背景亮则用黑字
        # - 背景暗则用白字
        return QColor(0, 0, 0) if TerminalDisplay._brightness(bg) > 128 else QColor(255, 255, 255)

    @staticmethod
    def _cursor_paint_colors(effective_fg: QColor, effective_bg: QColor, configured_cursor: QColor) -> tuple[QColor, QColor]:
        # 计算“块状光标”的两种颜色：
        # - fill: 光标的填充背景色（画一个矩形）
        # - text: 光标上的文字颜色（保证文字在光标上可读）
        #
        # 为什么需要同时计算两种？
        # - 传统终端会在块状光标处“反转字符颜色”来实现可读性
        # - 但在 RE_REVERSE / 特殊配色（例如绿色前景 + 绿色背景）下，简单反转不一定有效
        # - 所以这里统一做一个对比度兜底
        if configured_cursor.isValid():
            # 用户显式配置了固定光标颜色：直接使用配置色作为填充色；
            # 光标上的文字颜色则选黑/白以确保能看清。
            return configured_cursor, TerminalDisplay._best_bw_for_bg(configured_cursor)

        # 默认策略：沿用“effective 前景色”作为光标填充色，并用“effective 背景色”画光标内文字，
        # 等价于“反转字符颜色”。
        fill = effective_fg
        text = effective_bg
        if abs(TerminalDisplay._brightness(fill) - TerminalDisplay._brightness(text)) < 50:
            # 亮度差过小，反转后仍然可能看不清（例如 fg/bg 同为绿色）。
            # 此时使用更激进的智能选色（黑/白或彩色）作为光标填充色，
            # 并重新选择光标内文字颜色（黑/白）以确保可读。
            fill = TerminalDisplay._get_smart_cursor_color(effective_fg, effective_bg)
            text = TerminalDisplay._best_bw_for_bg(fill)
        return fill, text

    def _draw_characters_with_colors(self, painter: QPainter, rect: QRect, text: str, style: Character,
                                     fg_color: QColor, bg_color: QColor, invert_character_color: bool):
        """Draw characters with specific colors - 修复：简化并避免递归调用"""
        # Setup font styling
        font = painter.font()
        use_bold = ((style.rendition & RE_BOLD) and self._boldIntense) or font.bold()
        use_underline = style.rendition & RE_UNDERLINE or font.underline()
        use_italic = style.rendition & RE_ITALIC or font.italic()
        use_strikeout = style.rendition & RE_STRIKEOUT or font.strikeOut()
        use_overline = style.rendition & RE_OVERLINE or font.overline()

        if (font.bold() != use_bold or font.underline() != use_underline or
                font.italic() != use_italic or font.strikeOut() != use_strikeout or
                font.overline() != use_overline):
            font.setBold(use_bold)
            font.setUnderline(use_underline)
            font.setItalic(use_italic)
            font.setStrikeOut(use_strikeout)
            font.setOverline(use_overline)
            painter.setFont(font)

        # Set text color
        text_color = bg_color if invert_character_color else fg_color
        painter.setPen(text_color)

        # 绘制文本
        if self._fixed_font:
            # 对于等宽字体，强制逐字符绘制，确保对齐
            current_x = rect.x()
            fm = QFontMetrics(painter.font())
            for char in text:
                # 优化：居中绘制窄字符
                char_width = fm.horizontalAdvance(char)
                if char_width < self._fontWidth:
                    offset = (self._fontWidth - char_width) / 2
                    painter.drawText(current_x + offset, rect.y() + self._fontAscent + self._line_spacing, char)
                else:
                    painter.drawText(current_x, rect.y() + self._fontAscent + self._line_spacing, char)
                current_x += self._fontWidth
        else:
            painter.drawText(rect.x(), rect.y() + self._fontAscent + self._line_spacing, text)

    def _draw_cursor(self, painter: QPainter, rect: QRect, foreground_color: QColor,
                     background_color: QColor) -> bool:
        """Draw cursor - 返回是否需要反转字符颜色"""
        # 修复：使用正确的属性名称
        if self._cursor_blinking:
            return False

        cursor_rect = QRectF(rect)
        cursor_rect.setHeight(self._fontHeight - self._line_spacing - 1)

        if self._cursorColor.isValid():
            painter.setPen(self._cursorColor)
            cursor_color = self._cursorColor
        else:
            painter.setPen(foreground_color)
            cursor_color = foreground_color

        # 根据光标形状绘制
        if self._cursor_shape == KeyboardCursorShape.BlockCursor:
            # 绘制块状光标
            pen_width = max(1, painter.pen().width())
            painter.drawRect(cursor_rect.adjusted(pen_width / 2, pen_width / 2, -pen_width / 2, -pen_width / 2))

            if self.hasFocus():
                painter.fillRect(cursor_rect, cursor_color)
                # 如果没有设置光标颜色，则需要反转字符颜色以保证可读性
                if not self._cursorColor.isValid():
                    return True

        elif self._cursor_shape == KeyboardCursorShape.UnderlineCursor:
            # 绘制下划线光标
            painter.drawLine(cursor_rect.left(), cursor_rect.bottom(),
                             cursor_rect.right(), cursor_rect.bottom())

        elif self._cursor_shape == KeyboardCursorShape.IBeamCursor:
            # 绘制竖线光标
            painter.drawLine(cursor_rect.left(), cursor_rect.top(),
                             cursor_rect.left(), cursor_rect.bottom())

        return False

    @staticmethod
    def _get_smart_cursor_color(fg_color: QColor, bg_color: QColor) -> QColor:
        """
        智能光标颜色选择，确保光标在任何背景下都可见
        避免光标与背景色或前景色相同导致不可见
        """
        # 这个函数用于“兜底”场景：
        # - 默认的块状光标策略是“用前景色作为光标底色，并反转文字颜色”
        # - 但如果 fg/bg 亮度太接近（甚至相同），反转也无济于事
        # - 这里通过亮度阈值挑选黑/白；如果仍与前景太接近，则用醒目的红/黄
        # 计算背景色亮度 (基于人眼感知的加权公式)
        r, g, b = bg_color.red(), bg_color.green(), bg_color.blue()
        bg_brightness = (0.299 * r + 0.587 * g + 0.114 * b)

        # 计算前景色亮度
        fr, fg_val, fb = fg_color.red(), fg_color.green(), fg_color.blue()
        fg_brightness = (0.299 * fr + 0.587 * fg_val + 0.114 * fb)

        # 根据背景亮度选择基础对比色
        if bg_brightness > 128:
            # 背景较亮，优先使用深色光标
            contrast_color = QColor(0, 0, 0)  # 黑色
        else:
            # 背景较暗，优先使用亮色光标
            contrast_color = QColor(255, 255, 255)  # 白色

        # 如果对比色与前景色太接近，选择另一种颜色
        contrast_brightness = (0.299 * contrast_color.red() +
                               0.587 * contrast_color.green() +
                               0.114 * contrast_color.blue())

        if abs(contrast_brightness - fg_brightness) < 50:
            # 对比度不够，选择醒目的彩色
            if bg_brightness > 128:
                return QColor(255, 0, 0)  # 红色（在亮背景上）
            else:
                return QColor(255, 255, 0)  # 黄色（在暗背景上）

        return contrast_color

    def _is_line_char_string(self, text: str) -> bool:
        """正确判断是否为线字符串"""
        if not text or len(text) == 0:
            return False

        # 检查第一个字符是否在VT100图形字符范围
        first_char = ord(text[0])
        return self._draw_line_chars and (first_char & 0xFF80) == 0x2500

    def _is_line_char(self, char) -> bool:
        """正确判断单个字符是否为线字符"""
        if hasattr(char, 'character'):
            char_code = char.character
        elif isinstance(char, str):
            char_code = ord(char)
        else:
            char_code = int(char)

        # VT100图形字符范围检查
        return self._draw_line_chars and (char_code & 0xFF80) == 0x2500

    def _is_line_char_string(self, text: str) -> bool:
        """正确判断是否为线字符串"""
        if not text or len(text) == 0:
            return False

        # 检查第一个字符是否在VT100图形字符范围
        first_char = ord(text[0])
        return self._draw_line_chars and (first_char & 0xFF80) == 0x2500

    def _is_line_char(self, char) -> bool:
        """正确判断单个字符是否为线字符"""
        if hasattr(char, 'character'):
            char_code = char.character
        elif isinstance(char, str):
            char_code = ord(char)
        else:
            char_code = int(char)

        # VT100图形字符范围检查
        return self._draw_line_chars and (char_code & 0xFF80) == 0x2500

    def _draw_characters_with_colors(self, painter: QPainter, rect: QRect, text: str, style: Character,
                                     fg_color: QColor, bg_color: QColor, invert_colors: bool):
        """Draw text characters with specified colors - 用于选择背景处理"""
        # Don't draw blinking text when it should be hidden
        if self._blinking and hasattr(style, 'rendition') and (style.rendition & RE_BLINK):
            return

        # Don't draw concealed characters
        if hasattr(style, 'rendition') and (style.rendition & RE_CONCEAL):
            return

        # 修复：只检查文本是否完全为空（允许空格字符）
        if not text:
            return

        # Setup font attributes
        font = painter.font()

        # 修复：正确处理粗体
        if hasattr(style, 'rendition') and (style.rendition & RE_BOLD):
            font.setBold(True)
        else:
            font.setBold(False)

        # 修复：正确处理斜体
        if hasattr(style, 'rendition') and (style.rendition & RE_ITALIC):
            font.setItalic(True)
        else:
            font.setItalic(False)

        # 修复：正确处理下划线
        if hasattr(style, 'rendition') and (style.rendition & RE_UNDERLINE):
            font.setUnderline(True)
        else:
            font.setUnderline(False)

        painter.setFont(font)

        # 修复：使用传入的颜色而不是从style获取
        final_fg_color = fg_color
        final_bg_color = bg_color

        # 修复：处理颜色反转（光标处）
        if invert_colors:
            final_fg_color, final_bg_color = final_bg_color, final_fg_color

        # 修复：设置文本颜色
        painter.setPen(final_fg_color)

        # 修复：绘制文本
        painter.drawText(rect, Qt.AlignLeft | Qt.AlignTop, text)

        # 修复：绘制删除线
        if hasattr(style, 'rendition') and (style.rendition & RE_STRIKEOUT):
            painter.drawLine(rect.left(), rect.center().y(), rect.right(), rect.center().y())

    def _draw_characters(self, painter: QPainter, rect: QRect, text: str, style: Character, invert_colors: bool):
        """Draw text characters with proper styling - FIXED VERSION"""
        # Don't draw blinking text when it should be hidden
        if self._blinking and hasattr(style, 'rendition') and (style.rendition & RE_BLINK):  # 修复：使用RE_BLINK常量
            return

        # Don't draw concealed characters
        if hasattr(style, 'rendition') and (style.rendition & RE_CONCEAL):  # 修复：使用RE_CONCEAL常量
            return

        # 修复：只检查文本是否完全为空（允许空格字符）
        if not text:
            return

        # Setup font attributes
        font = painter.font()
        needs_font_change = False

        if hasattr(style, 'rendition'):
            use_bold = (style.rendition & RE_BOLD) and self._boldIntense  # 修复：使用RE_BOLD常量
            use_underline = bool(style.rendition & RE_UNDERLINE)  # 修复：使用RE_UNDERLINE常量
            use_italic = bool(style.rendition & RE_ITALIC)  # 修复：使用RE_ITALIC常量
            use_strikeout = bool(style.rendition & RE_STRIKEOUT)  # 修复：使用RE_STRIKEOUT常量
            use_overline = bool(style.rendition & RE_OVERLINE)  # 修复：使用RE_OVERLINE常量

            if (font.bold() != use_bold or font.underline() != use_underline or
                    font.italic() != use_italic or font.strikeOut() != use_strikeout or
                    font.overline() != use_overline):
                font.setBold(use_bold)
                font.setUnderline(use_underline)
                font.setItalic(use_italic)
                font.setStrikeOut(use_strikeout)
                font.setOverline(use_overline)
                needs_font_change = True

        if needs_font_change:
            painter.setFont(font)

        # Setup pen color
        if hasattr(style, 'foregroundColor') and hasattr(style, 'backgroundColor'):
            if invert_colors:
                color = style.backgroundColor.color(self._color_table)
            else:
                color = style.foregroundColor.color(self._color_table)
            painter.setPen(color)

        # 强制白色 - 防止黑线
        if not painter.pen().color().isValid() or painter.pen().color() == QColor(0, 0, 0):
            painter.setPen(QColor(255, 255, 255))

        # Draw text
        if self._is_line_char_string(text):
            self._draw_line_char_string(painter, rect.x(), rect.y(), text, style)
        else:
            # 修复：使用正确的baseline位置绘制文本
            fm = QFontMetrics(font)
            baseline_y = rect.y() + fm.ascent()

            # Force LTR layout for terminal
            painter.setLayoutDirection(Qt.LayoutDirection.LeftToRight)

            # 修复：简化文本绘制，不使用LTR override字符
            painter.drawText(rect.x(), baseline_y, text)

    def _paint_filters(self, painter: QPainter):
        """Paint filter highlights"""
        try:
            # 确保 filter chain 已经处理过当前的 buffer
            if self._filter_chain:
                # 这里我们不需要显式调用 process()，因为 updateFilters 信号连接应该已经触发了它
                # 但为了保险起见，我们可以检查一下热点列表
                pass

            cursor_pos = self.mapFromGlobal(QCursor.pos())
            char_line, char_column = self.getCharacterPosition(cursor_pos)

            if 0 <= char_line < len(self._image) // self._columns and 0 <= char_column < self._columns:
                cursor_char = self._image[char_line * self._columns + char_column]
                painter.setPen(QPen(cursor_char.foregroundColor.color(self._color_table)))

            # Draw hotspot highlights - 兼容性处理
            spots = []
            if hasattr(self._filter_chain, 'hot_spots'):
                spots = self._filter_chain.hot_spots()
            elif hasattr(self._filter_chain, 'hotSpots'):
                spots = self._filter_chain.hotSpots()

            # 如果没有热点，可能是因为还没来得及处理
            # 这里的逻辑依赖于 filter chain 已经被 ScreenWindow 的 updateFilters 触发

            for spot in spots:
                if spot.type() == Filter.HotSpot.Type.Link:
                    self._draw_hotspot_highlight(painter, spot)
                elif spot.type() == Filter.HotSpot.Type.Marker:
                    self._draw_hotspot_marker(painter, spot)
                elif spot.type() == Filter.HotSpot.Type.Highlight:
                    self._draw_custom_highlight(painter, spot)
        except Exception as e:
            print(f"Warning: Could not paint filters: {e}")

    def _draw_custom_highlight(self, painter: QPainter, spot):
        """
        绘制自定义高亮区域
        支持通过 spot.foregroundColor() 和 spot.backgroundColor() 获取颜色
        也支持对特殊热点类型 (如 PermissionHotSpot) 进行精细化绘制
        """
        try:
            # 检查是否是特殊的权限热点
            is_permission = spot.__class__.__name__ == 'PermissionHotSpot'

            # 保存画笔状态
            painter.save()

            # 遍历热点覆盖的每一行
            cursor_cell = self._cursor_position()
            for line in range(spot.startLine(), spot.endLine() + 1):
                # 计算当前行的列范围
                start_column = spot.startColumn() if line == spot.startLine() else 0
                end_column = spot.endColumn() if line == spot.endLine() else self._columns

                # 计算绘制区域
                # 修复：left_margin 计算需要统一
                left_margin = (self._left_base_margin +
                               (self._scrollbar_location == ScrollBarPosition.ScrollBarLeft and
                                not self._scroll_bar.style().styleHint(QStyle.StyleHint.SH_ScrollBar_Transient, None,
                                                                       self._scroll_bar)
                                ) * self._scroll_bar.width())

                # 绘制字符
                for col in range(start_column, end_column):
                    # 跳过当前键盘光标所在的单元格，避免覆盖导致不可见
                    if cursor_cell.y() == line and cursor_cell.x() == col:
                        continue
                    # 计算字符的像素位置
                    x = col * self._fontWidth + left_margin
                    y = line * self._fontHeight + self._top_base_margin
                    rect = QRect(x, y, self._fontWidth, self._fontHeight)

                    # 获取当前位置的字符
                    char_idx = line * self._columns + col
                    if char_idx >= len(self._image):
                        continue

                    char_obj = self._image[char_idx]
                    char_code = char_obj.character
                    char_text = chr(char_code) if char_code > 0 else ' '

                    # 确定颜色
                    fg_color = None
                    bg_color = None

                    if is_permission:
                        # 权限字符串的特殊着色逻辑
                        if char_text == 'd':
                            fg_color = QColor("#bd93f9")  # 紫色
                        elif char_text == 'r':
                            fg_color = QColor("#8be9fd")  # 蓝色
                        elif char_text == 'w':
                            fg_color = QColor("#f1fa8c")  # 黄色
                        elif char_text == 'x':
                            fg_color = QColor("#ff5555")  # 红色
                        elif char_text == '-':
                            fg_color = QColor("#6272a4")  # 灰色
                    else:
                        # 普通高亮热点
                        if hasattr(spot, 'foregroundColor'):
                            fg_color = spot.foregroundColor()
                        if hasattr(spot, 'backgroundColor'):
                            bg_color = spot.backgroundColor()

                    # 如果没有指定颜色，则跳过绘制（保持原有显示）
                    if not fg_color and not bg_color:
                        continue

                    # 绘制背景
                    if bg_color:
                        painter.fillRect(rect, bg_color)
                    elif fg_color:
                        # 如果只指定了前景色，我们需要擦除旧文字以避免重影
                        # 使用终端当前的默认背景色（带透明度）进行“擦除”
                        # 这是消除重影且不引入可见背景框的最佳方法

                        # 1. 获取应当使用的背景色
                        # 优先使用字符自身的背景色（如果有），否则使用终端默认背景色
                        erase_bg = None
                        if hasattr(char_obj, 'backgroundColor'):
                            erase_bg = char_obj.backgroundColor.color(self._color_table)

                        if not erase_bg or not erase_bg.isValid():
                            erase_bg = self._color_table[DEFAULT_BACK_COLOR].color

                        # 2. 执行擦除
                        if erase_bg and erase_bg.isValid():
                            painter.save()
                            if self._opacity < 1.0:
                                # 透明模式：使用 Source 模式直接替换像素（包括Alpha通道）
                                # 这样可以完美“抠掉”旧文字，恢复成背景色
                                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
                                c = QColor(erase_bg)
                                c.setAlphaF(self._opacity)
                                painter.fillRect(rect, c)
                            else:
                                # 不透明模式：直接填充背景色
                                painter.fillRect(rect, erase_bg)
                            painter.restore()

                    # 绘制字符
                    if fg_color:
                        painter.setPen(fg_color)

                        # 关键修复：完全复刻 _draw_text_fragment 的绘制逻辑以确保对齐
                        # 1. 设置字体样式 (粗体/斜体/下划线)
                        font = painter.font()
                        if hasattr(char_obj, 'rendition'):
                            font.setBold(bool(char_obj.rendition & RE_BOLD))
                            font.setItalic(bool(char_obj.rendition & RE_ITALIC))
                            font.setUnderline(bool(char_obj.rendition & RE_UNDERLINE))
                        painter.setFont(font)

                        # 2. 计算位置 (居中对齐 + 基线对齐)
                        fm = QFontMetrics(font)
                        char_width = fm.horizontalAdvance(char_text)

                        # 居中偏移量
                        offset = (self._fontWidth - char_width) / 2

                        # 基线位置计算: y + ascent + line_spacing
                        text_x = x + offset
                        text_y = y + self._fontAscent + self._line_spacing

                        painter.drawText(QPointF(text_x, text_y), char_text)

            # 恢复画笔状态
            painter.restore()

        except Exception as e:
            print(f"Error drawing custom highlight: {e}")
            # 确保出错时也能恢复状态
            try:
                painter.restore()
            except:
                pass

    def _draw_hotspot_highlight(self, painter: QPainter, spot):
        """Draw hotspot highlight"""
        left_margin = (self._left_base_margin +
                       (self._scrollbar_location == ScrollBarPosition.ScrollBarLeft and
                        not self._scroll_bar.style().styleHint(QStyle.StyleHint.SH_ScrollBar_Transient, None,
                                                               self._scroll_bar)
                        ) * self._scroll_bar.width())

        for line in range(spot.startLine(), spot.endLine() + 1):
            start_column = spot.startColumn() if line == spot.startLine() else 0
            end_column = spot.endColumn() if line == spot.endLine() else self._columns - 1

            # Skip whitespace at end
            while end_column > 0 and line < len(self._image) // self._columns:
                char_idx = line * self._columns + end_column
                if char_idx < len(self._image) and chr(self._image[char_idx].character).isspace():
                    end_column -= 1
                else:
                    break
            end_column += 1

            r = QRect(
                start_column * self._fontWidth + 1 + left_margin,
                line * self._fontHeight + 1 + self._top_base_margin,
                (end_column - start_column) * self._fontWidth - 1,
                self._fontHeight - 1
            )

            # Draw underline for links
            if spot.type() == Filter.HotSpot.Type.Link:
                fm = QFontMetrics(self.font())
                baseline = r.bottom() - fm.descent()
                underline_pos = baseline + fm.underlinePos()

                cursor_pos = self.mapFromGlobal(QCursor.pos())
                if r.contains(cursor_pos):
                    painter.drawLine(r.left(), underline_pos, r.right(), underline_pos)

    def _draw_hotspot_marker(self, painter: QPainter, spot):
        """Draw hotspot marker"""
        # Draw semi-transparent rectangle for markers
        painter.fillRect(self._get_hotspot_rect(spot), QBrush(QColor(255, 0, 0, 120)))

    def _get_hotspot_rect(self, spot) -> QRect:
        """Get rectangle for hotspot"""
        left_margin = self._left_base_margin
        if (self._scrollbar_location == ScrollBarPosition.ScrollBarLeft and
                not self._scroll_bar.style().styleHint(QStyle.StyleHint.SH_ScrollBar_Transient, None,
                                                       self._scroll_bar)):
            left_margin += self._scroll_bar.width()

        return QRect(
            spot.startColumn() * self._fontWidth + 1 + left_margin,
            spot.startLine() * self._fontHeight + 1 + self._top_base_margin,
            (spot.endColumn() - spot.startColumn()) * self._fontWidth - 1,
            (spot.endLine() - spot.startLine() + 1) * self._fontHeight - 1
        )

    def _preedit_rect(self) -> QRect:
        """Get rectangle for input method preedit string"""
        preedit_length = len(self._input_method_data.get('preedit_string', ''))

        if preedit_length == 0:
            return QRect()

        cursor_pos = self._cursor_position()
        return QRect(
            self._leftMargin + self._fontWidth * cursor_pos.x(),
            self._topMargin + self._fontHeight * cursor_pos.y(),
            self._fontWidth * preedit_length,
            self._fontHeight
        )

    def _draw_input_method_preedit_string(self, painter: QPainter, rect: QRect):
        """Draw input method preedit string"""
        preedit_string = self._input_method_data.get('preedit_string', '')
        if not preedit_string:
            return

        cursor_pos = self._cursor_position()
        invert_colors = False
        background = self._color_table[DEFAULT_BACK_COLOR].color
        foreground = self._color_table[DEFAULT_FORE_COLOR].color

        # Get style from cursor position
        char_idx = cursor_pos.y() * self._columns + cursor_pos.x()
        if 0 <= char_idx < len(self._image):
            style = self._image[char_idx]
        else:
            style = Character()  # Default character

        self._draw_background(painter, rect, background, True)
        self._draw_cursor(painter, rect, foreground, background, invert_colors)
        self._draw_characters(painter, rect, preedit_string, style, invert_colors)

        self._input_method_data['previous_preedit_rect'] = rect

    def getCharacterPosition(self, widget_point: QPointF) -> Tuple[int, int]:
        """Get character line and column from widget point"""
        line = int((widget_point.y() - self.contentsRect().top() - self._topMargin) / self._fontHeight)
        line = max(0, min(line, self._usedLines - 1))

        x = widget_point.x() - self.contentsRect().left() - self._leftMargin

        # Always use accumulated width calculation to support variable width characters (CJK)
        # This fixes the crash/misalignment when selecting Chinese text
        column = 0
        current_width = 0

        while column < self._usedColumns:
            char_idx = line * self._columns + column
            w = 1
            if char_idx < len(self._image):
                # Ensure consistent width calculation with _draw_contents
                w = konsole_wcwidth(self._image[char_idx].character)
                if w <= 0: w = 1

            char_pixel_width = w * self._fontWidth

            if current_width + char_pixel_width > x:
                break

            current_width += char_pixel_width
            column += 1

        column = max(0, min(column, self._usedColumns))
        return line, column

    def _text_width(self, start_column: int, length: int, line: int) -> int:
        """Calculate text width for given range"""
        if self._fixed_font:
            return length * self._fontWidth

        fm = QFontMetrics(self.font())
        result = 0

        for column in range(length):
            char_idx = line * self._columns + start_column + column
            if char_idx < len(self._image):
                char = self._image[char_idx]
                if self._fixed_font_original and not self._is_line_char(char):
                    result += fm.horizontalAdvance(REPCHAR[0])
                else:
                    result += fm.horizontalAdvance(chr(char.character))

        return result

    def _is_line_char(self, char: Character) -> bool:
        """Check if character is a line drawing character"""
        return self._draw_line_chars and hasattr(char, 'isLineChar') and char.isLineChar()

    def _is_line_char_string(self, text: str) -> bool:
        """Check if the text contains line characters"""
        if not text:
            return False
        return len(text) > 0 and self._draw_line_chars and (ord(text[0]) & 0xFF80) == 0x2500

    def _draw_line_char_string(self, painter: QPainter, x: int, y: int, text: str, attributes: Character):
        """Draw a string of line characters"""
        current_pen = painter.pen()

        # Apply bold if needed
        if hasattr(attributes, 'rendition') and (
                attributes.rendition & RE_BOLD) and self._boldIntense:  # 修复：使用RE_BOLD常量
            bold_pen = QPen(current_pen)
            bold_pen.setWidth(3)
            painter.setPen(bold_pen)

        for i, char in enumerate(text):
            code = ord(char) & 0xFF
            if code < len(LINE_CHARS) and LINE_CHARS[code]:
                draw_line_char(painter, x + (self._fontWidth * i), y, self._fontWidth, self._fontHeight, code)
            else:
                draw_other_char(painter, x + (self._fontWidth * i), y, self._fontWidth, self._fontHeight, code)

        painter.setPen(current_pen)

    def _image_to_widget(self, image_area: QRect) -> QRect:
        """Convert image coordinates to widget coordinates"""
        result = QRect()
        result.setLeft(self._leftMargin + self._fontWidth * image_area.left())
        result.setTop(self._topMargin + self._fontHeight * image_area.top())
        result.setWidth(self._fontWidth * image_area.width())
        result.setHeight(self._fontHeight * image_area.height())
        return result

    # Update methods
    @Slot()
    def updateImage(self):
        """Update the terminal image display"""
        if not self._screenWindow:
            return

        # Scroll existing image where possible
        # 修复：兼容两种命名方式
        try:
            if hasattr(self._screenWindow, 'scroll_count'):
                scroll_count = self._screenWindow.scroll_count()
                scroll_region = self._screenWindow.scroll_region()
                self._scroll_image(scroll_count, scroll_region)
                self._screenWindow.reset_scroll_count()
            elif hasattr(self._screenWindow, 'scrollCount'):
                scroll_count = self._screenWindow.scrollCount()
                scroll_region = self._screenWindow.scrollRegion()
                self._scroll_image(scroll_count, scroll_region)
                self._screenWindow.resetScrollCount()
        except Exception as e:
            print(f"Warning: Could not scroll image: {e}")

        if not self._image:
            self._update_image_size()

        # 获取新图像数据
        try:
            # 修复：兼容两种命名方式
            if hasattr(self._screenWindow, 'get_image'):
                new_image = self._screenWindow.get_image()
            elif hasattr(self._screenWindow, 'getImage'):
                new_image = self._screenWindow.getImage()
            else:
                print("Warning: No getImage method found")
                return

            if hasattr(self._screenWindow, 'window_lines'):
                lines = self._screenWindow.window_lines()
                columns = self._screenWindow.window_columns()
            else:
                lines = self._screenWindow.windowLines()
                columns = self._screenWindow.windowColumns()

            if hasattr(self._screenWindow, 'current_line'):
                current_line = self._screenWindow.current_line()
                line_count = self._screenWindow.line_count()
            else:
                current_line = self._screenWindow.currentLine()
                line_count = self._screenWindow.lineCount()

            self._set_scroll(current_line, line_count)
        except Exception as e:
            print(f"Warning: Could not get image data: {e}")
            return

        lines_to_update = min(self._lines, max(0, lines))
        columns_to_update = min(self._columns, max(0, columns))

        dirty_region = QRegion()
        self._has_blinker = False

        # 性能优化：使用批量比较而非逐像素比较
        try:
            def _char_diff(a: Character, b: Character) -> bool:
                return (
                        a.character != b.character or
                        a.foregroundColor != b.foregroundColor or
                        a.backgroundColor != b.backgroundColor or
                        a.rendition != b.rendition
                )

            for y in range(lines_to_update):
                current_line_start = y * self._columns
                new_line_start = y * columns

                if (current_line_start >= len(self._image) or
                        new_line_start >= len(new_image)):
                    break

                current_line_end = min(current_line_start + columns_to_update, len(self._image))
                new_line_end = min(new_line_start + columns_to_update, len(new_image))

                current_line = self._image[current_line_start:current_line_end]
                new_line = new_image[new_line_start:new_line_end]

                # 仅对差异区进行脏区标记与复制
                if len(current_line) != len(new_line) or current_line != new_line:
                    # 查找首个不同位置
                    start_x = 0
                    end_x = min(len(current_line), len(new_line)) - 1
                    while start_x <= end_x and not _char_diff(current_line[start_x], new_line[start_x]):
                        start_x += 1
                    while end_x >= start_x and not _char_diff(current_line[end_x], new_line[end_x]):
                        end_x -= 1

                    if start_x <= end_x:
                        dirty_rect = QRect(
                            self._leftMargin + self.contentsRect().left() + start_x * self._fontWidth,
                            self._topMargin + self.contentsRect().top() + self._fontHeight * y,
                            (end_x - start_x + 1) * self._fontWidth,
                            self._fontHeight
                        )
                        dirty_region |= dirty_rect

                        for x in range(start_x, end_x + 1):
                            ix = current_line_start + x
                            if ix < len(self._image):
                                self._image[ix] = new_line[x]

                # 检查是否存在闪烁文本（RE_BLINK）
                for x in range(min(len(new_line), columns_to_update)):
                    char = new_line[x]
                    if hasattr(char, 'rendition') and char.rendition & RE_BLINK:
                        self._has_blinker = True
                        break

        except Exception as e:
            print(f"Warning: updateImage optimization failed, falling back: {e}")
            # 如果优化版本失败，保持原有行为
            for y in range(lines_to_update):
                current_line_start = y * self._columns
                new_line_start = y * columns

                for x in range(columns_to_update):
                    current_idx = current_line_start + x
                    new_idx = new_line_start + x

                    if (current_idx < len(self._image) and new_idx < len(new_image)):
                        self._image[current_idx] = new_image[new_idx]

        # Clear areas outside new image
        if lines_to_update < self._usedLines:
            dirty_region |= QRect(
                self._leftMargin + self.contentsRect().left(),
                self._topMargin + self.contentsRect().top() + self._fontHeight * lines_to_update,
                self._fontWidth * self._columns,
                self._fontHeight * (self._usedLines - lines_to_update)
            )

        if columns_to_update < self._usedColumns:
            dirty_region |= QRect(
                self._leftMargin + self.contentsRect().left() + columns_to_update * self._fontWidth,
                self._topMargin + self.contentsRect().top(),
                self._fontWidth * (self._usedColumns - columns_to_update),
                self._fontHeight * self._lines
            )

        self._usedLines = lines_to_update
        self._usedColumns = columns_to_update

        # Add preedit rect to dirty region
        dirty_region |= self._input_method_data.get('previous_preedit_rect', QRect())

        # Update display
        self.update(dirty_region)

        # Handle blinking
        if self._has_blinker and not self._blink_timer.isActive():
            self._blink_timer.start(TEXT_BLINK_DELAY)
        if not self._has_blinker and self._blink_timer.isActive():
            self._blink_timer.stop()
            self._blinking = False

    @Slot()
    def updateFilters(self):
        """Update filters"""
        if self._screenWindow:
            self.processFilters()

    @Slot()
    def updateLineProperties(self):
        """Update line properties"""
        if not self._screenWindow:
            return

        try:
            # 修复：兼容两种命名方式
            if hasattr(self._screenWindow, 'get_line_properties'):
                self._line_properties = self._screenWindow.get_line_properties()
            elif hasattr(self._screenWindow, 'getLineProperties'):
                self._line_properties = self._screenWindow.getLineProperties()
        except Exception as e:
            print(f"Warning: Could not update line properties: {e}")

    def _scroll_image(self, lines: int, region: QRect):
        """Scroll the image by given number of lines"""
        if (lines == 0 or not self._image or not region.isValid() or
                (region.top() + abs(lines)) >= region.bottom() or
                self._lines <= region.height()):
            return

        # Hide resize widget during scroll
        if self._resize_widget and self._resize_widget.isVisible():
            self._resize_widget.hide()

        # Scroll the internal image
        region = QRect(region.left(), region.top(), region.width(),
                       min(region.bottom(), self._lines - 2))

        scroll_bar_width = 0 if self._scroll_bar.isHidden() else self._scroll_bar.width()
        SCROLLBAR_CONTENT_GAP = 1 if scroll_bar_width > 0 else 0

        scroll_rect = QRect()
        if self._scrollbar_location == ScrollBarPosition.ScrollBarLeft:
            scroll_rect.setLeft(scroll_bar_width + SCROLLBAR_CONTENT_GAP)
            scroll_rect.setRight(self.width())
        else:
            scroll_rect.setLeft(0)
            scroll_rect.setRight(self.width() - scroll_bar_width - SCROLLBAR_CONTENT_GAP)

        lines_to_move = region.height() - abs(lines)
        bytes_to_move = lines_to_move * self._columns

        if lines > 0:
            # Scroll down
            first_char_pos = region.top() * self._columns
            last_char_pos = (region.top() + abs(lines)) * self._columns

            if first_char_pos + bytes_to_move <= len(self._image):
                # Move image data
                for i in range(bytes_to_move):
                    if (first_char_pos + i < len(self._image) and
                            last_char_pos + i < len(self._image)):
                        self._image[first_char_pos + i] = self._image[last_char_pos + i]

            scroll_rect.setTop(self._topMargin + region.top() * self._fontHeight)
        else:
            # Scroll up
            first_char_pos = region.top() * self._columns
            last_char_pos = (region.top() + abs(lines)) * self._columns

            if last_char_pos + bytes_to_move <= len(self._image):
                # Move image data
                for i in range(bytes_to_move - 1, -1, -1):
                    if (first_char_pos + i < len(self._image) and
                            last_char_pos + i < len(self._image)):
                        self._image[last_char_pos + i] = self._image[first_char_pos + i]

            scroll_rect.setTop(self._topMargin + (region.top() + abs(lines)) * self._fontHeight)

        scroll_rect.setHeight(lines_to_move * self._fontHeight)

        if scroll_rect.isValid() and not scroll_rect.isEmpty():
            self.scroll(0, -self._fontHeight * lines, scroll_rect)

    # Resize and geometry methods
    def resizeEvent(self, event: QResizeEvent):
        """Handle resize events"""
        self._update_image_size()
        self.processFilters()
        super().resizeEvent(event)

    def _update_image_size(self):
        """Update image size based on widget size"""
        old_image = self._image
        old_lines = self._lines
        old_columns = self._columns

        self._make_image()

        # Copy old image to reduce flicker
        if old_image:
            lines = min(old_lines, self._lines)
            columns = min(old_columns, self._columns)

            for line in range(lines):
                old_start = line * old_columns
                new_start = line * self._columns

                for col in range(columns):
                    if (old_start + col < len(old_image) and
                            new_start + col < len(self._image)):
                        self._image[new_start + col] = old_image[old_start + col]

        if self._screenWindow:
            # 修复：兼容两种方法名
            if hasattr(self._screenWindow, 'set_window_lines'):
                self._screenWindow.set_window_lines(self._lines)
            elif hasattr(self._screenWindow, 'setWindowLines'):
                self._screenWindow.setWindowLines(self._lines)

        self._resizing = (old_lines != self._lines) or (old_columns != self._columns)

        if self._resizing:
            # TODO 实时显示终端大小信息小tips，测试的时候可以打开
            #self._show_resize_notification()
            self.changedContentSizeSignal.emit(self._content_height, self._content_width)

        self._resizing = False

    def _propagate_size(self):
        """Propagate size changes"""
        if self._is_fixed_size:
            self.setSize(self._columns, self._lines)
            super().setFixedSize(self.sizeHint())
            if self.parent():
                self.parent().adjustSize()
                self.parent().setFixedSize(self.parent().sizeHint())
            return

        if self._image:
            self._update_image_size()

    def _calc_geometry(self):
        """Calculate widget geometry"""
        self._scroll_bar.resize(self._scroll_bar.sizeHint().width(), self.contentsRect().height())
        scroll_bar_width = (
            0 if self._scroll_bar.style().styleHint(QStyle.StyleHint.SH_ScrollBar_Transient, None, self._scroll_bar)
            else self._scroll_bar.width())

        if self._scrollbar_location == ScrollBarPosition.NoScrollBar:
            self._leftMargin = self._left_base_margin
            self._content_width = self.contentsRect().width() - 2 * self._left_base_margin
        elif self._scrollbar_location == ScrollBarPosition.ScrollBarLeft:
            self._leftMargin = self._left_base_margin + scroll_bar_width
            self._content_width = self.contentsRect().width() - 2 * self._left_base_margin - scroll_bar_width
            self._scroll_bar.move(self.contentsRect().topLeft())
        else:  # ScrollBarRight
            self._leftMargin = self._left_base_margin
            self._content_width = self.contentsRect().width() - 2 * self._left_base_margin - scroll_bar_width
            self._scroll_bar.move(self.contentsRect().topRight() - QPoint(self._scroll_bar.width() - 1, 0))

        self._topMargin = self._top_base_margin
        self._content_height = self.contentsRect().height() - 2 * self._top_base_margin + 1

        if not self._is_fixed_size:
            self._columns = max(1, self._content_width // self._fontWidth)
            self._usedColumns = min(self._usedColumns, self._columns)
            self._lines = max(1, self._content_height // self._fontHeight)
            self._usedLines = min(self._usedLines, self._lines)

    def _make_image(self):
        """Create the character image array"""
        self._calc_geometry()

        assert self._lines > 0 and self._columns > 0
        assert self._usedLines <= self._lines and self._usedColumns <= self._columns

        self._image_size = self._lines * self._columns
        self._image = [Character() for _ in range(self._image_size + 1)]
        self._clear_image()

    def _clear_image(self):
        """Clear the character image"""
        if not self._image:
            return

        default_char = Character()
        default_char.character = ord(' ')
        default_char.foregroundColor = CharacterColor(0, DEFAULT_FORE_COLOR)  # COLOR_SPACE_DEFAULT
        default_char.backgroundColor = CharacterColor(0, DEFAULT_BACK_COLOR)  # COLOR_SPACE_DEFAULT
        default_char.rendition = 0  # DEFAULT_RENDITION

        for i in range(len(self._image)):
            self._image[i] = default_char

    def _show_resize_notification(self):
        """Show resize notification"""
        if self._terminal_size_hint and self.isVisible():
            if self._terminal_size_startup:
                self._terminal_size_startup = False
                return

            if not self._resize_widget:
                label = self.tr("Size: XXX x XXX")
                self._resize_widget = QLabel(label, self)
                self._resize_widget.setMinimumWidth(
                    self._resize_widget.fontMetrics().horizontalAdvance(label))
                self._resize_widget.setMinimumHeight(self._resize_widget.sizeHint().height())
                self._resize_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._resize_widget.setStyleSheet(
                    "background-color:palette(window);border-style:solid;border-width:1px;border-color:palette(dark)")

                self._resize_timer = QTimer(self)
                self._resize_timer.setSingleShot(True)
                self._resize_timer.timeout.connect(self._resize_widget.hide)

            self._resize_widget.setText(self.tr(f"Size: {self._columns} x {self._lines}"))
            self._resize_widget.move(
                (self.width() - self._resize_widget.width()) // 2,
                (self.height() - self._resize_widget.height()) // 2 + 20
            )
            self._resize_widget.show()
            self._resize_timer.start(1000)

    # Focus events
    def focusInEvent(self, event: QFocusEvent):
        """Handle focus in event - 修复：与C++一致的光标处理"""
        # 修复：启动光标闪烁定时器（如果启用）
        if self._has_blinking_cursor:
            flash_time = max(QApplication.cursorFlashTime(), 1000)
            self._blink_cursor_timer.start(flash_time // 2)

        # 修复：确保光标更新
        self._update_cursor()

        # 修复：启动文本闪烁定时器（如果有闪烁文本）
        if self._has_blinker:
            self._blink_timer.start(TEXT_BLINK_DELAY)

        self.termGetFocus.emit()
        super().focusInEvent(event)

    def focusOutEvent(self, event: QFocusEvent):
        """Handle focus out event - 修复：与C++一致的光标处理"""
        # 修复：确保光标可见并绘制为非焦点状态
        self._cursor_blinking = False
        self._update_cursor()
        self._blink_cursor_timer.stop()

        # 修复：处理文本闪烁
        if self._blinking:
            self._blink_event()
        self._blink_timer.stop()

        self.termLostFocus.emit()
        super().focusOutEvent(event)

        # 失去焦点时还原选择高亮，但如果是弹出菜单（如右键菜单）导致的失焦则保留选择
        if event.reason() != Qt.FocusReason.PopupFocusReason:
            if self._screenWindow:
                try:
                    self._screenWindow.clearSelection()
                    self.updateImage()
                except Exception:
                    pass

    def showEvent(self, event: QShowEvent):
        """Handle show events"""
        self.changedContentSizeSignal.emit(self._content_height, self._content_width)
        super().showEvent(event)

    def hideEvent(self, event: QHideEvent):
        """Handle hide events"""
        self.changedContentSizeSignal.emit(self._content_height, self._content_width)
        super().hideEvent(event)

    # Clipboard operations
    @Slot()
    def copyClipboard(self):
        """Copy selection to clipboard"""
        if not self._screenWindow:
            return

        text = self._screenWindow.selectedText(self._preserve_line_breaks)
        if text:
            QApplication.clipboard().setText(text)

    @Slot()
    def pasteClipboard(self):
        """Paste from clipboard"""
        self._emit_selection(False, False)

    @Slot()
    def pasteSelection(self):
        """Paste from selection"""
        self._emit_selection(True, False)

    def _emit_selection(self, use_selection: bool, append_return: bool):
        """Emit selection as key presses"""
        if not self._screenWindow:
            return

        clipboard_mode = QClipboard.Mode.Selection if use_selection else QClipboard.Mode.Clipboard
        text = QApplication.clipboard().text(clipboard_mode)

        if not text:
            return

        # Process text
        text = text.replace('\r\n', '\n').replace('\n', '\r')

        if self._trim_pasted_trailing_newlines:
            text = text.rstrip('\r')

        if self._confirm_multiline_paste and '\r' in text:
            if not self._multiline_confirmation(text):
                return

        self._bracket_text(text)

        if append_return:
            text += '\r'

        # Emit as key press event
        key_event = QKeyEvent(QEvent.Type.KeyPress, 0, Qt.KeyboardModifier.NoModifier, text)
        self.keyPressedSignal.emit(key_event, True)

        self._screenWindow.clearSelection()

        # Handle motion after pasting
        if self._motion_after_pasting == MotionAfterPasting.MoveStartScreenWindow:
            self._screenWindow.setTrackOutput(False)
            self._screenWindow.scrollTo(0)
        elif self._motion_after_pasting == MotionAfterPasting.MoveEndScreenWindow:
            self.scrollToEnd()

    def _bracket_text(self, text: str) -> str:
        """Add bracketed paste markers if enabled"""
        if self.bracketedPasteMode() and not self._disabled_bracketed_paste_mode:
            return f"\033[200~{text}\033[201~"
        return text

    def bracketText(self, text: str) -> str:
        """
        公共接口：处理括号文本

        对应C++: void bracketText(QString& text) const
        在Python中返回处理后的文本
        """
        return self._bracket_text(text)

    def _multiline_confirmation(self, text: str) -> bool:
        """Show confirmation dialog for multiline paste"""
        confirmation = QMessageBox(self)
        confirmation.setWindowTitle(self.tr("Paste multiline text"))
        confirmation.setText(self.tr("Are you sure you want to paste this text?"))
        confirmation.setDetailedText(text)
        confirmation.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

        # Show details by default
        for btn in confirmation.buttons():
            if (confirmation.buttonRole(btn) == QMessageBox.ButtonRole.ActionRole and
                    btn.text() == QMessageBox.tr("Show Details...")):
                btn.clicked.emit()
                break

        confirmation.setDefaultButton(QMessageBox.StandardButton.Yes)
        result = confirmation.exec()

        return confirmation.standardButton(confirmation.clickedButton()) == QMessageBox.StandardButton.Yes

    def setSelection(self, text: str):
        """Set selection text"""
        if QApplication.clipboard().supportsSelection():
            QApplication.clipboard().setText(text, QClipboard.Mode.Selection)

    @Slot()
    def selectionChanged(self):
        """Handle selection changes"""
        if self._screenWindow:
            has_selection = not self._screenWindow.selectedText(False).isEmpty()
            self.copyAvailable.emit(has_selection)

    # Motion after pasting
    def setMotionAfterPasting(self, action: MotionAfterPasting):
        """Set motion after pasting behavior"""
        self._motion_after_pasting = action

    def motionAfterPasting(self) -> int:
        """Get motion after pasting behavior"""
        return self._motion_after_pasting.value

    def setConfirmMultilinePaste(self, confirm: bool):
        """Set whether to confirm multiline paste"""
        self._confirm_multiline_paste = confirm

    def setTrimPastedTrailingNewlines(self, trim: bool):
        """Set whether to trim trailing newlines from pasted text"""
        self._trim_pasted_trailing_newlines = trim

    # Flow control warning
    def setFlowControlWarningEnabled(self, enabled: bool):
        """Set whether flow control warning is enabled"""
        self._flow_control_warning_enabled = enabled
        if not enabled:
            self.outputSuspended(False)

    def flowControlWarningEnabled(self) -> bool:
        """Get whether flow control warning is enabled"""
        return self._flow_control_warning_enabled

    @Slot(bool)
    def outputSuspended(self, suspended: bool):
        """Show/hide output suspended warning"""
        if not self._output_suspended_label:
            self._output_suspended_label = QLabel(
                self.tr('<qt>Output has been <a href="http://en.wikipedia.org/wiki/Flow_control">suspended</a>'
                        ' by pressing Ctrl+S. Press <b>Ctrl+Q</b> to resume.</qt>'),
                self
            )

            palette = self._output_suspended_label.palette()
            self._output_suspended_label.setPalette(palette)
            self._output_suspended_label.setAutoFillBackground(True)
            self._output_suspended_label.setBackgroundRole(QPalette.ColorRole.Base)
            self._output_suspended_label.setFont(QApplication.font())
            self._output_suspended_label.setContentsMargins(5, 5, 5, 5)
            self._output_suspended_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.LinksAccessibleByMouse | Qt.TextInteractionFlag.LinksAccessibleByKeyboard)
            self._output_suspended_label.setOpenExternalLinks(True)
            self._output_suspended_label.setVisible(False)

            self._grid_layout.addWidget(self._output_suspended_label)
            self._grid_layout.addItem(
                QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding), 1, 0)

        self._output_suspended_label.setVisible(suspended)

    # Terminal size hint
    def setTerminalSizeHint(self, enabled: bool):
        """Set whether to show terminal size hint during resize"""
        self._terminal_size_hint = enabled

    def terminalSizeHint(self) -> bool:
        """Get whether terminal size hint is enabled"""
        return self._terminal_size_hint

    def setTerminalSizeStartup(self, enabled: bool):
        """Set whether to show size hint on startup"""
        self._terminal_size_startup = enabled

    # BiDi support
    def setBidiEnabled(self, enabled: bool):
        """Set BiDi text rendering"""
        self._bidi_enabled = enabled

    def isBidiEnabled(self) -> bool:
        """Get BiDi text rendering status"""
        return self._bidi_enabled

    # Drawing settings
    def setDrawLineChars(self, draw: bool):
        """Set whether to draw line characters"""
        self._draw_line_chars = draw

    def setBoldIntense(self, bold: bool):
        """Set whether intense colors should be bold"""
        self._boldIntense = bold

    def getBoldIntense(self) -> bool:
        """Get whether intense colors are bold"""
        return self._boldIntense

    # Static methods
    @staticmethod
    def setAntialias(antialias: bool):
        """Set text antialiasing"""
        TerminalDisplay._antialias_text = antialias

    @staticmethod
    def antialias() -> bool:
        """Get text antialiasing status"""
        return TerminalDisplay._antialias_text

    @staticmethod
    def setTransparencyEnabled(enabled: bool):
        """Set transparency support"""
        TerminalDisplay.HAVE_TRANSPARENCY = enabled

    # Mouse auto-hide
    def autoHideMouseAfter(self, delay: int):
        """Set mouse auto-hide delay"""
        if delay > -1 and not self._hide_mouse_timer:
            self._hide_mouse_timer = QTimer()
            self._hide_mouse_timer.setSingleShot(True)

        if (self._mouse_autohide_delay < 0) == (delay < 0):
            self._mouse_autohide_delay = delay
            return

        if delay > -1:
            self._hide_mouse_timer.timeout.connect(self._hide_stale_mouse)
        elif self._hide_mouse_timer:
            self._hide_mouse_timer.timeout.disconnect()

        self._mouse_autohide_delay = delay

    def mouseAutohideDelay(self) -> int:
        """Get mouse auto-hide delay"""
        return self._mouse_autohide_delay

    def _hide_stale_mouse(self):
        """Hide mouse cursor after delay"""
        if not self.underMouse():
            return

        if QApplication.activeWindow() and QApplication.activeWindow() != self.window():
            return

        if self._scroll_bar.underMouse():
            return

        QApplication.setOverrideCursor(Qt.CursorShape.BlankCursor)

    # Mouse event handling
    def mousePressEvent(self, ev: QMouseEvent):
        """Handle mouse press events - 修复选择清除逻辑，避免过度重绘"""
        if self._possible_triple_click and ev.button() == Qt.MouseButton.LeftButton:
            self._mouse_triple_click_event(ev)
            return

        if not self.contentsRect().contains(ev.pos()):
            return

        if not self._screenWindow:
            return

        char_line, char_column = self.getCharacterPosition(ev.pos())
        pos = QPoint(char_column, char_line)

        if ev.button() == Qt.MouseButton.LeftButton:
            self._line_selection_mode = False
            self._word_selection_mode = False

            self.isBusySelecting.emit(True)

            selected = False
            if self._screenWindow:
                selected = self._screenWindow.isSelected(pos.x(), pos.y())

            if (not self._ctrl_drag or ev.modifiers() & Qt.KeyboardModifier.ControlModifier) and selected:
                # Clicked inside selection - prepare for drag
                self._drag_info['state'] = DragState.diPending
                self._drag_info['start'] = ev.pos()
            else:
                # Start new selection
                self._drag_info['state'] = DragState.diNone

                self._preserve_line_breaks = not (
                        (ev.modifiers() & Qt.KeyboardModifier.ControlModifier) and
                        not (ev.modifiers() & Qt.KeyboardModifier.AltModifier)
                )
                self._column_selection_mode = (
                        (ev.modifiers() & Qt.KeyboardModifier.AltModifier) and
                        (ev.modifiers() & Qt.KeyboardModifier.ControlModifier)
                )

                if self._mouse_marks or (ev.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                    # 修复：只清除选择，不立即重绘
                    if self._screenWindow:
                        self._screenWindow.clearSelection()

                    pos.setY(pos.y() + self._scroll_bar.value())
                    self._i_pnt_sel = self._pnt_sel = pos
                    self._act_sel = 1  # Left button pressed
                else:
                    # 修复：非选择模式时清除选择
                    if self._screenWindow:
                        self._screenWindow.clearSelection()

                    self.mouseSignal.emit(0, char_column + 1,
                                          char_line + 1 + self._scroll_bar.value() - self._scroll_bar.maximum(), 0)

                # Handle hotspot activation
                hotspot = self._filter_chain.hotSpotAt(char_line, char_column)
                if hotspot and hotspot.type() == Filter.HotSpot.Type.Link:
                    hotspot.activate("click-action")

        elif ev.button() == Qt.MouseButton.MiddleButton:
            if self._mouse_marks or (ev.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                self._emit_selection(True, ev.modifiers() & Qt.KeyboardModifier.ControlModifier)
            else:
                self.mouseSignal.emit(1, char_column + 1,
                                      char_line + 1 + self._scroll_bar.value() - self._scroll_bar.maximum(), 0)

        elif ev.button() == Qt.MouseButton.RightButton:
            if self._mouse_marks or (ev.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                self.configureRequest.emit(ev.pos())
            else:
                self.mouseSignal.emit(2, char_column + 1,
                                      char_line + 1 + self._scroll_bar.value() - self._scroll_bar.maximum(), 0)

    def mouseReleaseEvent(self, ev: QMouseEvent):
        """Handle mouse release events"""
        if not self._screenWindow:
            return

        char_line, char_column = self.getCharacterPosition(ev.pos())

        if ev.button() == Qt.MouseButton.LeftButton:
            self.isBusySelecting.emit(False)

            if self._drag_info['state'] == DragState.diPending:
                # Drag was pending but never confirmed
                if self._screenWindow:
                    self._screenWindow.clearSelection()
            else:
                if self._act_sel > 1:
                    if self._screenWindow:
                        self.setSelection(self._screenWindow.selectedText(self._preserve_line_breaks))

                self._act_sel = 0

                if not self._mouse_marks and not (ev.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                    self.mouseSignal.emit(0, char_column + 1,
                                          char_line + 1 + self._scroll_bar.value() - self._scroll_bar.maximum(), 2)

            self._drag_info['state'] = DragState.diNone

        if (not self._mouse_marks and
                ((ev.button() == Qt.MouseButton.RightButton and not (
                        ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)) or
                 ev.button() == Qt.MouseButton.MiddleButton)):
            button = 1 if ev.button() == Qt.MouseButton.MiddleButton else 2
            self.mouseSignal.emit(button, char_column + 1,
                                  char_line + 1 + self._scroll_bar.value() - self._scroll_bar.maximum(), 2)

    def mouseMoveEvent(self, ev: QMouseEvent):
        """Handle mouse move events"""
        # Handle mouse auto-hide
        if self._mouse_autohide_delay > -1:
            # Mouse movement handling for auto-hide
            pass

        char_line, char_column = self.getCharacterPosition(ev.pos())

        # Handle filter hotspots
        hotspot = self._filter_chain.hotSpotAt(char_line, char_column)
        if hotspot and hotspot.type() == Filter.HotSpot.Type.Link:
            # Update hotspot highlight
            previous_area = self._mouse_over_hotspot_area
            self._mouse_over_hotspot_area = self._get_hotspot_region(hotspot)
            self.update(self._mouse_over_hotspot_area | previous_area)
        elif not self._mouse_over_hotspot_area.isEmpty():
            self.update(self._mouse_over_hotspot_area)
            self._mouse_over_hotspot_area = QRegion()

        # Handle mouse events for terminal programs
        if ev.buttons() == Qt.MouseButton.NoButton:
            return

        if not self._mouse_marks and not (ev.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            button = 3
            if ev.buttons() & Qt.MouseButton.LeftButton:
                button = 0
            elif ev.buttons() & Qt.MouseButton.MiddleButton:
                button = 1
            elif ev.buttons() & Qt.MouseButton.RightButton:
                button = 2

            self.mouseSignal.emit(button, char_column + 1,
                                  char_line + 1 + self._scroll_bar.value() - self._scroll_bar.maximum(), 1)
            return

        # Handle drag operations
        if self._drag_info['state'] == DragState.diPending:
            distance = QApplication.startDragDistance()
            if (abs(ev.pos().x() - self._drag_info['start'].x()) > distance or
                    abs(ev.pos().y() - self._drag_info['start'].y()) > distance):
                self.isBusySelecting.emit(False)
                if self._screenWindow:
                    self._screenWindow.clearSelection()
                self._do_drag()
            return
        elif self._drag_info['state'] == DragState.diDragging:
            return

        if self._act_sel == 0:
            return

        # Don't extend selection while pasting
        if ev.buttons() & Qt.MouseButton.MiddleButton:
            return

        self._extend_selection(ev.pos())

    def _get_hotspot_region(self, hotspot) -> QRegion:
        """Get region for hotspot highlighting"""
        region = QRegion()
        left_margin = self._left_base_margin

        if (self._scrollbar_location == ScrollBarPosition.ScrollBarLeft and
                not self._scroll_bar.style().styleHint(QStyle.StyleHint.SH_ScrollBar_Transient, None,
                                                       self._scroll_bar)):
            left_margin += self._scroll_bar.width()

        for line in range(hotspot.startLine(), hotspot.endLine() + 1):
            start_col = hotspot.startColumn() if line == hotspot.startLine() else 0
            end_col = hotspot.endColumn() if line == hotspot.endLine() else self._columns

            r = QRect(
                start_col * self._fontWidth + left_margin,
                line * self._fontHeight + self._top_base_margin,
                (end_col - start_col) * self._fontWidth,
                self._fontHeight
            )
            region |= r

        return region

    def _extend_selection(self, position: QPoint):
        """Extend the current selection"""
        if not self._screenWindow:
            return

        # Get text bounds
        tl = self.contentsRect().topLeft()
        text_bounds = QRect(
            tl.x() + self._leftMargin,
            tl.y() + self._topMargin,
            self._usedColumns * self._fontWidth - 1,
            self._usedLines * self._fontHeight - 1
        )

        # Adjust position within bounds
        pos = position
        pos.setX(max(text_bounds.left(), min(pos.x(), text_bounds.right())))
        pos.setY(max(text_bounds.top(), min(pos.y(), text_bounds.bottom())))

        # Handle scrolling when dragging outside bounds
        if position.y() > text_bounds.bottom():
            lines_beyond = (position.y() - text_bounds.bottom()) // self._fontHeight
            self._scroll_bar.setValue(self._scroll_bar.value() + lines_beyond + 1)
        elif position.y() < text_bounds.top():
            lines_beyond = (text_bounds.top() - position.y()) // self._fontHeight
            self._scroll_bar.setValue(self._scroll_bar.value() - lines_beyond - 1)

        char_line, char_column = self.getCharacterPosition(pos)
        here = QPoint(char_column, char_line)

        # Handle word and line selection modes
        if self._word_selection_mode:
            self._extend_word_selection(here)
        elif self._line_selection_mode:
            self._extend_line_selection(here)
        else:
            self._extend_character_selection(here)

    def _extend_word_selection(self, here: QPoint):
        """Extend word selection"""
        if not self._screenWindow or not self._image:
            return

        # 修复：实现完整的单词选择扩展逻辑 - 基于C++版本
        i_pnt_sel_corr = QPoint(self._i_pnt_sel.x(), self._i_pnt_sel.y() - self._scroll_bar.value())
        pnt_sel_corr = QPoint(self._pnt_sel.x(), self._pnt_sel.y() - self._scroll_bar.value())

        left_not_right = (here.y() < i_pnt_sel_corr.y() or
                          (here.y() == i_pnt_sel_corr.y() and here.x() < i_pnt_sel_corr.x()))
        old_left_not_right = (pnt_sel_corr.y() < i_pnt_sel_corr.y() or
                              (pnt_sel_corr.y() == i_pnt_sel_corr.y() and pnt_sel_corr.x() < i_pnt_sel_corr.x()))
        swapping = left_not_right != old_left_not_right

        # 找到单词边界
        left = here if left_not_right else i_pnt_sel_corr
        right = i_pnt_sel_corr if left_not_right else here

        # 扩展到单词开始
        line_start = left.y() * self._columns
        char_idx = line_start + left.x()
        if 0 <= char_idx < len(self._image):
            sel_class = self._char_class(self._image[char_idx])
            while ((left.x() > 0) or (left.y() > 0 and self._line_properties and
                                      len(self._line_properties) > left.y() - 1 and
                                      self._line_properties[left.y() - 1] & 0x01)):  # LINE_WRAPPED
                if left.x() > 0:
                    if self._char_class(self._image[char_idx - 1]) != sel_class:
                        break
                    char_idx -= 1
                    left.setX(left.x() - 1)
                else:
                    left.setX(self._usedColumns - 1)
                    left.setY(left.y() - 1)
                    line_start = left.y() * self._columns
                    char_idx = line_start + left.x()

        # 扩展到单词结束
        line_start = right.y() * self._columns
        char_idx = line_start + right.x()
        if 0 <= char_idx < len(self._image):
            sel_class = self._char_class(self._image[char_idx])
            while ((right.x() < self._usedColumns - 1) or
                   (right.y() < self._usedLines - 1 and self._line_properties and
                    len(self._line_properties) > right.y() and
                    self._line_properties[right.y()] & 0x01)):  # LINE_WRAPPED
                if right.x() < self._usedColumns - 1:
                    if self._char_class(self._image[char_idx + 1]) != sel_class:
                        break
                    char_idx += 1
                    right.setX(right.x() + 1)
                else:
                    right.setX(0)
                    right.setY(right.y() + 1)
                    line_start = right.y() * self._columns
                    char_idx = line_start + right.x()

        # 设置选择
        if left_not_right:
            ohere = right
            here = left
        else:
            ohere = left
            here = right

        if self._act_sel < 2 or swapping:
            self._screenWindow.setSelectionStart(ohere.x(), ohere.y(), False)

        self._act_sel = 2
        self._pnt_sel = QPoint(here.x(), here.y())
        self._pnt_sel.setY(self._pnt_sel.y() + self._scroll_bar.value())
        self._screenWindow.setSelectionEnd(here.x(), here.y())

    def _extend_line_selection(self, here: QPoint):
        """Extend line selection"""
        if not self._screenWindow:
            return

        # 修复：实现完整的行选择扩展逻辑 - 基于C++版本
        i_pnt_sel_corr = QPoint(self._i_pnt_sel.x(), self._i_pnt_sel.y() - self._scroll_bar.value())

        above_not_below = here.y() < i_pnt_sel_corr.y()

        above = here if above_not_below else i_pnt_sel_corr
        below = i_pnt_sel_corr if above_not_below else here

        # 扩展到完整行
        while (above.y() > 0 and self._line_properties and
               len(self._line_properties) > above.y() - 1 and
               self._line_properties[above.y() - 1] & 0x01):  # LINE_WRAPPED
            above.setY(above.y() - 1)

        while (below.y() < self._usedLines - 1 and self._line_properties and
               len(self._line_properties) > below.y() and
               self._line_properties[below.y()] & 0x01):  # LINE_WRAPPED
            below.setY(below.y() + 1)

        above.setX(0)
        below.setX(self._usedColumns - 1)

        # 设置选择
        if above_not_below:
            ohere = below
            here = above
        else:
            ohere = above
            here = below

        new_sel_begin = QPoint(ohere.x(), ohere.y())
        swapping = self._triple_sel_begin != new_sel_begin
        self._triple_sel_begin = new_sel_begin

        if self._act_sel < 2 or swapping:
            self._screenWindow.setSelectionStart(ohere.x(), ohere.y(), False)

        self._act_sel = 2
        self._pnt_sel = QPoint(here.x(), here.y())
        self._pnt_sel.setY(self._pnt_sel.y() + self._scroll_bar.value())
        self._screenWindow.setSelectionEnd(here.x(), here.y())

    def _extend_character_selection(self, here: QPoint):
        """Extend character selection - 修复：简化逻辑，避免过度重绘"""
        if not self._screenWindow:
            return

        # 基本的选择范围计算
        i_pnt_sel_corr = QPoint(self._i_pnt_sel.x(), self._i_pnt_sel.y() - self._scroll_bar.value())
        pnt_sel_corr = QPoint(self._pnt_sel.x(), self._pnt_sel.y() - self._scroll_bar.value())

        # 检查选择方向
        left_not_right = (here.y() < i_pnt_sel_corr.y() or
                          (here.y() == i_pnt_sel_corr.y() and here.x() < i_pnt_sel_corr.x()))
        old_left_not_right = (pnt_sel_corr.y() < i_pnt_sel_corr.y() or
                              (pnt_sel_corr.y() == i_pnt_sel_corr.y() and pnt_sel_corr.x() < i_pnt_sel_corr.x()))
        swapping = left_not_right != old_left_not_right

        # 简化的选择点计算
        if left_not_right:
            ohere = i_pnt_sel_corr
            offset = 0
        else:
            ohere = i_pnt_sel_corr
            offset = -1

        # 检查是否移动了
        if here == pnt_sel_corr and self._scroll_bar.value() == self._scroll_bar.value():
            return

        if here == ohere:
            return

        # 设置选择范围
        if self._act_sel < 2 or swapping:
            if self._column_selection_mode and not self._line_selection_mode and not self._word_selection_mode:
                self._screenWindow.setSelectionStart(ohere.x(), ohere.y(), True)
            else:
                self._screenWindow.setSelectionStart(ohere.x() - 1 - offset, ohere.y(), False)

        self._act_sel = 2
        self._pnt_sel = QPoint(here.x(), here.y())
        self._pnt_sel.setY(self._pnt_sel.y() + self._scroll_bar.value())

        # 设置选择结束位置
        if self._column_selection_mode and not self._line_selection_mode and not self._word_selection_mode:
            self._screenWindow.setSelectionEnd(here.x(), here.y())
        else:
            self._screenWindow.setSelectionEnd(here.x() + offset, here.y())

        # 修复：移除延迟更新机制，使用正常的重绘
        # 延迟更新可能导致选择状态不同步
        self.update()

    def mouseDoubleClickEvent(self, ev: QMouseEvent):
        """Handle mouse double click events"""
        if ev.button() != Qt.MouseButton.LeftButton:
            return

        if not self._screenWindow:
            return

        char_line, char_column = self.getCharacterPosition(ev.pos())
        pos = QPoint(char_column, char_line)

        # Send double-click to terminal if not in selection mode
        if not self._mouse_marks and not (ev.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.mouseSignal.emit(0, pos.x() + 1,
                                  pos.y() + 1 + self._scroll_bar.value() - self._scroll_bar.maximum(), 0)
            return

        # Start word selection
        self._screenWindow.clearSelection()

        # 修复：创建新的 QPoint 对象，避免修改 pos 引用
        self._i_pnt_sel = QPoint(pos.x(), pos.y())
        self._i_pnt_sel.setY(self._i_pnt_sel.y() + self._scroll_bar.value())

        self._word_selection_mode = True

        # Select word under cursor
        self._select_word_at_position(pos)

        self._possible_triple_click = True
        QTimer.singleShot(QApplication.doubleClickInterval(), self._triple_click_timeout)

    def _select_word_at_position(self, pos: QPoint):
        """Select word at given position"""
        if not self._screenWindow or not self._image:
            return

        line_start = pos.y() * self._columns
        if line_start + pos.x() >= len(self._image):
            return

        char_idx = line_start + pos.x()
        sel_class = self._char_class(self._image[char_idx])

        # Find start of word
        start_x = pos.x()
        while start_x > 0 or (pos.y() > 0 and self._line_properties and
                              len(self._line_properties) > pos.y() - 1 and
                              self._line_properties[pos.y() - 1] & 0x01):  # LINE_WRAPPED
            if start_x > 0:
                if self._char_class(self._image[char_idx - 1]) != sel_class:
                    break
                char_idx -= 1
                start_x -= 1
            else:
                # Move to previous line
                start_x = self._usedColumns - 1
                pos.setY(pos.y() - 1)
                line_start = pos.y() * self._columns
                char_idx = line_start + start_x

        begin_sel = QPoint(start_x, pos.y())

        # Find end of word
        end_x = pos.x()
        char_idx = line_start + pos.x()
        while (end_x < self._usedColumns - 1 or
               (pos.y() < self._usedLines - 1 and self._line_properties and
                len(self._line_properties) > pos.y() and
                self._line_properties[pos.y()] & 0x01)):  # LINE_WRAPPED
            if end_x < self._usedColumns - 1:
                if self._char_class(self._image[char_idx + 1]) != sel_class:
                    break
                char_idx += 1
                end_x += 1
            else:
                # Move to next line
                end_x = 0
                pos.setY(pos.y() + 1)
                line_start = pos.y() * self._columns
                char_idx = line_start + end_x

        end_sel = QPoint(end_x, pos.y())

        self._act_sel = 2
        self._screenWindow.setSelectionStart(begin_sel.x(), begin_sel.y(), False)
        self._screenWindow.setSelectionEnd(end_sel.x(), end_sel.y())
        self.setSelection(self._screenWindow.selectedText(self._preserve_line_breaks))

    def _char_class(self, ch: Character) -> str:
        """Get character class for word selection"""
        # 修复：处理宽字符的第二部分（character为0），将其视为字母数字
        if ch.character == 0:
            return 'a'

        char = chr(ch.character) if ch.character > 0 else ' '

        if char.isspace():
            return ' '

        if char.isalnum() or char in self._word_characters:
            return 'a'

        return char

    def _mouse_triple_click_event(self, ev: QMouseEvent):
        """Handle mouse triple click events"""
        if not self._screenWindow:
            return

        char_line, char_column = self.getCharacterPosition(ev.pos())
        self._i_pnt_sel = QPoint(char_column, char_line)

        self._screenWindow.clearSelection()
        self._line_selection_mode = True
        self._word_selection_mode = False
        self._act_sel = 2

        self.isBusySelecting.emit(True)

        # Extend to line boundaries
        while (self._i_pnt_sel.y() > 0 and self._line_properties and
               len(self._line_properties) > self._i_pnt_sel.y() - 1 and
               self._line_properties[self._i_pnt_sel.y() - 1] & 0x01):  # LINE_WRAPPED
            self._i_pnt_sel.setY(self._i_pnt_sel.y() - 1)

        if self._triple_click_mode == TripleClickMode.SelectWholeLine:
            self._screenWindow.setSelectionStart(0, self._i_pnt_sel.y(), False)
            self._triple_sel_begin = QPoint(0, self._i_pnt_sel.y())
        else:  # SelectForwardsFromCursor
            # Find word boundary
            self._select_word_at_position(self._i_pnt_sel)
            self._triple_sel_begin = QPoint(self._i_pnt_sel.x(), self._i_pnt_sel.y())

        while (self._i_pnt_sel.y() < self._lines - 1 and self._line_properties and
               len(self._line_properties) > self._i_pnt_sel.y() and
               self._line_properties[self._i_pnt_sel.y()] & 0x01):  # LINE_WRAPPED
            self._i_pnt_sel.setY(self._i_pnt_sel.y() + 1)

        self._screenWindow.setSelectionEnd(self._columns - 1, self._i_pnt_sel.y())
        self.setSelection(self._screenWindow.selectedText(self._preserve_line_breaks))

        self._i_pnt_sel.setY(self._i_pnt_sel.y() + self._scroll_bar.value())

    @Slot()
    def _triple_click_timeout(self):
        """Reset triple click flag"""
        self._possible_triple_click = False

    def wheelEvent(self, ev: QWheelEvent):
        """Handle wheel events - 优化版本，减少滚动卡顿"""
        if ev.angleDelta().y() == 0:
            return

        # 滚轮事件节流 - 避免过于频繁的滚动
        if not hasattr(self, '_last_wheel_time'):
            self._last_wheel_time = 0
            self._accumulated_wheel_delta = 0

        import time
        current_time = time.time()

        # 累积滚轮增量，减少小幅滚动的频率
        self._accumulated_wheel_delta += ev.angleDelta().y()

        # 限制处理频率：至少间隔8ms（约120fps）
        if current_time - self._last_wheel_time < 0.008:
            return

        self._last_wheel_time = current_time
        wheel_delta = self._accumulated_wheel_delta
        self._accumulated_wheel_delta = 0

        if self._mouse_marks:
            # Terminal handles mouse marks - use scrollbar or send keys
            can_scroll = self._scroll_bar.maximum() > 0
            if can_scroll:
                # 直接调整滚动条值，避免中间的event处理
                current_value = self._scroll_bar.value()
                wheel_degrees = wheel_delta // 8
                lines_to_scroll = max(1, abs(wheel_degrees) // 120) * (1 if wheel_delta > 0 else -1)

                new_value = max(0, min(self._scroll_bar.maximum(),
                                       current_value - lines_to_scroll * 3))  # 3行每次滚动

                if new_value != current_value:
                    self._scroll_bar.setValue(new_value)
            else:
                # Send arrow keys to terminal
                key = Qt.Key.Key_Up if wheel_delta > 0 else Qt.Key.Key_Down
                wheel_degrees = abs(wheel_delta) // 8
                lines_to_scroll = max(1, wheel_degrees // 120)  # 每120度滚动1行

                for _ in range(lines_to_scroll):
                    key_event = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
                    self.keyPressedSignal.emit(key_event, False)
        else:
            # Send mouse wheel events to terminal
            char_line, char_column = self.getCharacterPosition(ev.position())
            button = 4 if wheel_delta > 0 else 5
            self.mouseSignal.emit(button, char_column + 1,
                                  char_line + 1 + self._scroll_bar.value() - self._scroll_bar.maximum(), 0)

    def enterEvent(self, event: QEnterEvent):
        """Handle mouse enter events"""
        # Handle mouse auto-hide
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent):
        """Handle mouse leave events"""
        # Handle mouse auto-hide
        super().leaveEvent(event)

    # Keyboard event handling
    def keyPressEvent(self, event: QKeyEvent):
        """处理按键事件 - 增强错误处理避免段错误"""
        try:
            # 修改安全检查：不要过于严格检查 _screenWindow
            # 因为信号链路已经建立，键盘事件应该通过信号传递
            if not hasattr(self, 'keyPressedSignal'):
                event.ignore()
                return

            # 发射键盘事件信号 - 这是最重要的部分
            try:
                self.keyPressedSignal.emit(event, False)
            except RuntimeError as e:
                # 信号连接可能已失效
                print(f"Warning: keyPressedSignal 发射失败: {e}")

            event.accept()

        except Exception as e:
            # 捕获所有异常以防止段错误
            print(f"Warning: keyPressEvent 错误: {e}")
            event.ignore()

    def event(self, event: QEvent) -> bool:
        """Handle general events"""
        if event.type() == QEvent.Type.ShortcutOverride:
            return self._handle_shortcut_override_event_v2(event)
        elif event.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange):
            self._scroll_bar.setPalette(QApplication.palette())

        return super().event(event)

    def _handle_shortcut_override_event_v2(self, event: QKeyEvent) -> bool:
        """Handle shortcut override events - 修复版本"""
        modifiers = event.modifiers()

        # Allow host to decide on shortcuts
        if modifiers != Qt.KeyboardModifier.NoModifier:
            modifier_count = bin(modifiers.value).count('1')
            if modifier_count < 2:
                override = False
                if hasattr(self, 'overrideShortcutCheck'):
                    self.overrideShortcutCheck.emit(event, override)
                if override:
                    event.accept()
                    return True

        # Override specific shortcuts needed by terminal
        override_keys = [
            Qt.Key.Key_Tab, Qt.Key.Key_Delete, Qt.Key.Key_Home, Qt.Key.Key_End,
            Qt.Key.Key_Backspace, Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Escape,
            Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown
        ]

        if event.key() in override_keys:
            event.accept()
            return True

        return False

    # Input method handling
    def inputMethodEvent(self, event: QInputMethodEvent):
        """Handle input method events"""
        if event.commitString():
            # 修复：直接发送UTF-8编码的字节到模拟器，而不是通过QKeyEvent
            # 这样可以正确处理中文等多字节字符
            self.sendStringToEmu.emit(event.commitString().encode('utf-8'))

        self._input_method_data['preedit_string'] = event.preeditString()
        self.update(self._preedit_rect() | self._input_method_data.get('previous_preedit_rect', QRect()))

        event.accept()

    def inputMethodQuery(self, query: Qt.InputMethodQuery):
        """Handle input method queries"""
        cursor_pos = self._cursor_position()

        if query == Qt.InputMethodQuery.ImCursorRectangle:
            return self._image_to_widget(QRect(cursor_pos.x(), cursor_pos.y(), 1, 1))
        elif query == Qt.InputMethodQuery.ImFont:
            return self.font()
        elif query == Qt.InputMethodQuery.ImCursorPosition:
            return cursor_pos.x()
        elif query == Qt.InputMethodQuery.ImSurroundingText:
            # Return text from current line
            line_text = ""
            if self._image and cursor_pos.y() < len(self._image) // self._columns:
                line_start = cursor_pos.y() * self._columns
                for x in range(self._usedColumns):
                    if line_start + x < len(self._image):
                        char = self._image[line_start + x]
                        if char.character > 0:
                            line_text += chr(char.character)
            return line_text
        elif query == Qt.InputMethodQuery.ImCurrentSelection:
            return ""

        return None

    # Drag and drop handling
    def dragEnterEvent(self, event: QDragEnterEvent):
        """Handle drag enter events"""
        if event.mimeData().hasFormat("text/plain") or event.mimeData().urls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        """Handle drop events"""
        urls = event.mimeData().urls()

        if urls:
            drop_text = ""
            for url in urls:
                if url.isLocalFile():
                    url_text = url.toLocalFile()
                else:
                    url_text = url.toString()

                # Quote the URL
                drop_text += f"'{url_text.replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}' "
        else:
            drop_text = event.mimeData().text()
            drop_text = drop_text.replace('\r\n', '\n').replace('\n', '\r')

            if self._trim_pasted_trailing_newlines:
                drop_text = drop_text.rstrip('\r')

            if self._confirm_multiline_paste and '\r' in drop_text:
                if not self._multiline_confirmation(drop_text):
                    return

        self.sendStringToEmu.emit(drop_text.encode('utf-8'))

    def _do_drag(self):
        """Perform drag operation"""
        self._drag_info['state'] = DragState.diDragging
        drag = QDrag(self)
        mime_data = QMimeData()

        if QApplication.clipboard().supportsSelection():
            mime_data.setText(QApplication.clipboard().text(QClipboard.Mode.Selection))

        drag.setMimeData(mime_data)
        drag.exec(Qt.DropAction.CopyAction)

    def focusNextPrevChild(self, next: bool) -> bool:
        """Handle focus navigation"""
        if next:
            return False  # Disable Tab navigation in terminal
        return super().focusNextPrevChild(next)

    def __del__(self):
        """析构函数 - 安全清理资源避免段错误"""
        try:
            # 首先停止所有定时器
            if hasattr(self, '_blink_timer') and self._blink_timer:
                try:
                    self._blink_timer.stop()
                    self._blink_timer.timeout.disconnect()
                    self._blink_timer.deleteLater()
                    self._blink_timer = None
                except (RuntimeError, AttributeError):
                    pass

            if hasattr(self, '_cursor_blink_timer') and self._cursor_blink_timer:
                try:
                    self._cursor_blink_timer.stop()
                    self._cursor_blink_timer.timeout.disconnect()
                    self._cursor_blink_timer.deleteLater()
                    self._cursor_blink_timer = None
                except (RuntimeError, AttributeError):
                    pass

            if hasattr(self, '_resize_timer') and self._resize_timer:
                try:
                    self._resize_timer.stop()
                    self._resize_timer.timeout.disconnect()
                    self._resize_timer.deleteLater()
                    self._resize_timer = None
                except (RuntimeError, AttributeError):
                    pass

            if hasattr(self, '_output_suspend_timer') and self._output_suspend_timer:
                try:
                    self._output_suspend_timer.stop()
                    self._output_suspend_timer.timeout.disconnect()
                    self._output_suspend_timer.deleteLater()
                    self._output_suspend_timer = None
                except (RuntimeError, AttributeError):
                    pass

            if hasattr(self, '_hide_mouse_timer') and self._hide_mouse_timer:
                try:
                    self._hide_mouse_timer.stop()
                    self._hide_mouse_timer.timeout.disconnect()
                    self._hide_mouse_timer.deleteLater()
                    self._hide_mouse_timer = None
                except (RuntimeError, AttributeError):
                    pass

            # 断开所有信号连接以防止回调到已删除的对象
            try:
                self.disconnect()
            except (RuntimeError, AttributeError):
                pass

            # 清理过滤器链
            if hasattr(self, '_filter_chain') and self._filter_chain:
                try:
                    self._filter_chain = None
                except (RuntimeError, AttributeError):
                    pass

            # 清理屏幕窗口连接
            if hasattr(self, '_screen_window') and self._screenWindow:
                try:
                    # 断开屏幕窗口的信号连接
                    self._screenWindow.disconnect(self)
                    self._screenWindow = None
                except (RuntimeError, AttributeError):
                    pass

            # 清理滚动条
            if hasattr(self, '_scroll_bar') and self._scroll_bar:
                try:
                    self._scroll_bar.disconnect()
                    self._scroll_bar.deleteLater()
                    self._scroll_bar = None
                except (RuntimeError, AttributeError):
                    pass

            # 清理自动滚动处理器
            if hasattr(self, '_auto_scroll_handler') and self._auto_scroll_handler:
                try:
                    self._auto_scroll_handler.deleteLater()
                    self._auto_scroll_handler = None
                except (RuntimeError, AttributeError):
                    pass

        except Exception:
            # 析构函数中忽略所有异常，防止程序崩溃
            pass
