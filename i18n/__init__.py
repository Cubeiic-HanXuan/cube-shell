# -*- coding: utf-8 -*-
"""
国际化 (i18n) 模块

提供多语言支持和翻译管理功能
"""

from .language_manager import (
    LanguageManager,
    get_language_manager,
    tr,
    SUPPORTED_LANGUAGES
)

__all__ = [
    'LanguageManager',
    'get_language_manager',
    'tr',
    'SUPPORTED_LANGUAGES'
]
