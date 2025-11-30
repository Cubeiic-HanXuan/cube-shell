"""
Screen模块 - 从Konsole终端模拟器转换而来

这个模块提供Screen类，用于管理终端屏幕的字符图像、光标位置、滚动和选择等功能。

原始文件：
- Screen.h
- Screen.cpp

版权信息：
Copyright 2007-2008 by Robert Knight <robert.knight@gmail.com>
Copyright 1997,1998 by Lars Doelle <lars.doelle@on-line.de>

转换为Python PySide6版本
"""

import copy
from typing import List, Tuple

from PySide6.QtCore import QRect

from qtermwidget.character import Character, LineProperty, LINE_DEFAULT, LINE_WRAPPED
from qtermwidget.character import (
    DEFAULT_RENDITION, RE_REVERSE, RE_BOLD, RE_CURSOR, RE_EXTENDED_CHAR,
    CharacterColor, COLOR_SPACE_DEFAULT, DEFAULT_FORE_COLOR, DEFAULT_BACK_COLOR
)
from qtermwidget.history import HistoryScroll, HistoryScrollNone, HistoryType
from qtermwidget.terminal_character_decoder import TerminalCharacterDecoder
from qtermwidget.wcwidth import konsole_wcwidth

# 模式常量定义
MODE_Origin = 0
MODE_Wrap = 1
MODE_Insert = 2
MODE_Screen = 3
MODE_Cursor = 4
MODE_NewLine = 5
MODES_SCREEN = 6

# 宏定义转换为函数
def loc(x: int, y: int, columns: int) -> int:
    """将x,y位置转换为图像偏移量"""
    return y * columns + x


class SavedState:
    """保存的光标状态"""
    def __init__(self):
        self.cursorColumn = 0
        self.cursorLine = 0
        self.rendition = DEFAULT_RENDITION
        self.foreground = CharacterColor(COLOR_SPACE_DEFAULT, DEFAULT_FORE_COLOR)
        self.background = CharacterColor(COLOR_SPACE_DEFAULT, DEFAULT_BACK_COLOR)


class Screen:
    """
    Screen类 - 终端屏幕字符图像管理
    
    终端仿真器从程序接收字符流，从中创建字符图像，
    最终由显示部件渲染。某些类型的仿真可能有多个屏幕图像。
    
    对应C++: class Screen
    """
    
    # 默认字符
    default_char = Character(' ',
                           CharacterColor(COLOR_SPACE_DEFAULT, DEFAULT_FORE_COLOR),
                           CharacterColor(COLOR_SPACE_DEFAULT, DEFAULT_BACK_COLOR),
                           DEFAULT_RENDITION)
    
    def __init__(self, lines: int, columns: int):
        """
        构造一个新的屏幕图像，大小为lines x columns。
        
        Args:
            lines: 行数
            columns: 列数
            
        对应C++: Screen::Screen(int l, int c)
        """
        self.lines = lines
        self.columns = columns
        
        # 屏幕图像 - 使用列表的列表存储字符
        self.screenLines: List[List[Character]] = []
        for _ in range(lines + 1):
            self.screenLines.append([])
        
        self._scrolledLines = 0
        self._droppedLines = 0
        self._lastScrolledRegion = QRect()
        
        # 历史缓冲区
        self.history: HistoryScroll = HistoryScrollNone()
        
        # 光标位置
        self.cuX = 0
        self.cuY = 0
        
        # 当前渲染属性
        self.currentRendition = DEFAULT_RENDITION
        self.currentForeground = CharacterColor(COLOR_SPACE_DEFAULT, DEFAULT_FORE_COLOR)
        self.currentBackground = CharacterColor(COLOR_SPACE_DEFAULT, DEFAULT_BACK_COLOR)
        
        # 边距
        self._topMargin = 0
        self._bottomMargin = 0
        
        # 状态数组
        self.currentModes = [False] * MODES_SCREEN
        self.savedModes = [False] * MODES_SCREEN
        
        # 行属性
        self.lineProperties: List[LineProperty] = []
        for _ in range(lines + 1):
            self.lineProperties.append(LINE_DEFAULT)
        
        # 制表符停止点
        self.tabStops: List[bool] = []
        
        # 选择相关
        self.selBegin = -1
        self.selTopLeft = -1
        self.selBottomRight = -1
        self.blockSelectionMode = False
        
        # 有效的颜色和渲染
        self.effectiveForeground = CharacterColor()
        self.effectiveBackground = CharacterColor()
        self.effectiveRendition = DEFAULT_RENDITION
        
        # 保存的状态
        self.savedState = SavedState()
        
        # 最后位置和字符
        self.lastPos = -1
        self.lastDrawnChar = 0
        
        # 初始化
        self.initTabStops()
        self.clearSelection()
        self.reset()
    
    def __del__(self):
        """析构函数"""
        # Python中由垃圾回收自动处理
        pass
    
    # 光标移动方法
    
    def cursorUp(self, n: int = 1):
        """
        向上移动光标n行。光标会在顶部边距处停止。
        
        Args:
            n: 移动行数，默认为1
            
        对应C++: void Screen::cursorUp(int n)
        """
        if n == 0:
            n = 1
        stop = 0 if self.cuY < self._topMargin else self._topMargin
        self.cuX = min(self.columns - 1, self.cuX)  # nowrap!
        self.cuY = max(stop, self.cuY - n)
    
    def cursorDown(self, n: int = 1):
        """
        向下移动光标n行。光标会在底部边距处停止。
        
        Args:
            n: 移动行数，默认为1
            
        对应C++: void Screen::cursorDown(int n)
        """
        if n == 0:
            n = 1
        stop = self.lines - 1 if self.cuY > self._bottomMargin else self._bottomMargin
        self.cuX = min(self.columns - 1, self.cuX)  # nowrap!
        self.cuY = min(stop, self.cuY + n)
    
    def cursorLeft(self, n: int = 1):
        """
        向左移动光标n列。光标会在第一列停止。
        
        Args:
            n: 移动列数，默认为1
            
        对应C++: void Screen::cursorLeft(int n)
        """
        if n == 0:
            n = 1
        self.cuX = min(self.columns - 1, self.cuX)  # nowrap!
        self.cuX = max(0, self.cuX - n)
    
    def cursorRight(self, n: int = 1):
        """
        向右移动光标n列。
        
        Args:
            n: 移动列数，默认为1
            
        对应C++: void Screen::cursorRight(int n)
        """
        if n == 0:
            n = 1
        self.cuX = min(self.columns - 1, self.cuX + n)
    
    def cursorNextLine(self, n: int = 1):
        """
        向下移动光标n行到行首。
        
        Args:
            n: 移动行数，默认为1
            
        对应C++: void Screen::cursorNextLine(int n)
        """
        if n == 0:
            n = 1
        self.cuX = 0
        while n > 0:
            if self.cuY < self.lines - 1:
                self.cuY += 1
            n -= 1
    
    def cursorPreviousLine(self, n: int = 1):
        """
        向上移动光标n行到行首。
        
        Args:
            n: 移动行数，默认为1
            
        对应C++: void Screen::cursorPreviousLine(int n)
        """
        if n == 0:
            n = 1
        self.cuX = 0
        while n > 0:
            if self.cuY > 0:
                self.cuY -= 1
            n -= 1
    
    def setCursorX(self, x: int):
        """
        设置光标列位置。
        
        Args:
            x: 列位置（1-based）
            
        对应C++: void Screen::setCursorX(int x)
        """
        if x == 0:
            x = 1  # Default
        x -= 1  # Adjust to 0-based
        self.cuX = max(0, min(self.columns - 1, x))
    
    def setCursorY(self, y: int):
        """
        设置光标行位置。
        
        Args:
            y: 行位置（1-based）
            
        对应C++: void Screen::setCursorY(int y)
        """
        if y == 0:
            y = 1  # Default
        y -= 1  # Adjust to 0-based
        origin_offset = self._topMargin if self.getMode(MODE_Origin) else 0
        self.cuY = max(0, min(self.lines - 1, y + origin_offset))
    
    def setCursorYX(self, y: int, x: int):
        """
        设置光标位置。
        
        Args:
            y: 行位置（1-based）
            x: 列位置（1-based）
            
        对应C++: void Screen::setCursorYX(int y, int x)
        """
        self.setCursorY(y)
        self.setCursorX(x)
    
    def getCursorX(self) -> int:
        """获取光标列位置（0-based）"""
        return self.cuX
    
    def getCursorY(self) -> int:
        """获取光标行位置（0-based）"""
        return self.cuY
    
    def home(self):
        """
        移动光标到起始位置。
        
        对应C++: void Screen::home()
        """
        self.cuX = 0
        self.cuY = 0
    
    def toStartOfLine(self):
        """
        移动光标到当前行的开始。
        
        对应C++: void Screen::toStartOfLine()
        """
        self.cuX = 0
    
    # 边距管理
    
    def setMargins(self, topLine: int, bottomLine: int):
        """
        设置滚动边距。
        
        Args:
            topLine: 顶部行（1-based）
            bottomLine: 底部行（1-based）
            
        对应C++: void Screen::setMargins(int top, int bot)
        """
        if topLine == 0:
            topLine = 1  # Default
        if bottomLine == 0:
            bottomLine = self.lines  # Default
        
        top = topLine - 1  # Adjust to 0-based
        bot = bottomLine - 1  # Adjust to 0-based
        
        if not (0 <= top < bot < self.lines):
            return  # Invalid range, ignore
        
        self._topMargin = top
        self._bottomMargin = bot
        self.cuX = 0
        self.cuY = top if self.getMode(MODE_Origin) else 0
    
    def topMargin(self) -> int:
        """获取顶部边距"""
        return self._topMargin
    
    def bottomMargin(self) -> int:
        """获取底部边距"""
        return self._bottomMargin
    
    def setDefaultMargins(self):
        """重置边距到屏幕顶部和底部"""
        self._topMargin = 0
        self._bottomMargin = self.lines - 1
    
    # 模式管理
    
    def setMode(self, mode: int):
        """
        设置（启用）指定的屏幕模式。
        
        Args:
            mode: 模式ID
            
        对应C++: void Screen::setMode(int m)
        """
        self.currentModes[mode] = True
        if mode == MODE_Origin:
            self.cuX = 0
            self.cuY = self._topMargin
    
    def resetMode(self, mode: int):
        """
        重置（禁用）指定的屏幕模式。
        
        Args:
            mode: 模式ID
            
        对应C++: void Screen::resetMode(int m)
        """
        self.currentModes[mode] = False
        if mode == MODE_Origin:
            self.cuX = 0
            self.cuY = 0
    
    def saveMode(self, mode: int):
        """
        保存指定模式的状态。
        
        Args:
            mode: 模式ID
            
        对应C++: void Screen::saveMode(int m)
        """
        self.savedModes[mode] = self.currentModes[mode]
    
    def restoreMode(self, mode: int):
        """
        恢复指定模式的状态。
        
        Args:
            mode: 模式ID
            
        对应C++: void Screen::restoreMode(int m)
        """
        self.currentModes[mode] = self.savedModes[mode]
    
    def getMode(self, mode: int) -> bool:
        """
        返回指定模式是否启用。
        
        Args:
            mode: 模式ID
            
        Returns:
            bool: 模式是否启用
            
        对应C++: bool Screen::getMode(int m) const
        """
        return self.currentModes[mode]
    
    # 状态保存和恢复
    
    def saveCursor(self):
        """
        保存当前光标位置和外观。
        
        对应C++: void Screen::saveCursor()
        """
        self.savedState.cursorColumn = self.cuX
        self.savedState.cursorLine = self.cuY
        self.savedState.rendition = self.currentRendition
        self.savedState.foreground = self.currentForeground
        self.savedState.background = self.currentBackground
    
    def restoreCursor(self):
        """
        恢复光标位置和外观。
        
        对应C++: void Screen::restoreCursor()
        """
        self.cuX = min(self.savedState.cursorColumn, self.columns - 1)
        self.cuY = min(self.savedState.cursorLine, self.lines - 1)
        self.currentRendition = self.savedState.rendition
        self.currentForeground = self.savedState.foreground
        self.currentBackground = self.savedState.background
        self.updateEffectiveRendition()
    
    # 制表符管理
    
    def initTabStops(self):
        """
        初始化制表符停止点。
        
        对应C++: void Screen::initTabStops()
        """
        self.tabStops = [False] * self.columns
        # 每8列设置一个制表符（除了第0列）
        for i in range(self.columns):
            self.tabStops[i] = (i % 8 == 0 and i != 0)
    
    def clearTabStops(self):
        """清除所有制表符停止点"""
        self.tabStops = [False] * self.columns
    
    def changeTabStop(self, setStop: bool):
        """
        在当前光标位置设置或清除制表符停止点。
        
        Args:
            setStop: True为设置，False为清除
            
        对应C++: void Screen::changeTabStop(bool set)
        """
        if self.cuX >= self.columns:
            return
        self.tabStops[self.cuX] = setStop
    
    def tab(self, n: int = 1):
        """
        移动光标到下一个制表符停止点。
        
        Args:
            n: 制表符数量
            
        对应C++: void Screen::tab(int n)
        """
        if n == 0:
            n = 1
        while n > 0 and self.cuX < self.columns - 1:
            self.cursorRight(1)
            while self.cuX < self.columns - 1 and not self.tabStops[self.cuX]:
                self.cursorRight(1)
            n -= 1
    
    def backtab(self, n: int = 1):
        """
        移动光标到上一个制表符停止点。
        
        Args:
            n: 制表符数量
            
        对应C++: void Screen::backtab(int n)
        """
        if n == 0:
            n = 1
        while n > 0 and self.cuX > 0:
            self.cursorLeft(1)
            while self.cuX > 0 and not self.tabStops[self.cuX]:
                self.cursorLeft(1)
            n -= 1
    
    # 基本属性
    
    def getLines(self) -> int:
        """返回行数"""
        return self.lines
    
    def getColumns(self) -> int:
        """返回列数"""
        return self.columns
    
    def getHistLines(self) -> int:
        """返回历史缓冲区行数"""
        return self.history.getLines()
    
    # 历史记录管理
    
    def setScroll(self, historyType: HistoryType, copyPreviousScroll: bool = True):
        """
        设置用于保存历史行的存储类型。
        
        Args:
            historyType: 历史类型
            copyPreviousScroll: 是否复制之前的滚动内容
            
        对应C++: void Screen::setScroll(const HistoryType& t, bool copyPreviousScroll)
        """
        self.clearSelection()
        
        if copyPreviousScroll:
            self.history = historyType.scroll(self.history)
        else:
            oldScroll = self.history
            self.history = historyType.scroll(None)
            del oldScroll
    
    def getScroll(self) -> HistoryType:
        """返回历史存储类型"""
        return self.history.getType()
    
    def hasScroll(self) -> bool:
        """返回是否保持滚动历史"""
        return self.history.hasScroll()
    
    # 选择管理
    
    def clearSelection(self):
        """清除当前选择"""
        self.selBottomRight = -1
        self.selTopLeft = -1
        self.selBegin = -1
    
    def setSelectionStart(self, column: int, line: int, blockMode: bool):
        """
        设置选择的开始位置。
        
        Args:
            column: 列索引
            line: 行索引
            blockMode: 是否为块选择模式
            
        对应C++: void Screen::setSelectionStart(const int x, const int y, const bool mode)
        """
        self.selBegin = loc(column, line, self.columns)
        # 修正超出右边界的情况
        if column == self.columns:
            self.selBegin -= 1
        
        self.selBottomRight = self.selBegin
        self.selTopLeft = self.selBegin
        self.blockSelectionMode = blockMode
    
    def setSelectionEnd(self, column: int, line: int):
        """
        设置选择的结束位置。
        
        Args:
            column: 列索引
            line: 行索引
            
        对应C++: void Screen::setSelectionEnd(const int x, const int y)
        """
        if self.selBegin == -1:
            return
        
        endPos = loc(column, line, self.columns)
        
        if endPos < self.selBegin:
            self.selTopLeft = endPos
            self.selBottomRight = self.selBegin
        else:
            # 修正超出右边界的情况
            if column == self.columns:
                endPos -= 1
            
            self.selTopLeft = self.selBegin
            self.selBottomRight = endPos
        
        # 规范化列模式选择
        if self.blockSelectionMode:
            topRow = self.selTopLeft // self.columns
            topColumn = self.selTopLeft % self.columns
            bottomRow = self.selBottomRight // self.columns
            bottomColumn = self.selBottomRight % self.columns
            
            self.selTopLeft = loc(min(topColumn, bottomColumn), topRow, self.columns)
            self.selBottomRight = loc(max(topColumn, bottomColumn), bottomRow, self.columns)
    
    def isSelected(self, column: int, line: int) -> bool:
        """
        返回指定位置是否被选中。
        
        Args:
            column: 列索引
            line: 行索引
            
        Returns:
            bool: 是否被选中
            
        对应C++: bool Screen::isSelected(const int x, const int y) const
        """
        columnInSelection = True
        if self.blockSelectionMode:
            columnInSelection = (column >= (self.selTopLeft % self.columns) and
                               column <= (self.selBottomRight % self.columns))
        
        pos = loc(column, line, self.columns)
        return (pos >= self.selTopLeft and pos <= self.selBottomRight and 
                columnInSelection)
    
    def isSelectionValid(self) -> bool:
        """返回选择是否有效"""
        return self.selTopLeft >= 0 and self.selBottomRight >= 0
    
    # 渲染和颜色管理
    
    def updateEffectiveRendition(self):
        """
        更新有效渲染属性。
        
        对应C++: void Screen::updateEffectiveRendition()
        """
        self.effectiveRendition = self.currentRendition
        if self.currentRendition & RE_REVERSE:
            self.effectiveForeground = self.currentBackground
            self.effectiveBackground = self.currentForeground
        else:
            self.effectiveForeground = self.currentForeground
            self.effectiveBackground = self.currentBackground
        
        if self.currentRendition & RE_BOLD:
            self.effectiveForeground.setIntensive()
    
    def setForegroundColor(self, space: int, color: int):
        """设置前景色"""
        self.currentForeground = CharacterColor(space, color)
        if self.currentForeground.isValid():
            self.updateEffectiveRendition()
        else:
            self.setForegroundColor(COLOR_SPACE_DEFAULT, DEFAULT_FORE_COLOR)
    
    def setBackgroundColor(self, space: int, color: int):
        """设置背景色"""
        self.currentBackground = CharacterColor(space, color)
        if self.currentBackground.isValid():
            self.updateEffectiveRendition()
        else:
            self.setBackgroundColor(COLOR_SPACE_DEFAULT, DEFAULT_BACK_COLOR)
    
    def setRendition(self, rendition: int):
        """启用给定的渲染标志"""
        self.currentRendition |= rendition
        self.updateEffectiveRendition()
    
    def resetRendition(self, rendition: int):
        """禁用给定的渲染标志"""
        self.currentRendition &= ~rendition
        self.updateEffectiveRendition()
    
    def setDefaultRendition(self):
        """重置渲染到默认设置"""
        self.setForegroundColor(COLOR_SPACE_DEFAULT, DEFAULT_FORE_COLOR)
        self.setBackgroundColor(COLOR_SPACE_DEFAULT, DEFAULT_BACK_COLOR)
        self.currentRendition = DEFAULT_RENDITION
        self.updateEffectiveRendition()
    
    # 基本清除和重置操作
    
    def clear(self):
        """清除整个屏幕并移动光标到home位置"""
        self.clearEntireScreen()
        self.home()
    
    def reset(self, clearScreen: bool = True):
        """
        重置屏幕状态。
        
        Args:
            clearScreen: 是否清除屏幕内容
            
        对应C++: void Screen::reset(bool clearScreen)
        """
        self.setMode(MODE_Wrap)
        self.saveMode(MODE_Wrap)  # 启用行末换行
        self.resetMode(MODE_Origin)
        self.saveMode(MODE_Origin)  # 位置参考[1,1]
        self.resetMode(MODE_Insert)
        self.saveMode(MODE_Insert)  # 覆盖模式
        self.setMode(MODE_Cursor)  # 光标可见
        self.resetMode(MODE_Screen)  # 屏幕非反转
        self.resetMode(MODE_NewLine)
        
        self._topMargin = 0
        self._bottomMargin = self.lines - 1
        
        self.setDefaultRendition()
        self.saveCursor()
        
        if clearScreen:
            self.clear()
    
    def clearEntireScreen(self):
        """
        清除整个屏幕，将当前屏幕内容移动到历史缓冲区。
        
        对应C++: void Screen::clearEntireScreen()
        
        优化版本：减少不必要的操作，提高clear命令性能。
        """
        # 快速检查：如果屏幕已经是空的，直接返回
        if self._isScreenEmpty():
            self.home()  # 只需要移动光标到主位置
            return
        
        # 批量添加到历史，减少逐行操作的开销
        if self.hasScroll():
            for i in range(self.lines - 1):
                if i < len(self.screenLines) and len(self.screenLines[i]) > 0:
                    self.history.addCellsVector(self.screenLines[i])
                    self.history.addLine(bool(self.lineProperties[i] & LINE_WRAPPED))
                else:
                    # 空行也要添加到历史
                    self.history.addCellsVector([])
                    self.history.addLine(False)
        
        # 直接清空屏幕，而不是使用scrollUp（避免复杂的移动操作）
        self._fastClearScreen()
        
        # 移动光标到主位置
        self.home()
    
    def _isScreenEmpty(self) -> bool:
        """检查屏幕是否为空"""
        for line in self.screenLines:
            if line and any(char.character != ' ' for char in line):
                return False
        return True
    
    def _fastClearScreen(self):
        """快速清空屏幕，避免复杂的图像操作"""
        # 清除选择
        self.clearSelection()
        
        # 直接重新初始化屏幕行
        for i in range(len(self.screenLines)):
            self.screenLines[i] = []
            if i < len(self.lineProperties):
                self.lineProperties[i] = LINE_DEFAULT
        
        # 重置光标
        self.cuX = 0
        self.cuY = 0
    
    def clearToEndOfScreen(self):
        """清除从当前光标位置到屏幕末尾的区域"""
        self.clearImage(loc(self.cuX, self.cuY, self.columns),
                        loc(self.columns - 1, self.lines - 1, self.columns), ' ')
    
    def clearToBeginOfScreen(self):
        """清除从屏幕开始到当前光标位置的区域"""
        self.clearImage(loc(0, 0, self.columns),
                        loc(self.cuX, self.cuY, self.columns), ' ')
    
    def clearEntireLine(self):
        """清除光标所在的整行"""
        self.clearImage(loc(0, self.cuY, self.columns),
                        loc(self.columns - 1, self.cuY, self.columns), ' ')
    
    def clearToEndOfLine(self):
        """清除从当前光标位置到行末"""
        self.clearImage(loc(self.cuX, self.cuY, self.columns),
                        loc(self.columns - 1, self.cuY, self.columns), ' ')
    
    def clearToBeginOfLine(self):
        """清除从行首到当前光标位置"""
        self.clearImage(loc(0, self.cuY, self.columns),
                        loc(self.cuX, self.cuY, self.columns), ' ')
    
    def helpAlign(self):
        """用字母'E'填充整个屏幕以帮助屏幕对齐"""
        self.clearImage(loc(0, 0, self.columns),
                        loc(self.columns - 1, self.lines - 1, self.columns), 'E')
    
    def backspace(self):
        """
        向左移动光标一列并删除该位置的字符。
        
        对应C++: void Screen::backspace()
        """
        self.cuX = min(self.columns - 1, self.cuX)  # nowrap!
        self.cuX = max(0, self.cuX - 1)
        
        if len(self.screenLines[self.cuY]) < self.cuX + 1:
            self.screenLines[self.cuY].extend([Screen.default_char] * 
                                              (self.cuX + 1 - len(self.screenLines[self.cuY])))
    
    # 内部辅助方法
    
    def clearImage(self, loca: int, loce: int, c: str):
        """
        用字符'c'填充屏幕图像的指定区域。
        
        Args:
            loca: 起始位置偏移量
            loce: 结束位置偏移量
            c: 填充字符
            
        对应C++: void Screen::clearImage(int loca, int loce, char c)
        """
        scr_tl = loc(0, self.history.getLines(), self.columns)
        
        # 如果选择区域与清除区域重叠，则清除选择
        if ((self.selBottomRight > (loca + scr_tl)) and 
            (self.selTopLeft < (loce + scr_tl))):
            self.clearSelection()
        
        top_line = loca // self.columns
        bottom_line = loce // self.columns
        
        clear_ch = Character(c, self.currentForeground, 
                           self.currentBackground, DEFAULT_RENDITION)
        
        # 检查是否为默认字符，如果是则可以简化操作
        is_default_ch = (clear_ch == Character())
        
        for y in range(top_line, bottom_line + 1):
            self.lineProperties[y] = LINE_DEFAULT
            
            end_col = (loce % self.columns) if y == bottom_line else self.columns - 1
            start_col = (loca % self.columns) if y == top_line else 0
            
            line = self.screenLines[y]
            
            if is_default_ch and end_col == self.columns - 1:
                # 可以简化：调整列表大小
                if start_col == 0:
                    line.clear()
                else:
                    line = line[:start_col]
                    self.screenLines[y] = line
            else:
                # 确保行足够长
                if len(line) < end_col + 1:
                    line.extend([Screen.default_char] * (end_col + 1 - len(line)))
                
                # 填充字符
                for i in range(start_col, end_col + 1):
                    line[i] = clear_ch
                self.screenLines[y] = line
    
    def addHistLine(self):
        """
        添加行到历史缓冲区。
        
        对应C++: void Screen::addHistLine()
        """
        if self.hasScroll():
            old_hist_lines = self.history.getLines()
            
            self.history.addCellsVector(self.screenLines[0])
            self.history.addLine(bool(self.lineProperties[0] & LINE_WRAPPED))
            
            new_hist_lines = self.history.getLines()
            
            begin_is_tl = (self.selBegin == self.selTopLeft)
            
            # 如果历史已满，增加丢弃行计数
            if new_hist_lines == old_hist_lines:
                self._droppedLines += 1
            
            # 调整选择以适应新的参考点
            if new_hist_lines > old_hist_lines:
                if self.selBegin != -1:
                    self.selTopLeft += self.columns
                    self.selBottomRight += self.columns
            
            if self.selBegin != -1:
                # 在历史中向上滚动选择
                top_br = loc(0, 1 + new_hist_lines, self.columns)
                
                if self.selTopLeft < top_br:
                    self.selTopLeft -= self.columns
                
                if self.selBottomRight < top_br:
                    self.selBottomRight -= self.columns
                
                if self.selBottomRight < 0:
                    self.clearSelection()
                else:
                    if self.selTopLeft < 0:
                        self.selTopLeft = 0
                
                if begin_is_tl:
                    self.selBegin = self.selTopLeft
                else:
                    self.selBegin = self.selBottomRight
    
    def scrollUp(self, fromLine: int, n: int):
        """
        向上滚动指定区域。
        
        Args:
            fromLine: 起始行
            n: 滚动行数
            
        对应C++: void Screen::scrollUp(int from, int n)
        """
        if n <= 0:
            return
        if fromLine > self._bottomMargin:
            return
        if fromLine + n > self._bottomMargin:
            n = self._bottomMargin + 1 - fromLine
        
        self._scrolledLines -= n
        self._lastScrolledRegion = QRect(0, self._topMargin, 
                                         self.columns - 1, 
                                         self._bottomMargin - self._topMargin)
        
        self.moveImage(loc(0, fromLine, self.columns),
                       loc(0, fromLine + n, self.columns),
                       loc(self.columns, self._bottomMargin, self.columns))
        self.clearImage(loc(0, self._bottomMargin - n + 1, self.columns),
                        loc(self.columns - 1, self._bottomMargin, self.columns), ' ')
    
    def moveImage(self, dest: int, sourceBegin: int, sourceEnd: int):
        """
        移动屏幕图像区域。
        
        Args:
            dest: 目标位置
            sourceBegin: 源起始位置
            sourceEnd: 源结束位置
            
        对应C++: void Screen::moveImage(int dest, int sourceBegin, int sourceEnd)
        """
        assert sourceBegin <= sourceEnd
        
        lines_count = (sourceEnd - sourceBegin) // self.columns
        
        # 根据移动方向选择复制顺序
        if dest < sourceBegin:
            # 向前移动
            for i in range(lines_count + 1):
                src_line = (sourceBegin // self.columns) + i
                dest_line = (dest // self.columns) + i
                if (src_line < len(self.screenLines) and 
                    dest_line < len(self.screenLines)):
                    self.screenLines[dest_line] = self.screenLines[src_line][:]
                    self.lineProperties[dest_line] = self.lineProperties[src_line]
        else:
            # 向后移动
            for i in range(lines_count, -1, -1):
                src_line = (sourceBegin // self.columns) + i
                dest_line = (dest // self.columns) + i
                if (src_line < len(self.screenLines) and 
                    dest_line < len(self.screenLines)):
                    self.screenLines[dest_line] = self.screenLines[src_line][:]
                    self.lineProperties[dest_line] = self.lineProperties[src_line]
        
        # 调整最后位置
        if self.lastPos != -1:
            diff = dest - sourceBegin
            self.lastPos += diff
            if self.lastPos < 0 or self.lastPos >= (self.lines * self.columns):
                self.lastPos = -1
        
        # 调整选择
        if self.selBegin != -1:
            begin_is_tl = (self.selBegin == self.selTopLeft)
            diff = dest - sourceBegin
            scr_tl = loc(0, self.history.getLines(), self.columns)
            srca = sourceBegin + scr_tl
            srce = sourceEnd + scr_tl
            desta = srca + diff
            deste = srce + diff
            
            if srca <= self.selTopLeft <= srce:
                self.selTopLeft += diff
            elif desta <= self.selTopLeft <= deste:
                self.selBottomRight = -1  # 清除选择
            
            if srca <= self.selBottomRight <= srce:
                self.selBottomRight += diff
            elif desta <= self.selBottomRight <= deste:
                self.selBottomRight = -1  # 清除选择
            
            if self.selBottomRight < 0:
                self.clearSelection()
            else:
                if self.selTopLeft < 0:
                    self.selTopLeft = 0
            
            if begin_is_tl:
                self.selBegin = self.selTopLeft
            else:
                self.selBegin = self.selBottomRight
    
    # 滚动相关方法
    
    def scrolledLines(self) -> int:
        """返回自上次重置以来滚动的行数"""
        return self._scrolledLines
    
    def droppedLines(self) -> int:
        """返回从历史中丢弃的行数"""
        return self._droppedLines
    
    def resetScrolledLines(self):
        """重置滚动行计数"""
        self._scrolledLines = 0
    
    def resetDroppedLines(self):
        """重置丢弃行计数"""
        self._droppedLines = 0
    
    def lastScrolledRegion(self) -> QRect:
        """返回最后滚动的区域"""
        return self._lastScrolledRegion
    
    @staticmethod
    def fillWithDefaultChar(dest: List[Character], count: int):
        """
        用默认字符填充缓冲区。
        
        Args:
            dest: 目标缓冲区
            count: 填充数量
            
        对应C++: static void Screen::fillWithDefaultChar(Character* dest, int count)
        """
        for i in range(count):
            # 修复：创建新的Character对象，避免引用共享问题
            new_char = Character(' ')
            if i < len(dest):
                dest[i] = new_char
            else:
                dest.append(new_char)
    
    # 字符显示
    
    def displayCharacter(self, c: str):
        """
        在当前光标位置显示一个新字符。
        
        Args:
            c: 要显示的字符（或Unicode码点）
            
        对应C++: void Screen::displayCharacter(wchar_t c)
        """
        if isinstance(c, str):
            if len(c) == 0:
                return
            if len(c) > 1:
                c = c[0]  # 只取第一个字符
            char_code = ord(c)
        else:
            char_code = int(c)
            c = chr(char_code) if char_code <= 0x10FFFF else ' '
        
        # 计算字符宽度
        w = konsole_wcwidth(char_code)
        if w < 0:
            return  # 不可打印字符
        
        # 处理零宽度字符（组合字符）
        if w == 0:
            # 简化处理：忽略组合字符
            return
        
        # 处理换行
        if self.cuX + w > self.columns:
            if self.getMode(MODE_Wrap):
                self.lineProperties[self.cuY] |= LINE_WRAPPED
                self.nextLine()
            else:
                self.cuX = self.columns - w
        
        # 确保当前行足够长 - 修复：创建新的Character对象，避免引用共享
        while len(self.screenLines[self.cuY]) < self.cuX + w:
            self.screenLines[self.cuY].append(Character(' '))
        
        # 插入模式处理
        if self.getMode(MODE_Insert):
            self.insertChars(w)
        
        self.lastPos = loc(self.cuX, self.cuY, self.columns)
        
        # 检查选择是否仍然有效
        self.checkSelection(self.lastPos, self.lastPos)
        
        # 创建字符对象
        current_char = Character(c, self.effectiveForeground,
                               self.effectiveBackground, self.effectiveRendition)
        
        # 设置主字符
        self.screenLines[self.cuY][self.cuX] = current_char
        self.lastDrawnChar = char_code
        
        # 处理宽字符的第二部分
        if w == 2:
            # 确保有足够空间 - 修复：创建新的Character对象，避免引用共享
            if len(self.screenLines[self.cuY]) < self.cuX + 2:
                self.screenLines[self.cuY].append(Character(' '))
            
            # 第二部分字符（宽字符的右半部分）
            second_char = Character(chr(0), self.effectiveForeground,
                                  self.effectiveBackground, self.effectiveRendition)
            self.screenLines[self.cuY][self.cuX + 1] = second_char
        
        self.cuX += w
    
    # 编辑操作
    
    def eraseChars(self, n: int):
        """
        从当前光标位置开始删除n个字符。
        
        Args:
            n: 要删除的字符数，0表示删除1个字符
            
        对应C++: void Screen::eraseChars(int n)
        """
        if n == 0:
            n = 1
        p = max(0, min(self.cuX + n - 1, self.columns - 1))
        self.clearImage(loc(self.cuX, self.cuY, self.columns),
                        loc(p, self.cuY, self.columns), ' ')
    
    def deleteChars(self, n: int):
        """
        从当前光标位置开始删除n个字符。
        
        Args:
            n: 要删除的字符数，0表示删除1个字符
            
        对应C++: void Screen::deleteChars(int n)
        """
        if n == 0:
            n = 1
        
        # 如果光标超出行末，无需操作
        if self.cuX >= len(self.screenLines[self.cuY]):
            return
        
        line = self.screenLines[self.cuY]
        if self.cuX + n > len(line):
            n = len(line) - self.cuX
        
        if n > 0:
            # 删除字符
            del line[self.cuX:self.cuX + n]
            self.screenLines[self.cuY] = line
    
    def insertChars(self, n: int):
        """
        从当前光标位置插入n个空白字符。
        
        Args:
            n: 要插入的字符数，0表示插入1个字符
            
        对应C++: void Screen::insertChars(int n)
        """
        if n == 0:
            n = 1
        
        line = self.screenLines[self.cuY]
        
        # 确保行足够长
        while len(line) < self.cuX:
            line.append(Screen.default_char)
        
        # 插入空白字符
        for _ in range(n):
            line.insert(self.cuX, Character(' '))
        
        # 限制行长度
        if len(line) > self.columns:
            line = line[:self.columns]
        
        self.screenLines[self.cuY] = line
    
    def repeatChars(self, count: int):
        """
        重复上一个绘制的字符count次。
        
        Args:
            count: 重复次数，0表示重复1次
            
        对应C++: void Screen::repeatChars(int count)
        """
        if count == 0:
            count = 1
        
        # 重复最后绘制的字符
        for _ in range(count):
            if self.lastDrawnChar > 0:
                self.displayCharacter(chr(self.lastDrawnChar))
    
    def deleteLines(self, n: int):
        """
        从当前光标位置开始删除n行。
        
        Args:
            n: 要删除的行数，0表示删除1行
            
        对应C++: void Screen::deleteLines(int n)
        """
        if n == 0:
            n = 1
        self.scrollUp(self.cuY, n)
    
    def insertLines(self, n: int):
        """
        从当前光标位置插入n行。
        
        Args:
            n: 要插入的行数，0表示插入1行
            
        对应C++: void Screen::insertLines(int n)
        """
        if n == 0:
            n = 1
        self.scrollDown(self.cuY, n)
    
    # 滚动操作
    
    def index(self):
        """
        将光标向下移动一行。如果在滚动区域底部则向上滚动。
        
        对应C++: void Screen::index()
        """
        if self.cuY == self._bottomMargin:
            self.scrollUpRegion(1)
        elif self.cuY < self.lines - 1:
            self.cuY += 1
    
    def reverseIndex(self):
        """
        将光标向上移动一行。如果在滚动区域顶部则向下滚动。
        
        对应C++: void Screen::reverseIndex()
        """
        if self.cuY == self._topMargin:
            self.scrollDown(self._topMargin, 1)
        elif self.cuY > 0:
            self.cuY -= 1
    
    def nextLine(self):
        """
        移动光标到下一行的开始位置。
        
        对应C++: void Screen::nextLine()
        """
        self.toStartOfLine()
        self.index()
    
    def newLine(self):
        """
        移动光标下一行，如果启用了MODE_NewLine则移动到行首。
        
        对应C++: void Screen::newLine()
        """
        if self.getMode(MODE_NewLine):
            self.toStartOfLine()
        self.index()
    
    def scrollUpRegion(self, n: int = 1):
        """
        向上滚动屏幕的滚动区域n行。
        
        Args:
            n: 滚动行数，0表示滚动1行
            
        对应C++: void Screen::scrollUp(int n)
        """
        if n == 0:
            n = 1
        if self._topMargin == 0:
            self.addHistLine()  # 添加到历史
        self.scrollUp(self._topMargin, n)
    
    def scrollDownRegion(self, n: int = 1):
        """
        向下滚动屏幕的滚动区域n行。
        
        Args:
            n: 滚动行数，0表示滚动1行
            
        对应C++: void Screen::scrollDown(int n)
        """
        if n == 0:
            n = 1
        self.scrollDown(self._topMargin, n)
    
    def scrollDown(self, fromLine: int, n: int):
        """
        向下滚动指定区域。
        
        Args:
            fromLine: 起始行
            n: 滚动行数
            
        对应C++: void Screen::scrollDown(int from, int n)
        """
        self._scrolledLines += n
        
        if n <= 0:
            return
        if fromLine > self._bottomMargin:
            return
        if fromLine + n > self._bottomMargin:
            n = self._bottomMargin - fromLine
        
        self.moveImage(loc(0, fromLine + n, self.columns),
                       loc(0, fromLine, self.columns),
                       loc(self.columns - 1, self._bottomMargin - n, self.columns))
        self.clearImage(loc(0, fromLine, self.columns),
                        loc(self.columns - 1, fromLine + n - 1, self.columns), ' ')
    
    # 图像获取和复制
    
    def getImage(self, dest: List[Character], size: int, startLine: int, endLine: int):
        """
        返回当前屏幕图像。
        
        Args:
            dest: 目标字符缓冲区
            size: 缓冲区大小
            startLine: 起始行索引
            endLine: 结束行索引
            
        对应C++: void Screen::getImage(Character* dest, int size, int startLine, int endLine) const
        """
        assert startLine >= 0
        assert endLine >= startLine and endLine < self.history.getLines() + self.lines
        
        merged_lines = endLine - startLine + 1
        assert size >= merged_lines * self.columns
        
        lines_in_history_buffer = max(0, min(self.history.getLines() - startLine, merged_lines))
        lines_in_screen_buffer = merged_lines - lines_in_history_buffer
        
        # 从历史缓冲区复制行
        force_copy = self.getMode(MODE_Screen)
        if lines_in_history_buffer > 0:
            self.copyFromHistory(dest, startLine, lines_in_history_buffer, force_copy)
        
        # 从屏幕缓冲区复制行
        if lines_in_screen_buffer > 0:
            screen_start = startLine + lines_in_history_buffer - self.history.getLines()
            dest_offset = lines_in_history_buffer * self.columns
            # 修复：传递offset参数而不是切片，避免Python切片引用问题
            self.copyFromScreenWithOffset(dest, dest_offset, screen_start, lines_in_screen_buffer, force_copy)
        
        # 反转显示模式
        if force_copy:
            for i in range(merged_lines * self.columns):
                if i < len(dest):
                    self.reverseRendition(dest[i])
        
        # 标记当前光标位置 - 修复：创建新的Character对象，避免引用共享问题
        cursor_index = loc(self.cuX, self.cuY + lines_in_history_buffer, self.columns)
        if self.getMode(MODE_Cursor) and cursor_index < self.columns * merged_lines:
            if cursor_index < len(dest):
                # 创建新的Character对象，复制原有属性，然后添加光标标志
                original_char = dest[cursor_index]
                new_char = Character(
                    chr(original_char.character) if original_char.character else ' ',
                    original_char.foregroundColor,
                    original_char.backgroundColor,
                    original_char.rendition | RE_CURSOR  # 添加光标标志
                )
                dest[cursor_index] = new_char
    
    def copyFromHistory(self, dest: List[Character], startLine: int, count: int, force_copy: bool = False):
        """
        从历史缓冲区复制字符。
        
        Args:
            dest: 目标缓冲区
            startLine: 起始行
            count: 行数
            force_copy: 是否强制深拷贝所有字符
            
        对应C++: void Screen::copyFromHistory(Character* dest, int startLine, int count) const
        """
        assert startLine >= 0 and count > 0 and startLine + count <= self.history.getLines()
        
        for line in range(startLine, startLine + count):
            length = min(self.columns, self.history.getLineLen(line))
            dest_line_offset = (line - startLine) * self.columns
            
            # 确保dest足够大 - 修复：创建新的Character对象，避免引用共享
            while len(dest) < dest_line_offset + self.columns:
                dest.append(Character(' '))
            
            # 从历史获取字符
            if length > 0:
                cells = self.history.getCells(line, 0, length)
                for i, cell in enumerate(cells):
                    if dest_line_offset + i < len(dest):
                        # 优化：仅在需要时进行深拷贝
                        if force_copy:
                            dest[dest_line_offset + i] = copy.copy(cell)
                        else:
                            dest[dest_line_offset + i] = cell
            
            # 填充剩余列 - 修复：创建新的Character对象，避免引用共享
            for column in range(length, self.columns):
                if dest_line_offset + column < len(dest):
                    dest[dest_line_offset + column] = Character(' ')
            
            # 反转选中的文本
            if self.selBegin != -1:
                for column in range(self.columns):
                    if self.isSelected(column, line):
                        idx = dest_line_offset + column
                        if idx < len(dest):
                            # 如果未强制拷贝，则在此处拷贝以进行修改
                            if not force_copy:
                                dest[idx] = copy.copy(dest[idx])
                            self.reverseRendition(dest[idx])

    def copyFromScreen(self, dest: List[Character], startLine: int, count: int, force_copy: bool = False):
        """
        从屏幕缓冲区复制字符。
        
        Args:
            dest: 目标缓冲区
            startLine: 起始行
            count: 行数
            force_copy: 是否强制深拷贝所有字符
            
        对应C++: void Screen::copyFromScreen(Character* dest, int startLine, int count) const
        """
        assert startLine >= 0 and count > 0 and startLine + count <= self.lines
        
        for line in range(startLine, startLine + count):
            dest_line_start_index = (line - startLine) * self.columns
            
            # 确保dest足够大 - 修复：创建新的Character对象，避免引用共享
            while len(dest) < dest_line_start_index + self.columns:
                dest.append(Character(' '))
            
            for column in range(self.columns):
                dest_index = dest_line_start_index + column
                
                # 从屏幕行获取字符
                if (line < len(self.screenLines) and 
                    column < len(self.screenLines[line])):
                    # 优化：仅在需要时进行深拷贝
                    if force_copy:
                        dest[dest_index] = copy.copy(self.screenLines[line][column])
                    else:
                        dest[dest_index] = self.screenLines[line][column]
                else:
                    dest[dest_index] = Screen.default_char
                
                # 反转选中的文本
                if (self.selBegin != -1 and 
                    self.isSelected(column, line + self.history.getLines())):
                    # 如果未强制拷贝，则在此处拷贝以进行修改
                    if not force_copy:
                        dest[dest_index] = copy.copy(dest[dest_index])
                    self.reverseRendition(dest[dest_index])
    
    def copyFromScreenWithOffset(self, dest: List[Character], dest_offset: int, startLine: int, count: int, force_copy: bool = False):
        """
        从屏幕缓冲区复制字符到指定offset位置。
        
        Args:
            dest: 目标缓冲区
            dest_offset: 目标缓冲区偏移量
            startLine: 起始行
            count: 行数
            force_copy: 是否强制深拷贝所有字符
            
        修复Python切片引用问题的版本
        """
        assert startLine >= 0 and count > 0 and startLine + count <= self.lines
        
        for line in range(startLine, startLine + count):
            dest_line_start_index = dest_offset + (line - startLine) * self.columns
            
            # 确保dest足够大 - 修复：创建新的Character对象，避免引用共享
            while len(dest) < dest_line_start_index + self.columns:
                dest.append(Character(' '))
            
            for column in range(self.columns):
                dest_index = dest_line_start_index + column
                
                # 从屏幕行获取字符
                if (line < len(self.screenLines) and 
                    column < len(self.screenLines[line])):
                    # 优化：仅在需要时进行深拷贝
                    if force_copy:
                        dest[dest_index] = copy.copy(self.screenLines[line][column])
                    else:
                        dest[dest_index] = self.screenLines[line][column]
                else:
                    dest[dest_index] = Screen.default_char
                
                # 反转选中的文本
                if (self.selBegin != -1 and 
                    self.isSelected(column, line + self.history.getLines())):
                    # 如果未强制拷贝，则在此处拷贝以进行修改
                    if not force_copy:
                        dest[dest_index] = copy.copy(dest[dest_index])
                    self.reverseRendition(dest[dest_index])
    
    def reverseRendition(self, char: Character):
        """
        反转字符的渲染（交换前景色和背景色）。
        
        Args:
            char: 要反转的字符
            
        对应C++: void Screen::reverseRendition(Character& p) const
        """
        f = char.foregroundColor
        b = char.backgroundColor
        char.foregroundColor = b
        char.backgroundColor = f
    
    # 选择相关辅助方法
    
    def checkSelection(self, fromPos: int, toPos: int):
        """
        检查选择区域是否与指定区域重叠，如果重叠则清除选择。
        
        Args:
            fromPos: 起始位置
            toPos: 结束位置
            
        对应C++: void Screen::checkSelection(int from, int to)
        """
        if self.selBegin == -1:
            return
        
        scr_tl = loc(0, self.history.getLines(), self.columns)
        # 如果选择与区域[from, to]重叠则清除整个选择
        if ((self.selBottomRight >= (fromPos + scr_tl)) and 
            (self.selTopLeft <= (toPos + scr_tl))):
            self.clearSelection()
    
    def getSelectionStart(self) -> Tuple[int, int]:
        """
        获取选择的开始位置。
        
        Returns:
            Tuple[int, int]: (列, 行)位置
            
        对应C++: void Screen::getSelectionStart(int& column, int& line) const
        """
        if self.selTopLeft != -1:
            column = self.selTopLeft % self.columns
            line = self.selTopLeft // self.columns
        else:
            column = self.cuX + self.getHistLines()
            line = self.cuY + self.getHistLines()
        return column, line
    
    def getSelectionEnd(self) -> Tuple[int, int]:
        """
        获取选择的结束位置。
        
        Returns:
            Tuple[int, int]: (列, 行)位置
            
        对应C++: void Screen::getSelectionEnd(int& column, int& line) const
        """
        if self.selBottomRight != -1:
            column = self.selBottomRight % self.columns
            line = self.selBottomRight // self.columns
        else:
            column = self.cuX + self.getHistLines()
            line = self.cuY + self.getHistLines()
        return column, line
    
    def selectedText(self, preserveLineBreaks: bool = True) -> str:
        """
        返回选中的文本
        
        Args:
            preserveLineBreaks: 是否保留换行符
            
        Returns:
            str: 选中的文本
            
        对应C++: QString Screen::selectedText(bool preserveLineBreaks) const
        """
        if not self.isSelectionValid():
            return ""
        
        # 直接收集字符串，不使用复杂的流机制
        result_lines = []
        
        top = self.selTopLeft // self.columns
        left = self.selTopLeft % self.columns
        bottom = self.selBottomRight // self.columns
        right = self.selBottomRight % self.columns
        
        for y in range(top, bottom + 1):
            start = 0
            if y == top or self.blockSelectionMode:
                start = left
            
            count = -1
            if y == bottom or self.blockSelectionMode:
                count = right - start + 1
            
            line_text = self._getLineText(y, start, count)
            
            # 添加换行符（除了最后一行）
            if y != bottom and preserveLineBreaks:
                # 检查是否需要换行
                line_props = LINE_DEFAULT
                if y < self.history.getLines():
                    if self.history.isWrappedLine(y):
                        line_props |= LINE_WRAPPED
                else:
                    screen_line = y - self.history.getLines()
                    if screen_line < len(self.lineProperties):
                        line_props = self.lineProperties[screen_line]
                
                if not (line_props & LINE_WRAPPED):
                    line_text += '\n'
            
            result_lines.append(line_text)
        
        return ''.join(result_lines)
    
    def _getLineText(self, line: int, start: int, count: int) -> str:
        """
        获取指定行的文本
        
        Args:
            line: 行号
            start: 起始列
            count: 字符数量(-1表示到行末)
            
        Returns:
            str: 行文本
        """
        if line < self.history.getLines():
            # 从历史获取
            line_length = self.history.getLineLen(line)
            start = min(start, max(0, line_length - 1))
            
            if count == -1:
                count = line_length - start
            else:
                count = min(start + count, line_length) - start
            
            if count <= 0:
                return ""
            
            characters = self.history.getCells(line, start, count)
            return ''.join(chr(char.character) for char in characters)
        else:
            # 从屏幕获取
            screen_line = line - self.history.getLines()
            if screen_line >= len(self.screenLines):
                return ""
            
            line_data = self.screenLines[screen_line]
            if count == -1:
                count = len(line_data) - start
            
            if start >= len(line_data) or count <= 0:
                return ""
            
            end_pos = min(start + count, len(line_data))
            characters = line_data[start:end_pos]
            return ''.join(chr(char.character) for char in characters)
    
    def writeSelectionToStream(self, decoder: TerminalCharacterDecoder, 
                                preserveLineBreaks: bool = True):
        """
        将选中的字符写入到流中。
        
        Args:
            decoder: 字符解码器
            preserveLineBreaks: 是否保留换行符
            
        对应C++: void Screen::writeSelectionToStream(TerminalCharacterDecoder* decoder, bool preserveLineBreaks) const
        """
        if not self.isSelectionValid():
            return
        
        self.writeToStream(decoder, self.selTopLeft, self.selBottomRight, 
                           preserveLineBreaks)
    
    def writeToStream(self, decoder: TerminalCharacterDecoder, 
                       startIndex: int, endIndex: int,
                       preserveLineBreaks: bool = True):
        """
        将指定范围的字符写入到流中。
        
        Args:
            decoder: 字符解码器
            startIndex: 起始索引
            endIndex: 结束索引
            preserveLineBreaks: 是否保留换行符
            
        对应C++: void Screen::writeToStream(TerminalCharacterDecoder* decoder, int startIndex, int endIndex, bool preserveLineBreaks) const
        """
        top = startIndex // self.columns
        left = startIndex % self.columns
        bottom = endIndex // self.columns
        right = endIndex % self.columns
        
        assert top >= 0 and left >= 0 and bottom >= 0 and right >= 0
        
        for y in range(top, bottom + 1):
            start = 0
            if y == top or self.blockSelectionMode:
                start = left
            
            count = -1
            if y == bottom or self.blockSelectionMode:
                count = right - start + 1
            
            appendNewLine = (y != bottom)
            copied = self.copyLineToStream(y, start, count, decoder,
                                            appendNewLine, preserveLineBreaks)
            
            # 如果选择超出最后一行的末尾，则添加换行符
            if y == bottom and copied < count:
                newLineChar = Character('\n')
                decoder.decodeLine([newLineChar], 1, 0)
    
    def copyLineToStream(self, line: int, start: int, count: int,
                          decoder: TerminalCharacterDecoder,
                          appendNewLine: bool, preserveLineBreaks: bool) -> int:
        """
        将指定行复制到流中。
        
        Args:
            line: 行号
            start: 起始列
            count: 字符数量
            decoder: 字符解码器
            appendNewLine: 是否添加换行符
            preserveLineBreaks: 是否保留换行符
            
        Returns:
            int: 实际复制的字符数
            
        对应C++: int Screen::copyLineToStream(int line, int start, int count, TerminalCharacterDecoder* decoder, bool appendNewLine, bool preserveLineBreaks) const
        """
        currentLineProperties = LINE_DEFAULT
        
        # 确定行是在历史缓冲区还是屏幕图像中
        if line < self.history.getLines():
            line_length = self.history.getLineLen(line)
            
            # 确保起始位置在行末之前
            start = min(start, max(0, line_length - 1))
            
            if count == -1:
                count = line_length - start
            else:
                count = min(start + count, line_length) - start
            
            # 安全检查
            assert start >= 0
            assert count >= 0
            assert (start + count) <= self.history.getLineLen(line)
            
            # 从历史获取字符
            character_buffer = self.history.getCells(line, start, count)
            
            if self.history.isWrappedLine(line):
                currentLineProperties |= LINE_WRAPPED
        else:
            if count == -1:
                count = self.columns - start
            
            assert count >= 0
            
            screen_line = line - self.history.getLines()
            character_buffer = []
            
            # 从屏幕图像获取行
            if screen_line < len(self.screenLines):
                line_data = self.screenLines[screen_line]
                length = len(line_data)
                
                for i in range(start, min(start + count, length)):
                    if i < len(line_data):
                        character_buffer.append(line_data[i])
                
                # count不能大于length
                count = max(0, min(count, length - start))
            else:
                count = 0
            
            assert screen_line < len(self.lineProperties)
            currentLineProperties |= self.lineProperties[screen_line]
        
        # 在末尾添加换行符
        omitLineBreak = ((currentLineProperties & LINE_WRAPPED) or 
                          not preserveLineBreaks)
        
        if not omitLineBreak and appendNewLine:
            character_buffer.append(Character('\n'))
            count += 1
        
        # 解码行并写入文本流
        decoder.decodeLine(character_buffer, count, currentLineProperties)
        
        return count
    
    def resizeImage(self, newLines: int, newColumns: int):
        """
        调整图像大小到新的固定大小。
        
        Args:
            newLines: 新行数
            newColumns: 新列数
            
        对应C++: void Screen::resizeImage(int new_lines, int new_columns)
        """
        if newLines == self.lines and newColumns == self.columns:
            return
        
        if self.cuY > newLines - 1:
            # 尝试保留焦点和行
            self._bottomMargin = self.lines - 1  # 边距丢失
            for i in range(self.cuY - (newLines - 1)):
                self.addHistLine()
                self.scrollUp(0, 1)
        
        # 创建新屏幕行并从旧的复制到新的
        new_screenLines = []
        for i in range(newLines + 1):
            if i < len(self.screenLines):
                line = self.screenLines[i][:]  # 复制现有行
                if len(line) < newColumns:
                    line.extend([Screen.default_char] * (newColumns - len(line)))
                elif len(line) > newColumns:
                    line = line[:newColumns]
                new_screenLines.append(line)
            else:
                # 新行，用默认字符填充
                new_screenLines.append([Screen.default_char] * newColumns)
        
        # 调整行属性
        new_lineProperties = []
        for i in range(newLines + 1):
            if i < len(self.lineProperties):
                new_lineProperties.append(self.lineProperties[i])
            else:
                new_lineProperties.append(LINE_DEFAULT)
        
        self.clearSelection()
        
        self.screenLines = new_screenLines
        self.lineProperties = new_lineProperties
        
        self.lines = newLines
        self.columns = newColumns
        self.cuX = min(self.cuX, self.columns - 1)
        self.cuY = min(self.cuY, self.lines - 1)
        
        # 重置边距
        self._topMargin = 0
        self._bottomMargin = self.lines - 1
        self.initTabStops()
        self.clearSelection()
    
    def setLineProperty(self, property: LineProperty, enable: bool):
        """
        设置或清除当前行的属性。
        
        Args:
            property: 行属性
            enable: True为设置，False为清除
            
        对应C++: void Screen::setLineProperty(LineProperty property, bool enable)
        """
        if enable:
            self.lineProperties[self.cuY] |= property
        else:
            self.lineProperties[self.cuY] &= ~property 
    
    def getLineProperties(self, startLine: int, endLine: int) -> List[LineProperty]:
        """
        返回与图像中的行相关联的附加属性。
        最重要的属性是LINE_WRAPPED，它指定行被换行，
        其他属性控制行中字符的大小。
        
        Args:
            startLine: 起始行索引
            endLine: 结束行索引
            
        Returns:
            List[LineProperty]: 行属性列表
            
        对应C++: QVector<LineProperty> Screen::getLineProperties(int startLine, int endLine) const
        """
        assert startLine >= 0
        assert endLine >= startLine and endLine < self.history.getLines() + self.lines
        
        merged_lines = endLine - startLine + 1
        lines_in_history = max(0, min(self.history.getLines() - startLine, merged_lines))
        lines_in_screen = merged_lines - lines_in_history
        
        result: List[LineProperty] = [LINE_DEFAULT] * merged_lines
        index = 0
        
        # 复制历史中行的属性
        for line in range(startLine, startLine + lines_in_history):
            # TODO: 支持除换行外的其他行属性
            if self.history.isWrappedLine(line):
                result[index] |= LINE_WRAPPED
            index += 1
        
        # 复制屏幕缓冲区中行的属性
        first_screen_line = startLine + lines_in_history - self.history.getLines()
        for line in range(first_screen_line, first_screen_line + lines_in_screen):
            if line < len(self.lineProperties):
                result[index] = self.lineProperties[line]
            index += 1
        
        return result
    
    def compose(self, composeString: str):
        """
        与最后显示的字符进行组合。
        
        Args:
            composeString: 组合字符串
            
        注意: 这个功能在原C++版本中未实现，这里提供占位符
        对应C++: void Screen::compose(const QString& compose)
        """
        # 原C++版本中这个方法未实现，只有assert
        # 这里提供一个基本的占位符实现
        assert False, "compose方法未实现 - 对应C++版本也未实现"
    
    def usedExtendedChars(self) -> set:
        """
        返回屏幕中使用的扩展字符集合。
        
        Returns:
            set: 扩展字符的Unicode码点集合
            
        对应C++: QSet<uint> Screen::usedExtendedChars() const
        """
        result = set()
        for i in range(self.lines):
            if i < len(self.screenLines):
                line = self.screenLines[i]
                for j in range(min(len(line), self.columns)):
                    char = line[j]
                    if char.rendition & RE_EXTENDED_CHAR:
                        result.add(char.character)
        return result
    
    def writeLinesToStream(self, decoder: TerminalCharacterDecoder, 
                             fromLine: int, toLine: int):
        """
        将输出的一部分复制到流中。
        
        Args:
            decoder: 将终端字符转换为文本的解码器
            fromLine: 要检索的历史中的第一行
            toLine: 要检索的历史中的最后一行
            
        对应C++: void Screen::writeLinesToStream(TerminalCharacterDecoder* decoder, int fromLine, int toLine) const
        """
        startIndex = loc(0, fromLine, self.columns)
        endIndex = loc(self.columns - 1, toLine, self.columns)
        self.writeToStream(decoder, startIndex, endIndex)
    
    def setForeColor(self, space: int, color: int):
        """
        设置光标的前景色。
        
        Args:
            space: 颜色参数使用的颜色空间
            color: 新的前景色
            
        对应C++: void Screen::setForeColor(int space, int color)
        """
        self.setForegroundColor(space, color)
    
    def setBackColor(self, space: int, color: int):
        """
        设置光标的背景色。
        
        Args:
            space: 颜色参数使用的颜色空间
            color: 新的背景色
            
        对应C++: void Screen::setBackColor(int space, int color)
        """
        self.setBackgroundColor(space, color)
    
    # 添加缺失的滚动方法 - 修复重名冲突
    
    def scrollUpLines(self, n: int = 1):
        """
        向上滚动屏幕的滚动区域n行。
        
        Args:
            n: 滚动行数，0表示滚动1行
            
        对应C++: void Screen::scrollUp(int n)
        """
        if n == 0:
            n = 1
        if self._topMargin == 0:
            self.addHistLine()  # 添加到历史
        self.scrollUp(self._topMargin, n)
    
    def scrollDownLines(self, n: int = 1):
        """
        向下滚动屏幕的滚动区域n行。
        
        Args:
            n: 滚动行数，0表示滚动1行
            
        对应C++: void Screen::scrollDown(int n)
        """
        if n == 0:
            n = 1
        self.scrollDown(self._topMargin, n)

    # 添加兼容性方法，支持snake_case调用
    
    # 光标移动方法的兼容性别名
    def cursor_up(self, n: int = 1):
        """兼容性方法：向上移动光标"""
        return self.cursorUp(n)
    
    def cursor_down(self, n: int = 1):
        """兼容性方法：向下移动光标"""
        return self.cursorDown(n)
    
    def cursor_left(self, n: int = 1):
        """兼容性方法：向左移动光标"""
        return self.cursorLeft(n)
    
    def cursor_right(self, n: int = 1):
        """兼容性方法：向右移动光标"""
        return self.cursorRight(n)
    
    def cursor_next_line(self, n: int = 1):
        """兼容性方法：向下移动光标n行到行首"""
        return self.cursorNextLine(n)
    
    def cursor_previous_line(self, n: int = 1):
        """兼容性方法：向上移动光标n行到行首"""
        return self.cursorPreviousLine(n)
    
    def set_cursor_x(self, x: int):
        """兼容性方法：设置光标列位置"""
        return self.setCursorX(x)
    
    def set_cursor_y(self, y: int):
        """兼容性方法：设置光标行位置"""
        return self.setCursorY(y)
    
    def set_cursor_yx(self, y: int, x: int):
        """兼容性方法：设置光标位置"""
        return self.setCursorYX(y, x)
    
    def get_cursor_x(self) -> int:
        """兼容性方法：获取光标列位置"""
        return self.getCursorX()
    
    def get_cursor_y(self) -> int:
        """兼容性方法：获取光标行位置"""
        return self.getCursorY()
    
    def to_start_of_line(self):
        """兼容性方法：移动光标到行首"""
        return self.toStartOfLine()
    
    # 边距管理的兼容性别名
    def set_margins(self, topLine: int, bottomLine: int):
        """兼容性方法：设置滚动边距"""
        return self.setMargins(topLine, bottomLine)
    
    def top_margin(self) -> int:
        """兼容性方法：获取顶部边距"""
        return self.topMargin()
    
    def bottom_margin(self) -> int:
        """兼容性方法：获取底部边距"""
        return self.bottomMargin()
    
    def set_default_margins(self):
        """兼容性方法：重置边距"""
        return self.setDefaultMargins()
    
    # 模式管理的兼容性别名
    def set_mode(self, mode: int):
        """兼容性方法：设置模式"""
        return self.setMode(mode)
    
    def reset_mode(self, mode: int):
        """兼容性方法：重置模式"""
        return self.resetMode(mode)
    
    def save_mode(self, mode: int):
        """兼容性方法：保存模式"""
        return self.saveMode(mode)
    
    def restore_mode(self, mode: int):
        """兼容性方法：恢复模式"""
        return self.restoreMode(mode)
    
    def get_mode(self, mode: int) -> bool:
        """兼容性方法：获取模式状态"""
        return self.getMode(mode)
    
    # 状态保存的兼容性别名
    def save_cursor(self):
        """兼容性方法：保存光标"""
        return self.saveCursor()
    
    def restore_cursor(self):
        """兼容性方法：恢复光标"""
        return self.restoreCursor()
    
    # 制表符的兼容性别名
    def init_tab_stops(self):
        """兼容性方法：初始化制表符"""
        return self.initTabStops()
    
    def clear_tab_stops(self):
        """兼容性方法：清除制表符"""
        return self.clearTabStops()
    
    def change_tab_stop(self, setStop: bool):
        """兼容性方法：更改制表符"""
        return self.changeTabStop(setStop)
    
    # 基本属性的兼容性别名
    def get_lines(self) -> int:
        """兼容性方法：获取行数"""
        return self.getLines()
    
    def get_columns(self) -> int:
        """兼容性方法：获取列数"""
        return self.getColumns()
    
    def get_hist_lines(self) -> int:
        """兼容性方法：获取历史行数"""
        return self.getHistLines()
    
    # 历史记录的兼容性别名
    def set_scroll(self, historyType: HistoryType, copyPreviousScroll: bool = True):
        """兼容性方法：设置滚动类型"""
        return self.setScroll(historyType, copyPreviousScroll)
    
    def get_scroll(self) -> HistoryType:
        """兼容性方法：获取滚动类型"""
        return self.getScroll()
    
    def has_scroll(self) -> bool:
        """兼容性方法：是否有滚动"""
        return self.hasScroll()
    
    # 选择的兼容性别名
    def clear_selection(self):
        """兼容性方法：清除选择"""
        return self.clearSelection()
    
    def set_selection_start(self, column: int, line: int, blockMode: bool):
        """兼容性方法：设置选择开始"""
        return self.setSelectionStart(column, line, blockMode)
    
    def set_selection_end(self, column: int, line: int):
        """兼容性方法：设置选择结束"""
        return self.setSelectionEnd(column, line)
    
    def is_selected(self, column: int, line: int) -> bool:
        """兼容性方法：检查是否被选中"""
        return self.isSelected(column, line)
    
    def is_selection_valid(self) -> bool:
        """兼容性方法：检查选择是否有效"""
        return self.isSelectionValid()
    
    # 渲染的兼容性别名
    def update_effective_rendition(self):
        """兼容性方法：更新有效渲染"""
        return self.updateEffectiveRendition()
    
    def set_foreground_color(self, space: int, color: int):
        """兼容性方法：设置前景色"""
        return self.setForegroundColor(space, color)
    
    def set_background_color(self, space: int, color: int):
        """兼容性方法：设置背景色"""
        return self.setBackgroundColor(space, color)
    
    def set_rendition(self, rendition: int):
        """兼容性方法：设置渲染"""
        return self.setRendition(rendition)
    
    def reset_rendition(self, rendition: int):
        """兼容性方法：重置渲染"""
        return self.resetRendition(rendition)
    
    def set_default_rendition(self):
        """兼容性方法：设置默认渲染"""
        return self.setDefaultRendition()
    
    # 清除操作的兼容性别名
    def clear_entire_screen(self):
        """兼容性方法：清除整个屏幕"""
        return self.clearEntireScreen()
    
    def clear_to_end_of_screen(self):
        """兼容性方法：清除到屏幕末尾"""
        return self.clearToEndOfScreen()
    
    def clear_to_begin_of_screen(self):
        """兼容性方法：清除到屏幕开始"""
        return self.clearToBeginOfScreen()
    
    def clear_entire_line(self):
        """兼容性方法：清除整行"""
        return self.clearEntireLine()
    
    def clear_to_end_of_line(self):
        """兼容性方法：清除到行末"""
        return self.clearToEndOfLine()
    
    def clear_to_begin_of_line(self):
        """兼容性方法：清除到行首"""
        return self.clearToBeginOfLine()
    
    def help_align(self):
        """兼容性方法：帮助对齐"""
        return self.helpAlign()
    
    # 内部方法的兼容性别名
    def clear_image(self, loca: int, loce: int, c: str):
        """兼容性方法：清除图像"""
        return self.clearImage(loca, loce, c)
    
    def add_hist_line(self):
        """兼容性方法：添加历史行"""
        return self.addHistLine()
    
    def scroll_up(self, fromLine: int, n: int):
        """兼容性方法：向上滚动"""
        return self.scrollUp(fromLine, n)
    
    def move_image(self, dest: int, sourceBegin: int, sourceEnd: int):
        """兼容性方法：移动图像"""
        return self.moveImage(dest, sourceBegin, sourceEnd)
    
    def scrolled_lines(self) -> int:
        """兼容性方法：获取滚动行数"""
        return self.scrolledLines()
    
    def dropped_lines(self) -> int:
        """兼容性方法：获取丢弃行数"""
        return self.droppedLines()
    
    def reset_scrolled_lines(self):
        """兼容性方法：重置滚动行数"""
        return self.resetScrolledLines()
    
    def reset_dropped_lines(self):
        """兼容性方法：重置丢弃行数"""
        return self.resetDroppedLines()
    
    def last_scrolled_region(self) -> QRect:
        """兼容性方法：获取最后滚动区域"""
        return self.lastScrolledRegion()
    
    # 字符显示的兼容性别名
    def display_character(self, c: str):
        """兼容性方法：显示字符"""
        return self.displayCharacter(c)
    
    # 编辑操作的兼容性别名
    def erase_chars(self, n: int):
        """兼容性方法：删除字符"""
        return self.eraseChars(n)
    
    def delete_chars(self, n: int):
        """兼容性方法：删除字符"""
        return self.deleteChars(n)
    
    def insert_chars(self, n: int):
        """兼容性方法：插入字符"""
        return self.insertChars(n)
    
    def repeat_chars(self, count: int):
        """兼容性方法：重复字符"""
        return self.repeatChars(count)
    
    def delete_lines(self, n: int):
        """兼容性方法：删除行"""
        return self.deleteLines(n)
    
    def insert_lines(self, n: int):
        """兼容性方法：插入行"""
        return self.insertLines(n)
    
    # 滚动操作的兼容性别名
    def reverse_index(self):
        """兼容性方法：反向索引"""
        return self.reverseIndex()
    
    def next_line(self):
        """兼容性方法：下一行"""
        return self.nextLine()
    
    def new_line(self):
        """兼容性方法：新行"""
        return self.newLine()
    
    def scroll_up_region(self, n: int = 1):
        """兼容性方法：向上滚动区域"""
        return self.scrollUpRegion(n)
    
    def scroll_down_region(self, n: int = 1):
        """兼容性方法：向下滚动区域"""
        return self.scrollDownRegion(n)
    
    def scroll_down(self, fromLine: int, n: int):
        """兼容性方法：向下滚动"""
        return self.scrollDown(fromLine, n)
    
    # 图像获取的兼容性别名
    def get_image(self, dest: List[Character], size: int, startLine: int, endLine: int):
        """兼容性方法：获取图像"""
        return self.getImage(dest, size, startLine, endLine)
    
    def copy_from_history(self, dest: List[Character], startLine: int, count: int):
        """兼容性方法：从历史复制"""
        return self.copyFromHistory(dest, startLine, count)
    
    def copy_from_screen(self, dest: List[Character], startLine: int, count: int):
        """兼容性方法：从屏幕复制"""
        return self.copyFromScreen(dest, startLine, count)
    
    def reverse_rendition(self, char: Character):
        """兼容性方法：反转渲染"""
        return self.reverseRendition(char)
    
    # 选择辅助方法的兼容性别名
    def check_selection(self, fromPos: int, toPos: int):
        """兼容性方法：检查选择"""
        return self.checkSelection(fromPos, toPos)
    
    def get_selection_start(self) -> Tuple[int, int]:
        """兼容性方法：获取选择开始"""
        return self.getSelectionStart()
    
    def get_selection_end(self) -> Tuple[int, int]:
        """兼容性方法：获取选择结束"""
        return self.getSelectionEnd()
    
    def selected_text(self, preserveLineBreaks: bool = True) -> str:
        """兼容性方法：获取选中文本"""
        return self.selectedText(preserveLineBreaks)
    
    def write_selection_to_stream(self, decoder: TerminalCharacterDecoder, preserveLineBreaks: bool = True):
        """兼容性方法：将选择写入流"""
        return self.writeSelectionToStream(decoder, preserveLineBreaks)
    
    def write_to_stream(self, decoder: TerminalCharacterDecoder, startIndex: int, endIndex: int, preserveLineBreaks: bool = True):
        """兼容性方法：写入流"""
        return self.writeToStream(decoder, startIndex, endIndex, preserveLineBreaks)
    
    def copy_line_to_stream(self, line: int, start: int, count: int, decoder: TerminalCharacterDecoder, appendNewLine: bool, preserveLineBreaks: bool) -> int:
        """兼容性方法：将行复制到流"""
        return self.copyLineToStream(line, start, count, decoder, appendNewLine, preserveLineBreaks)
    
    def resize_image(self, newLines: int, newColumns: int):
        """兼容性方法：调整图像大小"""
        return self.resizeImage(newLines, newColumns)
    
    def set_line_property(self, property: LineProperty, enable: bool):
        """兼容性方法：设置行属性"""
        return self.setLineProperty(property, enable)
    
    def get_line_properties(self, startLine: int, endLine: int) -> List[LineProperty]:
        """兼容性方法：获取行属性"""
        return self.getLineProperties(startLine, endLine)
    
    def used_extended_chars(self) -> set:
        """兼容性方法：获取使用的扩展字符"""
        return self.usedExtendedChars()
    
    def write_lines_to_stream(self, decoder: TerminalCharacterDecoder, fromLine: int, toLine: int):
        """兼容性方法：将行写入流"""
        return self.writeLinesToStream(decoder, fromLine, toLine)
    
    def set_fore_color(self, space: int, color: int):
        """兼容性方法：设置前景色"""
        return self.setForeColor(space, color)
    
    def set_back_color(self, space: int, color: int):
        """兼容性方法：设置背景色"""
        return self.setBackColor(space, color) 