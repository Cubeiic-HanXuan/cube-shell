import json
import os
from dataclasses import dataclass

import appdirs

from function import util


@dataclass
class AIUserPrefs:
    """
    AI 偏好设置（不包含敏感信息）。

    设计说明：
    - 仅保存“可公开”的参数，例如模型名、温度、max_tokens、系统提示词等；
    - API Key 绝不写入该配置文件，避免泄漏（Key 使用系统钥匙串或环境变量）。
    """

    model: str = "glm-4.7"
    base_url: str = ""
    thinking_enabled: bool = True
    stream: bool = True
    max_tokens: int = 8192
    temperature: float = 1.0
    system_prompt: str = "你是一个资深 Linux 运维与终端助手。输出尽量可执行、可复制。"


def _get_config_directory(app_name: str) -> str:
    """
    获取跨平台用户配置目录，并确保目录存在。

    - macOS: ~/Library/Application Support/<app_name>
    - Windows: %APPDATA%\\<app_name>
    - Linux: ~/.config/<app_name>
    """

    config_dir = appdirs.user_config_dir(app_name, appauthor=False)
    os.makedirs(config_dir, exist_ok=True)
    return config_dir


def get_ai_prefs_path() -> str:
    """
    AI 配置文件路径。

    注意：这里只返回“偏好设置”文件路径，不包含 API Key。
    """

    return os.path.join(_get_config_directory(util.APP_NAME), "ai.json")


def load_ai_prefs() -> AIUserPrefs:
    """
    读取 `ai.json` 并构造 `AIUserPrefs`。

    失败策略：
    - 文件不存在：返回默认值
    - 内容不合法：记录日志并返回默认值
    """

    path = get_ai_prefs_path()
    try:
        if not os.path.exists(path):
            return AIUserPrefs()
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
        return AIUserPrefs(
            model=str(data.get("model") or "glm-4.7"),
            base_url=str(data.get("base_url") or ""),
            thinking_enabled=bool(data.get("thinking_enabled", True)),
            stream=bool(data.get("stream", True)),
            max_tokens=int(data.get("max_tokens", 8192)),
            temperature=float(data.get("temperature", 1.0)),
            system_prompt=str(
                data.get("system_prompt") or "你是一个资深 Linux 运维与终端助手。输出尽量可执行、可复制。"
            ),
        )
    except Exception as e:
        util.logger.error(f"读取 AI 配置失败: {e}")
        return AIUserPrefs()


def save_ai_prefs(prefs: AIUserPrefs) -> None:
    """
    保存 `AIUserPrefs` 到 `ai.json`（不保存 API Key）。

    - 使用 `ensure_ascii=False` 保证中文可读；
    - 使用 `indent=2` 便于用户手工编辑。
    """

    path = get_ai_prefs_path()
    try:
        data = {
            "model": prefs.model,
            "base_url": prefs.base_url,
            "thinking_enabled": prefs.thinking_enabled,
            "stream": prefs.stream,
            "max_tokens": prefs.max_tokens,
            "temperature": prefs.temperature,
            "system_prompt": prefs.system_prompt,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        util.logger.error(f"保存 AI 配置失败: {e}")

