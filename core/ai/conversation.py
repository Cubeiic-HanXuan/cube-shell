"""
AI SSH 运维对话上下文管理器模块

管理多轮对话的消息历史、命令执行结果上下文，
并提供上下文压缩和输出截断功能以适配 LLM token 限制。
"""

import re
from datetime import datetime


# ANSI 转义序列正则
_ANSI_ESCAPE_RE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?\x07|\x1b\[.*?\x1b\\')


def _strip_ansi(text: str) -> str:
    """移除文本中的 ANSI 转义序列"""
    return _ANSI_ESCAPE_RE.sub('', text)


class ConversationManager:
    """AI SSH 运维对话上下文管理器

    管理多轮对话的消息历史、命令执行结果上下文，
    并提供上下文压缩和输出截断功能以适配 LLM token 限制。
    """

    # 配置常量
    MAX_HISTORY_ROUNDS = 20          # 最大历史轮数
    MAX_OUTPUT_CHARS = 4000          # 单次输出最大字符数
    TRUNCATE_KEEP_CHARS = 2000       # 截断时首尾各保留字符数
    COMPRESS_THRESHOLD = 40          # 消息数超过此值时触发压缩

    def __init__(self, system_prompt: str = "", max_history: int = 20):
        """
        初始化对话管理器。

        Args:
            system_prompt: 系统提示词（角色定义 + 安全约束）
            max_history: 最大保留的对话轮数
        """
        self._system_prompt = system_prompt
        self._max_history = max_history
        self._messages: list[dict] = []  # {"role": "user"|"assistant", "content": str}
        self._command_results: list[dict] = []  # 命令执行结果记录

    @property
    def system_prompt(self) -> str:
        """获取系统提示词"""
        return self._system_prompt

    @system_prompt.setter
    def system_prompt(self, value: str):
        """设置系统提示词"""
        self._system_prompt = value

    def add_user_message(self, content: str) -> None:
        """添加用户消息

        Args:
            content: 用户输入的消息内容
        """
        self._messages.append({
            "role": "user",
            "content": content
        })
        self._compress_if_needed()

    def add_assistant_message(self, content: str) -> None:
        """添加 AI 助手消息

        Args:
            content: AI 助手回复的消息内容
        """
        self._messages.append({
            "role": "assistant",
            "content": content
        })
        self._compress_if_needed()

    def add_command_result(
        self,
        command: str,
        stdout: str,
        stderr: str,
        exit_code: int,
        description: str = ""
    ) -> None:
        """添加命令执行结果到上下文。

        会自动截断过长的输出，并清理 ANSI 转义序列。

        Args:
            command: 执行的命令
            stdout: 标准输出内容
            stderr: 标准错误内容
            exit_code: 命令退出码
            description: 命令的可选描述信息
        """
        # 清理 ANSI 转义序列
        clean_stdout = _strip_ansi(stdout) if stdout else ""
        clean_stderr = _strip_ansi(stderr) if stderr else ""

        # 截断过长的输出
        truncated_stdout = self._truncate_output(clean_stdout)
        truncated_stderr = self._truncate_output(clean_stderr)

        # 记录命令执行结果
        result = {
            "command": command,
            "stdout": truncated_stdout,
            "stderr": truncated_stderr,
            "exit_code": exit_code,
            "description": description,
            "timestamp": datetime.now().isoformat()
        }
        self._command_results.append(result)

        # 构建命令结果消息并添加到对话历史
        result_parts = [f"[命令执行结果]"]
        if description:
            result_parts.append(f"描述: {description}")
        result_parts.append(f"命令: {command}")
        result_parts.append(f"退出码: {exit_code}")

        if truncated_stdout:
            result_parts.append(f"标准输出:\n{truncated_stdout}")
        if truncated_stderr:
            result_parts.append(f"标准错误:\n{truncated_stderr}")

        result_content = "\n".join(result_parts)

        # 命令结果以 user 角色添加（模拟用户反馈执行结果给 AI）
        self._messages.append({
            "role": "user",
            "content": result_content
        })
        self._compress_if_needed()

    def build_messages(self) -> list[dict]:
        """构建完整的消息列表，供 LLM API 调用。

        返回格式兼容 OpenAI Chat Completions API：
        [{"role": "system", "content": ...}, {"role": "user", ...}, ...]

        Returns:
            消息列表，包含系统消息和对话历史
        """
        messages = []

        # 添加系统消息
        if self._system_prompt:
            messages.append({
                "role": "system",
                "content": self._system_prompt
            })

        # 添加对话历史
        messages.extend(self._messages)

        return messages

    def get_recent_commands(self, n: int = 5) -> list[dict]:
        """获取最近 N 条命令执行记录

        Args:
            n: 获取的记录数量，默认为 5

        Returns:
            最近的命令执行记录列表
        """
        return self._command_results[-n:] if self._command_results else []

    def clear(self) -> None:
        """清空所有对话历史和命令记录"""
        self._messages.clear()
        self._command_results.clear()

    def get_stats(self) -> dict:
        """获取对话统计信息

        Returns:
            包含轮数、命令数、消息数、估算 token 数等统计数据的字典
        """
        # 计算对话轮数（一轮 = 一对 user + assistant 消息）
        user_count = sum(1 for m in self._messages if m["role"] == "user")
        assistant_count = sum(1 for m in self._messages if m["role"] == "assistant")
        rounds = min(user_count, assistant_count)

        return {
            "rounds": rounds,
            "total_messages": len(self._messages),
            "user_messages": user_count,
            "assistant_messages": assistant_count,
            "command_results": len(self._command_results),
            "estimated_tokens": self._estimate_tokens(),
            "max_history": self._max_history,
        }

    def _truncate_output(self, text: str) -> str:
        """截断过长的命令输出。

        如果 text 长度超过 MAX_OUTPUT_CHARS：
            保留前 TRUNCATE_KEEP_CHARS 字符 +
            截断提示信息 +
            后 TRUNCATE_KEEP_CHARS 字符

        Args:
            text: 要检查的文本

        Returns:
            截断后的文本（或原文本，如果未超长）
        """
        if len(text) <= self.MAX_OUTPUT_CHARS:
            return text

        # 计算被截断的字符数
        truncated_chars = len(text) - self.TRUNCATE_KEEP_CHARS * 2
        head = text[:self.TRUNCATE_KEEP_CHARS]
        tail = text[-self.TRUNCATE_KEEP_CHARS:]

        return f"{head}\n\n... [已截断 {truncated_chars} 字符] ...\n\n{tail}"

    def _compress_if_needed(self) -> None:
        """上下文压缩策略。

        当消息数超过 COMPRESS_THRESHOLD 或超过 max_history * 2 时：
        1. 保留系统消息（不在 _messages 中，不受影响）
        2. 保留最近 max_history * 2 条消息
        3. 丢弃中间的旧消息（未来可扩展为 AI 摘要）
        """
        # 保留最近的消息数量（max_history * 2 条，对应 max_history 轮对话）
        keep_count = self._max_history * 2

        # 当消息数未超过压缩阈值且未超过保留上限时，不做处理
        if len(self._messages) <= self.COMPRESS_THRESHOLD and len(self._messages) <= keep_count:
            return

        if len(self._messages) > keep_count:
            # 丢弃最旧的消息，仅保留最近的 keep_count 条
            self._messages = self._messages[-keep_count:]

    def _estimate_tokens(self) -> int:
        """粗略估算当前上下文的 token 数。

        估算规则：
        - 中文字符约 1.5 字/token
        - 英文/ASCII 字符约 4 字符/token

        Returns:
            估算的 token 数量
        """
        total_chars = len(self._system_prompt)

        for msg in self._messages:
            total_chars += len(msg["content"])

        # 分别统计中文字符和非中文字符
        all_text = self._system_prompt + "".join(m["content"] for m in self._messages)

        chinese_chars = 0
        ascii_chars = 0

        for char in all_text:
            if '\u4e00' <= char <= '\u9fff':
                chinese_chars += 1
            else:
                ascii_chars += 1

        # 中文约 1.5 字/token，英文约 4 字符/token
        chinese_tokens = chinese_chars / 1.5
        ascii_tokens = ascii_chars / 4

        # 每条消息有额外的格式开销（约 4 token）
        overhead = (len(self._messages) + 1) * 4  # +1 为 system 消息

        return int(chinese_tokens + ascii_tokens + overhead)
