"""
ScreenWindow模块 - 从Konsole终端模拟器转换而来

这个模块提供ScreenWindow类，用于提供对终端屏幕某一部分的窗口视图。
终端组件可以渲染窗口内容，并使用窗口来响应鼠标或键盘输入以改变终端屏幕的选择。

原始文件：
- ScreenWindow.h
- ScreenWindow.cpp

版权信息：
Copyright 2007-2008 by Robert Knight <robertknight@gmail.com>

转换为Python PySide6版本
"""

from enum import Enum
from typing import List, Optional, Tuple

from PySide6.QtCore import QObject
from PySide6.QtCore import QPoint, QRect, Signal

from qtermwidget.character import Character, LineProperty
from qtermwidget.keyboard_translator import KeyboardTranslator
from qtermwidget.screen import Screen


class ScreenWindow(QObject):
    """
    提供对终端屏幕某一部分的窗口视图。终端组件可以渲染窗口内容，
    并使用窗口来响应鼠标或键盘输入以改变终端屏幕的选择。
    
    可以通过调用 Emulation::createWindow() 为终端会话创建新的 ScreenWindow。
    
    使用 scrollTo() 方法在屏幕上上下滚动窗口。
    使用 getImage() 方法检索当前在窗口中可见的字符图像。
    
    setTrackOutput() 控制当新行添加到关联屏幕时，窗口是否移动到底部。
    
    每当底层屏幕的输出改变时，应该调用 notifyOutputChanged() 槽。
    这将相应地更新窗口位置，并在必要时发出 outputChanged() 信号。
    
    对应C++: class ScreenWindow : public QObject
    """
    
    # 滚动模式枚举
    class RelativeScrollMode(Enum):
        """描述 scrollBy() 移动窗口的单位"""
        ScrollLines = 0  # 按行数滚动窗口
        ScrollPages = 1  # 按页数滚动窗口，一页等于 windowLines() 行
    
    # 信号定义
    outputChanged = Signal()  # 当关联终端屏幕内容改变时发出
    scrolled = Signal(int)    # 当屏幕窗口滚动到不同位置时发出，参数为窗口顶部的行号
    selectionChanged = Signal()  # 当选择改变时发出
    scrollToEnd = Signal()    # 滚动到底部信号
    
    def __init__(self, parent: Optional[QObject] = None):
        """
        构造一个新的屏幕窗口。
        在调用 getImage() 或 getLineProperties() 之前，必须通过调用 setScreen() 指定屏幕。
        
        您不应该直接调用此构造函数，而应使用 Emulation::createWindow() 方法
        在您希望查看的仿真上创建窗口。这允许仿真在关联屏幕改变时通知窗口，
        并在会话的所有视图之间同步选择更新。
        
        Args:
            parent: 父对象
            
        对应C++: ScreenWindow::ScreenWindow(QObject* parent)
        """
        super().__init__(parent)
        
        self._screen = None
        self._windowBuffer = None
        self._windowBufferSize = 0
        self._bufferNeedsUpdate = True
        self._windowLines = 1
        self._currentLine = 0
        self._trackOutput = True
        self._scrollCount = 0
    
    def __del__(self):
        """
        析构函数
        
        对应C++: ScreenWindow::~ScreenWindow()
        """
        # Python中由垃圾回收自动处理
        self._windowBuffer = None
    
    def setScreen(self, screen):
        """
        设置此窗口查看的屏幕
        
        Args:
            screen: 屏幕对象
            
        对应C++: void ScreenWindow::setScreen(Screen* screen)
        """
        assert screen is not None
        self._screen = screen
    
    def screen(self):
        """
        返回此窗口查看的屏幕
        
        Returns:
            Screen: 屏幕对象
            
        对应C++: Screen* ScreenWindow::screen() const
        """
        return self._screen
    
    def getImage(self) -> List[Character]:
        """
        返回当前通过此窗口在屏幕上可见的字符图像。
        
        返回的缓冲区由 ScreenWindow 实例管理，调用者无需删除。
        
        Returns:
            List[Character]: 字符图像
            
        对应C++: Character* ScreenWindow::getImage()
        """
        if self._screen is None:
            return []  # 如果没有屏幕，返回空列表
            
        # 如果窗口大小改变，重新分配内部缓冲区
        size = self.windowLines() * self.windowColumns()
        if self._windowBuffer is None or self._windowBufferSize != size:
            self._windowBuffer = [Character()] * size
            self._windowBufferSize = size
            self._bufferNeedsUpdate = True
        
        if not self._bufferNeedsUpdate:
            return self._windowBuffer
        
        self._screen.getImage(self._windowBuffer, size,
                             self.currentLine(), self.endWindowLine())
        
        # 此窗口可能超出屏幕末尾，在这种情况下，
        # 有一个未使用的区域需要用空白字符填充
        self.fillUnusedArea()
        
        self._bufferNeedsUpdate = False
        return self._windowBuffer
    
    def getLineProperties(self) -> List[LineProperty]:
        """
        返回当前通过此窗口可见的字符行的相关行属性
        
        Returns:
            List[LineProperty]: 行属性列表
            
        对应C++: QVector<LineProperty> ScreenWindow::getLineProperties()
        """
        if self._screen is None:
            return [0] * self.windowLines()  # 返回默认属性
            
        result = self._screen.getLineProperties(self.currentLine(), self.endWindowLine())
        
        if len(result) != self.windowLines():
            # 调整结果大小
            if len(result) < self.windowLines():
                result.extend([0] * (self.windowLines() - len(result)))
            else:
                result = result[:self.windowLines()]
        
        return result
    
    def scrollCount(self) -> int:
        """
        返回自上次调用 resetScrollCount() 以来，
        scrollRegion() 指定的窗口区域已滚动的行数。
        
        scrollRegion() 在大多数情况下是整个窗口，
        但在例如提供分屏功能的应用程序中会是一个较小的区域。
        
        这不保证准确，但允许视图通过减少昂贵的文本渲染量来优化渲染，
        这在输出滚动时是需要的。
        
        Returns:
            int: 滚动行数
            
        对应C++: int ScreenWindow::scrollCount() const
        """
        return self._scrollCount
    
    def resetScrollCount(self):
        """
        重置 scrollCount() 返回的滚动行计数
        
        对应C++: void ScreenWindow::resetScrollCount()
        """
        self._scrollCount = 0
    
    def scrollRegion(self) -> QRect:
        """
        返回窗口中最后滚动的区域，这通常是整个窗口区域。
        
        与 scrollCount() 一样，这不保证准确，
        但允许视图优化渲染。
        
        Returns:
            QRect: 滚动区域
            
        对应C++: QRect ScreenWindow::scrollRegion() const
        """
        if self._screen is None:
            return QRect(0, 0, self.windowColumns(), self.windowLines())
            
        equal_to_screen_size = (self.windowLines() == self._screen.getLines())
        
        if self.atEndOfOutput() and equal_to_screen_size:
            return self._screen.lastScrolledRegion()
        else:
            return QRect(0, 0, self.windowColumns(), self.windowLines())
    
    def setSelectionStart(self, column: int, line: int, columnMode: bool = False):
        """
        设置窗口内选择的开始位置
        
        Args:
            column: 列索引
            line: 行索引
            columnMode: 是否为列模式
            
        对应C++: void ScreenWindow::setSelectionStart(int column, int line, bool columnMode)
        """
        if self._screen is None:
            return
            
        # C++: _screen->setSelectionStart( column , qMin(line + currentLine(),endWindowLine())  , columnMode);
        self._screen.setSelectionStart(column, 
                                       min(line + self.currentLine(), self.endWindowLine()),
                                       columnMode)
        
        self._bufferNeedsUpdate = True
        self.selectionChanged.emit()
    
    def setSelectionEnd(self, column: int, line: int):
        """
        设置窗口内选择的结束位置
        
        Args:
            column: 列索引
            line: 行索引
            
        对应C++: void ScreenWindow::setSelectionEnd(int column, int line)
        """
        if self._screen is None:
            return
            
        # C++: _screen->setSelectionEnd( column , qMin(line + currentLine(),endWindowLine()) );
        self._screen.setSelectionEnd(column, 
                                     min(line + self.currentLine(), self.endWindowLine()))
        
        self._bufferNeedsUpdate = True
        self.selectionChanged.emit()
    
    def getSelectionStart(self) -> Tuple[int, int]:
        """
        检索窗口内选择的开始位置
        
        Returns:
            Tuple[int, int]: (列, 行)
            
        对应C++: void ScreenWindow::getSelectionStart(int& column, int& line)
        """
        if self._screen is None:
            return 0, 0
            
        # C++: _screen->getSelectionStart(column,line); line -= currentLine();
        column, line = self._screen.getSelectionStart()
        line -= self.currentLine()
        return column, line
    
    def getSelectionEnd(self) -> Tuple[int, int]:
        """
        检索窗口内选择的结束位置
        
        Returns:
            Tuple[int, int]: (列, 行)
            
        对应C++: void ScreenWindow::getSelectionEnd(int& column, int& line)
        """
        if self._screen is None:
            return 0, 0
            
        # C++: _screen->getSelectionEnd(column,line); line -= currentLine();
        column, line = self._screen.getSelectionEnd()
        line -= self.currentLine()
        return column, line
    
    def isSelected(self, column: int, line: int) -> bool:
        """
        返回指定位置的字符是否为选择的一部分
        
        Args:
            column: 列索引
            line: 行索引
            
        Returns:
            bool: 是否被选中
            
        对应C++: bool ScreenWindow::isSelected(int column, int line)
        """
        if self._screen is None:
            return False
            
        # C++: return _screen->isSelected( column , qMin(line + currentLine(),endWindowLine()) );
        return self._screen.isSelected(column, 
                                      min(line + self.currentLine(), self.endWindowLine()))
    
    def clearSelection(self):
        """
        清除当前选择
        
        对应C++: void ScreenWindow::clearSelection()
        """
        if self._screen is None:
            return
            
        # C++: _screen->clearSelection(); emit selectionChanged();
        self._screen.clearSelection()
        self.selectionChanged.emit()
    
    def setWindowLines(self, lines: int):
        """
        设置窗口中的行数
        
        Args:
            lines: 行数
            
        对应C++: void ScreenWindow::setWindowLines(int lines)
        """
        # C++: Q_ASSERT(lines > 0); _windowLines = lines;
        assert lines > 0
        self._windowLines = lines
    
    def windowLines(self) -> int:
        """
        返回窗口中的行数
        
        Returns:
            int: 行数
            
        对应C++: int ScreenWindow::windowLines() const
        """
        return self._windowLines
    
    def windowColumns(self) -> int:
        """
        返回窗口中的列数
        
        Returns:
            int: 列数
            
        对应C++: int ScreenWindow::windowColumns() const
        """
        # C++: return _screen->getColumns();
        if self._screen is None:
            return 80  # 默认值
        return self._screen.getColumns()
    
    def lineCount(self) -> int:
        """
        返回屏幕中的总行数
        
        Returns:
            int: 总行数
            
        对应C++: int ScreenWindow::lineCount() const
        """
        # C++: return _screen->getHistLines() + _screen->getLines();
        if self._screen is None:
            return 1  # 默认值
        return self._screen.getHistLines() + self._screen.getLines()
    
    def columnCount(self) -> int:
        """
        返回屏幕中的总列数
        
        Returns:
            int: 总列数
            
        对应C++: int ScreenWindow::columnCount() const
        """
        # C++: return _screen->getColumns();
        if self._screen is None:
            return 80  # 默认值
        return self._screen.getColumns()
    
    def currentLine(self) -> int:
        """
        返回当前位于此窗口顶部的行索引
        
        Returns:
            int: 当前行索引
            
        对应C++: int ScreenWindow::currentLine() const
        """
        # C++: return qBound(0,_currentLine,lineCount()-windowLines());
        max_line = self.lineCount() - self.windowLines()
        return max(0, min(self._currentLine, max_line))
    
    def cursorPosition(self) -> QPoint:
        """
        返回光标在窗口内的位置
        
        Returns:
            QPoint: 光标位置
            
        对应C++: QPoint ScreenWindow::cursorPosition() const
        """
        # C++: QPoint position; position.setX( _screen->getCursorX() ); position.setY( _screen->getCursorY() ); return position;
        position = QPoint()
        if self._screen is not None:
            position.setX(self._screen.getCursorX())
            position.setY(self._screen.getCursorY())
        else:
            position.setX(0)
            position.setY(0)
        return position
    
    def atEndOfOutput(self) -> bool:
        """
        便利方法。如果窗口当前位于屏幕底部，则返回 True
        
        Returns:
            bool: 是否在输出末尾
            
        对应C++: bool ScreenWindow::atEndOfOutput() const
        """
        # C++: return currentLine() == (lineCount()-windowLines());
        return self.currentLine() == (self.lineCount() - self.windowLines())
    
    def scrollTo(self, line: int):
        """
        滚动窗口，使指定行位于窗口顶部
        
        Args:
            line: 目标行
            
        对应C++: void ScreenWindow::scrollTo(int line)
        """
        # C++完整实现:
        # int maxCurrentLineNumber = lineCount() - windowLines();
        # line = qBound(0,line,maxCurrentLineNumber);
        # const int delta = line - _currentLine;
        # _currentLine = line;
        # _scrollCount += delta;
        # _bufferNeedsUpdate = true;
        # emit scrolled(_currentLine);
        
        max_current_line_number = self.lineCount() - self.windowLines()
        line = max(0, min(line, max_current_line_number))
        
        delta = line - self._currentLine
        self._currentLine = line
        
        # 跟踪滚动的行数，可以通过调用 resetScrollCount() 重置
        self._scrollCount += delta
        
        self._bufferNeedsUpdate = True

        self.scrolled.emit(self._currentLine)
    
    def scrollBy(self, mode: 'ScreenWindow.RelativeScrollMode', amount: int):
        """
        相对于窗口在屏幕上的当前位置滚动窗口
        
        Args:
            mode: 指定 amount 是指行数还是页数
            amount: 要滚动的行数或页数。如果这个数字是正数，视图向下滚动。
                   如果这个数字是负数，视图向上滚动。
                   
        对应C++: void ScreenWindow::scrollBy(RelativeScrollMode mode, int amount)
        """
        # C++完整实现:
        # if ( mode == ScrollLines ) { scrollTo( currentLine() + amount ); }
        # else if ( mode == ScrollPages ) { scrollTo( currentLine() + amount * ( windowLines() / 2 ) ); }
        
        if mode == ScreenWindow.RelativeScrollMode.ScrollLines:
            self.scrollTo(self.currentLine() + amount)
        elif mode == ScreenWindow.RelativeScrollMode.ScrollPages:
            self.scrollTo(self.currentLine() + amount * (self.windowLines() // 2))
    
    def setTrackOutput(self, trackOutput: bool):
        """
        指定当添加新输出时，窗口是否应自动移动到屏幕底部
        
        如果设置为 True，当调用 notifyOutputChanged() 方法时，
        窗口将移动到关联屏幕的底部。
        
        Args:
            trackOutput: 是否跟踪输出
            
        对应C++: void ScreenWindow::setTrackOutput(bool trackOutput)
        """
        self._trackOutput = trackOutput
    
    def trackOutput(self) -> bool:
        """
        返回窗口是否在添加新输出时自动移动到屏幕底部
        
        Returns:
            bool: 是否跟踪输出
            
        对应C++: bool ScreenWindow::trackOutput() const
        """
        return self._trackOutput
    
    def selectedText(self, preserveLineBreaks: bool = True) -> str:
        """
        返回当前选中的文本
        
        Args:
            preserveLineBreaks: 参见 Screen::selectedText()
            
        Returns:
            str: 选中的文本
            
        对应C++: QString ScreenWindow::selectedText(bool preserveLineBreaks) const
        """
        if self._screen is None:
            return ""
            
        # C++: return _screen->selectedText( preserveLineBreaks );
        return self._screen.selectedText(preserveLineBreaks)
    
    def notifyOutputChanged(self):
        """
        通知窗口关联终端屏幕的内容已改变。
        如果 trackOutput() 为 True，这会将窗口移动到屏幕底部，
        并导致发出 outputChanged() 信号。
        
        对应C++: void ScreenWindow::notifyOutputChanged()
        """
        if self._screen is None:
            self.outputChanged.emit()
            return
            
        # C++完整实现:
        # move window to the bottom of the screen and update scroll count
        # if this window is currently tracking the bottom of the screen
        # if ( _trackOutput )
        # {
        #     _scrollCount -= _screen->scrolledLines();
        #     _currentLine = qMax(0,_screen->getHistLines() - (windowLines()-_screen->getLines()));
        # }
        # else
        # {
        #     // if the history is not unlimited then it may
        #     // have run out of space and dropped the oldest
        #     // lines of output - in this case the screen
        #     // window's current line number will need to
        #     // be adjusted - otherwise the output will scroll
        #     _currentLine = qMax(0,_currentLine -
        #                           _screen->droppedLines());
        #
        #     // ensure that the screen window's current position does
        #     // not go beyond the bottom of the screen
        #     _currentLine = qMin( _currentLine , _screen->getHistLines() );
        # }
        # _bufferNeedsUpdate = true;
        # emit outputChanged();
        
        if self._trackOutput:
            self._scrollCount -= self._screen.scrolledLines()
            self._currentLine = max(0, self._screen.getHistLines() - 
                                   (self.windowLines() - self._screen.getLines()))
        else:
            # 如果历史不是无限的，那么它可能已经用完空间并丢弃了最旧的输出行 -
            # 在这种情况下，屏幕窗口的当前行号需要调整 - 否则输出将滚动
            self._currentLine = max(0, self._currentLine - self._screen.droppedLines())
            
            # 确保屏幕窗口的当前位置不会超出屏幕底部
            self._currentLine = min(self._currentLine, self._screen.getHistLines())
        
        self._bufferNeedsUpdate = True
        
        self.outputChanged.emit()
    
    def handleCommandFromKeyboard(self, command: 'KeyboardTranslator.Command'):
        """
        处理来自键盘的命令
        
        Args:
            command: 键盘命令
            
        对应C++: void ScreenWindow::handleCommandFromKeyboard(KeyboardTranslator::Command command)
        """
        # C++完整实现:
        # // Keyboard-based navigation
        # bool update = false;
        # 
        # // EraseCommand is handled in Vt102Emulation
        # if ( command & KeyboardTranslator::ScrollPageUpCommand )
        # {
        #     scrollBy( ScreenWindow::ScrollPages , -1 );
        #     update = true;
        # }
        # if ( command & KeyboardTranslator::ScrollPageDownCommand )
        # {
        #     scrollBy( ScreenWindow::ScrollPages , 1 );
        #     update = true;
        # }
        # if ( command & KeyboardTranslator::ScrollLineUpCommand )
        # {
        #     scrollBy( ScreenWindow::ScrollLines , -1 );
        #     update = true;
        # }
        # if ( command & KeyboardTranslator::ScrollLineDownCommand )
        # {
        #     scrollBy( ScreenWindow::ScrollLines , 1 );
        #     update = true;
        # }
        # if ( command & KeyboardTranslator::ScrollDownToBottomCommand )
        # {
        #     Q_EMIT scrollToEnd();
        #     update = true;
        # }
        # if ( command & KeyboardTranslator::ScrollUpToTopCommand)
        # {
        #     scrollTo(0);
        #     update = true;
        # }
        # // TODO: KeyboardTranslator::ScrollLockCommand
        # // TODO: KeyboardTranslator::SendCommand
        # 
        # if ( update )
        # {
        #     setTrackOutput( atEndOfOutput() );
        #     Q_EMIT outputChanged();
        # }
        
        # 基于键盘的导航
        update = False
        
        # EraseCommand 在 Vt102Emulation 中处理
        if command & KeyboardTranslator.Command.ScrollPageUpCommand:
            self.scrollBy(ScreenWindow.RelativeScrollMode.ScrollPages, -1)
            update = True
        if command & KeyboardTranslator.Command.ScrollPageDownCommand:
            self.scrollBy(ScreenWindow.RelativeScrollMode.ScrollPages, 1)
            update = True
        if command & KeyboardTranslator.Command.ScrollLineUpCommand:
            self.scrollBy(ScreenWindow.RelativeScrollMode.ScrollLines, -1)
            update = True
        if command & KeyboardTranslator.Command.ScrollLineDownCommand:
            self.scrollBy(ScreenWindow.RelativeScrollMode.ScrollLines, 1)
            update = True
        if command & KeyboardTranslator.Command.ScrollDownToBottomCommand:
            self.scrollToEnd.emit()
            update = True
        if command & KeyboardTranslator.Command.ScrollUpToTopCommand:
            self.scrollTo(0)
            update = True
        # TODO: KeyboardTranslator::ScrollLockCommand
        # TODO: KeyboardTranslator::SendCommand
        
        if update:
            self.setTrackOutput(self.atEndOfOutput())
            self.outputChanged.emit()
    
    def endWindowLine(self) -> int:
        """
        返回此窗口末尾的行索引，或者如果此窗口超出屏幕末尾，
        则返回屏幕末尾的行索引。
        
        当将行号传递给 Screen 方法时，行号不应超过 endWindowLine()
        
        Returns:
            int: 窗口末尾行索引
            
        对应C++: int ScreenWindow::endWindowLine() const
        """
        # C++: return qMin(currentLine() + windowLines() - 1, lineCount() - 1);
        return min(self.currentLine() + self.windowLines() - 1,
                  self.lineCount() - 1)
    
    def fillUnusedArea(self):
        """
        填充未使用的区域
        
        对应C++: void ScreenWindow::fillUnusedArea()
        """
        if self._screen is None or self._windowBuffer is None:
            return
            
        # C++完整实现:
        # int screenEndLine = _screen->getHistLines() + _screen->getLines() - 1;
        # int windowEndLine = currentLine() + windowLines() - 1;
        # int unusedLines = windowEndLine - screenEndLine;
        # int charsToFill = unusedLines * windowColumns();
        # Screen::fillWithDefaultChar(_windowBuffer + _windowBufferSize - charsToFill,charsToFill);
        
        screen_end_line = self._screen.getHistLines() + self._screen.getLines() - 1
        window_end_line = self.currentLine() + self.windowLines() - 1
        
        unused_lines = window_end_line - screen_end_line
        chars_to_fill = unused_lines * self.windowColumns()
        
        # 只有当实际有字符需要填充时才调用填充方法
        if chars_to_fill > 0:
            # Python中导入Screen类来调用静态方法
            from .screen import Screen
            fill_start = self._windowBufferSize - chars_to_fill
            Screen.fillWithDefaultChar(self._windowBuffer[fill_start:], chars_to_fill)