#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Emulation Base Class for Python PySide6
Converted from Konsole's Emulation.cpp/h

Copyright 2007-2008 by Robert Knight <robertknight@gmail.com>
Copyright 1997,1998 by Lars Doelle <lars.doelle@on-line.de>
Copyright 1996 by Matthias Ettrich <ettrich@kde.org>

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.
"""

from abc import ABC, ABCMeta, abstractmethod
from enum import Enum
from typing import Optional, List, Dict, Tuple, Set

from PySide6.QtCore import (
    QTimer, QSize, QObject,
    Signal, Slot
)
from PySide6.QtGui import QKeyEvent

from qtermwidget.history import HistoryType
from qtermwidget.keyboard_translator import KeyboardTranslator, KeyboardTranslatorManager
# Import the already implemented modules
from qtermwidget.screen import Screen
from qtermwidget.screen_window import ScreenWindow
from qtermwidget.terminal_character_decoder import TerminalCharacterDecoder

# Emulation state constants - 对应C++: enum
NOTIFYNORMAL = 0
NOTIFYBELL = 1
NOTIFYACTIVITY = 2
NOTIFYSILENCE = 3


class KeyboardCursorShape(Enum):
    """Available shapes for the keyboard cursor - 对应C++: enum class KeyboardCursorShape"""
    BlockCursor = 0
    UnderlineCursor = 1
    IBeamCursor = 2


class EmulationCodec(Enum):
    """Available character encoding codecs"""
    LocaleCodec = 0
    Utf8Codec = 1


class ExtendedCharTable:
    """
    Table for storing sequences of unicode characters, indexed by hash keys.
    Used for characters which require more than one unicode code point.
    
    对应C++: class ExtendedCharTable
    """
    
    def __init__(self):
        """
        构造新的字符表。
        对应C++: ExtendedCharTable()
        """
        # 对应C++: QHash<uint,uint*> extendedCharTable
        # 在C++中存储格式: buffer[0] = length, buffer[1..length] = unicode points
        # Python中使用Dict[int, List[int]]，其中List[0] = length, List[1:] = unicode points
        self.extendedCharTable: Dict[int, List[int]] = {}
        
        # 对应C++: QSet<ScreenWindow*> windows
        self.windows: List[ScreenWindow] = []
    
    def extendedCharHash(self, unicodePoints: List[int]) -> int:
        """
        计算unicode点序列的哈希键
        对应C++: uint extendedCharHash(uint* unicodePoints , ushort length) const
        """
        hash_value = 0
        for point in unicodePoints:
            hash_value = (31 * hash_value + point) & 0xFFFFFFFF
        return hash_value
    
    def extendedCharMatch(self, hash_value: int, unicodePoints: List[int]) -> bool:
        """
        测试由hash指定的表中条目是否与字符序列unicodePoints匹配
        对应C++: bool extendedCharMatch(uint hash , uint* unicodePoints , ushort length) const
        """
        if hash_value not in self.extendedCharTable:
            return False
        
        entry = self.extendedCharTable[hash_value]
        if not entry or entry[0] != len(unicodePoints):
            return False
        
        # 比较实际内容（从entry[1]开始）
        for i in range(len(unicodePoints)):
            if entry[i + 1] != unicodePoints[i]:
                return False
        
        return True
    
    def createExtendedChar(self, unicodePoints: List[int]) -> int:
        """
        将unicode字符序列添加到表中并返回哈希码
        对应C++: uint createExtendedChar(uint* unicodePoints , ushort length)
        """
        if not unicodePoints:
            return 0
        
        # 查找此序列在表中的位置
        hash_value = self.extendedCharHash(unicodePoints)
        initial_hash = hash_value
        tried_cleaning_solution = False
        
        # 检查现有条目是否匹配
        while hash_value in self.extendedCharTable and hash_value != 0:  # 0对字符有特殊含义，因此不使用
            if self.extendedCharMatch(hash_value, unicodePoints):
                # 该序列已在表中有条目，返回其哈希
                return hash_value
            else:
                # 如果哈希已被不同的unicode字符点序列使用，则尝试下一个哈希
                hash_value = (hash_value + 1) & 0xFFFFFFFF
                
                if hash_value == initial_hash:
                    if not tried_cleaning_solution:
                        tried_cleaning_solution = True
                        # 所有哈希都满了，转到所有Screen并尝试释放一些
                        # 这很慢但应该很少发生
                        used_extended_chars: Set[int] = set()
                        for window in self.windows:
                            if window.screen():
                                used_extended_chars.update(window.screen().usedExtendedChars())
                        
                        # 移除未使用的条目
                        to_remove = []
                        for hash_key in self.extendedCharTable:
                            if hash_key not in used_extended_chars:
                                to_remove.append(hash_key)
                        
                        for hash_key in to_remove:
                            del self.extendedCharTable[hash_key]
                    else:
                        print("Warning: Using all the extended char hashes, going to miss this extended character")
                        return 0
        
        # 将新序列添加到表中并返回索引
        # 格式: [length, unicode_point1, unicode_point2, ...]
        buffer = [len(unicodePoints)] + unicodePoints
        self.extendedCharTable[hash_value] = buffer
        
        return hash_value
    
    def lookupExtendedChar(self, hash_value: int) -> Tuple[Optional[List[int]], int]:
        """
        查找并返回指向unicode字符序列的指针
        对应C++: uint* lookupExtendedChar(uint hash , ushort& length) const
        """
        if hash_value in self.extendedCharTable:
            buffer = self.extendedCharTable[hash_value]
            if buffer:
                length = buffer[0]
                return buffer[1:1+length], length
        
        return None, 0


# Global instance - 对应C++: ExtendedCharTable ExtendedCharTable::instance;
extended_char_table = ExtendedCharTable()


# Create a custom metaclass that combines QObject and ABC metaclasses
class QABCMeta(type(QObject), ABCMeta):
    """Metaclass that combines QObject and ABC metaclasses"""
    pass


class Emulation(QObject, ABC, metaclass=QABCMeta):
    """
    Base class for terminal emulation back-ends.
    
    The back-end is responsible for decoding an incoming character stream and
    producing an output image of characters.
    
    对应C++: class Emulation : public QObject
    """
    
    # Signals - 对应C++版本的所有信号
    sendData = Signal(bytes, int)  # data, length
    lockPtyRequest = Signal(bool)  # suspend
    useUtf8Request = Signal(bool)
    stateSet = Signal(int)  # state
    zmodemDetected = Signal()
    changeTabTextColorRequest = Signal(int)  # color
    programUsesMouseChanged = Signal(bool)  # usesMouse
    programBracketedPasteModeChanged = Signal(bool)  # bracketedPasteMode
    outputChanged = Signal()
    titleChanged = Signal(int, str)  # title, newTitle
    imageSizeChanged = Signal(int, int)  # lineCount, columnCount
    imageSizeInitialized = Signal()
    imageResizeRequest = Signal(QSize)  # size
    profileChangeCommandReceived = Signal(str)  # text
    flowControlKeyPressed = Signal(bool)  # suspendKeyPressed
    cursorChanged = Signal(KeyboardCursorShape, bool)  # cursorShape, blinkingEnabled
    handleCommandFromKeyboard = Signal(object)  # KeyboardTranslator.Command
    outputFromKeypressEvent = Signal()
    
    def __init__(self):
        """
        构造新的终端仿真
        对应C++: Emulation()
        """
        super().__init__()
        
        # 初始化成员变量 - 对应C++版本
        self._currentScreen: Optional[Screen] = None
        self._keyTranslator: Optional[KeyboardTranslator] = None
        self._usesMouse = False
        self._bracketedPasteMode = False
        
        # 创建具有默认大小的屏幕 - 对应C++: create screens with a default size
        self._screen = [Screen(40, 80), Screen(40, 80)]
        self._currentScreen = self._screen[0]
        
        # 窗口列表 - 对应C++: QList<ScreenWindow*> _windows
        self._windows: List[ScreenWindow] = []
        
        # 批量更新定时器 - 对应C++: QTimer _bulkTimer1, _bulkTimer2
        self._bulkTimer1 = QTimer(self)
        self._bulkTimer2 = QTimer(self)
        self._bulkTimer1.timeout.connect(self.showBulk)
        self._bulkTimer2.timeout.connect(self.showBulk)
        
        # 字符串解码器 - 对应C++: QStringDecoder _toUtf16
        self._toUtf16 = 'utf-8'
        
        # 连接信号 - 对应C++版本的connect调用
        self.programUsesMouseChanged.connect(self.usesMouseChanged)
        self.programBracketedPasteModeChanged.connect(self.bracketedPasteModeChanged)
        
        # 连接光标变化信号
        self.cursorChanged.connect(self._onCursorChanged)
    
    def programUsesMouse(self) -> bool:
        """
        返回活动终端程序是否需要鼠标输入事件
        对应C++: bool programUsesMouse() const
        """
        return self._usesMouse
    
    @Slot(bool)
    def usesMouseChanged(self, usesMouse: bool):
        """
        处理鼠标使用状态变化
        对应C++: void usesMouseChanged(bool usesMouse)
        """
        self._usesMouse = usesMouse
    
    def programBracketedPasteMode(self) -> bool:
        """
        返回是否启用了括号粘贴模式
        对应C++: bool programBracketedPasteMode() const
        """
        return self._bracketedPasteMode
    
    @Slot(bool)
    def bracketedPasteModeChanged(self, bracketedPasteMode: bool):
        """
        处理括号粘贴模式变化
        对应C++: void bracketedPasteModeChanged(bool bracketedPasteMode)
        """
        self._bracketedPasteMode = bracketedPasteMode
    
    def createWindow(self) -> ScreenWindow:
        """
        创建一个新窗口到此仿真的输出
        对应C++: ScreenWindow* createWindow()
        """
        window = ScreenWindow()
        window.setScreen(self._currentScreen)
        self._windows.append(window)
        extended_char_table.windows.append(window)
        
        # 连接信号 - 对应C++版本
        window.selectionChanged.connect(self.bufferedUpdate)
        self.outputChanged.connect(window.notifyOutputChanged)
        self.handleCommandFromKeyboard.connect(window.handleCommandFromKeyboard)
        self.outputFromKeypressEvent.connect(window.scrollToEnd)
        
        return window
    
    def __del__(self):
        """
        析构函数
        对应C++: ~Emulation()
        """
        # 从全局扩展字符表中移除窗口
        for window in self._windows:
            if window in extended_char_table.windows:
                extended_char_table.windows.remove(window)
        
        # Python的垃圾回收会自动处理Screen对象的删除
    
    def setScreen(self, n: int):
        """
        设置活动屏幕（0 = 主屏幕，1 = 备用屏幕）
        对应C++: void setScreen(int n)
        """
        old = self._currentScreen
        self._currentScreen = self._screen[n & 1]
        
        if self._currentScreen != old:
            # 告诉所有窗口切换到新激活的屏幕
            for window in self._windows:
                window.setScreen(self._currentScreen)
    
    def clearHistory(self):
        """
        清除历史滚动
        对应C++: void clearHistory()
        """
        self._screen[0].setScroll(self._screen[0].getScroll(), False)
    
    def setHistory(self, t: HistoryType):
        """
        设置此仿真使用的历史存储
        对应C++: void setHistory(const HistoryType& t)
        """
        self._screen[0].setScroll(t)
        self.showBulk()
    
    def history(self) -> HistoryType:
        """
        返回此仿真使用的历史存储
        对应C++: const HistoryType& history() const
        """
        return self._screen[0].getScroll()
    
    def setKeyBindings(self, name: str):
        """
        设置用于将键事件转换为字符流的键绑定
        对应C++: void setKeyBindings(const QString& name)
        """
        manager = KeyboardTranslatorManager.instance()
        self._keyTranslator = manager.findTranslator(name)
        if not self._keyTranslator:
            self._keyTranslator = manager.defaultTranslator()
    
    def keyBindings(self) -> str:
        """
        返回仿真当前键绑定的名称
        对应C++: QString keyBindings() const
        """
        return self._keyTranslator.name() if self._keyTranslator else ""
    
    def receiveChar(self, c: int):
        """
        处理应用程序unicode输入到终端
        对应C++: void receiveChar(wchar_t c)
        """
        c &= 0xff
        
        if c == ord('\b'):  # Backspace
            self._currentScreen.backspace()
        elif c == ord('\t'):  # Tab
            self._currentScreen.tab()
        elif c == ord('\n'):  # Newline
            self._currentScreen.newLine()
        elif c == ord('\r'):  # Carriage return
            self._currentScreen.toStartOfLine()
        elif c == 0x07:  # Bell
            self.stateSet.emit(NOTIFYBELL)
        else:
            self._currentScreen.displayCharacter(chr(c) if c <= 0x10FFFF else ' ')
    
    def sendKeyEvent(self, ev: QKeyEvent, fromPaste: bool = False):
        """
        解释按键事件并发射sendData信号
        对应C++: void sendKeyEvent(QKeyEvent* ev, bool fromPaste)
        """
        self.stateSet.emit(NOTIFYNORMAL)
        
        if not ev.text():
            return
        
        # 将文本转换为字节并发送 - 对应C++版本
        text_bytes = ev.text().encode('utf-8')
        self.sendData.emit(text_bytes, len(text_bytes))
    
    def sendMouseEvent(self, buttons: int, column: int, row: int, eventType: int):
        """
        将鼠标事件信息转换为xterm兼容的转义序列
        对应C++: void sendMouseEvent(int buttons, int column, int row, int eventType)
        """
        # 默认实现不做任何事
        # 子类应该重写此方法
        pass
    
    def receiveData(self, text: bytes, length: int):
        """
        处理传入的字符流
        对应C++: void receiveData(const char* text, int length)
        """
        self.stateSet.emit(NOTIFYACTIVITY)
        self.bufferedUpdate()
        
        try:
            # 解码字节到字符串 - 对应C++的_toUtf16解码过程
            ba = text[:length]
            text_str = ba.decode(self._toUtf16, errors='replace')
            
            # 将字符发送到终端仿真器
            for char in text_str:
                self.receiveChar(ord(char))
            
            # 查找z-modem指示器 - 对应C++版本
            for i in range(length):
                if text[i] == 0x18:  # \030
                    if (length - i - 1 > 3 and 
                        text[i+1:i+4] == b'B00'):
                        self.zmodemDetected.emit()
        except UnicodeDecodeError as e:
            print(f"Unicode decode error: {e}")
    
    def writeToStream(self, decoder: TerminalCharacterDecoder, startLine: int, endLine: int):
        """
        使用解码器将输出历史复制到流
        对应C++: void writeToStream(TerminalCharacterDecoder* decoder, int startLine, int endLine)
        """
        self._currentScreen.writeLinesToStream(decoder, startLine, endLine)
    
    def lineCount(self) -> int:
        """
        返回包括历史在内的总行数
        对应C++: int lineCount() const
        """
        return self._currentScreen.getLines() + self._currentScreen.getHistLines()
    
    @Slot()
    def showBulk(self):
        """
        发射outputChanged信号并重置计时器
        对应C++: void showBulk()
        """
        self._bulkTimer1.stop()
        self._bulkTimer2.stop()
        
        self.outputChanged.emit()
        
        self._currentScreen.resetScrolledLines()
        self._currentScreen.resetDroppedLines()
    
    @Slot()
    def bufferedUpdate(self):
        """
        调度附加视图的更新
        对应C++: void bufferedUpdate()
        """
        BULK_TIMEOUT1 = 10
        BULK_TIMEOUT2 = 40
        
        self._bulkTimer1.setSingleShot(True)
        self._bulkTimer1.start(BULK_TIMEOUT1)
        
        if not self._bulkTimer2.isActive():
            self._bulkTimer2.setSingleShot(True)
            self._bulkTimer2.start(BULK_TIMEOUT2)
    
    def eraseChar(self) -> str:
        """
        返回用于退格的字符
        对应C++: char eraseChar() const
        """
        return '\b'
    
    def setImageSize(self, lines: int, columns: int):
        """
        更改仿真图像的大小
        对应C++: void setImageSize(int lines, int columns)
        """
        if lines < 1 or columns < 1:
            return
        
        screenSize = [
            QSize(self._screen[0].getColumns(), self._screen[0].getLines()),
            QSize(self._screen[1].getColumns(), self._screen[1].getLines())
        ]
        newSize = QSize(columns, lines)
        
        if newSize == screenSize[0] and newSize == screenSize[1]:
            return
        
        self._screen[0].resizeImage(lines, columns)
        self._screen[1].resizeImage(lines, columns)
        
        self.imageSizeChanged.emit(lines, columns)
        self.bufferedUpdate()
    
    def imageSize(self) -> QSize:
        """
        返回屏幕图像的大小
        对应C++: QSize imageSize() const
        """
        return QSize(self._currentScreen.getColumns(), self._currentScreen.getLines())
    
    @Slot(KeyboardCursorShape, bool)
    def _onCursorChanged(self, cursorShape: KeyboardCursorShape, blinkingEnabled: bool):
        """
        处理光标变化事件
        对应C++中的connect lambda
        """
        # 发射带有光标信息的标题变化信号
        titleText = f"CursorShape={cursorShape.value};BlinkingCursorEnabled={blinkingEnabled}"
        self.titleChanged.emit(50, titleText)
    
    # 抽象方法，子类必须实现 - 对应C++的纯虚函数
    @abstractmethod
    def clearEntireScreen(self):
        """
        将当前图像复制到历史并清除屏幕
        对应C++: virtual void clearEntireScreen() =0
        """
        pass
    
    @abstractmethod
    def reset(self):
        """
        重置终端状态
        对应C++: virtual void reset() =0
        """
        pass
    
    @abstractmethod
    def sendText(self, text: str):
        """
        解释字符序列并将结果发送到终端
        对应C++: virtual void sendText(const QString& text) = 0
        """
        pass
    
    @abstractmethod
    def sendString(self, string: str, length: int = -1):
        """
        向前台终端进程发送字符串
        对应C++: virtual void sendString(const char* string, int length = -1) = 0
        """
        pass
    
    @abstractmethod
    def setMode(self, mode: int):
        """
        设置终端模式
        对应C++: virtual void setMode(int mode) = 0
        """
        pass
    
    @abstractmethod
    def resetMode(self, mode: int):
        """
        重置终端模式
        对应C++: virtual void resetMode(int mode) = 0
        """
        pass