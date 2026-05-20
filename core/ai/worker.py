import traceback

from PySide6.QtCore import QThread, Signal

from function import util
from .prefs import AIUserPrefs, get_provider_preset
from .secrets import get_ai_api_key


class AIChatWorker(QThread):
    """
    AI 请求工作线程（QThread）。

    为什么用 QThread 而不是 threading.Thread？
    - 这是 Qt 应用，QThread 更适合与 UI 交互；
    - 通过 Signal 把 token 增量推回主线程，避免跨线程直接操作 UI 控件。
    """

    delta_ready = Signal(str, str)
    finished_text = Signal(str)
    failed = Signal(str)

    def __init__(self, prefs: AIUserPrefs, messages: list[dict], parent=None):
        super().__init__(parent)
        self.prefs = prefs
        self.messages = messages
        self._stop_flag = False

    def request_stop(self):
        """
        请求停止生成。

        说明：
        - SDK 的流式迭代器通常不支持强制中断 socket；
        - 这里采用"软停止"：停止后不再消费后续 chunk。
        """

        self._stop_flag = True

    def run(self):
        """
        线程入口：调用 OpenAI 兼容 SDK 的 chat.completions.create。

        关键点：
        - 读取 API Key：环境变量或系统钥匙串；
        - 支持 thinking 开关与 stream；
        - stream=True 时逐 chunk 发射 delta_ready(reasoning, content)。
        """

        try:
            from openai import OpenAI

            api_key = get_ai_api_key(self.prefs.provider)
            if not api_key:
                self.failed.emit("未配置 API Key，请在「设置 -> AI 设置」中配置")
                return

            preset = get_provider_preset(self.prefs.provider)
            base_url = self.prefs.base_url or preset["base_url"]
            client = OpenAI(api_key=api_key, base_url=base_url)

            call_kwargs = {
                "model": self.prefs.model,
                "messages": self.messages,
                "stream": self.prefs.stream,
                "max_tokens": self.prefs.max_tokens,
                "temperature": self.prefs.temperature,
            }
            if preset["supports_thinking"] and self.prefs.thinking_enabled:
                call_kwargs["extra_body"] = {"thinking": {"type": "enabled"}}

            response = client.chat.completions.create(**call_kwargs)

            full_text = ""
            if self.prefs.stream:
                for chunk in response:
                    if self._stop_flag:
                        break
                    reasoning = ""
                    content = ""
                    try:
                        delta = chunk.choices[0].delta
                        reasoning = getattr(delta, "reasoning_content", "") or ""
                        content = getattr(delta, "content", "") or ""
                    except Exception:
                        pass
                    if reasoning or content:
                        full_text += content
                        self.delta_ready.emit(reasoning, content)
            else:
                try:
                    full_text = response.choices[0].message.content or ""
                except Exception:
                    full_text = ""

            self.finished_text.emit(full_text)
        except Exception as e:
            util.logger.error(f"AI 调用失败: {e}\n{traceback.format_exc()}")
            self.failed.emit(str(e))
