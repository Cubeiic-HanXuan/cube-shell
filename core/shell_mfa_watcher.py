"""
Shell 层 MFA/OTP 提示检测器。

在 SSH 认证成功后，目标服务器可能通过 PAM 等机制在 shell 会话中
弹出二次验证提示（如 "Verification code: "）。本模块监控终端输出，
检测这类提示并通过信号通知 UI 层获取验证码。

重要：feed() 方法必须是非阻塞的，因为它在 _read_loop 线程中调用。
检测到提示后只返回提示文本，由调用方通过 Qt Signal 通知主线程弹对话框，
避免阻塞读取线程导致 channel 超时关闭。

典型场景：
- JumpServer 通过 KoKo 代理连接目标服务器，目标服务器开启了 Google Authenticator
- 服务器 PAM 配置了 google_authenticator，登录后显示 "Verification code: "
- Duo Security 等第三方 MFA 在 shell 层的 challenge 提示
"""
import re
import time

_ANSI_RE = re.compile(rb'\x1b\[[0-9;]*[a-zA-Z]|\x1b\][^\x07]*\x07|\x1b\][^\x1b]*\x1b\\|\x1b\[\?[0-9]+[hl]')

_PROMPT_PATTERNS = [
    r'verification\s+code(?:\s*\([^)]+\))?\s*[:?]',
    r'verify\s+code\s*[:?]',
    r'auth(?:entication|enticator)?\s+code\s*[:?]',
    r'enter\s+(?:your\s+)?(?:verification|auth(?:entication|enticator)?|otp|totp|6[-\s]?digit|one[-\s]?time)[^:]{0,40}\s*[:?]',
    r'otp\s*[:?]',
    r'totp\s*[:?]',
    r'one[-\s]?time\s+(?:password|code|token)\s*[:?]',
    r'6[-\s]?digit\s+code\s*[:?]',
    r'google\s+auth(?:enticator)?[^:]{0,30}\s*[:?]',
    r'(?:请(?:输入)?\s*)?(?:动态口令|动态密码|二次验证|两步验证|身份验证器|验证码|令牌)\s*[:?：]',
    r'\[?mfa[^:：\r\n]{0,30}[:?：]',
    r'passcode\s*[:?]',
    r'challenge\s*[:?]',
    r'\btoken\s*[:?]',
    r'\bcode\s*[:?]\s*$',
]

_PROMPT_RE = re.compile(
    rb'(?:^|\r\n|\n|\x1b\[\?25h|\x1b\[K|\x1b\[0m|\$\s|>\s|#\s)'
    rb'(?:' + b'|'.join(p.encode() for p in _PROMPT_PATTERNS) + rb')',
    re.IGNORECASE,
)

# 行级匹配（无前缀锚点），用于从缓冲区中提取具体的提示行展示给用户
_PROMPT_LINE_RE = re.compile(
    rb'(?:' + b'|'.join(p.encode() for p in _PROMPT_PATTERNS) + rb')',
    re.IGNORECASE,
)

_COOLDOWN_SECONDS = 5
_BUFFER_SIZE = 4096


def strip_ansi(data: bytes) -> bytes:
    return _ANSI_RE.sub(b'', data)


def looks_like_mfa_prompt(buffer: bytes) -> bool:
    if not buffer:
        return False
    text = strip_ansi(buffer)
    return bool(_PROMPT_RE.search(text))


class ShellMfaWatcher:
    """监控终端输出流，检测 MFA 提示。

    非阻塞设计：feed() 只做检测，返回提示文本或 None。
    由调用方通过 Qt Signal 将提示转发到主线程弹对话框，
    用户输入验证码后通过 send_shell_mfa_code() 回填 channel。
    这样 _read_loop 线程永远不会被 UI 操作阻塞。
    """

    def __init__(self):
        self._buffer = bytearray()
        self._last_trigger_ts = 0.0

    def feed(self, data: bytes) -> str | None:
        """喂入一段终端输出，检测到 MFA 提示时返回提示文本，否则返回 None。

        此方法是非阻塞的，可安全在 _read_loop 线程中调用。
        """
        if not data:
            return None

        self._buffer.extend(data)
        if len(self._buffer) > _BUFFER_SIZE:
            self._buffer = self._buffer[-_BUFFER_SIZE:]

        now = time.monotonic()
        if now - self._last_trigger_ts < _COOLDOWN_SECONDS:
            return None

        if not looks_like_mfa_prompt(bytes(self._buffer)):
            return None

        prompt_text = self._extract_prompt_line(bytes(self._buffer))

        self._buffer.clear()
        self._last_trigger_ts = now

        return prompt_text

    @staticmethod
    def _extract_prompt_line(buffer: bytes) -> str:
        """从缓冲区中提取匹配的提示行（而非整个缓冲区）。

        缓冲区可能包含进度动画、横幅等无关内容（如 KoKo 的连接倒计时），
        直接返回整个缓冲区会让对话框显示一堆乱码。
        """
        text = strip_ansi(buffer).decode('utf-8', errors='replace')
        lines = [line.strip() for line in re.split(r'[\r\n]+', text)]
        # 从后向前找第一个匹配提示模式的行（提示通常是最新输出）
        for line in reversed(lines):
            if line and _PROMPT_LINE_RE.search(line.encode('utf-8', errors='ignore')):
                return line
        # 兜底：返回最后一个非空行
        for line in reversed(lines):
            if line:
                return line
        return text.strip()
