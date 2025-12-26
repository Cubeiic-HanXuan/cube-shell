"""
cube-shell 的 AI 子模块（GLM-4.7 / zai-sdk）。

该包的设计目标：
1) 把 AI 相关逻辑从巨大的 `cube-shell.py` 中解耦出来，便于维护与测试；
2) UI 与网络请求分层：UI 只负责交互与展示，请求/配置由独立模块负责；
3) 不改变原有终端功能：AI 只是右键菜单的可选增强能力。
"""

from .prefs import AIUserPrefs, load_ai_prefs, save_ai_prefs
from .secrets import get_ai_api_key, set_ai_api_key
from .worker import AIChatWorker
from .ui import AISettingsDialog, AIOutputDialog, open_ai_dialog

__all__ = [
    "AIUserPrefs",
    "load_ai_prefs",
    "save_ai_prefs",
    "get_ai_api_key",
    "set_ai_api_key",
    "AIChatWorker",
    "AISettingsDialog",
    "AIOutputDialog",
    "open_ai_dialog",
]
