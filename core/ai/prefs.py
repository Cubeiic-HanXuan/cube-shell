import json
import os
from dataclasses import dataclass

import appdirs

from function import util


PROVIDER_PRESETS = {
    "zhipuai": {
        "name": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "models": ["glm-4.5", "glm-4.5-air", "glm-4.6", "glm-4.7", "glm-5", "glm-5-turbo", "glm-5.1"],
        "supports_thinking": True,
    },
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "models": ["deepseek-v4-pro", "deepseek-v4-flash"],
        "supports_thinking": True,
    },
    "aliyun": {
        "name": "通义千问",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": ["qwen-max", "qwen-plus", "qwen-turbo"],
        "supports_thinking": False,
    },
    "moonshot": {
        "name": "Kimi (月之暗面)",
        "base_url": "https://api.moonshot.cn/v1",
        "models": ["kimi-k2.6", "kimi-k2.5", "moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
        "supports_thinking": False,
    },
    "spark": {
        "name": "讯飞星火",
        "base_url": "https://spark-api-open.xf-yun.com/v1",
        "models": ["general", "generalv3", "generalv3.5"],
        "supports_thinking": False,
    },
    "baichuan": {
        "name": "百川",
        "base_url": "https://api.baichuan-ai.com/v1",
        "models": ["Baichuan4", "Baichuan3-Turbo"],
        "supports_thinking": False,
    },
    "minimax": {
        "name": "MiniMax",
        "base_url": "https://api.minimax.chat/v1",
        "models": ["MiniMax-Text-01", "abab6.5s-chat", "abab5.5-chat"],
        "supports_thinking": False,
    },
    "xiaomi": {
        "name": "小米 MiLM",
        "base_url": "https://api.xiaomi.com/v1",
        "models": ["MiLM-1"],
        "supports_thinking": False,
    },
    "doubao": {
        "name": "豆包 (火山引擎)",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "models": ["doubao-seed-2-0-code-preview-260215", "doubao-seed-2-0-mini-260215", "doubao-seed-2-0-pro-260215"],
        "supports_thinking": True,
    },
    "custom": {
        "name": "自定义",
        "base_url": "",
        "models": [],
        "supports_thinking": False,
    },
}


@dataclass
class AIUserPrefs:
    """
    AI 偏好设置（不包含敏感信息）。

    设计说明：
    - 仅保存“可公开”的参数，例如模型名、温度、max_tokens、系统提示词等；
    - API Key 绝不写入该配置文件，避免泄漏（Key 使用系统钥匙串或环境变量）。
    """

    provider: str = "zhipuai"  # AI 服务提供商
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
            provider=str(data.get("provider") or "zhipuai"),
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
            "provider": prefs.provider,
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


def get_provider_preset(provider: str) -> dict:
    """获取指定提供商的预设配置"""
    return PROVIDER_PRESETS.get(provider, PROVIDER_PRESETS["custom"])

