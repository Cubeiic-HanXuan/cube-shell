"""
TerminalCharacterDecoder模块 - 从Konsole转换而来

原始文件：
- TerminalCharacterDecoder.h  
- TerminalCharacterDecoder.cpp

版权信息：
Copyright 2006-2008 by Robert Knight <robertknight@gmail.com>

转换为Python PySide6版本
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from PySide6.QtCore import QTextStream

from qtermwidget.character import (
    ExtendedCharTable,
    LineProperty, DEFAULT_RENDITION, RE_EXTENDED_CHAR, RE_BOLD,
    RE_UNDERLINE
)
from qtermwidget.character_color import (
    CharacterColor, ColorEntry, base_color_table
)
from qtermwidget.wcwidth import konsole_wcwidth, string_width


class TerminalCharacterDecoder(ABC):
    """
    终端字符解码器基类。
    
    解码器将由unicode字符、前景色和背景色以及其他外观相关属性组成的
    终端字符行转换为文本字符串。
    
    派生类可以生成没有其他颜色或外观信息的纯文本，或者
    生成包含这些附加属性的文本。
    
    对应C++: class TerminalCharacterDecoder
    """
    
    def __init__(self):
        """构造函数 - 对应C++: TerminalCharacterDecoder()"""
        pass
    
    def __del__(self):
        """析构函数 - 对应C++: virtual ~TerminalCharacterDecoder()"""
        pass
    
    @abstractmethod
    def begin(self, output: QTextStream):
        """
        开始解码字符。结果文本将追加到output中。
        
        Args:
            output: 输出流
            
        对应C++: virtual void begin(QTextStream* output) = 0
        """
        pass
    
    @abstractmethod
    def end(self):
        """
        结束解码。
        
        对应C++: virtual void end() = 0
        """
        pass
    
    @abstractmethod
    def decodeLine(self, characters, count: int, properties: LineProperty):
        """
        将具有关联属性的终端字符行转换为文本字符串，
        并将字符串写入输出QTextStream。
        
        Args:
            characters: 字符数组 (const Character* const)
            count: 字符数量
            properties: 影响该行所有字符的附加属性
            
        对应C++: virtual void decodeLine(const Character* const characters,
                                        int count, LineProperty properties) = 0
        """
        pass


class PlainTextDecoder(TerminalCharacterDecoder):
    """
    生成纯文本的终端字符解码器，忽略原始字符的颜色和其他外观相关属性。
    
    对应C++: class PlainTextDecoder : public TerminalCharacterDecoder
    """
    
    def __init__(self):
        """
        构造函数。
        
        对应C++: PlainTextDecoder::PlainTextDecoder()
        """
        super().__init__()
        self._output: Optional[QTextStream] = None  # 对应C++: QTextStream* _output
        self._includeTrailingWhitespace: bool = True  # 对应C++: bool _includeTrailingWhitespace
        self._recordLinePositions: bool = False  # 对应C++: bool _recordLinePositions
        self._linePositions: List[int] = []  # 对应C++: QList<int> _linePositions
    
    def setTrailingWhitespace(self, enable: bool):
        """
        设置是否在输出中包含行尾的尾随空白。
        默认为True。
        
        Args:
            enable: 是否启用尾随空白
            
        对应C++: void setTrailingWhitespace(bool enable)
        """
        self._includeTrailingWhitespace = enable
    
    def trailingWhitespace(self) -> bool:
        """
        返回输出中是否包含行尾的尾随空白。
        
        Returns:
            bool: 是否包含尾随空白
            
        对应C++: bool trailingWhitespace() const
        """
        return self._includeTrailingWhitespace
    
    def linePositions(self) -> List[int]:
        """
        返回输出流中添加新行的字符位置。
        如果setRecordLinePositions()为False或输出设备不是字符串，则返回空列表。
        
        Returns:
            List[int]: 行位置列表
            
        对应C++: QList<int> linePositions() const
        """
        return self._linePositions.copy()
    
    def setRecordLinePositions(self, record: bool):
        """
        启用记录添加新行的字符位置。参见linePositions()。
        
        Args:
            record: 是否记录行位置
            
        对应C++: void setRecordLinePositions(bool record)
        """
        self._recordLinePositions = record
    
    def begin(self, output: QTextStream):
        """
        开始解码字符。
        
        Args:
            output: 输出流
            
        对应C++: void begin(QTextStream* output) override
        """
        self._output = output
        if self._linePositions:
            self._linePositions.clear()
    
    def end(self):
        """
        结束解码。
        
        对应C++: void end() override
        """
        self._output = None
    
    def decodeLine(self, characters, count: int, properties: LineProperty):
        """
        解码一行字符。
        
        Args:
            characters: 字符数组 (const Character* const)
            count: 字符数量
            properties: 行属性（未使用）
            
        对应C++: void decodeLine(const Character* const characters,
                                int count, LineProperty /*properties*/) override
        """
        assert self._output is not None, "Q_ASSERT( _output )"
        
        if self._recordLinePositions and hasattr(self._output, 'string') and self._output.string():
            pos = len(self._output.string())
            self._linePositions.append(pos)
        
        if characters is None:
            return
        
        plainText = []
        plainText_reserve = count
        
        outputCount = count
        
        if not self._includeTrailingWhitespace:
            for i in range(count - 1, -1, -1):
                if not characters[i].isSpace():
                    break
                else:
                    outputCount -= 1
        
        i = 0
        while i < outputCount:
            if characters[i].rendition & RE_EXTENDED_CHAR:
                extendedCharLength = 0
                chars = ExtendedCharTable.instance.lookupExtendedChar(
                    characters[i].character, extendedCharLength
                )
                if chars:
                    char_str = ""
                    for nchar in range(extendedCharLength):
                        char_str += chr(chars[nchar])
                    plainText.append(char_str)
                    i += max(1, string_width(char_str))
                else:
                    i += 1
            else:
                plainText.append(chr(characters[i].character))
                i += max(1, konsole_wcwidth(characters[i].character))
        
        plain_text_str = "".join(plainText)
        self._output << plain_text_str


class HTMLDecoder(TerminalCharacterDecoder):
    """
    生成漂亮HTML标记的终端字符解码器。
    
    对应C++: class HTMLDecoder : public TerminalCharacterDecoder
    """
    
    def __init__(self):
        """
        使用默认的黑底白字配色方案构造HTML解码器。
        
        对应C++: HTMLDecoder::HTMLDecoder()
        """
        super().__init__()
        self._output: Optional[QTextStream] = None  # 对应C++: QTextStream* _output
        self._colorTable = base_color_table  # 对应C++: const ColorEntry* _colorTable
        self._innerSpanOpen: bool = False  # 对应C++: bool _innerSpanOpen
        self._lastRendition: int = DEFAULT_RENDITION  # 对应C++: quint8 _lastRendition
        self._lastForeColor: CharacterColor = CharacterColor()  # 对应C++: CharacterColor _lastForeColor
        self._lastBackColor: CharacterColor = CharacterColor()  # 对应C++: CharacterColor _lastBackColor
    
    def setColorTable(self, table):
        """
        设置解码器用于在输出中生成HTML颜色代码的颜色表。
        
        Args:
            table: 颜色表 (const ColorEntry*)
            
        对应C++: void setColorTable(const ColorEntry* table)
        """
        self._colorTable = table
    
    def begin(self, output: QTextStream):
        """
        开始HTML解码。
        
        Args:
            output: 输出流
            
        对应C++: void begin(QTextStream* output) override
        """
        self._output = output
        
        text = ""
        text = self.openSpan(text, "font-family:monospace")
        
        output << text
    
    def end(self):
        """
        结束HTML解码。
        
        对应C++: void end() override
        """
        assert self._output is not None, "Q_ASSERT( _output )"
        
        text = ""
        text = self.closeSpan(text)
        
        self._output << text
        self._output = None
    
    def decodeLine(self, characters, count: int, properties: LineProperty):
        """
        解码一行字符为HTML。
        
        Args:
            characters: 字符数组 (const Character* const)
            count: 字符数量
            properties: 行属性（未使用）
            
        对应C++: void decodeLine(const Character* const characters,
                                int count, LineProperty /*properties*/) override
        """
        assert self._output is not None, "Q_ASSERT( _output )"
        
        text = ""
        spaceCount = 0
        
        for i in range(count):
            if (characters[i].rendition != self._lastRendition or
                characters[i].foregroundColor != self._lastForeColor or
                characters[i].backgroundColor != self._lastBackColor):
                
                if self._innerSpanOpen:
                    text = self.closeSpan(text)
                
                self._lastRendition = characters[i].rendition
                self._lastForeColor = characters[i].foregroundColor
                self._lastBackColor = characters[i].backgroundColor
                
                style = ""
                
                useBold = False
                weight = characters[i].fontWeight(self._colorTable)
                if weight == ColorEntry.FontWeight.UseCurrentFormat:
                    useBold = self._lastRendition & RE_BOLD
                else:
                    useBold = weight == ColorEntry.FontWeight.Bold
                
                if useBold:
                    style += "font-weight:bold;"
                
                if self._lastRendition & RE_UNDERLINE:
                    style += "font-decoration:underline;"
                
                if self._colorTable:
                    fore_color = self._lastForeColor.color(self._colorTable)
                    style += f"color:{fore_color.name()};"
                    
                    if not characters[i].isTransparent(self._colorTable):
                        back_color = self._lastBackColor.color(self._colorTable)
                        style += f"background-color:{back_color.name()};"
                
                text = self.openSpan(text, style)
                self._innerSpanOpen = True
            
            if characters[i].isSpace():
                spaceCount += 1
            else:
                spaceCount = 0
            
            if spaceCount < 2:
                if characters[i].rendition & RE_EXTENDED_CHAR:
                    extendedCharLength = 0
                    chars = ExtendedCharTable.instance.lookupExtendedChar(
                        characters[i].character, extendedCharLength
                    )
                    if chars:
                        for nchar in range(extendedCharLength):
                            text += chr(chars[nchar])
                else:
                    ch = chr(characters[i].character)
                    if ch == '<':
                        text += "&lt;"
                    elif ch == '>':
                        text += "&gt;"
                    elif ch == '&':
                        text += "&amp;"
                    else:
                        text += ch
            else:
                text += "&#160;"
        
        if self._innerSpanOpen:
            text = self.closeSpan(text)
        
        text += "<br>"
        
        self._output << text
    
    def openSpan(self, text: str, style: str) -> str:
        """
        在文本中打开HTML span标签。
        
        Args:
            text: 要修改的文本字符串
            style: CSS样式字符串
            
        Returns:
            str: 修改后的文本字符串
            
        对应C++: void openSpan(std::wstring& text, const QString& style)
        """
        span_text = f'<span style="{style}">'
        return text + span_text
    
    def closeSpan(self, text: str) -> str:
        """
        在文本中关闭HTML span标签。
        
        Args:
            text: 要修改的文本字符串
            
        Returns:
            str: 修改后的文本字符串
            
        对应C++: void closeSpan(std::wstring& text)
        """
        return text + "</span>" 