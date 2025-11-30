"""
键盘翻译器模块 - 从Konsole终端模拟器转换而来

原始文件：
- KeyboardTranslator.h
- KeyboardTranslator.cpp

版权信息：
Copyright 2007-2008 by Robert Knight <robertknight@gmail.com>

转换为Python PySide6版本
"""

import os
import re
import sys
from enum import IntFlag, IntEnum
from typing import List, Dict, Optional, Union, TextIO

from PySide6.QtCore import Qt, QIODevice, QTextStream
from PySide6.QtGui import QKeySequence

from qtermwidget.tools import get_kb_layout_dir


def oneOrZero(value: bool) -> int:
    """
    辅助函数：将布尔值转换为整数。
    对应C++: inline int oneOrZero(int value) { return value ? 1 : 0; }
    """
    return 1 if value else 0


class KeyboardTranslatorState(IntFlag):
    """
    键盘翻译器状态标志。
    对应C++: KeyboardTranslator::State enum
    """
    # 无特殊状态
    NoState = 0
    # 新行状态
    NewLineState = 1
    # ANSI模式状态
    AnsiState = 2
    # 光标键状态
    CursorKeysState = 4
    # 替代屏幕状态（如vim、screen等程序使用）
    AlternateScreenState = 8
    # 任意修饰键状态
    AnyModifierState = 16
    # 应用键盘状态
    ApplicationKeypadState = 32


class KeyboardTranslatorCommand(IntFlag):
    """
    键盘翻译器命令。
    对应C++: KeyboardTranslator::Command enum
    """
    # 无命令
    NoCommand = 0
    # 发送命令
    SendCommand = 1
    # 向上滚动一页
    ScrollPageUpCommand = 2
    # 向下滚动一页
    ScrollPageDownCommand = 4
    # 向上滚动一行
    ScrollLineUpCommand = 8
    # 向下滚动一行
    ScrollLineDownCommand = 16
    # 切换滚动锁定
    ScrollLockCommand = 32
    # 滚动到顶部
    ScrollUpToTopCommand = 64
    # 滚动到底部
    ScrollDownToBottomCommand = 128
    # 删除字符命令
    EraseCommand = 256


# 在Mac上Qt::ControlModifier表示Cmd，MetaModifier表示Ctrl
if sys.platform == "darwin":
    CTRL_MOD = Qt.KeyboardModifier.MetaModifier
else:
    CTRL_MOD = Qt.KeyboardModifier.ControlModifier


class KeyboardTranslatorEntry:
    """
    键盘翻译器条目，表示按键序列与字符序列/命令的关联。
    对应C++: KeyboardTranslator::Entry class
    """
    
    def __init__(self):
        """
        构造函数。
        对应C++: Entry::Entry()
        """
        self._key_code: int = 0
        self._modifiers: Qt.KeyboardModifiers = Qt.KeyboardModifier.NoModifier
        self._modifier_mask: Qt.KeyboardModifiers = Qt.KeyboardModifier.NoModifier
        self._state: KeyboardTranslatorState = KeyboardTranslatorState.NoState
        self._state_mask: KeyboardTranslatorState = KeyboardTranslatorState.NoState
        self._command: KeyboardTranslatorCommand = KeyboardTranslatorCommand.NoCommand
        self._text: bytes = b""
    
    def isNull(self) -> bool:
        """
        返回此条目是否为空。
        对应C++: bool Entry::isNull() const
        """
        return self == KeyboardTranslatorEntry()
    
    def command(self) -> KeyboardTranslatorCommand:
        """
        返回与此条目关联的命令。
        对应C++: Command Entry::command() const
        """
        return self._command
    
    def setCommand(self, command: KeyboardTranslatorCommand):
        """
        设置与此条目关联的命令。
        对应C++: void Entry::setCommand(Command command)
        """
        self._command = command
    
    def text(self, expandWildCards: bool = False, 
             modifiers: Qt.KeyboardModifiers = Qt.KeyboardModifier.NoModifier) -> bytes:
        """
        返回与此条目关联的字符序列。
        
        Args:
            expandWildCards: 是否展开通配符
            modifiers: 键盘修饰键
            
        Returns:
            bytes: 字符序列
            
        对应C++: QByteArray Entry::text(bool expandWildCards, Qt::KeyboardModifiers modifiers) const
        """
        expandedText = bytearray(self._text)
        
        if expandWildCards:
            # 修正修饰符值计算逻辑，与C++保持一致
            modifierValue = 1
            modifierValue += oneOrZero(bool(modifiers & Qt.KeyboardModifier.ShiftModifier))
            modifierValue += oneOrZero(bool(modifiers & Qt.KeyboardModifier.AltModifier)) << 1
            modifierValue += oneOrZero(bool(modifiers & CTRL_MOD)) << 2
            
            for i in range(len(expandedText)):
                if expandedText[i] == ord('*'):
                    expandedText[i] = ord('0') + modifierValue
        
        return bytes(expandedText)
    
    def setText(self, text: bytes):
        """
        设置与此条目关联的字符序列。
        对应C++: void Entry::setText(const QByteArray& text)
        """
        self._text = self._unescape(text)
    
    def keyCode(self) -> int:
        """
        返回与此条目关联的键码。
        对应C++: int Entry::keyCode() const
        """
        return self._key_code
    
    def setKeyCode(self, keyCode: int):
        """
        设置与此条目关联的键码。
        对应C++: void Entry::setKeyCode(int keyCode)
        """
        self._key_code = keyCode
    
    def modifiers(self) -> Qt.KeyboardModifiers:
        """
        返回启用的键盘修饰键。
        对应C++: Qt::KeyboardModifiers Entry::modifiers() const
        """
        return self._modifiers
    
    def modifierMask(self) -> Qt.KeyboardModifiers:
        """
        返回有效的键盘修饰键掩码。
        对应C++: Qt::KeyboardModifiers Entry::modifierMask() const
        """
        return self._modifier_mask
    
    def setModifiers(self, modifiers: Qt.KeyboardModifiers):
        """
        设置键盘修饰键。
        对应C++: void Entry::setModifiers(Qt::KeyboardModifiers modifiers)
        """
        self._modifiers = modifiers
    
    def setModifierMask(self, mask: Qt.KeyboardModifiers):
        """
        设置键盘修饰键掩码。
        对应C++: void Entry::setModifierMask(Qt::KeyboardModifiers modifiers)
        """
        self._modifier_mask = mask
    
    def state(self) -> KeyboardTranslatorState:
        """
        返回启用的状态标志。
        对应C++: States Entry::state() const
        """
        return self._state
    
    def stateMask(self) -> KeyboardTranslatorState:
        """
        返回有效的状态标志掩码。
        对应C++: States Entry::stateMask() const
        """
        return self._state_mask
    
    def setState(self, state: KeyboardTranslatorState):
        """
        设置状态标志。
        对应C++: void Entry::setState(States state)
        """
        self._state = state
    
    def setStateMask(self, mask: KeyboardTranslatorState):
        """
        设置状态标志掩码。
        对应C++: void Entry::setStateMask(States mask)
        """
        self._state_mask = mask
    
    def matches(self, key_code: int, modifiers: Qt.KeyboardModifiers, 
                test_state: KeyboardTranslatorState) -> bool:
        """
        检查此条目是否匹配给定的键序列。
        
        Args:
            key_code: 键码
            modifiers: 修饰键
            test_state: 测试状态
            
        Returns:
            bool: 是否匹配
            
        对应C++: bool Entry::matches(int keyCode, Qt::KeyboardModifiers modifiers, States testState) const
        """
        # 在Mac上，箭头键被认为是键盘的一部分，忽略这一点
        if sys.platform == "darwin":
            modifiers &= ~Qt.KeyboardModifier.KeypadModifier
        
        if self._key_code != key_code:
            return False
        
        if (modifiers & self._modifier_mask) != (self._modifiers & self._modifier_mask):
            return False
        
        # 如果修饰键非零，隐含"任意修饰键"状态
        if (modifiers & ~Qt.KeyboardModifier.KeypadModifier) != Qt.KeyboardModifier.NoModifier:
            test_state |= KeyboardTranslatorState.AnyModifierState
        
        if (test_state & self._state_mask) != (self._state & self._state_mask):
            return False
        
        # 特殊处理"任意修饰键"状态
        any_modifiers_set = (modifiers != Qt.KeyboardModifier.NoModifier and 
                            modifiers != Qt.KeyboardModifier.KeypadModifier)
        want_any_modifier = bool(self._state & KeyboardTranslatorState.AnyModifierState)
        
        if self._state_mask & KeyboardTranslatorState.AnyModifierState:
            if want_any_modifier != any_modifiers_set:
                return False
        
        return True
    
    def escapedText(self, expandWildCards: bool = False,
                    modifiers: Qt.KeyboardModifiers = Qt.KeyboardModifier.NoModifier) -> bytes:
        """
        返回转义后的文本。
        
        Args:
            expandWildCards: 是否展开通配符
            modifiers: 修饰键
            
        Returns:
            bytes: 转义后的文本
            
        对应C++: QByteArray Entry::escapedText(bool expandWildCards, Qt::KeyboardModifiers modifiers) const
        """
        result = bytearray(self.text(expandWildCards, modifiers))
        
        i = 0
        while i < len(result):
            ch = result[i]
            replacement = None
            
            if ch == 27:    # ESC
                replacement = b'\\E'
            elif ch == 8:   # Backspace
                replacement = b'\\b'
            elif ch == 12:  # Form Feed
                replacement = b'\\f'
            elif ch == 9:   # Tab
                replacement = b'\\t'
            elif ch == 13:  # Carriage Return
                replacement = b'\\r'
            elif ch == 10:  # Line Feed
                replacement = b'\\n'
            elif not chr(ch).isprintable():
                # 不可打印字符用\xhh表示
                replacement = f'\\x{ch:02x}'.encode('ascii')
            
            if replacement:
                result[i:i+1] = replacement
                i += len(replacement)
            else:
                i += 1
        
        return bytes(result)
    
    def _unescape(self, input_bytes: bytes) -> bytes:
        """
        解转义字节序列。
        
        Args:
            input_bytes: 输入字节序列
            
        Returns:
            bytes: 解转义后的字节序列
            
        对应C++: QByteArray Entry::unescape(const QByteArray& input) const
        """
        result = bytearray(input_bytes)
        
        i = 0
        while i < len(result) - 1:
            if result[i] == ord('\\'):
                replacement = None
                chars_to_remove = 2
                escaped_char = True
                
                next_char = chr(result[i + 1])
                if next_char == 'E':
                    replacement = [27]  # ESC
                elif next_char == 'b':
                    replacement = [8]   # Backspace
                elif next_char == 'f':
                    replacement = [12]  # Form Feed
                elif next_char == 't':
                    replacement = [9]   # Tab
                elif next_char == 'r':
                    replacement = [13]  # Carriage Return
                elif next_char == 'n':
                    replacement = [10]  # Line Feed
                elif next_char == 'x':
                    # 十六进制转义序列 \xhh
                    hex_digits = ""
                    if (i + 2 < len(result) and 
                        chr(result[i + 2]) in '0123456789abcdefABCDEF'):
                        hex_digits += chr(result[i + 2])
                    if (i + 3 < len(result) and 
                        chr(result[i + 3]) in '0123456789abcdefABCDEF'):
                        hex_digits += chr(result[i + 3])
                    
                    if hex_digits:
                        try:
                            char_value = int(hex_digits, 16)
                            replacement = [char_value]
                            chars_to_remove = 2 + len(hex_digits)
                        except ValueError:
                            escaped_char = False
                    else:
                        escaped_char = False
                else:
                    escaped_char = False
                
                if escaped_char and replacement is not None:
                    result[i:i + chars_to_remove] = replacement
                    i += len(replacement)
                else:
                    i += 1
            else:
                i += 1
        
        return bytes(result)
    
    def _insertModifier(self, item: str, modifier: Qt.KeyboardModifier) -> str:
        """
        插入修饰键字符串。
        对应C++: void Entry::insertModifier(QString& item, int modifier) const
        """
        if not (modifier & self._modifier_mask):
            return item
        
        if modifier & self._modifiers:
            item += "+"
        else:
            item += "-"
        
        if modifier == Qt.KeyboardModifier.ShiftModifier:
            item += "Shift"
        elif modifier == Qt.KeyboardModifier.ControlModifier:
            item += "Ctrl"
        elif modifier == Qt.KeyboardModifier.AltModifier:
            item += "Alt"
        elif modifier == Qt.KeyboardModifier.MetaModifier:
            item += "Meta"
        elif modifier == Qt.KeyboardModifier.KeypadModifier:
            item += "KeyPad"
        
        return item
    
    def _insertState(self, item: str, state: KeyboardTranslatorState) -> str:
        """
        插入状态字符串。
        对应C++: void Entry::insertState(QString& item, int state) const
        """
        if not (state & self._state_mask):
            return item
        
        if state & self._state:
            item += "+"
        else:
            item += "-"
        
        if state == KeyboardTranslatorState.AlternateScreenState:
            item += "AppScreen"
        elif state == KeyboardTranslatorState.NewLineState:
            item += "NewLine"
        elif state == KeyboardTranslatorState.AnsiState:
            item += "Ansi"
        elif state == KeyboardTranslatorState.CursorKeysState:
            item += "AppCursorKeys"
        elif state == KeyboardTranslatorState.AnyModifierState:
            item += "AnyModifier"
        elif state == KeyboardTranslatorState.ApplicationKeypadState:
            item += "AppKeypad"
        
        return item
    
    def conditionToString(self) -> str:
        """
        将条件转换为字符串。
        对应C++: QString Entry::conditionToString() const
        """
        result = QKeySequence(self._key_code).toString()
        
        result = self._insertModifier(result, Qt.KeyboardModifier.ShiftModifier)
        result = self._insertModifier(result, Qt.KeyboardModifier.ControlModifier)
        result = self._insertModifier(result, Qt.KeyboardModifier.AltModifier)
        result = self._insertModifier(result, Qt.KeyboardModifier.MetaModifier)
        result = self._insertModifier(result, Qt.KeyboardModifier.KeypadModifier)
        
        result = self._insertState(result, KeyboardTranslatorState.AlternateScreenState)
        result = self._insertState(result, KeyboardTranslatorState.NewLineState)
        result = self._insertState(result, KeyboardTranslatorState.AnsiState)
        result = self._insertState(result, KeyboardTranslatorState.CursorKeysState)
        result = self._insertState(result, KeyboardTranslatorState.AnyModifierState)
        result = self._insertState(result, KeyboardTranslatorState.ApplicationKeypadState)
        
        return result
    
    def resultToString(self, expandWildCards: bool = False,
                        modifiers: Qt.KeyboardModifiers = Qt.KeyboardModifier.NoModifier) -> str:
        """
        将结果转换为字符串。
        
        Args:
            expandWildCards: 是否展开通配符
            modifiers: 修饰键
            
        Returns:
            str: 结果字符串
            
        对应C++: QString Entry::resultToString(bool expandWildCards, Qt::KeyboardModifiers modifiers) const
        """
        if self._text:
            return self.escapedText(expandWildCards, modifiers).decode('latin-1')
        elif self._command == KeyboardTranslatorCommand.EraseCommand:
            return "Erase"
        elif self._command == KeyboardTranslatorCommand.ScrollPageUpCommand:
            return "ScrollPageUp"
        elif self._command == KeyboardTranslatorCommand.ScrollPageDownCommand:
            return "ScrollPageDown"
        elif self._command == KeyboardTranslatorCommand.ScrollLineUpCommand:
            return "ScrollLineUp"
        elif self._command == KeyboardTranslatorCommand.ScrollLineDownCommand:
            return "ScrollLineDown"
        elif self._command == KeyboardTranslatorCommand.ScrollLockCommand:
            return "ScrollLock"
        elif self._command == KeyboardTranslatorCommand.ScrollUpToTopCommand:
            return "ScrollUpToTop"
        elif self._command == KeyboardTranslatorCommand.ScrollDownToBottomCommand:
            return "ScrollDownToBottom"
        
        return ""
    
    def __eq__(self, other) -> bool:
        """
        比较两个条目是否相等。
        对应C++: bool Entry::operator==(const Entry& rhs) const
        """
        if not isinstance(other, KeyboardTranslatorEntry):
            return False
        
        return (self._key_code == other._key_code and
                self._modifiers == other._modifiers and
                self._modifier_mask == other._modifier_mask and
                self._state == other._state and
                self._state_mask == other._state_mask and
                self._command == other._command and
                self._text == other._text)


class KeyboardTranslator:
    """
    键盘翻译器主类。
    对应C++: class KeyboardTranslator
    """
    
    def __init__(self, name: str):
        """
        构造函数。
        
        Args:
            name: 翻译器名称
            
        对应C++: KeyboardTranslator::KeyboardTranslator(const QString& name)
        """
        self._name = name
        self._description = ""
        self._entries: Dict[int, List[KeyboardTranslatorEntry]] = {}
    
    def name(self) -> str:
        """
        返回翻译器名称。
        对应C++: QString KeyboardTranslator::name() const
        """
        return self._name
    
    def setName(self, name: str):
        """
        设置翻译器名称。
        对应C++: void KeyboardTranslator::setName(const QString& name)
        """
        self._name = name
    
    def description(self) -> str:
        """
        返回翻译器描述。
        对应C++: QString KeyboardTranslator::description() const
        """
        return self._description
    
    def setDescription(self, description: str):
        """
        设置翻译器描述。
        对应C++: void KeyboardTranslator::setDescription(const QString& description)
        """
        self._description = description
    
    def findEntry(self, keyCode: int, modifiers: Qt.KeyboardModifiers,
                  state: KeyboardTranslatorState = KeyboardTranslatorState.NoState) -> KeyboardTranslatorEntry:
        """
        查找匹配的条目。
        
        Args:
            keyCode: 键码
            modifiers: 修饰键
            state: 状态
            
        Returns:
            KeyboardTranslatorEntry: 匹配的条目，如果未找到则返回空条目
            
        对应C++: Entry KeyboardTranslator::findEntry(int keyCode, Qt::KeyboardModifiers modifiers, States state) const
        """
        if keyCode in self._entries:
            for entry in self._entries[keyCode]:
                if entry.matches(keyCode, modifiers, state):
                    return entry
        
        return KeyboardTranslatorEntry()  # 返回空条目
    
    def addEntry(self, entry: KeyboardTranslatorEntry):
        """
        添加条目。
        
        Args:
            entry: 要添加的条目
            
        对应C++: void KeyboardTranslator::addEntry(const Entry& entry)
        """
        keyCode = entry.keyCode()
        if keyCode not in self._entries:
            self._entries[keyCode] = []
        self._entries[keyCode].append(entry)
    
    def replaceEntry(self, existing: KeyboardTranslatorEntry, replacement: KeyboardTranslatorEntry):
        """
        替换条目。
        
        Args:
            existing: 现有条目
            replacement: 替换条目
            
        对应C++: void KeyboardTranslator::replaceEntry(const Entry& existing, const Entry& replacement)
        """
        if not existing.isNull():
            self.removeEntry(existing)
        self.addEntry(replacement)
    
    def removeEntry(self, entry: KeyboardTranslatorEntry):
        """
        移除条目。
        
        Args:
            entry: 要移除的条目
            
        对应C++: void KeyboardTranslator::removeEntry(const Entry& entry)
        """
        keyCode = entry.keyCode()
        if keyCode in self._entries:
            try:
                self._entries[keyCode].remove(entry)
                if not self._entries[keyCode]:  # 如果列表为空则删除键
                    del self._entries[keyCode]
            except ValueError:
                pass  # 条目不存在
    
    def entries(self) -> List[KeyboardTranslatorEntry]:
        """
        返回所有条目列表。
        对应C++: QList<Entry> KeyboardTranslator::entries() const
        """
        result = []
        for entryList in self._entries.values():
            result.extend(entryList)
        return result


# 为了兼容性导出类型别名
States = KeyboardTranslatorState
Commands = KeyboardTranslatorCommand
Entry = KeyboardTranslatorEntry 


class KeyboardTranslatorToken:
    """
    键盘翻译器解析标记。
    对应C++: KeyboardTranslatorReader::Token struct
    """
    
    class Type(IntEnum):
        TitleKeyword = 0
        TitleText = 1
        KeyKeyword = 2
        KeySequence = 3
        Command = 4
        OutputText = 5
    
    def __init__(self, token_type: Type, text: str = ""):
        self.type = token_type
        self.text = text


class KeyboardTranslatorReader:
    """
    键盘翻译器文件解析器。
    对应C++: class KeyboardTranslatorReader
    """
    
    def __init__(self, source: Union[QIODevice, TextIO, str]):
        """
        构造函数。
        
        Args:
            source: 数据源（QIODevice、文件对象或字符串）
            
        对应C++: KeyboardTranslatorReader::KeyboardTranslatorReader(QIODevice* source)
        """
        self._source = source
        self._description = ""
        self._hasNext = False
        self._nextEntry = KeyboardTranslatorEntry()
        
        # 如果是字符串，将其转换为行列表
        if isinstance(source, str):
            self._lines = source.split('\n')
            self._lineIndex = 0
        else:
            self._lines = None
            self._lineIndex = 0
        
        # 读取描述
        self._readDescription()
        # 读取第一个条目
        self._readNext()
    
    def _readLine(self) -> Optional[str]:
        """读取下一行"""
        if self._lines is not None:
            # 从字符串列表读取
            if self._lineIndex < len(self._lines):
                line = self._lines[self._lineIndex]
                self._lineIndex += 1
                return line
            return None
        else:
            # 从文件对象读取
            if hasattr(self._source, 'readLine'):
                # QIODevice
                line = self._source.readLine()
                if line:
                    return line.data().decode('utf-8')
                return None
            elif hasattr(self._source, 'readline'):
                # Python文件对象
                line = self._source.readline()
                return line.rstrip('\n\r') if line else None
            return None
    
    def _atEnd(self) -> bool:
        """检查是否到达文件末尾"""
        if self._lines is not None:
            return self._lineIndex >= len(self._lines)
        elif hasattr(self._source, 'atEnd'):
            return self._source.atEnd()
        elif hasattr(self._source, 'readable'):
            return not self._source.readable()
        return True
    
    def _readDescription(self):
        """读取描述信息"""
        while self._description == "" and not self._atEnd():
            line = self._readLine()
            if line is None:
                break
            
            tokens = self._tokenize(line)
            if tokens and tokens[0].type == KeyboardTranslatorToken.Type.TitleKeyword:
                if len(tokens) > 1:
                    self._description = tokens[1].text
    
    def description(self) -> str:
        """
        返回描述文本。
        对应C++: QString KeyboardTranslatorReader::description() const
        """
        return self._description
    
    def hasNextEntry(self) -> bool:
        """
        返回是否还有下一个条目。
        对应C++: bool KeyboardTranslatorReader::hasNextEntry() const
        """
        return self._hasNext
    
    def nextEntry(self) -> KeyboardTranslatorEntry:
        """
        返回下一个条目。
        对应C++: Entry KeyboardTranslatorReader::nextEntry()
        """
        if not self._hasNext:
            return KeyboardTranslatorEntry()
        
        entry = self._nextEntry
        self._readNext()
        return entry
    
    def _readNext(self):
        """读取下一个条目"""
        while not self._atEnd():
            line = self._readLine()
            if line is None:
                break
            
            tokens = self._tokenize(line)
            if tokens and tokens[0].type == KeyboardTranslatorToken.Type.KeyKeyword:
                if len(tokens) >= 3:
                    # 解析键序列
                    flags = KeyboardTranslatorState.NoState
                    flagMask = KeyboardTranslatorState.NoState
                    modifiers = Qt.KeyboardModifier.NoModifier
                    modifierMask = Qt.KeyboardModifier.NoModifier
                    keyCode = Qt.Key.Key_unknown
                    
                    result = self._decodeSequence(
                        tokens[1].text.lower(),
                        keyCode, modifiers, modifierMask, flags, flagMask
                    )
                    
                    if result[0]:  # success
                        success, keyCode, modifiers, modifierMask, flags, flagMask = result
                        command = KeyboardTranslatorCommand.NoCommand
                        text = b""
                        
                        # 获取文本或命令
                        if tokens[2].type == KeyboardTranslatorToken.Type.OutputText:
                            text = tokens[2].text.encode('latin-1')
                        elif tokens[2].type == KeyboardTranslatorToken.Type.Command:
                            command = self._parseAsCommand(tokens[2].text)
                        
                        # 创建新条目
                        newEntry = KeyboardTranslatorEntry()
                        newEntry.setKeyCode(keyCode)
                        newEntry.setState(flags)
                        newEntry.setStateMask(flagMask)
                        newEntry.setModifiers(modifiers)
                        newEntry.setModifierMask(modifierMask)
                        newEntry.setText(text)
                        newEntry.setCommand(command)
                        
                        self._nextEntry = newEntry
                        self._hasNext = True
                        return
        
        self._hasNext = False
    
    def _tokenize(self, line: str) -> List[KeyboardTranslatorToken]:
        """
        解析一行文本为标记。
        对应C++: QList<Token> KeyboardTranslatorReader::tokenize(const QString& line)
        """
        text = line.strip()
        
        # 移除注释
        inQuotes = False
        commentPos = -1
        for i in range(len(text) - 1, -1, -1):
            ch = text[i]
            if ch == '"':
                inQuotes = not inQuotes
            elif ch == '#' and not inQuotes:
                commentPos = i
                break
        
        if commentPos != -1:
            text = text[:commentPos]
        
        text = text.strip()
        
        if not text:
            return []
        
        # 使用正则表达式解析
        titlePattern = r'keyboard\s+"([^"]*)"'
        keyPattern = r'key\s+([\w\+\s\-\*\.]+)\s*:\s*("([^"]*)"|(\w+))'
        
        titleMatch = re.search(titlePattern, text, re.IGNORECASE)
        keyMatch = re.search(keyPattern, text, re.IGNORECASE)
        
        tokens = []
        
        if titleMatch:
            tokens.append(KeyboardTranslatorToken(KeyboardTranslatorToken.Type.TitleKeyword))
            tokens.append(KeyboardTranslatorToken(KeyboardTranslatorToken.Type.TitleText, titleMatch.group(1)))
        elif keyMatch:
            tokens.append(KeyboardTranslatorToken(KeyboardTranslatorToken.Type.KeyKeyword))
            tokens.append(KeyboardTranslatorToken(KeyboardTranslatorToken.Type.KeySequence, 
                                                 keyMatch.group(1).replace(' ', '')))
            
            if keyMatch.group(3):  # 引号内的文本
                tokens.append(KeyboardTranslatorToken(KeyboardTranslatorToken.Type.OutputText, keyMatch.group(3)))
            elif keyMatch.group(4):  # 命令
                tokens.append(KeyboardTranslatorToken(KeyboardTranslatorToken.Type.Command, keyMatch.group(4)))
        
        return tokens
    
    def _decodeSequence(self, text: str, keyCode: int, modifiers: Qt.KeyboardModifiers,
                        modifierMask: Qt.KeyboardModifiers, flags: KeyboardTranslatorState,
                        flagMask: KeyboardTranslatorState) -> tuple:
        """
        解码键序列。
        对应C++: bool KeyboardTranslatorReader::decodeSequence(...)
        
        Returns:
            tuple: (success, key_code, modifiers, modifier_mask, flags, flag_mask)
        """
        isWanted = True
        buffer = ""
        
        tempModifiers = modifiers
        tempModifierMask = modifierMask
        tempFlags = flags
        tempFlagMask = flagMask
        tempKeyCode = keyCode
        
        i = 0
        while i < len(text):
            ch = text[i]
            isFirstLetter = (i == 0)
            isLastLetter = (i == len(text) - 1)
            endOfItem = True
            
            if ch.isalnum():
                endOfItem = False
                buffer += ch
            elif isFirstLetter:
                buffer += ch
            
            if (endOfItem or isLastLetter) and buffer:
                itemModifier = Qt.KeyboardModifier.NoModifier
                itemKeyCode = 0
                itemFlag = KeyboardTranslatorState.NoState
                
                # 尝试解析为修饰键
                success, itemModifier = self._parseAsModifier(buffer)
                if success:
                    tempModifierMask |= itemModifier
                    if isWanted:
                        tempModifiers |= itemModifier
                else:
                    # 尝试解析为状态标志
                    success, itemFlag = self._parseAsStateFlag(buffer)
                    if success:
                        tempFlagMask |= itemFlag
                        if isWanted:
                            tempFlags |= itemFlag
                    else:
                        # 尝试解析为键码
                        success, itemKeyCode = self._parseAsKeyCode(buffer)
                        if success:
                            tempKeyCode = itemKeyCode
                        else:
                            # 无法解析的项目，记录调试信息
                            from .tools import qtermwidget_logger
                            qtermwidget_logger.debug(f"Unable to parse key binding item: {buffer}")
                
                buffer = ""
            
            # 检查是否为需要/不需要的标志
            if ch == '+':
                isWanted = True
            elif ch == '-':
                isWanted = False
            
            i += 1
        
        # 返回解析的值
        return (True, tempKeyCode, tempModifiers, tempModifierMask, tempFlags, tempFlagMask)
    
    @staticmethod
    def _parseAsModifier(item: str) -> tuple:
        """
        解析修饰键。
        对应C++: bool KeyboardTranslatorReader::parseAsModifier(...)
        
        Returns:
            tuple: (success, modifier)
        """
        itemLower = item.lower()
        if itemLower == "shift":
            return (True, Qt.KeyboardModifier.ShiftModifier)
        elif itemLower in ("ctrl", "control"):
            return (True, Qt.KeyboardModifier.ControlModifier)
        elif itemLower == "alt":
            return (True, Qt.KeyboardModifier.AltModifier)
        elif itemLower == "meta":
            return (True, Qt.KeyboardModifier.MetaModifier)
        elif itemLower == "keypad":
            return (True, Qt.KeyboardModifier.KeypadModifier)
        else:
            return (False, Qt.KeyboardModifier.NoModifier)
    
    @staticmethod
    def _parseAsStateFlag(item: str) -> tuple:
        """
        解析状态标志。
        对应C++: bool KeyboardTranslatorReader::parseAsStateFlag(...)
        
        Returns:
            tuple: (success, flag)
        """
        itemLower = item.lower()
        if itemLower in ("appcukeys", "appcursorkeys"):
            return (True, KeyboardTranslatorState.CursorKeysState)
        elif itemLower == "ansi":
            return (True, KeyboardTranslatorState.AnsiState)
        elif itemLower == "newline":
            return (True, KeyboardTranslatorState.NewLineState)
        elif itemLower == "appscreen":
            return (True, KeyboardTranslatorState.AlternateScreenState)
        elif itemLower in ("anymod", "anymodifier"):
            return (True, KeyboardTranslatorState.AnyModifierState)
        elif itemLower == "appkeypad":
            return (True, KeyboardTranslatorState.ApplicationKeypadState)
        else:
            return (False, KeyboardTranslatorState.NoState)
    
    @staticmethod
    def _parseAsKeyCode(item: str) -> tuple:
        """
        解析键码。
        对应C++: bool KeyboardTranslatorReader::parseAsKeyCode(...)
        
        Returns:
            tuple: (success, key_code)
        """
        # 向后兼容性处理 - 优先检查特殊键名
        itemLower = item.lower()
        if itemLower == "prior":
            return (True, Qt.Key.Key_PageUp)
        elif itemLower == "next":
            return (True, Qt.Key.Key_PageDown)
        elif itemLower == "tab":
            return (True, Qt.Key.Key_Tab)
        elif itemLower == "return":
            return (True, Qt.Key.Key_Return)
        elif itemLower == "enter":
            return (True, Qt.Key.Key_Enter)
        elif itemLower == "escape":
            return (True, Qt.Key.Key_Escape)
        elif itemLower == "space":
            return (True, Qt.Key.Key_Space)
        elif itemLower == "up":
            return (True, Qt.Key.Key_Up)
        elif itemLower == "down":
            return (True, Qt.Key.Key_Down)
        elif itemLower == "left":
            return (True, Qt.Key.Key_Left)
        elif itemLower == "right":
            return (True, Qt.Key.Key_Right)
        elif itemLower == "insert":
            return (True, Qt.Key.Key_Insert)
        elif itemLower == "delete":
            return (True, Qt.Key.Key_Delete)
        elif itemLower == "home":
            return (True, Qt.Key.Key_Home)
        elif itemLower == "end":
            return (True, Qt.Key.Key_End)
        elif itemLower == "pageup":
            return (True, Qt.Key.Key_PageUp)
        elif itemLower == "pagedown":
            return (True, Qt.Key.Key_PageDown)
        elif itemLower == "backspace":
            return (True, Qt.Key.Key_Backspace)
        elif itemLower == "backtab":
            return (True, Qt.Key.Key_Backtab)
        
        # 功能键处理
        if itemLower.startswith('f') and len(itemLower) > 1:
            try:
                funcNum = int(itemLower[1:])
                if 1 <= funcNum <= 35:  # Qt supports F1-F35
                    return (True, getattr(Qt.Key, f'Key_F{funcNum}'))
            except ValueError:
                pass
        
        # 数字键处理 
        if itemLower.isdigit() and len(itemLower) == 1:
            return (True, getattr(Qt.Key, f'Key_{itemLower}'))
        
        # 字母键处理
        if len(itemLower) == 1 and itemLower.isalpha():
            return (True, getattr(Qt.Key, f'Key_{itemLower.upper()}'))
        
        # 尝试使用QKeySequence解析
        try:
            sequence = QKeySequence.fromString(item)
            if not sequence.isEmpty():
                if sequence.count() > 0:
                    # 提取键码部分，去除修饰键
                    combined = sequence[0].toCombined()
                    keyCode = combined & ~Qt.KeyboardModifier.ModifierMask.value
                    return (True, keyCode)
        except Exception:
            pass
        
        # 尝试大写版本
        try:
            sequence = QKeySequence.fromString(item.title())
            if not sequence.isEmpty():
                if sequence.count() > 0:
                    combined = sequence[0].toCombined()
                    keyCode = combined & ~Qt.KeyboardModifier.ModifierMask.value
                    return (True, keyCode)
        except Exception:
            pass
        
        return (False, Qt.Key.Key_unknown)
    
    @staticmethod
    def _parseAsCommand(text: str) -> KeyboardTranslatorCommand:
        """
        解析命令。
        对应C++: bool KeyboardTranslatorReader::parseAsCommand(...)
        """
        textLower = text.lower()
        
        if textLower == "erase":
            return KeyboardTranslatorCommand.EraseCommand
        elif textLower == "scrollpageup":
            return KeyboardTranslatorCommand.ScrollPageUpCommand
        elif textLower == "scrollpagedown":
            return KeyboardTranslatorCommand.ScrollPageDownCommand
        elif textLower == "scrolllineup":
            return KeyboardTranslatorCommand.ScrollLineUpCommand
        elif textLower == "scrolllinedown":
            return KeyboardTranslatorCommand.ScrollLineDownCommand
        elif textLower == "scrolllock":
            return KeyboardTranslatorCommand.ScrollLockCommand
        elif textLower == "scrolluptotop":
            return KeyboardTranslatorCommand.ScrollUpToTopCommand
        elif textLower == "scrolldowntobottom":
            return KeyboardTranslatorCommand.ScrollDownToBottomCommand
        
        return KeyboardTranslatorCommand.NoCommand
    
    def parseError(self) -> bool:
        """
        返回是否有解析错误。
        对应C++: bool KeyboardTranslatorReader::parseError()
        """
        # TODO: 实现真正的错误检测
        return False
    
    @staticmethod
    def createEntry(condition: str, result: str) -> KeyboardTranslatorEntry:
        """
        创建条目。
        对应C++: Entry KeyboardTranslatorReader::createEntry(...)
        """
        entryString = f'keyboard "temporary"\nkey {condition} : '
        
        # 检查结果是否为命令
        command = KeyboardTranslatorReader._parseAsCommand(result)
        if command != KeyboardTranslatorCommand.NoCommand:
            entryString += result
        else:
            entryString += f'"{result}"'
        
        reader = KeyboardTranslatorReader(entryString)
        
        if reader.hasNextEntry():
            return reader.nextEntry()
        
        return KeyboardTranslatorEntry()


class KeyboardTranslatorWriter:
    """
    键盘翻译器文件写入器。
    对应C++: class KeyboardTranslatorWriter
    """
    
    def __init__(self, destination: Union[QIODevice, TextIO]):
        """
        构造函数。
        
        Args:
            destination: 输出目标
            
        对应C++: KeyboardTranslatorWriter::KeyboardTranslatorWriter(QIODevice* destination)
        """
        self._destination = destination
        
        if hasattr(destination, 'isWritable') and destination.isWritable():
            self._writer = QTextStream(destination)
        else:
            self._writer = destination
    
    def writeHeader(self, description: str):
        """
        写入头部信息。
        
        Args:
            description: 描述
            
        对应C++: void KeyboardTranslatorWriter::writeHeader(const QString& description)
        """
        if hasattr(self._writer, 'writeString'):
            self._writer.writeString(f'keyboard "{description}"\n')
        else:
            self._writer.write(f'keyboard "{description}"\n')
    
    def writeEntry(self, entry: KeyboardTranslatorEntry):
        """
        写入条目。
        
        Args:
            entry: 要写入的条目
            
        对应C++: void KeyboardTranslatorWriter::writeEntry(const Entry& entry)
        """
        if entry.command() != KeyboardTranslatorCommand.NoCommand:
            result = entry.resultToString()
        else:
            result = f'"{entry.resultToString()}"'
        
        line = f"key {entry.conditionToString()} : {result}\n"
        
        if hasattr(self._writer, 'writeString'):
            self._writer.writeString(line)
        else:
            self._writer.write(line)


class KeyboardTranslatorManager:
    """
    键盘翻译器管理器。
    对应C++: class KeyboardTranslatorManager
    """
    
    # 默认翻译器文本 - 对应C++的defaultTranslatorText
    defaultTranslatorText = (
        'keyboard "Fallback Key Translator"\n'
        'key Tab : "\\t"'
    )
    
    _instance: Optional['KeyboardTranslatorManager'] = None
    
    def __init__(self):
        """
        构造函数。
        对应C++: KeyboardTranslatorManager::KeyboardTranslatorManager()
        """
        # C++风格的成员变量命名
        self._translators: Dict[str, KeyboardTranslator] = {}
        self._haveLoadedAll = False
    
    @classmethod
    def instance(cls) -> 'KeyboardTranslatorManager':
        """
        获取全局实例。
        对应C++: KeyboardTranslatorManager* KeyboardTranslatorManager::instance()
        """
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def findTranslatorPath(self, name: str) -> str:
        """
        查找翻译器文件路径。
        对应C++: QString KeyboardTranslatorManager::findTranslatorPath(const QString& name)
        """
        return os.path.join(get_kb_layout_dir(), f"{name}.keytab")
    
    def findTranslators(self):
        """
        查找可用的翻译器。
        对应C++: void KeyboardTranslatorManager::findTranslators()
        """
        kbDir = get_kb_layout_dir()
        if not os.path.exists(kbDir):
            self._haveLoadedAll = True
            return
        
        try:
            for filename in os.listdir(kbDir):
                if filename.endswith('.keytab'):
                    name = filename[:-7]  # 移除.keytab扩展名
                    if name not in self._translators:
                        self._translators[name] = None
        except OSError:
            pass
        
        self._haveLoadedAll = True
    
    def findTranslator(self, name: str) -> Optional[KeyboardTranslator]:
        """
        查找翻译器。
        
        Args:
            name: 翻译器名称
            
        Returns:
            KeyboardTranslator: 翻译器实例，如果未找到则返回None
            
        对应C++: const KeyboardTranslator* KeyboardTranslatorManager::findTranslator(const QString& name)
        """
        if not name:
            return self.defaultTranslator()
        
        if name in self._translators and self._translators[name] is not None:
            return self._translators[name]
        
        translator = self.loadTranslator(name)
        
        if translator is not None:
            self._translators[name] = translator
        elif name:
            from .tools import qtermwidget_logger
            qtermwidget_logger.debug(f"Unable to load translator {name}")
        
        return translator
    
    def loadTranslator(self, name: str) -> Optional[KeyboardTranslator]:
        """
        加载翻译器。
        对应C++: KeyboardTranslator* KeyboardTranslatorManager::loadTranslator(const QString& name)
        """
        path = self.findTranslatorPath(name)
        
        if not name or not os.path.exists(path):
            return None
        
        try:
            with open(path, 'r', encoding='utf-8') as file:
                return self.loadTranslatorFromDevice(file, name)
        except (IOError, UnicodeDecodeError):
            return None
    
    def loadTranslatorFromDevice(self, source: Union[QIODevice, TextIO, str], 
                                name: str) -> Optional[KeyboardTranslator]:
        """
        从设备加载翻译器。
        对应C++: KeyboardTranslator* KeyboardTranslatorManager::loadTranslator(QIODevice* source, const QString& name)
        """
        translator = KeyboardTranslator(name)
        reader = KeyboardTranslatorReader(source)
        
        translator.setDescription(reader.description())
        
        while reader.hasNextEntry():
            translator.addEntry(reader.nextEntry())
        
        if not reader.parseError():
            return translator
        else:
            return None
    
    def defaultTranslator(self) -> KeyboardTranslator:
        """
        获取默认翻译器。
        对应C++: const KeyboardTranslator* KeyboardTranslatorManager::defaultTranslator()
        """
        # 尝试查找default.keytab文件
        translator = self.findTranslator("default")
        if translator is None:
            # 使用硬编码的默认翻译器
            translator = self.loadTranslatorFromDevice(
                self.defaultTranslatorText, "fallback"
            )
        
        return translator
    
    def saveTranslator(self, translator: KeyboardTranslator) -> bool:
        """
        保存翻译器。
        
        Args:
            translator: 要保存的翻译器
            
        Returns:
            bool: 是否保存成功
            
        对应C++: bool KeyboardTranslatorManager::saveTranslator(const KeyboardTranslator* translator)
        """
        from .tools import qtermwidget_logger
        qtermwidget_logger.debug("KeyboardTranslatorManager::saveTranslator unimplemented")
        return True  # 简化实现，与C++保持一致
    
    def addTranslator(self, translator: KeyboardTranslator):
        """
        添加翻译器。
        
        Args:
            translator: 要添加的翻译器
            
        对应C++: void KeyboardTranslatorManager::addTranslator(KeyboardTranslator* translator)
        """
        self._translators[translator.name()] = translator
        
        if not self.saveTranslator(translator):
            from .tools import qtermwidget_logger
            qtermwidget_logger.debug(f"Unable to save translator {translator.name()} to disk.")
    
    def deleteTranslator(self, name: str) -> bool:
        """
        删除翻译器。
        
        Args:
            name: 翻译器名称
            
        Returns:
            bool: 是否删除成功
            
        对应C++: bool KeyboardTranslatorManager::deleteTranslator(const QString& name)
        """
        if name not in self._translators:
            return False
        
        path = self.findTranslatorPath(name)
        try:
            if os.path.exists(path):
                os.remove(path)
            del self._translators[name]
            return True
        except OSError:
            from .tools import qtermwidget_logger
            qtermwidget_logger.debug(f"Failed to remove translator - {path}")
            return False
    
    def allTranslators(self) -> List[str]:
        """
        获取所有翻译器名称列表。
        
        Returns:
            List[str]: 翻译器名称列表
            
        对应C++: QList<QString> KeyboardTranslatorManager::allTranslators()
        """
        if not self._haveLoadedAll:
            self.findTranslators()
        
        return list(self._translators.keys())


# 导出全局管理器实例函数
def getKeyboardTranslatorManager() -> KeyboardTranslatorManager:
    """获取全局键盘翻译器管理器实例"""
    return KeyboardTranslatorManager.instance() 