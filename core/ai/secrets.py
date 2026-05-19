import os

from function import util

# 各厂商专属环境变量映射
_PROVIDER_ENV_VARS = {
    "zhipuai": ["ZAI_API_KEY", "ZHIPUAI_API_KEY"],
    "deepseek": ["DEEPSEEK_API_KEY"],
    "aliyun": ["DASHSCOPE_API_KEY"],
    "moonshot": ["MOONSHOT_API_KEY"],
    "spark": ["SPARK_API_KEY"],
    "baichuan": ["BAICHUAN_API_KEY"],
    "minimax": ["MINIMAX_API_KEY"],
    "xiaomi": ["XIAOMI_API_KEY"],
    "doubao": ["DOUBAO_API_KEY", "ARK_API_KEY"],
}


def get_ai_api_key(provider: str = "zhipuai") -> str:
    """
    获取 AI API Key（敏感信息）。

    读取优先级：
    1) 各厂商专属环境变量（由 _PROVIDER_ENV_VARS 定义）
    2) 通用环境变量 `AI_API_KEY`（所有 provider 通用 fallback）
    3) keyring 新格式键名 `ai_api_key_{provider}`
    4) keyring 旧格式键名 `zai_api_key`（向后兼容，仅当 provider=zhipuai 时回退）

    注意：
    - 任何情况下都不把 Key 写入 `ai.json`，并且不在日志中输出 Key。
    """

    # 1) 厂商专属环境变量
    for env_var in _PROVIDER_ENV_VARS.get(provider, []):
        val = os.environ.get(env_var, "")
        if val:
            return val

    # 2) 通用环境变量
    generic = os.environ.get("AI_API_KEY", "")
    if generic:
        return generic

    # 3) keyring 新格式
    try:
        import keyring

        new_key = keyring.get_password(util.APP_NAME, f"ai_api_key_{provider}")
        if new_key:
            return new_key

        # 4) 旧格式回退（仅 zhipuai）
        if provider == "zhipuai":
            old_key = keyring.get_password(util.APP_NAME, "zai_api_key")
            if old_key:
                return old_key
    except Exception:
        pass

    return ""


def set_ai_api_key(api_key: str, provider: str = "zhipuai") -> bool:
    """
    将 API Key 写入系统钥匙串。

    - macOS: Keychain
    - Windows: Credential Manager
    - Linux: Secret Service (依赖桌面环境/后端)

    键名格式：ai_api_key_{provider}

    返回值：
    - True: 写入成功
    - False: 写入失败（通常是系统缺少 keyring 后端、权限受限、或无图形环境）
    """

    try:
        import keyring

        keyring.set_password(util.APP_NAME, f"ai_api_key_{provider}", api_key)
        return True
    except Exception as e:
        util.logger.error(f"保存 API Key 到系统钥匙串失败: {e}")
        return False

