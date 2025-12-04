#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Vt102Emulation - VT102终端模拟器 (修正版)
从Konsole的Vt102Emulation.cpp/h转换而来，使用C++风格的命名

Copyright 2007-2008 by Robert Knight <robert.knight@gmail.com>
Copyright 1997,1998 by Lars Doelle <lars.doelle@on-line.de>

转换为Python PySide6版本，使用C++风格命名
"""

from PySide6.QtCore import (
    Qt, QTimer, Slot, QStringEncoder, QSize
)
from PySide6.QtGui import QKeyEvent

from qtermwidget.emulation import Emulation
from qtermwidget.keyboard_translator import CTRL_MOD
from qtermwidget.screen import MODES_SCREEN, MODE_NewLine, MODE_Insert, MODE_Cursor

# VT102模式常量定义 (从Vt102Emulation.h)
MODE_AppScreen = MODES_SCREEN + 0  # Mode #1
MODE_AppCuKeys = MODES_SCREEN + 1  # Application cursor keys (DECCKM)
MODE_AppKeyPad = MODES_SCREEN + 2  # Application keypad
MODE_Mouse1000 = MODES_SCREEN + 3  # Send mouse X,Y position on press and release
MODE_Mouse1001 = MODES_SCREEN + 4  # Use Highlight mouse tracking
MODE_Mouse1002 = MODES_SCREEN + 5  # Use cell motion mouse tracking
MODE_Mouse1003 = MODES_SCREEN + 6  # Use all motion mouse tracking
MODE_Mouse1005 = MODES_SCREEN + 7  # Xterm-style extended coordinates
MODE_Mouse1006 = MODES_SCREEN + 8  # 2nd Xterm-style extended coordinates
MODE_Mouse1015 = MODES_SCREEN + 9  # Urxvt-style extended coordinates
MODE_Ansi = MODES_SCREEN + 10  # Use US Ascii for character sets G0-G3 (DECANM)
MODE_132Columns = MODES_SCREEN + 11  # 80 <-> 132 column mode switch (DECCOLM)
MODE_Allow132Columns = MODES_SCREEN + 12  # Allow DECCOLM mode
MODE_BracketedPaste = MODES_SCREEN + 13  # Xterm-style bracketed paste mode
MODE_total = MODES_SCREEN + 14


# Token类型宏定义 - 与C++版本完全一致
# TY_CONSTRUCT 构造一个32位整数：
# Bits 0-7: Type (T)
# Bits 8-15: Character Code (A)
# Bits 16-31: Parameter/Value (N)
def TY_CONSTRUCT(T, A, N):
    return (((int(N) & 0xffff) << 16) | ((int(A) & 0xff) << 8) | (int(T) & 0xff))


def TY_CHR(): return TY_CONSTRUCT(0, 0, 0)


def TY_CTL(A): return TY_CONSTRUCT(1, A, 0)


def TY_ESC(A): return TY_CONSTRUCT(2, A, 0)


def TY_ESC_CS(A, B): return TY_CONSTRUCT(3, A, B)


def TY_ESC_DE(A): return TY_CONSTRUCT(4, A, 0)


def TY_CSI_PS(A, N): return TY_CONSTRUCT(5, A, N)


def TY_CSI_PN(A): return TY_CONSTRUCT(6, A, 0)


def TY_CSI_PR(A, N): return TY_CONSTRUCT(7, A, N)


def TY_VT52(A): return TY_CONSTRUCT(8, A, 0)


def TY_CSI_PG(A): return TY_CONSTRUCT(9, A, 0)


def TY_CSI_PE(A): return TY_CONSTRUCT(10, A, 0)


def TY_CSI_PS_SP(A, N): return TY_CONSTRUCT(11, A, N)


# 常量定义 - 与C++版本一致
MAX_ARGUMENT = 4096
MAX_TOKEN_LENGTH = 256
MAXARGS = 15
ESC = 27
DEL = 127

# 字符类别标志位 - 与C++版本一致
CTL = 1  # Control character
CHR = 2  # Printable character
CPN = 4  # Parameter ending character
DIG = 8  # Digit
SCS = 16  # Character set selection
GRP = 32  # Group characters
CPS = 64  # Character which indicates end of window resize sequence

# 颜色空间常量
COLOR_SPACE_RGB = 1
COLOR_SPACE_256 = 2
COLOR_SPACE_SYSTEM = 3
COLOR_SPACE_DEFAULT = 4

# VT100图形字符映射表
vt100_graphics = [
    0x0020, 0x25C6, 0x2592, 0x2409, 0x240C, 0x240D, 0x240A, 0x00B0,
    0x00B1, 0x2424, 0x240B, 0x2518, 0x2510, 0x250C, 0x2514, 0x253C,
    0x23BA, 0x23BB, 0x2500, 0x23BC, 0x23BD, 0x251C, 0x2524, 0x2534,
    0x252C, 0x2502, 0x2264, 0x2265, 0x03C0, 0x2260, 0x00A3, 0x00B7
]


# 宏定义函数 - 与C++版本的宏完全对应
def CNTL(c):
    return ord(c) - ord('@')


class CharCodes:
    """字符集编码信息 - 对应C++: struct CharCodes"""

    def __init__(self):
        self.charset = ['B', 'B', 'B', 'B']  # char charset[4]
        self.cu_cs = 0  # int cu_cs
        self.graphic = False  # bool graphic
        self.pound = False  # bool pound
        self.sa_graphic = False  # bool sa_graphic
        self.sa_pound = False  # bool sa_pound


class TerminalState:
    """终端状态 - 对应C++: class TerminalState"""

    def __init__(self):
        self.mode = [False] * MODE_total


class Vt102Emulation(Emulation):
    """
    VT102终端模拟器实现 - 对应C++: class Vt102Emulation : public Emulation
    """

    def __init__(self):
        super().__init__()

        # 初始化成员变量 - 对应C++版本成员变量
        self.prevCC = 0  # int prevCC
        self._titleUpdateTimer = QTimer(self)  # QTimer* _titleUpdateTimer
        self._reportFocusEvents = False  # bool _reportFocusEvents
        self._toUtf8 = QStringEncoder(QStringEncoder.Encoding.Utf8)  # QStringEncoder _toUtf8

        # 字符集管理 - 对应C++: CharCodes _charset[2]
        self._charset = [CharCodes(), CharCodes()]

        # 终端状态 - 对应C++: TerminalState _currentModes, _savedModes
        self._currentModes = TerminalState()
        self._savedModes = TerminalState()

        # Tokenizer变量 - 对应C++版本
        self.tokenBuffer = [0] * MAX_TOKEN_LENGTH  # wchar_t tokenBuffer[MAX_TOKEN_LENGTH]
        self.tokenBufferPos = 0  # int tokenBufferPos
        self.argc = 0  # int argc
        self.argv = [0] * MAXARGS  # int argv[MAXARGS]

        # 字符分类表 - 对应C++: int charClass[256]
        self.charClass = [0] * 256

        # 标题更新缓冲 - 对应C++: QHash<int,QString> _pendingTitleUpdates
        self._pendingTitleUpdates = {}

        # 设置定时器
        self._titleUpdateTimer.setSingleShot(True)
        self._titleUpdateTimer.timeout.connect(self.updateTitle)

        # 初始化tokenizer和重置状态
        self.initTokenizer()
        self.reset()

    def __del__(self):
        """析构函数 - 对应C++: ~Vt102Emulation()"""
        pass

    # ============================================================================
    # 公共接口方法 - 对应C++头文件中的public方法
    # ============================================================================

    def clearEntireScreen(self):
        """清空整个屏幕 - 对应C++: void clearEntireScreen() override"""
        self._currentScreen.clearEntireScreen()
        # 对于清屏操作，使用更高效的更新策略
        self._bulkTimer1.stop()
        self._bulkTimer2.stop()
        self.outputChanged.emit()  # 立即发射信号，不使用定时器

    def reset(self):
        """重置终端状态 - 对应C++: void reset() override"""
        self.resetTokenizer()
        self.resetModes()
        self.resetCharset(0)
        self._screen[0].reset()
        self.resetCharset(1)
        self._screen[1].reset()
        self.bufferedUpdate()

    def eraseChar(self) -> str:
        """返回用于退格的字符 - 对应C++: char eraseChar() const override"""
        if hasattr(self, '_keyTranslator') and self._keyTranslator:
            # 简化处理，返回标准退格字符
            return '\b'
        return '\b'

    # ============================================================================
    # 公共槽方法 - 对应C++头文件中的public slots
    # ============================================================================

    def sendString(self, s: str | bytes, length: int = -1):
        """发送字符串 - 对应C++: void sendString(const char*,int length = -1) override"""
        if isinstance(s, bytes):
            data = s[:length] if length >= 0 else s
        else:
            if length >= 0:
                data = s[:length].encode('utf-8')
            else:
                data = s.encode('utf-8')
        self.sendData.emit(data, len(data))

    def sendText(self, text: str):
        """发送文本 - 对应C++: void sendText(const QString& text) override"""
        if text:
            # 对应C++版本：创建QKeyEvent并调用sendKeyEvent
            from PySide6.QtGui import QKeyEvent
            from PySide6.QtCore import QEvent, Qt

            event = QKeyEvent(QEvent.Type.KeyPress, 0, Qt.KeyboardModifier.NoModifier, text)
            self.sendKeyEvent(event, False)  # 使用sendKeyEvent处理文本

    def sendKeyEvent(self, event: QKeyEvent, fromPaste: bool = False):
        """发送键盘事件 - 对应C++: void sendKeyEvent(QKeyEvent*, bool fromPaste) override"""
        modifiers = event.modifiers()

        # 获取当前终端状态标志 - 对应C++的states获取逻辑
        from .keyboard_translator import KeyboardTranslatorState
        states = KeyboardTranslatorState.NoState

        if self.getMode(MODE_NewLine):
            states |= KeyboardTranslatorState.NewLineState
        if self.getMode(MODE_Ansi):
            states |= KeyboardTranslatorState.AnsiState
        if self.getMode(MODE_AppCuKeys):
            states |= KeyboardTranslatorState.CursorKeysState
        if self.getMode(MODE_AppScreen):
            states |= KeyboardTranslatorState.AlternateScreenState
        if self.getMode(MODE_AppKeyPad) and (modifiers & Qt.KeyboardModifier.KeypadModifier):
            states |= KeyboardTranslatorState.ApplicationKeypadState

        # 检查流控制状态
        if modifiers & CTRL_MOD:
            if event.key() == Qt.Key.Key_S:
                self.flowControlKeyPressed.emit(True)
            elif event.key() in (Qt.Key.Key_Q, Qt.Key.Key_C):
                self.flowControlKeyPressed.emit(False)

        # 查找键绑定 - 使用键盘翻译器
        if hasattr(self, '_keyTranslator') and self._keyTranslator:
            # 查找键映射条目
            entry = self._keyTranslator.findEntry(event.key(), modifiers, states)

            # 发送结果到终端
            textToSend = b""

            # Alt修饰符的特殊处理
            wantsAltModifier = bool(entry.modifiers() & entry.modifierMask() & Qt.KeyboardModifier.AltModifier)
            wantsMetaModifier = bool(entry.modifiers() & entry.modifierMask() & Qt.KeyboardModifier.MetaModifier)
            wantsAnyModifier = bool(entry.state() & entry.stateMask() & KeyboardTranslatorState.AnyModifierState)

            if (modifiers & Qt.KeyboardModifier.AltModifier and
                    not (wantsAltModifier or wantsAnyModifier) and
                    event.text()):
                textToSend = b"\033" + textToSend

            if (modifiers & Qt.KeyboardModifier.MetaModifier and
                    not (wantsMetaModifier or wantsAnyModifier) and
                    event.text()):
                textToSend = b"\030@s" + textToSend

            # 处理命令或文本
            from .keyboard_translator import KeyboardTranslatorCommand
            if entry.command() != KeyboardTranslatorCommand.NoCommand:
                if entry.command() & KeyboardTranslatorCommand.EraseCommand:
                    textToSend += self.eraseChar().encode('utf-8')
                else:
                    self.handleCommandFromKeyboard.emit(entry.command())
            elif entry.text():
                # 获取映射的文本（应用通配符扩展）- 对应C++: entry.text(true,modifiers)
                entry_text = entry.text(True, modifiers)
                textToSend += entry_text
            elif (modifiers & CTRL_MOD and
                  0x40 <= event.key() < 0x5f):
                # Ctrl+字母组合
                textToSend += bytes([event.key() & 0x1f])
            elif event.key() == Qt.Key.Key_Tab:
                textToSend += b"\x09"
            elif event.key() == Qt.Key.Key_PageUp:
                textToSend += b"\033[5~"
            elif event.key() == Qt.Key.Key_PageDown:
                textToSend += b"\033[6~"
            elif event.text():
                # 回退到默认文本处理
                textToSend += event.text().encode('utf-8')

            # 发送输出
            if not fromPaste and textToSend:
                self.outputFromKeypressEvent.emit()

            if textToSend:
                # print(f"Vt102Emulation.sendKeyEvent: 发射sendData信号，数据: {repr(textToSend)}")
                self.sendData.emit(textToSend, len(textToSend))

        else:
            # 没有键盘翻译器的错误处理
            error_msg = "No keyboard translator available. The information needed to convert key presses into characters to send to the terminal is missing."
            self.reset()
            self.receiveData(error_msg.encode('utf-8'), len(error_msg.encode('utf-8')))

    def sendMouseEvent(self, cb: int, cx: int, cy: int, eventType: int):
        """发送鼠标事件 - 对应C++: void sendMouseEvent(int buttons, int column, int line, int eventType) override"""
        if cx < 1 or cy < 1:
            return

        # 按钮释放编码（除了1006模式）
        if eventType == 2 and not self.getMode(MODE_Mouse1006):
            cb = 3

        # 普通按钮编码为 0x20 + button
        # 鼠标滚轮(buttons 4,5)编码为 0x5c + button
        if cb >= 4:
            cb += 0x3c

        # 鼠标移动处理
        if ((self.getMode(MODE_Mouse1002) or self.getMode(MODE_Mouse1003)) and
                eventType == 1):
            cb += 0x20  # 添加32表示移动事件

        command = ""

        # 检查扩展（按偏好递减顺序）
        if self.getMode(MODE_Mouse1006):
            command = f"\033[<{cb};{cx};{cy}{'m' if eventType == 2 else 'M'}"
        elif self.getMode(MODE_Mouse1015):
            command = f"\033[{cb + 0x20};{cx};{cy}M"
        elif self.getMode(MODE_Mouse1005):
            if cx <= 2015 and cy <= 2015:
                # UTF-8编码坐标
                coords = chr(cx + 0x20) + chr(cy + 0x20)
                command = f"\033[M{chr(cb + 0x20)}{coords}"
        elif cx <= 223 and cy <= 223:
            command = f"\033[M{chr(cb + 0x20)}{chr(cx + 0x20)}{chr(cy + 0x20)}"

        if command:
            self.sendString(command)

    def focusLost(self):
        """焦点丢失 - 对应C++: virtual void focusLost()"""
        if self._reportFocusEvents:
            self.sendString("\033[O")

    def focusGained(self):
        """焦点获得 - 对应C++: virtual void focusGained()"""
        if self._reportFocusEvents:
            self.sendString("\033[I")

    # ============================================================================
    # 受保护方法 - 对应C++头文件中的protected方法
    # ============================================================================

    def setMode(self, mode: int):
        """设置模式 - 对应C++: void setMode(int mode) override"""
        self._currentModes.mode[mode] = True

        if mode == MODE_132Columns:
            if self.getMode(MODE_Allow132Columns):
                self.clearScreenAndSetColumns(132)
            else:
                self._currentModes.mode[mode] = False
        elif mode in (MODE_Mouse1000, MODE_Mouse1001, MODE_Mouse1002, MODE_Mouse1003):
            self.programUsesMouseChanged.emit(False)
        elif mode == MODE_BracketedPaste:
            self.programBracketedPasteModeChanged.emit(True)
        elif mode == MODE_AppScreen:
            self._screen[1].clearSelection()
            self.setScreen(1)

        if mode < MODES_SCREEN:
            self._screen[0].setMode(mode)
            self._screen[1].setMode(mode)

    def resetMode(self, mode: int):
        """重置模式 - 对应C++: void resetMode(int mode) override"""
        self._currentModes.mode[mode] = False

        if mode == MODE_132Columns:
            if self.getMode(MODE_Allow132Columns):
                self.clearScreenAndSetColumns(80)
        elif mode in (MODE_Mouse1000, MODE_Mouse1001, MODE_Mouse1002, MODE_Mouse1003):
            self.programUsesMouseChanged.emit(True)
        elif mode == MODE_BracketedPaste:
            self.programBracketedPasteModeChanged.emit(False)
        elif mode == MODE_AppScreen:
            self._screen[0].clearSelection()
            self.setScreen(0)

        if mode < MODES_SCREEN:
            self._screen[0].resetMode(mode)
            self._screen[1].resetMode(mode)

    def receiveChar(self, cc: int):
        """
        接收字符并处理 - 对应C++: void Vt102Emulation::receiveChar(wchar_t cc)
        这是终端模拟器的核心状态机，用于解析输入的字符流
        """
        if cc == DEL:
            return  # VT100: ignore.

        if self.ces(CTL, cc):
            # 忽略 OSC "ESC]" 文本部分的控制字符
            if self.Xpe():
                self.prevCC = cc
                return

            # DEC HACK: 控制字符允许出现在 ESC 序列内部
            if cc == CNTL('X') or cc == CNTL('Z') or cc == ESC:
                self.resetTokenizer()  # VT100: CAN or SUB
            if cc != ESC:
                self.processToken(TY_CTL(cc + ord('@')), 0, 0)
                return

        # 推进状态
        self.addToCurrentToken(cc)

        s = self.tokenBuffer
        p = self.tokenBufferPos

        if self.getMode(MODE_Ansi):
            if self.lec(1, 0, ESC):
                return
            if self.lec(1, 0, ESC + 128):
                s[0] = ESC
                self.receiveChar(ord('['))
                return
            if self.les(2, 1, GRP):
                return
            if self.Xte(cc):
                self.processWindowAttributeChange()
                self.resetTokenizer()
                return
            if self.Xpe():
                self.prevCC = cc
                return
            if self.lec(3, 2, ord('?')):
                return
            if self.lec(3, 2, ord('>')):
                return
            if self.lec(3, 2, ord('!')):
                return
            if self.lun():
                self.processToken(TY_CHR(), self.applyCharset(cc), 0)
                self.resetTokenizer()
                return
            if self.lec(2, 0, ESC):
                self.processToken(TY_ESC(s[1]), 0, 0)
                self.resetTokenizer()
                return
            if self.les(3, 1, SCS):
                self.processToken(TY_ESC_CS(s[1], s[2]), 0, 0)
                self.resetTokenizer()
                return
            if self.lec(3, 1, ord('#')):
                self.processToken(TY_ESC_DE(s[2]), 0, 0)
                self.resetTokenizer()
                return
            if self.eps(CPN):
                self.processToken(TY_CSI_PN(cc), self.argv[0], self.argv[1])
                self.resetTokenizer()
                return
            if self.esp():
                return
            if self.lec(5, 4, ord('q')) and s[3] == ord(' '):
                self.processToken(TY_CSI_PS_SP(cc, self.argv[0]), self.argv[0], 0)
                self.resetTokenizer()
                return

            # resize = \e[8;<row>;<col>t
            if self.eps(CPS):
                self.processToken(TY_CSI_PS(cc, self.argv[0]), self.argv[1], self.argv[2])
                self.resetTokenizer()
                return

            if self.epe():
                self.processToken(TY_CSI_PE(cc), 0, 0)
                self.resetTokenizer()
                return
            if self.ees(DIG):
                self.addDigit(cc - ord('0'))
                return
            if self.eec(ord(';')) or self.eec(ord(':')):
                self.addArgument()
                return

            for i in range(self.argc + 1):
                if self.epp():
                    self.processToken(TY_CSI_PR(cc, self.argv[i]), 0, 0)
                elif self.egt():
                    self.processToken(TY_CSI_PG(cc), 0, 0)  # spec. case for ESC]>0c or ESC]>c
                elif (cc == ord('m') and self.argc - i >= 4 and (self.argv[i] == 38 or self.argv[i] == 48)
                      and self.argv[i + 1] == 2):
                    # ESC[ ... 48;2;<red>;<green>;<blue> ... m -or- ESC[ ... 38;2;<red>;<green>;<blue> ... m
                    i += 2
                    self.processToken(TY_CSI_PS(cc, self.argv[i - 2]), COLOR_SPACE_RGB,
                                      (self.argv[i] << 16) | (self.argv[i + 1] << 8) | self.argv[i + 2])
                    i += 2
                elif (cc == ord('m') and self.argc - i >= 2 and (self.argv[i] == 38 or self.argv[i] == 48)
                      and self.argv[i + 1] == 5):
                    # ESC[ ... 48;5;<index> ... m -or- ESC[ ... 38;5;<index> ... m
                    i += 2
                    self.processToken(TY_CSI_PS(cc, self.argv[i - 2]), COLOR_SPACE_256, self.argv[i])
                    i += 2
                else:
                    self.processToken(TY_CSI_PS(cc, self.argv[i]), 0, 0)
            self.resetTokenizer()
        else:
            # VT52 Mode
            if self.lec(1, 0, ESC):
                return
            if self.les(1, 0, CHR):
                self.processToken(TY_CHR(), s[0], 0)
                self.resetTokenizer()
                return
            if self.lec(2, 1, ord('Y')):
                return
            if self.lec(3, 1, ord('Y')):
                return
            if p < 4:
                self.processToken(TY_VT52(s[1]), 0, 0)
                self.resetTokenizer()
                return
            self.processToken(TY_VT52(s[1]), s[2], s[3])
            self.resetTokenizer()
            return

    def processWindowAttributeChange(self):
        """
        处理窗口属性变化 - 对应C++: void Vt102Emulation::processWindowAttributeChange()
        处理 OSC 序列 (Operating System Command)
        """
        attributeToChange = 0
        i = 2

        # 解析属性编号
        while (i < self.tokenBufferPos and
               ord('0') <= self.tokenBuffer[i] <= ord('9')):
            attributeToChange = 10 * attributeToChange + (self.tokenBuffer[i] - ord('0'))
            i += 1

        if i >= self.tokenBufferPos or self.tokenBuffer[i] != ord(';'):
            self.reportDecodingError()
            return

        # 从分号后的第一个字符开始
        start_pos = i + 1
        # # 减2跳过结束标记
        length = self.tokenBufferPos - i - 2

        if length < 0:
            length = 0

        chars = []
        for j in range(start_pos, start_pos + length):
            if j < self.tokenBufferPos:
                chars.append(chr(self.tokenBuffer[j]))

        new_value = ''.join(chars)

        self._pendingTitleUpdates[attributeToChange] = new_value
        self._titleUpdateTimer.start(20)

    # ============================================================================
    # 私有槽方法 - 对应C++头文件中的private slots
    # ============================================================================

    @Slot()
    def updateTitle(self):
        """更新标题 - 对应C++: void updateTitle()"""
        for arg in list(self._pendingTitleUpdates.keys()):
            self.titleChanged.emit(arg, self._pendingTitleUpdates[arg])
        self._pendingTitleUpdates.clear()

    # ============================================================================
    # 私有方法 - 对应C++头文件中的private方法
    # ============================================================================

    def applyCharset(self, c: int) -> int:
        """应用当前字符映射"""
        charset = self._charset[self._currentScreen == self._screen[1]]

        if charset.graphic and 0x5f <= c <= 0x7e:
            return vt100_graphics[c - 0x5f]
        if charset.pound and c == ord('#'):
            return 0xa3  # 英镑符号
        return c

    def setCharset(self, n: int, cs: str):
        """设置字符集（在两个屏幕上）"""
        self._charset[0].charset[n & 3] = cs
        self.useCharset(self._charset[0].cu_cs)
        self._charset[1].charset[n & 3] = cs
        self.useCharset(self._charset[1].cu_cs)

    def useCharset(self, n: int):
        """使用字符集"""
        charset = self._charset[self._currentScreen == self._screen[1]]
        charset.cu_cs = n & 3
        charset.graphic = (charset.charset[n & 3] == '0')
        charset.pound = (charset.charset[n & 3] == 'A')

    def setAndUseCharset(self, n: int, cs: str):
        """设置并使用字符集"""
        charset = self._charset[self._currentScreen == self._screen[1]]
        charset.charset[n & 3] = cs
        self.useCharset(n & 3)

    def saveCursor(self):
        """保存光标"""
        charset = self._charset[self._currentScreen == self._screen[1]]
        charset.sa_graphic = charset.graphic
        charset.sa_pound = charset.pound
        self._currentScreen.saveCursor()

    def restoreCursor(self):
        """恢复光标"""
        charset = self._charset[self._currentScreen == self._screen[1]]
        charset.graphic = charset.sa_graphic
        charset.pound = charset.sa_pound
        self._currentScreen.restoreCursor()

    def resetCharset(self, scrno: int):
        """重置字符集"""
        self._charset[scrno].cu_cs = 0
        self._charset[scrno].charset = ['B', 'B', 'B', 'B']
        self._charset[scrno].sa_graphic = False
        self._charset[scrno].sa_pound = False
        self._charset[scrno].graphic = False
        self._charset[scrno].pound = False

    def setMargins(self, top: int, bottom: int):
        """设置边距"""
        self._screen[0].setMargins(top, bottom)
        self._screen[1].setMargins(top, bottom)

    def setDefaultMargins(self):
        """设置默认边距"""
        self._screen[0].setDefaultMargins()
        self._screen[1].setDefaultMargins()

    def getMode(self, mode: int) -> bool:
        """获取模式状态"""
        return self._currentModes.mode[mode]

    def saveMode(self, mode: int):
        """保存模式"""
        self._savedModes.mode[mode] = self._currentModes.mode[mode]

    def restoreMode(self, mode: int):
        """恢复模式"""
        if self._savedModes.mode[mode]:
            self.setMode(mode)
        else:
            self.resetMode(mode)

    def resetModes(self):
        """重置模式"""
        modes_to_reset = [
            MODE_132Columns, MODE_Mouse1000, MODE_Mouse1001, MODE_Mouse1002,
            MODE_Mouse1003, MODE_Mouse1005, MODE_Mouse1006, MODE_Mouse1015,
            MODE_BracketedPaste, MODE_AppScreen, MODE_AppCuKeys, MODE_AppKeyPad
        ]

        for mode in modes_to_reset:
            self.resetMode(mode)
            self.saveMode(mode)

        self.resetMode(MODE_NewLine)
        self.setMode(MODE_Ansi)

    def resetTokenizer(self):
        """重置tokenizer状态"""
        self.tokenBufferPos = 0
        self.argc = 0
        self.argv[0] = 0
        self.argv[1] = 0
        self.prevCC = 0

    def addToCurrentToken(self, cc: int):
        """添加字符到当前token"""
        self.tokenBuffer[self.tokenBufferPos] = cc
        self.tokenBufferPos = min(self.tokenBufferPos + 1, MAX_TOKEN_LENGTH - 1)

    def addDigit(self, digit: int):
        """添加数字到当前参数"""
        if self.argv[self.argc] < MAX_ARGUMENT:
            self.argv[self.argc] = 10 * self.argv[self.argc] + digit

    def addArgument(self):
        """添加新参数"""
        self.argc = min(self.argc + 1, MAXARGS - 1)
        self.argv[self.argc] = 0

    def initTokenizer(self):
        """初始化字符分类表"""
        for i in range(256):
            self.charClass[i] = 0
        # 控制字符 (0-31)
        for i in range(32):
            self.charClass[i] |= CTL

        # 可打印字符 (32-255)
        for i in range(32, 256):
            self.charClass[i] |= CHR

        # 参数结束字符
        for char in b"@ABCDEFGHILMPSTXZbcdfry":
            self.charClass[char] |= CPN

        # 窗口尺寸改变序列结束字符
        for char in b"t":
            self.charClass[char] |= CPS

        # 数字字符
        for char in b"0123456789":
            self.charClass[char] |= DIG

        # 字符集选择字符
        for char in b"()+*%":
            self.charClass[char] |= SCS

        # 组字符
        for char in b"()+*#[]%":
            self.charClass[char] |= GRP
        self.resetTokenizer()

    # ============================================================================
    # VT102状态检查宏 - 模拟C++宏以保持逻辑一致性
    # ============================================================================

    def lec(self, P: int, L: int, C: int) -> bool:
        return self.tokenBufferPos == P and L < self.tokenBufferPos and self.tokenBuffer[L] == C

    def lun(self) -> bool:
        return self.tokenBufferPos == 1 and self.tokenBuffer[0] >= 32

    def les(self, P: int, L: int, C: int) -> bool:
        return (self.tokenBufferPos == P and L < self.tokenBufferPos and
                self.tokenBuffer[L] < 256 and (self.charClass[self.tokenBuffer[L]] & C) == C)

    def eec(self, C: int) -> bool:
        return self.tokenBufferPos >= 3 and self.tokenBuffer[self.tokenBufferPos - 1] == C

    def ees(self, C: int) -> bool:
        cc = self.tokenBuffer[self.tokenBufferPos - 1] if self.tokenBufferPos > 0 else 0
        return self.tokenBufferPos >= 3 and cc < 256 and (self.charClass[cc] & C) == C

    def eps(self, C: int) -> bool:
        if self.tokenBufferPos < 3 or self.tokenBuffer[2] in (ord('?'), ord('!'), ord('>')):
            return False
        cc = self.tokenBuffer[self.tokenBufferPos - 1] if self.tokenBufferPos > 0 else 0
        return cc < 256 and (self.charClass[cc] & C) == C

    def epp(self) -> bool:
        return self.tokenBufferPos >= 3 and self.tokenBuffer[2] == ord('?')

    def epe(self) -> bool:
        return self.tokenBufferPos >= 3 and self.tokenBuffer[2] == ord('!')

    def egt(self) -> bool:
        return self.tokenBufferPos >= 3 and self.tokenBuffer[2] == ord('>')

    def esp(self) -> bool:
        return self.tokenBufferPos == 4 and self.tokenBuffer[3] == ord(' ')

    def Xpe(self) -> bool:
        return self.tokenBufferPos >= 2 and self.tokenBuffer[1] == ord(']')

    def Xte(self, cc: int) -> bool:
        return self.Xpe() and (cc == 7 or (self.prevCC == 27 and cc == 92))

    def ces(self, c: int, cc: int) -> bool:
        return cc < 256 and (self.charClass[cc] & c) == c and not self.Xte(cc)

    # ============================================================================
    # Token处理核心逻辑 - 已重构优化
    # ============================================================================

    def reportDecodingError(self):
        """报告解码错误"""
        if (self.tokenBufferPos == 0 or
                (self.tokenBufferPos == 1 and (self.tokenBuffer[0] & 0xff) >= 32)):
            return
        token_str = ''.join(chr(c) for c in self.tokenBuffer[:self.tokenBufferPos])
        print(f"Undecodable sequence: {repr(token_str)}")

    def reportCursorPosition(self):
        """报告光标位置 (CPR)"""
        y = self._currentScreen.getCursorY() + 1
        x = self._currentScreen.getCursorX() + 1
        self.sendString(f"\033[{y};{x}R")

    def reportTerminalType(self):
        """报告终端类型 (DA)"""
        if self.getMode(MODE_Ansi):
            self.sendString("\033[?1;2c")  # VT100
        else:
            self.sendString("\033/Z")  # VT52

    def reportSecondaryAttributes(self):
        """报告次要属性 (DA2)"""
        if self.getMode(MODE_Ansi):
            self.sendString("\033[>0;115;0c")
        else:
            self.sendString("\033/Z")

    def reportTerminalParms(self, p: int):
        """报告终端参数"""
        self.sendString(f"\033[{p};1;1;112;112;1;0x")

    def reportStatus(self):
        """报告状态 (DSR)"""
        self.sendString("\033[0n")  # 0 = Ready

    def reportAnswerBack(self):
        """报告应答 (ENQ)"""
        self.sendString("")  # 默认为空

    def processToken(self, token: int, p: int, q: int):
        """
        解释token - 对应C++: void processToken(int token, wchar_t p, int q)
        将巨型的switch/if-else结构重构为分发处理，提高代码可读性和维护性
        """
        # 解析token结构
        # token = (param << 16) | (char << 8) | type
        token_type = token & 0xff
        ch = (token >> 8) & 0xff
        param = (token >> 16) & 0xffff

        if token_type == 0:  # TY_CHR
            # 显示字符
            self._currentScreen.displayCharacter(chr(p) if p <= 0x10FFFF else ' ')
        elif token_type == 1:  # TY_CTL
            self._process_control_char(ch)
        elif token_type == 2:  # TY_ESC
            self._process_escape_sequence(ch)
        elif token_type == 3:  # TY_ESC_CS
            self._process_charset_selection(ch, param)
        elif token_type == 4:  # TY_ESC_DE
            self._process_dec_sequence(ch)
        elif token_type == 5:  # TY_CSI_PS
            self._process_csi_ps(ch, param, p, q)
        elif token_type == 6:  # TY_CSI_PN
            self._process_csi_pn(ch, p, q)
        elif token_type == 7:  # TY_CSI_PR
            self._process_csi_pr(ch, param)
        elif token_type == 8:  # TY_VT52
            self._process_vt52(ch, p, q)
        elif token_type == 9:  # TY_CSI_PG
            if ch == ord('c'):
                self.reportSecondaryAttributes()
        elif token_type == 10:  # TY_CSI_PE
            pass  # 暂不处理
        elif token_type == 11:  # TY_CSI_PS_SP
            self._process_csi_ps_sp(ch, param)
        else:
            self.reportDecodingError()

    def _process_control_char(self, ch: int):
        """处理控制字符 (0-31)"""
        # 常用控制字符处理
        if ch == ord('H'):  # BS: Backspace
            self._currentScreen.backspace()
        elif ch == ord('I'):  # HT: Horizontal Tab
            self._currentScreen.tab()
        elif ch in (ord('J'), ord('K'), ord('L')):  # LF, VT, FF
            self._currentScreen.newLine()
        elif ch == ord('M'):  # CR: Carriage Return
            self._currentScreen.toStartOfLine()
        elif ch == ord('G'):  # BEL: Bell
            self.stateSet.emit(1)
        elif ch == ord('E'):  # ENQ: Enquiry
            self.reportAnswerBack()
        elif ch == ord('N'):  # SO: Shift Out (Use G1)
            self.useCharset(1)
        elif ch == ord('O'):  # SI: Shift In (Use G0)
            self.useCharset(0)
        elif ch in (ord('X'), ord('Z')):  # CAN, SUB
            self._currentScreen.displayCharacter('\u2592')
        # 忽略其他字符

    def _process_escape_sequence(self, ch: int):
        """处理 ESC 序列"""
        if ch == ord('D'):  # IND: Index
            self._currentScreen.index()
        elif ch == ord('E'):  # NEL: Next Line
            self._currentScreen.nextLine()
        elif ch == ord('H'):  # HTS: Horizontal Tab Set
            self._currentScreen.changeTabStop(True)
        elif ch == ord('M'):  # RI: Reverse Index
            self._currentScreen.reverseIndex()
        elif ch == ord('Z'):  # DECID: Identify Terminal
            self.reportTerminalType()
        elif ch == ord('c'):  # RIS: Reset to Initial State
            self.reset()
        elif ch == ord('n'):  # LS2: Locking Shift 2
            self.useCharset(2)
        elif ch == ord('o'):  # LS3: Locking Shift 3
            self.useCharset(3)
        elif ch == ord('7'):  # DECSC: Save Cursor
            self.saveCursor()
        elif ch == ord('8'):  # DECRC: Restore Cursor
            self.restoreCursor()
        elif ch == ord('='):  # DECKPAM: Keypad Application Mode
            self.setMode(MODE_AppKeyPad)
        elif ch == ord('>'):  # DECKPNM: Keypad Numeric Mode
            self.resetMode(MODE_AppKeyPad)
        elif ch == ord('<'):  # VT52 -> ANSI
            self.setMode(MODE_Ansi)

    def _process_charset_selection(self, ch: int, param: int):
        """处理字符集选择序列 ESC (,),*,+"""
        # param is the second char (B in TY_CONSTRUCT(3, A, B))
        # ch is the designator ((, ), *, +)
        cs = chr(param)
        if ch == ord('('):
            self.setCharset(0, cs)  # G0
        elif ch == ord(')'):
            self.setCharset(1, cs)  # G1
        elif ch == ord('*'):
            self.setCharset(2, cs)  # G2
        elif ch == ord('+'):
            self.setCharset(3, cs)  # G3

    def _process_dec_sequence(self, ch: int):
        """处理 DEC 私有序列 ESC #"""
        if ch == ord('8'):  # DECALN: Screen Alignment Pattern
            self._currentScreen.helpAlign()
        elif ch in (ord('3'), ord('4'), ord('5'), ord('6')):
            # double-height/width lines
            double_width = (ch != ord('5'))
            double_height = (ch in (ord('3'), ord('4')))
            self._currentScreen.setLineProperty(2, double_width)
            self._currentScreen.setLineProperty(4, double_height)

    def _process_csi_ps(self, ch: int, param: int, p: int, q: int):
        """处理 CSI Pn... 序列"""
        if ch == ord('m'):  # SGR: Select Graphic Rendition
            self._process_sgr(param, p, q)
        elif ch == ord('t'):  # Window manipulation
            if param == 8:  # Resize
                self.setImageSize(p, q)
                self.imageResizeRequest.emit(QSize(q, p))
            elif param == 28:
                self.changeTabTextColorRequest.emit(p)
        elif ch == ord('K'):  # EL: Erase in Line
            if param == 0:
                self._currentScreen.clearToEndOfLine()
            elif param == 1:
                self._currentScreen.clearToBeginOfLine()
            elif param == 2:
                self._currentScreen.clearEntireLine()
        elif ch == ord('J'):  # ED: Erase in Display
            if param == 0:
                self._currentScreen.clearToEndOfScreen()
            elif param == 1:
                self._currentScreen.clearToBeginOfScreen()
            elif param == 2:
                self._currentScreen.clearEntireScreen()
            elif param == 3:
                self.clearHistory()
        elif ch == ord('g'):  # TBC: Tab Clear
            if param == 0:
                self._currentScreen.changeTabStop(False)
            elif param == 3:
                self._currentScreen.clearTabStops()
        elif ch == ord('h'):  # SM: Set Mode
            if param == 4:
                self._currentScreen.setMode(MODE_Insert)
            elif param == 20:
                self.setMode(MODE_NewLine)
        elif ch == ord('l'):  # RM: Reset Mode
            if param == 4:
                self._currentScreen.resetMode(MODE_Insert)
            elif param == 20:
                self.resetMode(MODE_NewLine)
        elif ch == ord('s'):  # SCP: Save Cursor Position
            self.saveCursor()
        elif ch == ord('u'):  # RCP: Restore Cursor Position
            self.restoreCursor()
        elif ch == ord('n'):  # DSR: Device Status Report
            if param == 5:
                self.reportStatus()
            elif param == 6:
                self.reportCursorPosition()
        elif ch == ord('x'):  # DECREQTPARM
            if param in (0, 1):
                self.reportTerminalParms(param + 2)

    def _process_sgr(self, param: int, p: int, q: int):
        """处理 SGR (Select Graphic Rendition) 序列"""
        if param == 0:
            self._currentScreen.setDefaultRendition()
        elif param == 1:
            self._currentScreen.setRendition(1)  # Bold
        elif param == 2:
            self._currentScreen.setRendition(256)  # Faint
        elif param == 3:
            self._currentScreen.setRendition(4)  # Italic
        elif param == 4:
            self._currentScreen.setRendition(2)  # Underline
        elif param == 5:
            self._currentScreen.setRendition(8)  # Blink
        elif param == 7:
            self._currentScreen.setRendition(16)  # Reverse
        elif param == 8:
            self._currentScreen.setRendition(32)  # Conceal
        elif param == 9:
            self._currentScreen.setRendition(64)  # Strikeout
        elif param == 53:
            self._currentScreen.setRendition(128)  # Overline
        # Reset
        elif param == 21:
            self._currentScreen.resetRendition(1)
        elif param == 22:
            self._currentScreen.resetRendition(1)
            self._currentScreen.resetRendition(256)
        elif param == 23:
            self._currentScreen.resetRendition(4)
        elif param == 24:
            self._currentScreen.resetRendition(2)
        elif param == 25:
            self._currentScreen.resetRendition(8)
        elif param == 27:
            self._currentScreen.resetRendition(16)
        elif param == 28:
            self._currentScreen.resetRendition(32)
        elif param == 29:
            self._currentScreen.resetRendition(64)
        elif param == 55:
            self._currentScreen.resetRendition(128)
        # Colors
        elif 30 <= param <= 37:
            self._currentScreen.setForeColor(COLOR_SPACE_SYSTEM, param - 30)
        elif param == 38:
            self._currentScreen.setForeColor(p, q)  # Extended foreground
        elif param == 39:
            self._currentScreen.setForeColor(COLOR_SPACE_DEFAULT, 0)
        elif 40 <= param <= 47:
            self._currentScreen.setBackColor(COLOR_SPACE_SYSTEM, param - 40)
        elif param == 48:
            self._currentScreen.setBackColor(p, q)  # Extended background
        elif param == 49:
            self._currentScreen.setBackColor(COLOR_SPACE_DEFAULT, 1)
        # Bright Colors
        elif 90 <= param <= 97:
            self._currentScreen.setForeColor(COLOR_SPACE_SYSTEM, param - 90 + 8)
        elif 100 <= param <= 107:
            self._currentScreen.setBackColor(COLOR_SPACE_SYSTEM, param - 100 + 8)

    def _process_csi_pn(self, ch: int, p: int, q: int):
        """处理 CSI Pn 序列 (参数通常是数值)"""
        if ch == ord('@'):
            self._currentScreen.insertChars(p)
        elif ch == ord('A'):
            self._currentScreen.cursorUp(p)
        elif ch == ord('B'):
            self._currentScreen.cursorDown(p)
        elif ch == ord('C'):
            self._currentScreen.cursorRight(p)
        elif ch == ord('D'):
            self._currentScreen.cursorLeft(p)
        elif ch == ord('E'):
            self._currentScreen.cursorNextLine(p)
        elif ch == ord('F'):
            self._currentScreen.cursorPreviousLine(p)
        elif ch == ord('G'):
            self._currentScreen.setCursorX(p)
        elif ch == ord('H') or ch == ord('f'):
            self._currentScreen.setCursorYX(p, q)
        elif ch == ord('I'):
            self._currentScreen.tab(p)
        elif ch == ord('L'):
            self._currentScreen.insertLines(p)
        elif ch == ord('M'):
            self._currentScreen.deleteLines(p)
        elif ch == ord('P'):
            self._currentScreen.deleteChars(p)
        elif ch == ord('S'):
            self._currentScreen.scrollUp(p)
        elif ch == ord('T'):
            self._currentScreen.scrollDown(p)
        elif ch == ord('X'):
            self._currentScreen.eraseChars(p)
        elif ch == ord('Z'):
            self._currentScreen.backtab(p)
        elif ch == ord('b'):
            self._currentScreen.repeatChars(p)
        elif ch == ord('c'):
            self.reportTerminalType()
        elif ch == ord('d'):
            self._currentScreen.setCursorY(p)
        elif ch == ord('r'):
            self.setMargins(p, q)

    def _process_csi_pr(self, ch: int, param: int):
        """处理私有 CSI 序列 (?h/?l)"""
        # param combines the mode number and '?' (which is ignored here as type is checked)
        # Actually, CSI_PR is for "? Pn h" or "? Pn l"
        # token has '?' encoded? No, TY_CSI_PR is triggered by '?' in receiveChar.
        # param is the mode number. ch is 'h' or 'l'.

        if ch == ord('h'):  # DECSET
            self._process_private_mode(param, True)
        elif ch == ord('l'):  # DECRST
            self._process_private_mode(param, False)

    def _process_private_mode(self, mode_num: int, enable: bool):
        """处理私有模式设置/重置"""
        target_mode = -1

        if mode_num == 1:
            target_mode = MODE_AppCuKeys
        elif mode_num == 25:
            target_mode = MODE_Cursor
        elif mode_num == 47:
            target_mode = MODE_AppScreen
        elif mode_num == 1000:
            target_mode = MODE_Mouse1000
        elif mode_num == 1002:
            target_mode = MODE_Mouse1002
        elif mode_num == 1005:
            target_mode = MODE_Mouse1005
        elif mode_num == 1006:
            target_mode = MODE_Mouse1006
        elif mode_num == 1015:
            target_mode = MODE_Mouse1015
        elif mode_num == 1047:
            target_mode = MODE_AppScreen

        # 特殊处理
        if mode_num == 1048:
            if enable:
                self.saveCursor()
            else:
                self.restoreCursor()
            return
        elif mode_num == 1049:
            if enable:
                self.saveCursor()
                self.setMode(MODE_AppScreen)
                self.clearEntireScreen()
            else:
                self.resetMode(MODE_AppScreen)
                self.restoreCursor()
            return

        if target_mode != -1:
            if enable:
                self.setMode(target_mode)
            else:
                self.resetMode(target_mode)

    def _process_csi_ps_sp(self, ch: int, param: int):
        """处理带空格的 CSI 序列"""
        if ch == ord('q'):  # DECSCUSR (Set Cursor Style)
            # 0,1: Blinking Block
            # 2: Steady Block
            # 3: Blinking Underline
            # 4: Steady Underline
            # 5: Blinking Bar
            # 6: Steady Bar
            shape = 0  # Block
            blinking = True

            if param in (0, 1):
                pass
            elif param == 2:
                blinking = False
            elif param == 3:
                shape = 1
            elif param == 4:
                shape = 1
                blinking = False
            elif param == 5:
                shape = 2
            elif param == 6:
                shape = 2
                blinking = False

            self.cursorChanged.emit(shape, blinking)

    def _process_vt52(self, ch: int, p: int, q: int):
        """处理 VT52 序列"""
        if ch == ord('A'):
            self._currentScreen.cursorUp(1)
        elif ch == ord('B'):
            self._currentScreen.cursorDown(1)
        elif ch == ord('C'):
            self._currentScreen.cursorRight(1)
        elif ch == ord('D'):
            self._currentScreen.cursorLeft(1)
        elif ch == ord('F'):
            self.setAndUseCharset(0, '0')  # Graphics
        elif ch == ord('G'):
            self.setAndUseCharset(0, 'B')  # ASCII
        elif ch == ord('H'):
            self._currentScreen.setCursorYX(1, 1)
        elif ch == ord('I'):
            self._currentScreen.reverseIndex()
        elif ch == ord('J'):
            self._currentScreen.clearToEndOfScreen()
        elif ch == ord('K'):
            self._currentScreen.clearToEndOfLine()
        elif ch == ord('Y'):
            self._currentScreen.setCursorYX(p - 31, q - 31)
        elif ch == ord('Z'):
            self.reportTerminalType()
        elif ch == ord('<'):
            self.setMode(MODE_Ansi)
        elif ch == ord('='):
            self.setMode(MODE_AppKeyPad)
        elif ch == ord('>'):
            self.resetMode(MODE_AppKeyPad)
