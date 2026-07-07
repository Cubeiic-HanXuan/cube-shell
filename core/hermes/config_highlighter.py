# -*- coding: utf-8 -*-
"""Hermes 配置文件语法高亮器（Pygments 驱动）

用 Pygments 的 lexer + style 驱动 QSyntaxHighlighter：
  - 配色直接取自 `util.THEME['theme']`（一个合法的 Pygments style 名），
    主题切换时高亮自动跟随，无需维护手写配色表。
  - YAML 用 `yaml` lexer，.env 用 `properties` lexer。
  - 逐行 lex（YAML 缩进键仍可识别为 Name.Tag），避免跨行状态处理。
"""

from PySide6.QtGui import (QColor, QSyntaxHighlighter, QTextCharFormat,
                           QFont, QPalette)

from pygments.lexers import get_lexer_by_name
from pygments.styles import get_style_by_name
from pygments.util import ClassNotFound

from function import util
from function.util import logger


# 配置文件专属高亮主题（与终端 theme 解耦）。
# 经对全部 Pygments 主题按「配置文件可读性」评测+真实预览选定：
#   - 键名清晰醒目（浏览配置的结构主线）
#   - 值/字符串对比充足、数字/布尔各有专属色
#   - 注释适度弱化（不喧宾夺主）、token 区分度高
# 暗色用 gruvbox-dark（暖色柔和、键名易扫读、注释低饱和退居其次）；
# 浅色用 tango（蓝色键名结构感强、绿串棕注、层次分明）。
_CONFIG_STYLE_DARK = "gruvbox-dark"
_CONFIG_STYLE_LIGHT = "tango"


def _current_style_name() -> str:
    """按 appearance 选配置文件专属高亮主题（不跟随终端 theme）。"""
    try:
        appearance = (util.THEME or {}).get("appearance", "dark")
    except Exception:
        appearance = "dark"
    return _CONFIG_STYLE_LIGHT if appearance == "light" else _CONFIG_STYLE_DARK


def palette_is_dark(widget) -> bool:
    """根据控件 Base 背景亮度判断是否为暗色主题（保留供外部引用）。"""
    try:
        base = widget.palette().color(QPalette.ColorRole.Base)
        return base.lightness() < 128
    except Exception:
        return True


class PygmentsHighlighter(QSyntaxHighlighter):
    """通用 Pygments 高亮器：按 lexer 分词、按 style 取色。"""

    def __init__(self, document, lexer_name: str, style_name: str = None):
        super().__init__(document)
        self._lexer = get_lexer_by_name(lexer_name, stripnl=False,
                                        ensurenl=False)
        self._fmt_cache = {}
        self._background = None
        self._load_style(style_name or _current_style_name())

    # ── style 加载 / 取色 ──

    def _load_style(self, style_name: str):
        """加载 Pygments style，构建 token→颜色的全量映射。"""
        try:
            style = get_style_by_name(style_name)
        except ClassNotFound:
            logger.warning(f"未知 Pygments style: {style_name!r}，回退 default")
            style = get_style_by_name("default")
        # dict(style) 给出 {token: styledef} 全量映射，用于沿继承链回退取色
        self._style_map = dict(style)
        try:
            self._background = style.background_color
        except Exception:
            self._background = None
        self._fmt_cache.clear()

    def background_color(self):
        """返回 style 的背景色（十六进制字符串或 None）。"""
        return self._background

    def set_style(self, style_name: str):
        """切换 style 并重新高亮整个文档。"""
        self._load_style(style_name)
        self.rehighlight()

    def _resolve_style(self, token):
        """沿 token 继承链找到首个定义了 color 的样式，避免 KeyError。"""
        t = token
        while t is not None:
            sdef = self._style_map.get(t)
            if sdef and (sdef.get("color") or sdef.get("bold") or sdef.get("italic")):
                return sdef
            t = t.parent
        return None

    def _format_for(self, token) -> QTextCharFormat:
        """token → QTextCharFormat（带缓存）。"""
        cached = self._fmt_cache.get(token)
        if cached is not None:
            return cached
        fmt = QTextCharFormat()
        sdef = self._resolve_style(token)
        if sdef:
            color = sdef.get("color")
            if color:
                fmt.setForeground(QColor(f"#{color}"))
            if sdef.get("bold"):
                fmt.setFontWeight(QFont.Weight.Bold)
            if sdef.get("italic"):
                fmt.setFontItalic(True)
        self._fmt_cache[token] = fmt
        return fmt

    # ── 逐行高亮 ──

    def highlightBlock(self, text: str):
        if not text:
            return
        offset = 0
        for token, value in self._lexer.get_tokens(text):
            length = len(value)
            if length == 0:
                continue
            if value.strip():
                self.setFormat(offset, length, self._format_for(token))
            offset += length


class YamlHighlighter(PygmentsHighlighter):
    """YAML 高亮器（config.yaml）。"""

    def __init__(self, document, style_name: str = None):
        super().__init__(document, "yaml", style_name)


class DotenvHighlighter(PygmentsHighlighter):
    """.env 高亮器（KEY=VALUE，用 properties lexer）。"""

    def __init__(self, document, style_name: str = None):
        super().__init__(document, "properties", style_name)
