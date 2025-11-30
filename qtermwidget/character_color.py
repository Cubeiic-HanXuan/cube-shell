"""
字符颜色模块 - 从Konsole终端模拟器转换而来

Copyright 2007-2008 by Robert Knight <robertknight@gmail.com>
Copyright 1997,1998 by Lars Doelle <lars.doelle@on-line.de>

转换为Python PySide6版本
"""

from enum import IntEnum
from typing import List

from PySide6.QtGui import QColor

# 颜色相关常量定义 - 对应C++中的宏定义
BASE_COLORS = 2 + 8     # 对应C++: #define BASE_COLORS   (2+8)
INTENSITIES = 2         # 对应C++: #define INTENSITIES   2
TABLE_COLORS = INTENSITIES * BASE_COLORS  # 对应C++: #define TABLE_COLORS  (INTENSITIES*BASE_COLORS)

DEFAULT_FORE_COLOR = 0  # 对应C++: #define DEFAULT_FORE_COLOR 0
DEFAULT_BACK_COLOR = 1  # 对应C++: #define DEFAULT_BACK_COLOR 1

# 颜色空间常量定义
COLOR_SPACE_UNDEFINED = 0  # 对应C++: #define COLOR_SPACE_UNDEFINED   0
COLOR_SPACE_DEFAULT = 1    # 对应C++: #define COLOR_SPACE_DEFAULT     1
COLOR_SPACE_SYSTEM = 2     # 对应C++: #define COLOR_SPACE_SYSTEM      2
COLOR_SPACE_256 = 3        # 对应C++: #define COLOR_SPACE_256         3
COLOR_SPACE_RGB = 4        # 对应C++: #define COLOR_SPACE_RGB         4


class ColorEntry:
    """
    终端显示颜色调色板中的条目。
    
    颜色调色板是包含16个ColorEntry实例的数组，
    将系统颜色索引（从0到15）映射到实际颜色。
    
    对应C++: class ColorEntry
    """
    
    class FontWeight(IntEnum):
        """
        指定绘制此颜色文本时使用的字体粗细。
        对应C++: enum FontWeight
        """
        # 始终用粗体绘制此颜色的文本 - 对应C++: Bold
        Bold = 0
        # 始终用正常粗细绘制此颜色的文本 - 对应C++: Normal  
        Normal = 1
        # 使用终端应用程序设置的当前字体粗细 - 对应C++: UseCurrentFormat
        UseCurrentFormat = 2
    
    def __init__(self, color: QColor = None, transparent: bool = False, 
                 font_weight: FontWeight = FontWeight.UseCurrentFormat):
        """
        构造新的颜色调色板条目。
        
        Args:
            color: 此条目的颜色值
            transparent: 指定用作背景色时颜色应透明
            font_weight: 指定用此颜色绘制文本时使用的字体粗细
            
        对应C++: ColorEntry(QColor c, bool tr, FontWeight weight = UseCurrentFormat)
        """
        if color is None:
            # 对应C++: ColorEntry() : transparent(false), fontWeight(UseCurrentFormat) {}
            self.color = QColor()
            self.transparent = False
            self.fontWeight = ColorEntry.FontWeight.UseCurrentFormat
        else:
            self.color = color               # 对应C++: QColor color
            self.transparent = transparent   # 对应C++: bool transparent
            self.fontWeight = font_weight    # 对应C++: FontWeight fontWeight


def color256(u: int, base: List[ColorEntry]) -> QColor:
    """
    256色模式的颜色计算函数
    对应C++中的inline const QColor color256(quint8 u, const ColorEntry* base)
    
    Args:
        u: 颜色索引
        base: 基础颜色调色板
        
    Returns:
        QColor: 计算得到的颜色
    """
    # 0..16: 系统颜色
    # 对应C++: if (u <   8) return base[u+2            ].color;
    if u < 8:
        return base[u + 2].color
    
    u -= 8
    # 对应C++: if (u <   8) return base[u+2+BASE_COLORS].color;
    if u < 8:
        return base[u + 2 + BASE_COLORS].color
    
    u -= 8
    
    # 16..231: 6x6x6 rgb颜色立方体
    # 对应C++: if (u < 216) return QColor(((u/36)%6) ? (40*((u/36)%6)+55) : 0, ...)
    if u < 216:
        r = (40 * ((u // 36) % 6) + 55) if ((u // 36) % 6) else 0
        g = (40 * ((u // 6) % 6) + 55) if ((u // 6) % 6) else 0
        b = (40 * ((u // 1) % 6) + 55) if ((u // 1) % 6) else 0
        return QColor(r, g, b)
    
    u -= 216
    
    # 232..255: 灰度，排除黑色和白色
    # 对应C++: int gray = u*10+8; return QColor(gray,gray,gray);
    gray = u * 10 + 8
    return QColor(gray, gray, gray)


class CharacterColor:
    """
    描述终端中单个字符的颜色。
    
    CharacterColor是各种颜色空间的联合体。
    
    分配如下：
    Type  - Space        - Values
    0     - Undefined   - u:  0,      v:0        w:0
    1     - Default     - u:  0..1    v:intense  w:0
    2     - System      - u:  0..7    v:intense  w:0
    3     - Index(256)  - u: 16..255  v:0        w:0
    4     - RGB         - u:  0..255  v:0..256   w:0..256
    
    对应C++: class CharacterColor
    """
    
    def __init__(self, color_space: int = COLOR_SPACE_UNDEFINED, co: int = 0):
        """
        构造新的CharacterColor。
        
        Args:
            color_space: 颜色空间类型
            co: 颜色值，其含义取决于使用的颜色空间
            
        对应C++: CharacterColor() 和 CharacterColor(quint8 colorSpace, int co)
        """
        # 对应C++中的私有成员变量
        self._colorSpace = color_space  # 对应C++: quint8 _colorSpace
        self._u = 0                     # 对应C++: quint8 _u
        self._v = 0                     # 对应C++: quint8 _v  
        self._w = 0                     # 对应C++: quint8 _w
        
        if color_space == COLOR_SPACE_UNDEFINED:
            # 对应C++默认构造函数的逻辑
            return
        
        # 对应C++构造函数中的switch语句
        if color_space == COLOR_SPACE_DEFAULT:
            self._u = co & 1
        elif color_space == COLOR_SPACE_SYSTEM:
            self._u = co & 7
            self._v = (co >> 3) & 1
        elif color_space == COLOR_SPACE_256:
            self._u = co & 255
        elif color_space == COLOR_SPACE_RGB:
            self._u = (co >> 16) & 255
            self._v = (co >> 8) & 255
            self._w = co & 255
        else:
            self._colorSpace = COLOR_SPACE_UNDEFINED
    
    def __eq__(self, other):
        """
        比较两个CharacterColor对象是否相等
        """
        if not isinstance(other, CharacterColor):
            return False
        return (self._colorSpace == other._colorSpace and
                self._u == other._u and
                self._v == other._v and
                self._w == other._w)
    
    def isValid(self) -> bool:
        """
        如果此字符颜色条目有效，则返回true。
        对应C++: bool isValid() const
        """
        return self._colorSpace != COLOR_SPACE_UNDEFINED
    
    def setIntensive(self):
        """
        如果不是集约系统颜色，则将此颜色的值从正常系统颜色设置为相应的集约系统颜色。
        
        这仅适用于颜色使用COLOR_SPACE_DEFAULT或COLOR_SPACE_SYSTEM颜色空间时。
        对应C++: void setIntensive()
        """
        if self._colorSpace == COLOR_SPACE_SYSTEM or self._colorSpace == COLOR_SPACE_DEFAULT:
            self._v = 1
    
    def color(self, palette: List[ColorEntry]) -> QColor:
        """
        返回指定颜色调色板中的颜色。
        
        只有当此颜色是16种系统颜色之一时才使用调色板，否则将被忽略。
        
        Args:
            palette: 颜色调色板
            
        Returns:
            QColor: 颜色值
            
        对应C++: QColor color(const ColorEntry* palette) const
        """
        # 对应C++中的switch语句
        if self._colorSpace == COLOR_SPACE_DEFAULT:
            return palette[self._u + 0 + (BASE_COLORS if self._v else 0)].color
        elif self._colorSpace == COLOR_SPACE_SYSTEM:
            return palette[self._u + 2 + (BASE_COLORS if self._v else 0)].color
        elif self._colorSpace == COLOR_SPACE_256:
            return color256(self._u, palette)
        elif self._colorSpace == COLOR_SPACE_RGB:
            return QColor(self._u, self._v, self._w)
        elif self._colorSpace == COLOR_SPACE_UNDEFINED:
            return QColor()
        
        # 对应C++: Q_ASSERT(false); // invalid color space
        raise ValueError("Invalid color space")
    
    def __eq__(self, other: 'CharacterColor') -> bool:
        """
        比较两个颜色，如果它们表示相同的颜色值并使用相同的颜色空间，则返回true。
        对应C++: friend bool operator == (const CharacterColor& a, const CharacterColor& b)
        """
        if not isinstance(other, CharacterColor):
            return False
        
        return (self._colorSpace == other._colorSpace and
                self._u == other._u and
                self._v == other._v and
                self._w == other._w)
    
    def __ne__(self, other: 'CharacterColor') -> bool:
        """
        比较两个颜色，如果它们表示不同的颜色值或使用不同的颜色空间，则返回true。
        对应C++: friend bool operator != (const CharacterColor& a, const CharacterColor& b)
        """
        return not self.__eq__(other)
    
    def __repr__(self) -> str:
        """Python风格的字符串表示"""
        return f"CharacterColor(space={self._colorSpace}, u={self._u}, v={self._v}, w={self._w})"


# 标准颜色表的声明 - 对应C++: extern const ColorEntry base_color_table[TABLE_COLORS]
# 注意：实际的颜色表在TerminalDisplay.cpp中定义，这里我们提供一个基本的实现
def create_base_color_table() -> List[ColorEntry]:
    """
    创建基础颜色表
    对应C++中在TerminalDisplay.cpp中定义的base_color_table
    """
    color_table = []
    
    # 基础颜色定义（简化版本）
    # 默认颜色
    color_table.append(ColorEntry(QColor(0, 0, 0), False))        # 默认前景色（黑色）
    color_table.append(ColorEntry(QColor(255, 255, 255), False))  # 默认背景色（白色）
    
    # 系统颜色（8种标准颜色）
    system_colors = [
        QColor(0, 0, 0),        # 黑色
        QColor(178, 24, 24),    # 红色
        QColor(24, 178, 24),    # 绿色  
        QColor(178, 104, 24),   # 黄色
        QColor(24, 24, 178),    # 蓝色
        QColor(178, 24, 178),   # 品红色
        QColor(24, 178, 178),   # 青色
        QColor(178, 178, 178),  # 白色
    ]
    
    for color in system_colors:
        color_table.append(ColorEntry(color, False))
    
    # 高亮颜色（同样的8种颜色，但更亮）
    for color in system_colors:
        # 增亮颜色
        bright_color = QColor(
            min(255, color.red() + 77),
            min(255, color.green() + 77), 
            min(255, color.blue() + 77)
        )
        color_table.append(ColorEntry(bright_color, False))
    
    return color_table


# 全局颜色表实例
base_color_table = create_base_color_table()
