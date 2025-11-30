"""
字符模块 - 从Konsole终端模拟器转换而来

Copyright 2007-2008 by Robert Knight <robertknight@gmail.com>
Copyright 1997,1998 by Lars Doelle <lars.doelle@on-line.de>

转换为Python PySide6版本
"""

from typing import Optional, Dict, List, Set

from qtermwidget.character_color import COLOR_SPACE_DEFAULT, COLOR_SPACE_SYSTEM, BASE_COLORS
from qtermwidget.character_color import CharacterColor, ColorEntry, DEFAULT_FORE_COLOR, DEFAULT_BACK_COLOR

# 行属性类型定义
LineProperty = int  # 对应C++: typedef unsigned char LineProperty;

# 行属性常量定义 - 对应C++中的static const int定义
LINE_DEFAULT = 0  # 对应C++: static const int LINE_DEFAULT        = 0;
LINE_WRAPPED = 1 << 0  # 对应C++: static const int LINE_WRAPPED          = (1 << 0);
LINE_DOUBLEWIDTH = 1 << 1  # 对应C++: static const int LINE_DOUBLEWIDTH      = (1 << 1);
LINE_DOUBLEHEIGHT = 1 << 2  # 对应C++: static const int LINE_DOUBLEHEIGHT    = (1 << 2);

# 渲染标志常量定义 - 对应C++中的#define定义
DEFAULT_RENDITION = 0  # 对应C++: #define DEFAULT_RENDITION  0
RE_BOLD = 1 << 0  # 对应C++: #define RE_BOLD            (1 << 0)
RE_BLINK = 1 << 1  # 对应C++: #define RE_BLINK           (1 << 1)
RE_UNDERLINE = 1 << 2  # 对应C++: #define RE_UNDERLINE       (1 << 2)
RE_REVERSE = 1 << 3  # 对应C++: #define RE_REVERSE         (1 << 3) // Screen only
RE_INTENSIVE = 1 << 3  # 对应C++: #define RE_INTENSIVE       (1 << 3) // Widget only
RE_ITALIC = 1 << 4  # 对应C++: #define RE_ITALIC          (1 << 4)
RE_CURSOR = 1 << 5  # 对应C++: #define RE_CURSOR          (1 << 5)
RE_EXTENDED_CHAR = 1 << 6  # 对应C++: #define RE_EXTENDED_CHAR   (1 << 6)
RE_FAINT = 1 << 7  # 对应C++: #define RE_FAINT           (1 << 7)
RE_STRIKEOUT = 1 << 8  # 对应C++: #define RE_STRIKEOUT       (1 << 8)
RE_CONCEAL = 1 << 9  # 对应C++: #define RE_CONCEAL         (1 << 9)
RE_OVERLINE = 1 << 10  # 对应C++: #define RE_OVERLINE        (1 << 10)


def _isSpaceChar(char_code: int) -> bool:
    """
    检查字符是否为空格字符
    替代QChar.isSpace()的功能
    """
    char = chr(char_code)
    return char.isspace()


class Character:
    """
    终端中的单个字符，由unicode字符值、前景和背景颜色以及
    一组指定如何绘制的渲染属性组成。
    
    对应C++: class Character
    """

    def __init__(self, c=' ',
                 f: CharacterColor = None,
                 b: CharacterColor = None,
                 r: int = DEFAULT_RENDITION):
        """
        构造新字符。
        
        Args:
            c: 此字符的unicode字符值或字符串字符
            f: 用于绘制字符的前景色
            b: 用于绘制字符背景的颜色
            r: 一组渲染标志，指定如何绘制此字符
            
        对应C++: inline Character(quint16 _c = ' ', CharacterColor _f = ..., CharacterColor _b = ..., quint8 _r = DEFAULT_RENDITION)
        """
        # 对应C++: wchar_t character;
        if isinstance(c, str):
            self.character = ord(c) if len(c) > 0 else ord(' ')
        elif isinstance(c, int):
            self.character = c
        else:
            self.character = ord(' ')

        # 对应C++: quint8 rendition;
        self.rendition = r & 0xFF  # 确保是8位值

        # 对应C++: CharacterColor foregroundColor;
        if f is None:
            self.foregroundColor = CharacterColor(COLOR_SPACE_DEFAULT, DEFAULT_FORE_COLOR)
        else:
            self.foregroundColor = f

        # 对应C++: CharacterColor backgroundColor;
        if b is None:
            self.backgroundColor = CharacterColor(COLOR_SPACE_DEFAULT, DEFAULT_BACK_COLOR)
        else:
            self.backgroundColor = b
            
    def __eq__(self, other):
        """
        比较两个Character对象是否相等
        """
        if not isinstance(other, Character):
            return False
        return (self.character == other.character and
                self.foregroundColor == other.foregroundColor and
                self.backgroundColor == other.backgroundColor and
                self.rendition == other.rendition)

    def isTransparent(self, palette: List[ColorEntry]) -> bool:
        """
        当用指定的调色板绘制时，如果此字符具有透明背景，则返回true。
        
        Args:
            palette: 颜色调色板
            
        Returns:
            bool: 是否透明
            
        对应C++: bool isTransparent(const ColorEntry* palette) const;
        """
        # 对应C++中的inline实现

        if (self.backgroundColor._colorSpace == COLOR_SPACE_DEFAULT and
                palette[self.backgroundColor._u + 0 + (BASE_COLORS if self.backgroundColor._v else 0)].transparent):
            return True
        elif (self.backgroundColor._colorSpace == COLOR_SPACE_SYSTEM and
              palette[self.backgroundColor._u + 2 + (BASE_COLORS if self.backgroundColor._v else 0)].transparent):
            return True

        return False

    def fontWeight(self, base: List[ColorEntry]) -> 'ColorEntry.FontWeight':
        """
        返回字体粗细。
        
        Args:
            base: 基础颜色调色板
            
        Returns:
            ColorEntry.FontWeight: 字体粗细
            
        对应C++: ColorEntry::FontWeight fontWeight(const ColorEntry* base) const;
        """
        # 对应C++中的inline实现

        if self.backgroundColor._colorSpace == COLOR_SPACE_DEFAULT:
            return base[self.backgroundColor._u + 0 + (BASE_COLORS if self.backgroundColor._v else 0)].fontWeight
        elif self.backgroundColor._colorSpace == COLOR_SPACE_SYSTEM:
            return base[self.backgroundColor._u + 2 + (BASE_COLORS if self.backgroundColor._v else 0)].fontWeight
        else:
            return ColorEntry.FontWeight.UseCurrentFormat

    def equalsFormat(self, other: 'Character') -> bool:
        """
        如果比较字符的格式（颜色、渲染标志）相等，则返回true。
        
        Args:
            other: 要比较的其他字符
            
        Returns:
            bool: 格式是否相等
            
        对应C++: bool equalsFormat(const Character &other) const;
        """
        return (self.backgroundColor == other.backgroundColor and
                self.foregroundColor == other.foregroundColor and
                self.rendition == other.rendition)

    def isLineChar(self) -> bool:
        """
        检查是否为线条字符。
        
        Returns:
            bool: 是否为线条字符
            
        对应C++: inline bool isLineChar() const
        """
        if self.rendition & RE_EXTENDED_CHAR:
            return False
        return (self.character & 0xFF80) == 0x2500

    def isSpace(self) -> bool:
        """
        检查是否为空格字符。
        
        Returns:
            bool: 是否为空格字符
            
        对应C++: inline bool isSpace() const
        """
        if self.rendition & RE_EXTENDED_CHAR:
            return False
        return _isSpaceChar(self.character)

    def __eq__(self, other: 'Character') -> bool:
        """
        比较两个字符，如果它们具有相同的unicode字符值、渲染和颜色，则返回true。
        
        Args:
            other: 要比较的其他字符
            
        Returns:
            bool: 是否相等
            
        对应C++: friend bool operator == (const Character& a, const Character& b);
        """
        if not isinstance(other, Character):
            return False

        return (self.character == other.character and
                self.rendition == other.rendition and
                self.foregroundColor == other.foregroundColor and
                self.backgroundColor == other.backgroundColor)

    def __ne__(self, other: 'Character') -> bool:
        """
        比较两个字符，如果它们具有不同的unicode字符值、渲染或颜色，则返回true。
        
        Args:
            other: 要比较的其他字符
            
        Returns:
            bool: 是否不相等
            
        对应C++: friend bool operator != (const Character& a, const Character& b);
        """
        return not self.__eq__(other)

    def __repr__(self) -> str:
        """
        返回字符的字符串表示。
        """
        return f"Character('{chr(self.character)}', fg={self.foregroundColor}, bg={self.backgroundColor}, r={self.rendition})"


class ExtendedCharTable:
    """
    存储unicode字符序列的表，通过哈希键引用。
    哈希键本身与unicode字符的大小相同（ushort），
    因此它可以在结构中占用相同的空间。
    
    对应C++: class ExtendedCharTable
    """

    def __init__(self):
        """
        构造新的字符表。
        对应C++: ExtendedCharTable();
        """
        # 对应C++: QHash<uint,uint*> extendedCharTable;
        self.extendedCharTable: Dict[int, List[int]] = {}

        # 对应C++: QSet<ScreenWindow*> windows;
        # 注意：ScreenWindow在Python版本中可能不需要，这里先保留接口
        self.windows: Set = set()

    def createExtendedChar(self, unicode_points: List[int]) -> int:
        """
        将unicode字符序列添加到表中，并返回一个哈希码，
        稍后可以使用lookupExtendedChar()查找该序列。
        
        如果表中已存在相同的序列，将返回现有序列的哈希。
        
        Args:
            unicode_points: unicode字符点数组
            
        Returns:
            int: 哈希键
            
        对应C++: uint createExtendedChar(uint* unicodePoints , ushort length);
        """
        length = len(unicode_points)
        if length == 0:
            return 0

        # 计算哈希值 - 对应C++: extendedCharHash
        hash_value = self._extendedCharHash(unicode_points)

        # 检查是否已存在 - 对应C++: extendedCharMatch
        if hash_value in self.extendedCharTable:
            if self._extendedCharMatch(hash_value, unicode_points):
                return hash_value

        # 创建新条目
        # 格式：[length, unicode_point1, unicode_point2, ...]
        entry = [length] + unicode_points
        self.extendedCharTable[hash_value] = entry

        return hash_value

    def lookupExtendedChar(self, hash_key: int) -> Optional[List[int]]:
        """
        查找并返回使用createExtendedChar()添加到表中的unicode字符序列。
        
        Args:
            hash_key: createExtendedChar()返回的哈希键
            
        Returns:
            Optional[List[int]]: unicode字符序列，如果未找到则返回None
            
        对应C++: uint* lookupExtendedChar(uint hash , ushort& length) const;
        """
        if hash_key not in self.extendedCharTable:
            return None

        entry = self.extendedCharTable[hash_key]
        if len(entry) == 0:
            return None

        # 第一个元素是长度，其余是实际的unicode点
        length = entry[0]
        return entry[1:1 + length]

    def _extendedCharHash(self, unicode_points: List[int]) -> int:
        """
        计算unicode点序列的哈希键。
        
        Args:
            unicode_points: unicode点序列
            
        Returns:
            int: 哈希值
            
        对应C++: uint extendedCharHash(uint* unicodePoints , ushort length) const;
        """
        # 简单的哈希函数实现
        hash_value = 0
        for point in unicode_points:
            hash_value = (hash_value * 31 + point) & 0xFFFFFFFF
        return hash_value

    def _extendedCharMatch(self, hash_key: int, unicode_points: List[int]) -> bool:
        """
        测试由'hash_key'指定的表中条目是否与大小为'length'的字符序列'unicode_points'匹配。
        
        Args:
            hash_key: 哈希键
            unicode_points: unicode点序列
            
        Returns:
            bool: 是否匹配
            
        对应C++: bool extendedCharMatch(uint hash , uint* unicodePoints , ushort length) const;
        """
        if hash_key not in self.extendedCharTable:
            return False

        entry = self.extendedCharTable[hash_key]
        if len(entry) == 0:
            return False

        # 检查长度
        length = entry[0]
        if length != len(unicode_points):
            return False

        # 检查内容
        for i in range(length):
            if entry[1 + i] != unicode_points[i]:
                return False

        return True

    def clear(self):
        """
        清空扩展字符表。
        """
        self.extendedCharTable.clear()
        self.windows.clear()


# VT100图形字符表 - 对应C++: extern unsigned short vt100_graphics[32];
# 这是VT100终端的特殊图形字符映射表
vt100_graphics = [
    0x0020,  # 空格
    0x25C6,  # 黑色钻石 ♦
    0x2592,  # 中等阴影 ▒
    0x2409,  # 水平制表符符号 ␉
    0x240C,  # 换页符号 ␌
    0x240D,  # 回车符号 ␍
    0x240A,  # 换行符号 ␊
    0x00B0,  # 度数符号 °
    0x00B1,  # 加减号 ±
    0x2424,  # 换行符号 ␤
    0x240B,  # 垂直制表符符号 ␋
    0x2518,  # 右下角 ┘
    0x2510,  # 右上角 ┐
    0x250C,  # 左上角 ┌
    0x2514,  # 左下角 └
    0x253C,  # 十字交叉 ┼
    0x23BA,  # 水平线上段 ⎺
    0x23BB,  # 水平线中段 ⎻
    0x2500,  # 水平线 ─
    0x23BC,  # 水平线下段 ⎼
    0x23BD,  # 水平线底段 ⎽
    0x251C,  # 左中交叉 ├
    0x2524,  # 右中交叉 ┤
    0x2534,  # 下中交叉 ┴
    0x252C,  # 上中交叉 ┬
    0x2502,  # 垂直线 │
    0x2264,  # 小于等于 ≤
    0x2265,  # 大于等于 ≥
    0x03C0,  # 希腊字母pi π
    0x2260,  # 不等于 ≠
    0x00A3,  # 英镑符号 £
    0x00B7,  # 中点 ·
]

# 全局ExtendedCharTable实例 - 对应C++: static ExtendedCharTable instance;
extended_char_table_instance = ExtendedCharTable()
