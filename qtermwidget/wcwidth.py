"""
Unicode字符宽度计算模块 - 从Konsole终端模拟器转换而来

原始文件：
- konsole_wcwidth.h
- konsole_wcwidth.cpp

作者信息：
- Markus Kuhn -- 2001-01-12 -- public domain
- Adaptations for KDE by Waldo Bastian <bastian@kde.org>
- Rewritten for QT4 by e_k <e_k at users.sourceforge.net>

转换为Python PySide6版本
"""

import unicodedata
from typing import Union

# 字符宽度缓存，提高性能
_width_cache = {}


def konsole_wcwidth(char: Union[str, int]) -> int:
    """
    计算单个Unicode字符在终端中的显示宽度。
    
    Args:
        char: Unicode字符（字符串）或Unicode码点（整数）
        
    Returns:
        int: 字符宽度
            - 0: 不可见字符或组合字符
            - 1: 正常宽度字符
            - 2: 宽字符（如中文、日文等）
            - -1: 控制字符
            
    对应C++: int konsole_wcwidth(wchar_t ucs)
    """
    # 转换为Unicode码点
    if isinstance(char, str):
        if len(char) == 0:
            return 0
        if len(char) > 1:
            # 如果是多字符字符串，只处理第一个字符
            char = char[0]
        codepoint = ord(char)
    else:
        codepoint = char

    # 检查缓存
    if codepoint in _width_cache:
        return _width_cache[codepoint]

    # 计算字符宽度
    width = _calculate_char_width(codepoint)

    # 缓存结果
    _width_cache[codepoint] = width
    return width


def _calculate_char_width(codepoint: int) -> int:
    """
    计算字符宽度的内部实现。
    
    Args:
        codepoint: Unicode码点
        
    Returns:
        int: 字符宽度
    """
    # 处理基本ASCII控制字符
    if codepoint < 32:
        return -1  # 控制字符

    # 处理DEL字符
    if codepoint == 0x7F:
        return -1  # DEL控制字符

    # 处理基本ASCII可打印字符
    if 32 <= codepoint < 127:
        return 1

    # 处理C1控制字符
    if 0x80 <= codepoint < 0xA0:
        return -1  # C1控制字符

    # 获取Unicode字符属性
    try:
        char = chr(codepoint)
        category = unicodedata.category(char)

        # 处理不可见字符
        if category in ('Mn', 'Me', 'Cf'):  # 非间距标记、包围标记、格式字符
            return 0

        # 处理控制字符
        if category in ('Cc', 'Cs'):  # 控制字符、代理字符
            return -1

        # 私有使用区域 - 对应C++中的UTF8PROC_CATEGORY_CO处理
        if category == 'Co':  # 私有使用字符
            return 1  # 如tmux所假设，宽度为1

        # 检查是否为宽字符
        if _is_wide_character(codepoint):
            return 2

        # 默认为正常宽度字符
        return 1

    except ValueError:
        # 无效的Unicode码点
        return -1


def _is_wide_character(codepoint: int) -> bool:
    """
    检查字符是否为宽字符（占用2个终端列位置）。
    
    Args:
        codepoint: Unicode码点
        
    Returns:
        bool: 是否为宽字符
    """
    # 东亚全角字符的主要范围
    wide_ranges = [
        # CJK统一汉字
        (0x4E00, 0x9FFF),  # CJK Unified Ideographs
        (0x3400, 0x4DBF),  # CJK Extension A
        (0x20000, 0x2A6DF),  # CJK Extension B
        (0x2A700, 0x2B73F),  # CJK Extension C
        (0x2B740, 0x2B81F),  # CJK Extension D
        (0x2B820, 0x2CEAF),  # CJK Extension E
        (0x2CEB0, 0x2EBEF),  # CJK Extension F

        # 平假名和片假名
        (0x3040, 0x309F),  # Hiragana
        (0x30A0, 0x30FF),  # Katakana

        # 韩文字母
        (0x1100, 0x11FF),  # Hangul Jamo
        (0xAC00, 0xD7AF),  # Hangul Syllables
        (0x3130, 0x318F),  # Hangul Compatibility Jamo

        # 全角ASCII和标点符号
        (0xFF01, 0xFF60),  # Fullwidth Forms
        (0xFFE0, 0xFFE6),  # Fullwidth Forms (currency symbols)

        # CJK符号和标点
        (0x3000, 0x303F),  # CJK Symbols and Punctuation

        # 其他常见的宽字符范围
        (0x2E80, 0x2EFF),  # CJK Radicals Supplement
        (0x2F00, 0x2FDF),  # Kangxi Radicals
        (0x31C0, 0x31EF),  # CJK Strokes
        (0x3200, 0x32FF),  # Enclosed CJK Letters and Months
        (0x3300, 0x33FF),  # CJK Compatibility
        (0xF900, 0xFAFF),  # CJK Compatibility Ideographs
        (0xFE30, 0xFE4F),  # CJK Compatibility Forms
    ]

    # 检查字符是否在宽字符范围内
    for start, end in wide_ranges:
        if start <= codepoint <= end:
            return True

    # 使用unicodedata检查东亚宽度属性
    try:
        char = chr(codepoint)
        east_asian_width = unicodedata.east_asian_width(char)
        # 'F'=Fullwidth, 'W'=Wide
        if east_asian_width in ('F', 'W'):
            return True
    except ValueError:
        pass

    return False


def string_width(text: str) -> int:
    """
    计算字符串在终端中的显示宽度。
    
    Args:
        text: 要计算宽度的字符串
        
    Returns:
        int: 字符串的总显示宽度
        
    对应C++: int string_width(const std::wstring & wstr)
    """
    if not text:
        return 0

    total_width = 0
    for char in text:
        char_width = konsole_wcwidth(char)
        if char_width > 0:  # 只累加可见字符的宽度
            total_width += char_width

    return total_width


def clear_width_cache():
    """
    清空字符宽度缓存。
    在处理大量不同字符后可以调用此函数来释放内存。
    """
    global _width_cache
    _width_cache.clear()


def get_cache_size() -> int:
    """
    获取当前缓存的字符数量。
    
    Returns:
        int: 缓存中的字符数量
    """
    return len(_width_cache)


# 一些常用的宽度计算辅助函数

def is_wide_char(char: str) -> bool:
    """
    检查单个字符是否为宽字符。
    
    Args:
        char: 字符
        
    Returns:
        bool: 是否为宽字符（宽度为2）
    """
    return konsole_wcwidth(char) == 2


def is_printable_char(char: str) -> bool:
    """
    检查字符是否为可打印字符。
    
    Args:
        char: 字符
        
    Returns:
        bool: 是否为可打印字符（宽度 > 0）
    """
    return konsole_wcwidth(char) > 0


def truncate_string(text: str, max_width: int, ellipsis: str = "...") -> str:
    """
    截断字符串到指定的显示宽度。
    
    Args:
        text: 要截断的字符串
        max_width: 最大显示宽度
        ellipsis: 省略号字符串
        
    Returns:
        str: 截断后的字符串
    """
    if string_width(text) <= max_width:
        return text

    ellipsis_width = string_width(ellipsis)
    if ellipsis_width >= max_width:
        return ellipsis[:max_width]

    target_width = max_width - ellipsis_width
    current_width = 0
    result = []

    for char in text:
        char_width = konsole_wcwidth(char)
        if char_width > 0:  # 只处理可见字符
            if current_width + char_width > target_width:
                break
            current_width += char_width
        result.append(char)

    return ''.join(result) + ellipsis


def pad_string(text: str, width: int, align: str = 'left', fill_char: str = ' ') -> str:
    """
    填充字符串到指定的显示宽度。
    
    Args:
        text: 要填充的字符串
        width: 目标显示宽度
        align: 对齐方式 ('left', 'right', 'center')
        fill_char: 填充字符
        
    Returns:
        str: 填充后的字符串
    """
    current_width = string_width(text)
    if current_width >= width:
        return text

    padding_needed = width - current_width
    fill_width = konsole_wcwidth(fill_char)

    if fill_width <= 0:
        fill_char = ' '
        fill_width = 1

    padding_chars = padding_needed // fill_width

    if align == 'left':
        return text + fill_char * padding_chars
    elif align == 'right':
        return fill_char * padding_chars + text
    elif align == 'center':
        left_padding = padding_chars // 2
        right_padding = padding_chars - left_padding
        return fill_char * left_padding + text + fill_char * right_padding
    else:
        raise ValueError(f"Invalid align value: {align}. Must be 'left', 'right', or 'center'")
