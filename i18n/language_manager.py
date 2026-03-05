# -*- coding: utf-8 -*-
"""
语言管理模块 - 用于管理应用程序的国际化和多语言支持

支持的语言列表包含常见国家/地区的语言
"""

import os
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QTranslator, QLocale, QCoreApplication
from PySide6.QtWidgets import QApplication


# 支持的语言列表 - 包含常见国家/地区的语言
# 格式: (语言代码, 显示名称, 原生名称)
SUPPORTED_LANGUAGES: List[Tuple[str, str, str]] = [
    ("zh_CN", "Chinese (Simplified)", "简体中文"),
    ("zh_TW", "Chinese (Traditional)", "繁體中文"),
    ("en_US", "English (US)", "English (US)"),
    ("en_GB", "English (UK)", "English (UK)"),
    ("ja_JP", "Japanese", "日本語"),
    ("ko_KR", "Korean", "한국어"),
    ("de_DE", "German", "Deutsch"),
    ("fr_FR", "French", "Français"),
    ("es_ES", "Spanish", "Español"),
    ("pt_BR", "Portuguese (Brazil)", "Português (Brasil)"),
    ("pt_PT", "Portuguese (Portugal)", "Português (Portugal)"),
    ("ru_RU", "Russian", "Русский"),
    ("it_IT", "Italian", "Italiano"),
    ("nl_NL", "Dutch", "Nederlands"),
    ("pl_PL", "Polish", "Polski"),
    ("tr_TR", "Turkish", "Türkçe"),
    ("ar_SA", "Arabic", "العربية"),
    ("he_IL", "Hebrew", "עברית"),
    ("th_TH", "Thai", "ไทย"),
    ("vi_VN", "Vietnamese", "Tiếng Việt"),
    ("id_ID", "Indonesian", "Bahasa Indonesia"),
    ("ms_MY", "Malay", "Bahasa Melayu"),
    ("hi_IN", "Hindi", "हिन्दी"),
    ("uk_UA", "Ukrainian", "Українська"),
    # ("cs_CZ", "Czech", "Čeština"),
    # ("sv_SE", "Swedish", "Svenska"),
    # ("da_DK", "Danish", "Dansk"),
    # ("fi_FI", "Finnish", "Suomi"),
    # ("nb_NO", "Norwegian", "Norsk"),
    ("el_GR", "Greek", "Ελληνικά"),
    # ("hu_HU", "Hungarian", "Magyar"),
    # ("ro_RO", "Romanian", "Română"),
    # ("sk_SK", "Slovak", "Slovenčina"),
    # ("bg_BG", "Bulgarian", "Български"),
    # ("hr_HR", "Croatian", "Hrvatski"),
    # ("ca_ES", "Catalan", "Català"),
]


class LanguageManager:
    """语言管理器 - 管理应用程序的翻译和语言切换"""
    
    _instance: Optional['LanguageManager'] = None
    
    def __init__(self):
        self._app: Optional[QApplication] = None
        self._translator: Optional[QTranslator] = None
        self._qt_translator: Optional[QTranslator] = None
        self._current_language: str = "zh_CN"
        self._translations_dir: str = ""
        
    @classmethod
    def instance(cls) -> 'LanguageManager':
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def initialize(self, app: QApplication, translations_dir: str = "") -> None:
        """
        初始化语言管理器
        
        :param app: QApplication 实例
        :param translations_dir: 翻译文件目录，默认为应用程序目录
        """
        self._app = app
        self._translator = QTranslator()
        self._qt_translator = QTranslator()
        
        if translations_dir:
            self._translations_dir = translations_dir
        else:
            # 默认使用 i18n 文件夹（即当前文件所在目录）
            self._translations_dir = os.path.dirname(os.path.abspath(__file__))
    
    def get_supported_languages(self) -> List[Tuple[str, str, str]]:
        """
        获取支持的语言列表
        
        :return: 语言列表 [(语言代码, 英文名称, 原生名称), ...]
        """
        return SUPPORTED_LANGUAGES.copy()
    
    def get_language_display_name(self, lang_code: str) -> str:
        """
        获取语言的显示名称（原生名称）
        
        :param lang_code: 语言代码，如 'zh_CN'
        :return: 原生名称，如 '简体中文'
        """
        for code, _, native_name in SUPPORTED_LANGUAGES:
            if code == lang_code:
                return native_name
        return lang_code
    
    def get_current_language(self) -> str:
        """获取当前语言代码"""
        return self._current_language
    
    def set_language(self, lang_code: str) -> bool:
        """
        设置应用程序语言
        
        :param lang_code: 语言代码，如 'zh_CN', 'en_US'
        :return: 是否成功加载翻译
        """
        if not self._app:
            return False
        
        # 移除旧的翻译器
        if self._translator:
            self._app.removeTranslator(self._translator)
        if self._qt_translator:
            self._app.removeTranslator(self._qt_translator)
        
        # 创建新的翻译器
        self._translator = QTranslator()
        self._qt_translator = QTranslator()
        
        success = False
        
        # 简化的语言代码 (如 en_US -> en, zh_CN -> zh_CN)
        short_code = lang_code.split('_')[0] if '_' in lang_code else lang_code
        
        # 尝试加载应用翻译文件
        # 查找顺序: app_{lang_code}.qm -> app_{short_code}.qm
        candidates = [
            os.path.join(self._translations_dir, f"app_{lang_code}.qm"),
            os.path.join(self._translations_dir, f"app_{short_code}.qm"),
        ]
        
        for qm_path in candidates:
            if os.path.exists(qm_path):
                if self._translator.load(qm_path):
                    self._app.installTranslator(self._translator)
                    success = True
                    print(f"Loaded translation file: {qm_path}")
                    break
        
        if not success:
            print(f"Translation file not found for language: {lang_code}")
            print(f"Searched paths: {candidates}")
        
        # 尝试加载 Qt 基础翻译
        qt_qm = f"qtbase_{lang_code}.qm"
        if self._qt_translator.load(qt_qm, QCoreApplication.applicationDirPath()):
            self._app.installTranslator(self._qt_translator)
        
        self._current_language = lang_code
        return success
    
    def load_from_config(self, lang_code: str) -> bool:
        """
        从配置加载语言设置
        
        :param lang_code: 配置中保存的语言代码
        :return: 是否成功
        """
        if lang_code:
            return self.set_language(lang_code)
        return False
    
    @staticmethod
    def get_system_language() -> str:
        """
        获取系统语言代码
        
        :return: 系统语言代码，如 'zh_CN'
        """
        locale = QLocale.system()
        lang_name = locale.name()  # 返回格式如 'zh_CN'
        return lang_name if lang_name else "en_US"
    
    def is_rtl_language(self, lang_code: str = None) -> bool:
        """
        检查是否为从右到左书写的语言（如阿拉伯语、希伯来语）
        
        :param lang_code: 语言代码，默认使用当前语言
        :return: 是否为 RTL 语言
        """
        if lang_code is None:
            lang_code = self._current_language
        
        rtl_languages = ['ar', 'he', 'fa', 'ur']
        short_code = lang_code.split('_')[0] if '_' in lang_code else lang_code
        return short_code in rtl_languages


# 便捷函数
def get_language_manager() -> LanguageManager:
    """获取语言管理器单例"""
    return LanguageManager.instance()


def tr(text: str, context: str = "MainDialog") -> str:
    """
    翻译文本的便捷函数
    
    :param text: 原始文本
    :param context: 翻译上下文
    :return: 翻译后的文本
    """
    return QCoreApplication.translate(context, text)
