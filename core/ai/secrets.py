import os

from function import util


def get_ai_api_key() -> str:
    """
    获取 AI API Key（敏感信息）。

    读取优先级：
    1) 环境变量 `ZAI_API_KEY`（推荐在 CI/容器中使用）
    2) 环境变量 `ZHIPUAI_API_KEY`（兼容部分用户习惯）
    3) 系统钥匙串（keyring），service 使用 util.APP_NAME

    注意：
    - 任何情况下都不把 Key 写入 `ai.json`，并且不在日志中输出 Key。
    """

    env_key = os.environ.get("ZAI_API_KEY", "") or os.environ.get("ZHIPUAI_API_KEY", "")
    if env_key:
        return env_key
    try:
        import keyring

        return keyring.get_password(util.APP_NAME, "zai_api_key") or ""
    except Exception:
        return ""


def set_ai_api_key(api_key: str) -> bool:
    """
    将 API Key 写入系统钥匙串。

    - macOS: Keychain
    - Windows: Credential Manager
    - Linux: Secret Service (依赖桌面环境/后端)

    返回值：
    - True: 写入成功
    - False: 写入失败（通常是系统缺少 keyring 后端、权限受限、或无图形环境）
    """

    try:
        import keyring

        keyring.set_password(util.APP_NAME, "zai_api_key", api_key)
        return True
    except Exception as e:
        util.logger.error(f"保存 API Key 到系统钥匙串失败: {e}")
        return False

