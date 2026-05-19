"""
AI 驱动 SSH 操作的核心代理模块。

SSHAIAgent 是 AI SSH 运维功能的核心调度中枢，负责：
- 处理用户自然语言输入并调用 LLM
- 使用 Function Calling 解析 AI 响应为可执行命令
- 对命令进行安全检查
- 异步执行命令并收集结果
- 执行失败时自动触发 AI 诊断
"""

from __future__ import annotations

import json
import re
import threading
import time
import traceback
import uuid
from typing import Optional

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Qt

from function import util
from .audit import AuditLogger
from .conversation import ConversationManager
from .prefs import AIUserPrefs, load_ai_prefs, get_provider_preset
from .safety import CommandSafetyChecker, RiskLevel, SafetyCheckResult
from .secrets import get_ai_api_key
from .server_profile import ServerProfileBuilder


# ──────────────────────────── Function Calling 工具定义 ────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "execute_ssh_commands",
            "description": "在远程SSH服务器上执行一组命令。注意根据当前连接用户的权限级别决定是否添加sudo前缀",
            "parameters": {
                "type": "object",
                "properties": {
                    "commands": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "cmd": {"type": "string", "description": "要执行的命令。重要：若当前非 root 用户，对需要超级权限的操作（apt/yum/dnf/systemctl/service/chmod/chown/mkdir -p /etc/等系统目录写入）必须以 sudo 开头"},
                                "description": {"type": "string", "description": "命令的用途说明"},
                                "allow_failure": {"type": "boolean", "description": "是否允许失败"},
                                "interactive": {
                                    "type": "boolean",
                                    "description": "是否在用户的终端中执行（默认 true）。true 时命令会被发送到当前 SSH 终端窗口执行，天然支持密码/passphrase/y-n 等人工交互。仅在需要静默后台执行并精确抓取 stdout/stderr 的查询类场景（如查看服务状态/读取配置文件）才设为 false。"
                                }
                            },
                            "required": ["cmd", "description"]
                        }
                    },
                    "explanation": {"type": "string", "description": "整体方案说明"}
                },
                "required": ["commands", "explanation"]
            }
        }
    }
]


# ──────────────────────────── 内部工作线程 ────────────────────────────


class _FunctionProxy:
    """将 dict 模拟为具有属性的函数对象。"""
    def __init__(self, data: dict):
        self.name = data.get("name", "")
        self.arguments = data.get("arguments", "")


class _ToolCallProxy:
    """将 dict 模拟为 tool_call 对象，兼容 _parse_tool_calls。"""
    def __init__(self, data: dict):
        self.id = data.get("id", "")
        self.type = data.get("type", "function")
        self.function = _FunctionProxy(data.get("function", {}))


class _AIWorkerThread(QThread):
    """AI 请求工作线程，用于在后台执行 LLM 调用。"""

    result_ready = Signal(object)   # AI 响应结果 (dict)
    error = Signal(str)             # 错误信息
    delta_ready = Signal(str, str)  # 流式增量 (reasoning, content)

    def __init__(self, prefs: AIUserPrefs, messages: list[dict], tools=None, parent=None):
        super().__init__(parent)
        self._prefs = prefs
        self._messages = messages
        self._tools = tools
        self._stop_flag = False
        # 流式增量节流：防止高频 emit 导致 UI 主线程事件队列溢出 SIGABRT
        self._last_delta_emit_time: float = 0.0
        self._DELTA_EMIT_INTERVAL: float = 0.08  # 最小间隔 80ms（约 12fps，足够流畅）
        self._pending_reasoning: str = ""
        self._pending_content: str = ""

    def request_stop(self):
        """请求软停止"""
        self._stop_flag = True

    def _flush_delta(self, force: bool = False) -> None:
        """节流刷新 delta_ready 信号。

        将 chunk 累积在 _pending_* 缓冲，仅当达到最小间隔或 force=True 时才 emit，
        避免 SSE 高频 chunk 导致 UI 主线程事件队列溢出引发 SIGABRT。
        """
        if not self._pending_reasoning and not self._pending_content:
            return
        now = time.time()
        if not force and (now - self._last_delta_emit_time) < self._DELTA_EMIT_INTERVAL:
            return
        self.delta_ready.emit(self._pending_reasoning, self._pending_content)
        self._pending_reasoning = ""
        self._pending_content = ""
        self._last_delta_emit_time = now

    def run(self):
        try:
            from openai import OpenAI

            api_key = get_ai_api_key(self._prefs.provider)
            if not api_key:
                self.error.emit('未配置 API Key，请在「设置 -> AI 设置」中配置')
                return

            preset = get_provider_preset(self._prefs.provider)
            base_url = self._prefs.base_url or preset["base_url"]
            client = OpenAI(api_key=api_key, base_url=base_url)

            # 构建请求参数 - 使用流式
            call_kwargs = {
                "model": self._prefs.model,
                "messages": self._messages,
                "max_tokens": self._prefs.max_tokens,
                "temperature": self._prefs.temperature,
                "stream": True,
            }
            if preset["supports_thinking"] and self._prefs.thinking_enabled:
                call_kwargs["thinking"] = {"type": "enabled"}
            if self._tools:
                call_kwargs["tools"] = self._tools
                call_kwargs["tool_choice"] = "auto"

            response = client.chat.completions.create(**call_kwargs)

            full_content = ""
            full_reasoning = ""
            tool_calls_data = []  # 收集 tool_calls 的增量片段

            for chunk in response:
                if self._stop_flag:
                    break

                choices = getattr(chunk, 'choices', None)
                if not choices:
                    continue
                choice = choices[0]
                delta = getattr(choice, 'delta', None)
                if delta is None:
                    continue

                # 处理文本内容增量（节流发射，防止 SIGABRT）
                reasoning = getattr(delta, "reasoning_content", "") or ""
                content = getattr(delta, "content", "") or ""
                if reasoning or content:
                    full_reasoning += reasoning
                    full_content += content
                    self._pending_reasoning += reasoning
                    self._pending_content += content
                    self._flush_delta(force=False)

                # 处理 tool_calls 增量
                tc_list = getattr(delta, "tool_calls", None)
                if tc_list:
                    for tc in tc_list:
                        idx = getattr(tc, 'index', 0) or 0
                        while len(tool_calls_data) <= idx:
                            tool_calls_data.append({
                                "id": "", "type": "function",
                                "function": {"name": "", "arguments": ""}
                            })
                        tc_id = getattr(tc, 'id', None)
                        if tc_id:
                            tool_calls_data[idx]["id"] = tc_id
                        tc_func = getattr(tc, 'function', None)
                        if tc_func:
                            fname = getattr(tc_func, 'name', None)
                            if fname:
                                tool_calls_data[idx]["function"]["name"] += fname
                            fargs = getattr(tc_func, 'arguments', None)
                            if fargs:
                                tool_calls_data[idx]["function"]["arguments"] += fargs

            # 流结束，强制刷新最后一段缓冲增量
            self._flush_delta(force=True)

            if self._stop_flag:
                return

            # 将收集到的 tool_calls 转换为代理对象以兼容 _parse_tool_calls
            final_tool_calls = None
            if tool_calls_data:
                final_tool_calls = [_ToolCallProxy(tc) for tc in tool_calls_data]

            result = {
                "content": full_content,
                "tool_calls": final_tool_calls,
                "role": "assistant",
            }
            self.result_ready.emit(result)

        except Exception as e:
            util.logger.error(f"AI 调用失败: {e}\n{traceback.format_exc()}")
            self.error.emit(str(e))


class _ProfileRefreshThread(QThread):
    """后台线程：异步刷新服务器画像。"""
    done = Signal(object)

    def __init__(self, builder, parent=None):
        super().__init__(parent)
        self._builder = builder

    def run(self):
        try:
            profile = self._builder.build()
            self.done.emit(profile)
        except Exception:
            self.done.emit(None)


class _TerminalExecutor(QObject):
    """主线程 QObject，负责将交互式命令发到当前 QTermWidget 终端执行。

    在命令末尾追加哨兵 ``; echo __CUBE_AI_END__:<id>:$?``，通过监听
    ``receivedData`` 信号抓取到哨兵即可获得退出码与实际输出。
    提供给工作线程调用的 ``run_blocking`` 接口：内部通过
    跨线程信号将 sendText 动作投递到主线程执行（QTimer.singleShot
    在没有事件循环的 QThread 里会失效），通过 ``threading.Event`` 同步等待完成。
    """

    _SENTINEL_PREFIX = "__CUBE_AI_END__"
    _SENTINEL_RE = re.compile(r"__CUBE_AI_END__:(\d+):(-?\d+)")
    _ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

    # 跨线程投递信号：从工作线程 emit，通过 QueuedConnection 在主线程执行 _dispatch
    _request_dispatch = Signal(str, object, object)  # (cmd, event, holder)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._terminal = None
        self._buffer: str = ""
        self._current_id: int = 0
        self._current_event: Optional[threading.Event] = None
        self._current_holder: Optional[dict] = None
        self._cmd_id_seq: int = 0
        self._lock = threading.Lock()
        # 已为哪些终端实例注入过分页器/交互变量（同一 shell 会话中只需一次）
        # 使用 set 存对象 id；终端重建时 id 可能复用，但 set_terminal 会重置标记。
        self._env_initialized_term_ids: set = set()
        # 必须在主线程连接，使用 QueuedConnection 保证投递到主线程 EventLoop
        self._request_dispatch.connect(self._dispatch, Qt.QueuedConnection)

    # ---------- 主线程 API ----------

    def set_terminal(self, terminal) -> None:
        """设置（或切换）要使用的终端。仅主线程调用。"""
        if self._terminal is terminal:
            return
        # 断开旧连接
        if self._terminal is not None and hasattr(self._terminal, 'receivedData'):
            try:
                self._terminal.receivedData.disconnect(self._on_received)
            except (RuntimeError, TypeError):
                pass
            # 旧终端不再使用，清理其环境初始化标记
            self._env_initialized_term_ids.discard(id(self._terminal))
        self._terminal = terminal
        if terminal is not None and hasattr(terminal, 'receivedData'):
            # receivedData 在主线程 emit，同线程使用 DirectConnection 立即响应
            terminal.receivedData.connect(self._on_received, Qt.DirectConnection)

    def has_terminal(self) -> bool:
        return self._terminal is not None and hasattr(self._terminal, 'sendText')

    def cancel(self) -> None:
        """主动取消当前等待，让 ``run_blocking`` 立即返回。

        用于其他线程（如 UI 点击“停止”按钮）强制中断卡住的交互命令，
        避免哨兵丢失后工作线程一直阻塞在 ``event.wait`` 上。
        """
        ev = self._current_event
        holder = self._current_holder
        if ev is not None and holder is not None:
            holder.setdefault("exit_code", -1)
            holder.setdefault("output", "(用户取消与终端的交互命令)")
            try:
                ev.set()
            except Exception:
                pass
        self._current_event = None
        self._current_holder = None
        self._buffer = ""

    # ---------- 工作线程 API（阻塞） ----------

    def run_blocking(self, cmd: str, timeout: float = 180.0) -> tuple[int, str]:
        """同步执行一条交互命令，返回 (exit_code, output)。

        允许从 QThread 工作线程调用。内部通过 QTimer.singleShot 将
        sendText 投递到主线程执行，避免跨线程操作 QWidget。
        """
        if not self.has_terminal():
            return -1, "(当前无可用的终端，无法执行交互命令)"

        # 串行化：同一时间只能有一条交互命令在终端中
        with self._lock:
            event = threading.Event()
            holder: dict = {}
            # 使用跨线程信号投递到主线程 EventLoop（QTimer.singleShot 在无事件循环的 QThread 里不生效）
            self._request_dispatch.emit(cmd, event, holder)
            finished = event.wait(timeout)
            if not finished:
                # 超时 — 清理状态避免后续数据误伤
                self._current_event = None
                self._current_holder = None
                self._buffer = ""
                return -1, "(交互命令执行超时)"
            return int(holder.get("exit_code", -1)), str(holder.get("output", ""))

    # ---------- 内部（主线程） ----------

    def _dispatch(self, cmd: str, event: threading.Event, holder: dict) -> None:
        self._cmd_id_seq += 1
        self._current_id = self._cmd_id_seq
        self._current_event = event
        self._current_holder = holder
        self._buffer = ""
        # 禁用各类分页器：避免 systemctl status / git log / journalctl / man 等命令调起 less，
        # less 会进入 alternate screen 等用户按 q，导致后面的哨兵永远不会执行，进而卡死 run_blocking。
        # LESS=FRX: -F 输出不满一屏时自动退出；-R 保留颜色；-X 不进入 alt screen。
        # 哨兵机制采用 PROMPT_COMMAND 钩子（方案 B）：
        #   1) 首次初始化时定义 __cube_end 函数与 PROMPT_COMMAND——bash 会在每条命令
        #      执行完、显示 PS1 之前自动调用一次 __cube_end。
        #   2) 每次 dispatch 只发 "_CUBE_ID=<id>; <cmd>" 这一行，不再额外追加哨兵调用。
        # 这样可以彻底陣住以下场景：
        #   - sudo 贪婪读 PTY 缓冲映身为密码：同一主输入循环只有一行，哨兵从未进入 PTY 缓冲
        #     区、sudo 拿不到 "下一行" 当密码（与之前“换行连接哨兵”被吃的 bug 隔离）。
        #   - heredoc / for / if / case 多行语句：bash 读完整个逻辑语句后才触发 PROMPT_COMMAND，
        #     不会出现“哨兵提前输出”。
        #   - 窄终端折行：哨兵 echo 来自 PROMPT_COMMAND 内部调用、未被 bash 回显（函数调用不 echo），
        #     只需清一行 "echo 输出行" 即可，清行收峰几乎不会失败。
        term_id = id(self._terminal) if self._terminal is not None else 0
        if term_id and term_id not in self._env_initialized_term_ids:
            try:
                # __cube_end 函数要点：
                #   - 首行 `local rc=$?`：捕获“上一条主命令”的退出码（PROMPT_COMMAND 运行于
                #     命令完成之后、PS1 打印之前）。
                #   - `[ -n "$_CUBE_ID" ] || return`：只有 AI 下发的命令（设过 _CUBE_ID）才输出哨兵；
                #     用户在终端中手动敲的命令 / 空回车 不会打印哨兵。
                #   - 打印后立刻置 _CUBE_ID 为空，避免重复输出。
                #   - 末尾 printf 上移一行清行，把“__CUBE_AI_END__:N:rc”输出行从终端视图中抹掉。
                init_line = (
                    "export PAGER=cat SYSTEMD_PAGER=cat GIT_PAGER=cat MANPAGER=cat "
                    "DEBIAN_FRONTEND=noninteractive LESS=FRX > /dev/null 2>&1; "
                    "__cube_end() { local rc=$?; [ -n \"$_CUBE_ID\" ] || return; "
                    f"echo \"{self._SENTINEL_PREFIX}:$_CUBE_ID:$rc\"; "
                    "_CUBE_ID=\"\"; "
                    "printf '\\033[A\\033[2K\\r'; }; "
                    "PROMPT_COMMAND='__cube_end'; "
                    "printf '\\033[A\\033[2K\\r'\n"
                )
                self._terminal.sendText(init_line)
                self._env_initialized_term_ids.add(term_id)
            except Exception:
                pass
        # 必须用“单行 + 分号”拼接 _CUBE_ID 赋值与主命令，不能用换行：
        #   - 如果用换行，bash 读完 "_CUBE_ID=N" 后会触发一次 PROMPT_COMMAND，
        #     此时 _CUBE_ID 已设、主命令还未执行，__cube_end 会提前输出哨兵、并提前清空 _CUBE_ID，
        #     导致主命令完成后的二次 PROMPT_COMMAND 不再输出哨兵 → run_blocking 超时卡死。
        #   - 单行 “_CUBE_ID=N; <cmd>” 则是一个主输入循环、一次 PROMPT_COMMAND，$? 是 <cmd> 的退出码。
        # cmd 本身可以含多行（heredoc / if/for/case），bash 会读完整个逻辑语句后才触发 PROMPT_COMMAND。
        sep = "" if cmd.endswith("\n") else "\n"
        wrapped = f"_CUBE_ID={self._current_id}; {cmd}{sep}"
        # 兼容性兑底：若该终端的 shell 不支持 local / PROMPT_COMMAND（如 dash），__cube_end
        # 不会被调用，哨兵不会输出，run_blocking 走超时分支返回。这种环境极少见。
        try:
            self._terminal.sendText(wrapped)
        except Exception as e:
            holder["exit_code"] = -1
            holder["output"] = f"(发送到终端失败: {e})"
            event.set()
            self._current_event = None
            self._current_holder = None

    def _on_received(self, text: str) -> None:
        if self._current_event is None or self._current_holder is None:
            return
        # 提前清洗 ANSI 转义与 \r，避免哨兵被颜色序列/光标控制等转义字符插入中间导致正则失配
        clean = self._ANSI_RE.sub("", text).replace("\r", "")
        self._buffer += clean
        # 查找本次命令的哨兵（按 id 区分，避免历史输出误匹配）
        for m in self._SENTINEL_RE.finditer(self._buffer):
            cmd_id = int(m.group(1))
            if cmd_id != self._current_id:
                continue
            exit_code = int(m.group(2))
            # 提取命令输出：哨兵之前的全部内容（buffer 已提前清洗 ANSI/\r），
            # 去掉包含哨兵拼接的原始命令行回显（含 SENTINEL_PREFIX 的开头行）
            raw = self._buffer[:m.start()]
            lines = [
                ln for ln in raw.splitlines()
                if self._SENTINEL_PREFIX not in ln
            ]
            output = "\n".join(lines).strip()
            self._current_holder["exit_code"] = exit_code
            self._current_holder["output"] = output
            self._current_event.set()
            self._current_event = None
            self._current_holder = None
            self._buffer = ""
            return


class _CommandExecThread(QThread):
    """命令执行工作线程，在后台通过 SSH 执行命令。"""

    command_started = Signal(str)         # 开始执行某命令
    command_finished = Signal(dict)       # 单条命令执行完成
    all_finished = Signal(list)           # 全部命令执行完毕
    error = Signal(str)                   # 执行错误
    progress = Signal(int, int)           # (当前序号, 总数)
    output_stream = Signal(str)           # 实时输出流（用于显示下载进度等）

    def __init__(self, ssh_client, commands: list[dict], parent=None,
                 terminal_executor: Optional["_TerminalExecutor"] = None):
        super().__init__(parent)
        self._ssh = ssh_client
        self._commands = commands
        self._stop_flag = False
        self._last_emit_time: float = 0.0          # 上次发射 output_stream 的时间
        self._EMIT_INTERVAL: float = 0.2            # 最小发射间隔（秒），防止高频更新导致 UI 崩溃
        self._terminal_executor = terminal_executor

    def request_stop(self):
        self._stop_flag = True
        # 同步唤醒可能阻塞在 _TerminalExecutor.run_blocking 里的 event.wait，
        # 避免工作线程“只设了标志位但出不去”，也避免 _lock 一直被占住导致后续命令无法进入。
        if self._terminal_executor is not None:
            try:
                self._terminal_executor.cancel()
            except Exception:
                pass

    def run(self):
        results = []
        total = len(self._commands)
        for i, cmd_info in enumerate(self._commands):
            if self._stop_flag:
                break

            cmd = cmd_info.get("cmd", "")
            description = cmd_info.get("description", "")
            allow_failure = cmd_info.get("allow_failure", False)
            # 强制：所有 AI 下发命令一律走当前终端执行，天然支持密码/passphrase/y-n 等交互。
            # 不再读取 cmd_info["interactive"]，避免 AI 误判导致命令走 paramiko 而卡死在密码提示。
            interactive = True

            self.progress.emit(i + 1, total)
            self.command_started.emit(cmd)

            try:
                start_time = time.time()
                if self._terminal_executor is not None and self._terminal_executor.has_terminal():
                    exit_code, stdout, stderr = self._execute_interactive(cmd)
                else:
                    # 没绑定终端 → 明确告知用户，不要静默降级到 paramiko，否则一旦遇到密码就死等
                    exit_code = -1
                    stdout = ""
                    stderr = (
                        "(未绑定 SSH 终端，无法执行命令。请确认 AI 面板已关联到一个已打开的 SSH Tab，"
                        "或切换到目标 Tab 后重试。)"
                    )
                duration_ms = int((time.time() - start_time) * 1000)

                result = {
                    "cmd": cmd,
                    "description": description,
                    "exit_code": exit_code,
                    "stdout": stdout,
                    "stderr": stderr,
                    "duration_ms": duration_ms,
                    "allow_failure": allow_failure,
                    "interactive": interactive,
                }
                results.append(result)
                self.command_finished.emit(result)

                # 如果命令失败且不允许失败，停止后续执行
                if exit_code != 0 and not allow_failure:
                    break

            except Exception as e:
                result = {
                    "cmd": cmd,
                    "description": description,
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": str(e),
                    "duration_ms": 0,
                    "allow_failure": allow_failure,
                }
                results.append(result)
                self.command_finished.emit(result)
                self.error.emit(f"执行命令失败 [{cmd}]: {e}")
                if not allow_failure:
                    break

        self.all_finished.emit(results)

    def _execute_interactive(self, cmd: str) -> tuple[int, str, str]:
        """交互式命令：在用户当前 QTermWidget 终端中执行。

        由 _TerminalExecutor 负责发送哨兵包装后的命令并接收退出码。
        用户可在终端中直接响应提示（密码、y/n、passphrase 等）。
        """
        if self._terminal_executor is None or not self._terminal_executor.has_terminal():
            return -1, "", "(未连接终端或终端不可用，无法执行交互命令)"
        try:
            exit_code, output = self._terminal_executor.run_blocking(cmd, timeout=1800.0)
            # 交互命令不区分 stdout/stderr，统一放 stdout
            return exit_code, output, ""
        except Exception as e:
            return -1, "", f"交互命令执行异常: {e}"

    def _execute_single(self, cmd: str) -> tuple[int, str, str]:
        """执行单条命令，返回 (exit_code, stdout, stderr)。

        通过 paramiko 的 exec_command 获取完整输出和退出码。
        使用 bash -l -c 包装命令，确保加载用户环境变量（如 JAVA_HOME、PATH 等）。
        自动检测 sudo 命令并通过 stdin 传入密码，解决非交互式 Shell 无法输入密码的问题。
        对下载/安装等长时间命令使用流式读取，实时推送输出到 UI。
        """
        # 检测命令是否包含 sudo，如果是则替换为 sudo -S（从 stdin 读取密码）
        needs_sudo_password = self._needs_sudo_password(cmd)
        if needs_sudo_password:
            cmd = self._inject_sudo_stdin_flag(cmd)

        # 检测是否为长时间命令（需要流式输出）
        is_long_running = self._is_long_running_command(cmd)
        timeout = 600 if is_long_running else 120

        # 用 bash -l -c 包装，使其作为登录 Shell 执行，加载 /etc/profile 和 ~/.bashrc
        escaped_cmd = cmd.replace("'", "'\\''")
        wrapped_cmd = f"bash -l -c '{escaped_cmd}'"

        try:
            if hasattr(self._ssh, 'conn') and self._ssh.conn:
                stdin, stdout_ch, stderr_ch = self._ssh.conn.exec_command(
                    command=wrapped_cmd, timeout=timeout
                )
                # 如果命令需要 sudo 密码，通过 stdin 传入
                if needs_sudo_password and hasattr(self._ssh, 'password') and self._ssh.password:
                    stdin.write(f"{self._ssh.password}\n")
                    stdin.flush()

                if is_long_running:
                    # 流式读取：同时监控 stdout 和 stderr，实时推送输出
                    stdout_text, stderr_text = self._stream_read_output(stdout_ch, stderr_ch)
                else:
                    # 普通命令：一次性读取
                    stdout_text = stdout_ch.read().decode('utf-8', errors='replace')
                    stderr_text = stderr_ch.read().decode('utf-8', errors='replace')

                exit_code = stdout_ch.channel.recv_exit_status()
                return exit_code, stdout_text, stderr_text
            else:
                output = self._ssh.exec(cmd=wrapped_cmd, pty=False) or ""
                return 0, output, ""
        except Exception as e:
            raise RuntimeError(f"SSH 命令执行异常: {e}") from e

    def _throttled_emit(self, text: str) -> None:
        """节流发射 output_stream 信号，防止高频更新导致 UI 崩溃。

        wget/curl 的 \r 进度更新可能每秒触发几十次，如果每次都 emit 会使
        UI 事件队列溢出，导致 SIGABRT 崩溃。这里限制最小间隔为 _EMIT_INTERVAL。
        """
        if not text:
            return
        now = time.time()
        if now - self._last_emit_time >= self._EMIT_INTERVAL:
            self.output_stream.emit(text)
            self._last_emit_time = now

    def _stream_read_output(self, stdout_ch, stderr_ch) -> tuple[str, str]:
        """流式读取 stdout 和 stderr，实时推送进度到 UI。

        wget/curl 等工具的下载进度输出到 stderr，因此必须同时监控两个流。
        使用节流机制（_throttled_emit）避免高频信号导致 UI 崩溃。

        Returns:
            (stdout_text, stderr_text) 元组
        """
        channel = stdout_ch.channel
        stdout_lines = []
        stderr_lines = []
        stdout_buf = ""
        stderr_buf = ""

        while not channel.exit_status_ready() or channel.recv_ready() or channel.recv_stderr_ready():
            if self._stop_flag:
                break

            got_data = False

            # 读取 stdout
            if channel.recv_ready():
                chunk = channel.recv(4096).decode('utf-8', errors='replace')
                stdout_buf += chunk
                got_data = True
                while '\n' in stdout_buf:
                    line, stdout_buf = stdout_buf.split('\n', 1)
                    stdout_lines.append(line)
                    self._throttled_emit(line.rstrip())
                if '\r' in stdout_buf:
                    parts = stdout_buf.split('\r')
                    self._throttled_emit(parts[-1].rstrip())
                    stdout_buf = parts[-1]

            # 读取 stderr（wget/curl 进度条输出在这里）
            if channel.recv_stderr_ready():
                chunk = channel.recv_stderr(4096).decode('utf-8', errors='replace')
                stderr_buf += chunk
                got_data = True
                while '\n' in stderr_buf:
                    line, stderr_buf = stderr_buf.split('\n', 1)
                    stderr_lines.append(line)
                    self._throttled_emit(line.rstrip())
                # 处理 \r 覆盖行（wget/curl 进度条用 \r 刷新同一行）
                if '\r' in stderr_buf:
                    parts = stderr_buf.split('\r')
                    self._throttled_emit(parts[-1].rstrip())
                    stderr_buf = parts[-1]

            if not got_data:
                time.sleep(0.1)

        # 读取剩余数据
        try:
            remaining_out = stdout_ch.read().decode('utf-8', errors='replace')
            if remaining_out:
                stdout_buf += remaining_out
        except Exception:
            pass
        try:
            remaining_err = stderr_ch.read().decode('utf-8', errors='replace')
            if remaining_err:
                stderr_buf += remaining_err
        except Exception:
            pass

        if stdout_buf.strip():
            stdout_lines.append(stdout_buf)
        if stderr_buf.strip():
            stderr_lines.append(stderr_buf)

        return '\n'.join(stdout_lines), '\n'.join(stderr_lines)

    @staticmethod
    def _is_long_running_command(cmd: str) -> bool:
        """判断命令是否为长时间运行命令（需要流式输出）。"""
        import re
        _LONG_RUNNING_PATTERNS = [
            r'\bwget\b', r'\bcurl\b.*(-o|-O|--output)',
            r'\bcurl\b.*\|',
            r'\bapt\b', r'\bapt-get\b',
            r'\byum\b', r'\bdnf\b',
            r'\bpacman\b', r'\bzypper\b',
            r'\bpip\s+install\b', r'\bnpm\s+install\b',
            r'\byarn\s+(add|install)\b',
            r'\bmake\b', r'\bmvn\b', r'\bgradle\b',
            r'\bdocker\s+(pull|build)\b',
            r'\bgit\s+clone\b',
            r'\brsync\b', r'\bscp\b',
        ]
        for pattern in _LONG_RUNNING_PATTERNS:
            if re.search(pattern, cmd):
                return True
        return False

    def _needs_sudo_password(self, cmd: str) -> bool:
        """判断命令是否需要 sudo 密码。

        如果当前用户是 root，则不需要密码。
        如果命令中包含 sudo 且已经有 -S 标志，则不需要重复处理。
        """
        # root 用户不需要 sudo 密码
        if hasattr(self._ssh, 'username') and self._ssh.username == 'root':
            return False
        # 检查命令中是否包含 sudo
        import re
        # 匹配命令中的 sudo（作为独立单词）
        if not re.search(r'\bsudo\b', cmd):
            return False
        # 已经有 -S 标志的不需要再处理
        if re.search(r'\bsudo\s+.*-S', cmd) or re.search(r'\bsudo\s+-S', cmd):
            return False
        return True

    def _inject_sudo_stdin_flag(self, cmd: str) -> str:
        """将命令中的 sudo 替换为 sudo -S，使其从 stdin 读取密码。"""
        import re
        # 将 "sudo " 替换为 "sudo -S "，保留其他参数
        return re.sub(r'\bsudo\b(?!\s*-S)', 'sudo -S', cmd)


# ──────────────────────────── SSHAIAgent 核心类 ────────────────────────────


class SSHAIAgent(QObject):
    """AI 驱动 SSH 操作的核心代理。

    作为 AI SSH 运维功能的调度中枢，协调 LLM 调用、命令安全检查、
    命令执行和审计日志等子系统。
    """

    # ────────── 信号定义 ──────────
    command_ready = Signal(list)        # 命令就绪 (待确认), list of dict
    execution_started = Signal(str)     # 开始执行某命令
    execution_finished = Signal(dict)   # 执行完成 (含结果)
    ai_message = Signal(str, str)       # AI 消息 (reasoning, content)
    error_occurred = Signal(str)        # 错误发生
    thinking_started = Signal()         # AI 开始思考
    thinking_finished = Signal()        # AI 思考结束
    execution_progress = Signal(int, int)   # (当前, 总数)
    diagnosing_started = Signal()           # AI 开始诊断失败命令
    task_summary = Signal(str)              # 任务执行总结
    command_output = Signal(str)            # 命令实时输出（下载进度等）

    def __init__(self, ssh_client, prefs: AIUserPrefs = None, parent=None):
        """
        初始化 AI SSH 代理。

        Args:
            ssh_client: SSH 客户端实例（鸭子类型，需有 conn 属性或 exec 方法）
            prefs: AI 偏好设置，为 None 时自动加载
            parent: QObject 父对象
        """
        super().__init__(parent)

        self._ssh_client = ssh_client
        self._prefs = prefs or load_ai_prefs()
        self._session_id = str(uuid.uuid4())

        # 缓存服务器画像（必须在 _build_system_prompt 之前初始化）
        self._server_profile = None

        # 任务目标跟踪（用于验证闭环）
        self._original_goal: str = ""         # 用户原始任务目标
        self._is_diagnosing: bool = False      # 是否在诊断/修复流程中
        self._goal_verify_count: int = 0       # 验证次数（防止无限循环）
        self._MAX_VERIFY_ROUNDS: int = 3       # 最多验证轮数

        # 子系统初始化
        self._safety_checker = CommandSafetyChecker()
        self._audit_logger = AuditLogger()
        self._profile_builder = ServerProfileBuilder(ssh_client)
        self._conversation = ConversationManager(
            system_prompt=self._build_system_prompt(),
            max_history=20,
        )

        # 交互命令执行器（用于 interactive=true 的命令发到终端中执行）
        self._terminal_executor = _TerminalExecutor(parent=self)

        # 工作线程引用
        self._ai_worker: Optional[_AIWorkerThread] = None
        self._exec_worker: Optional[_CommandExecThread] = None
        self._profile_thread: Optional[_ProfileRefreshThread] = None

    # ──────────────────────────── 公共接口 ────────────────────────────

    def set_terminal(self, terminal) -> None:
        """设置（或切换）交互式命令要使用的终端。

        主程序应在 SSH Tab 切换、重连、创建新连接时调用本方法，传入
        当前 Tab 的 QTermWidget 实例（或 None 以断开）。仅交互命令会
        使用该终端，普通命令仍然走 paramiko exec_command 独立通道。
        """
        if hasattr(self, '_terminal_executor') and self._terminal_executor is not None:
            self._terminal_executor.set_terminal(terminal)

    def process_user_input(self, user_input: str) -> None:
        """
        处理用户自然语言输入（异步，在工作线程执行 AI 调用）。

        流程：
        1. 使用缓存的服务器画像构建系统提示词（不阻塞主线程）
        2. 通过 ConversationManager 构建消息列表
        3. 使用 Function Calling 方式调用 LLM（流式）
        4. 解析 AI 响应，提取命令列表
        5. 对每条命令用 CommandSafetyChecker 做安全检查
        6. 发射 command_ready 信号（附带命令 + 安全检查结果）

        Args:
            user_input: 用户输入的自然语言文本
        """
        if not user_input.strip():
            return

        # 记录原始任务目标（只记录用户真实输入，不记录内部诊断/验证提示词）
        if not self._is_diagnosing:
            self._original_goal = user_input
            self._goal_verify_count = 0

        # 使用缓存的画像构建 system prompt（不阻塞）
        self._conversation.system_prompt = self._build_system_prompt()

        # 添加用户消息到对话历史
        self._conversation.add_user_message(user_input)

        # 构建消息列表
        messages = self._conversation.build_messages()

        # 发射思考开始信号
        self.thinking_started.emit()

        # 启动 AI 工作线程（跨线程信号必须显式 QueuedConnection，否则可能退化为
        # DirectConnection 导致槽函数在工作线程执行 → SIGABRT）
        self._ai_worker = _AIWorkerThread(
            prefs=self._prefs,
            messages=messages,
            tools=TOOLS,
            parent=self,
        )
        self._ai_worker.result_ready.connect(self._on_ai_result, Qt.QueuedConnection)
        self._ai_worker.delta_ready.connect(self._on_ai_delta, Qt.QueuedConnection)
        self._ai_worker.error.connect(self._on_ai_error, Qt.QueuedConnection)
        self._ai_worker.finished.connect(self._on_ai_worker_finished, Qt.QueuedConnection)
        self._ai_worker.start()

        # 异步刷新画像（供下次使用）
        self._async_refresh_profile()

    def execute_commands(self, commands: list[dict]) -> None:
        """
        执行已确认的命令列表（异步，在工作线程执行）。

        通过 ssh_client 执行每条命令，发射执行状态信号，
        并将结果记入对话上下文和审计日志。

        Args:
            commands: 命令列表，每个元素为 dict：
                      {"cmd": str, "description": str, "allow_failure": bool}
        """
        if not commands:
            return

        # 自愈防线：如果上一轮 exec_worker 还在跑（常见于哨兵丢失导致 run_blocking 被锁在 wait 里），
        # 必须先取消旧交互命令使其释放 _TerminalExecutor._lock，否则新 worker 会被 with self._lock 永久阻塞。
        if self._exec_worker is not None and self._exec_worker.isRunning():
            try:
                self._exec_worker.request_stop()
            except Exception:
                pass
            try:
                self._terminal_executor.cancel()
            except Exception:
                pass

        self._exec_worker = _CommandExecThread(
            ssh_client=self._ssh_client,
            commands=commands,
            parent=self,
            terminal_executor=self._terminal_executor,
        )
        # 全链路显式 Qt.QueuedConnection，确保槽函数在主线程执行
        self._exec_worker.command_started.connect(self._on_exec_started, Qt.QueuedConnection)
        self._exec_worker.command_finished.connect(self._on_exec_finished, Qt.QueuedConnection)
        self._exec_worker.all_finished.connect(self._on_all_exec_finished, Qt.QueuedConnection)
        self._exec_worker.error.connect(self._on_exec_error, Qt.QueuedConnection)
        self._exec_worker.progress.connect(
            lambda cur, tot: self.execution_progress.emit(cur, tot),
            Qt.QueuedConnection,
        )
        self._exec_worker.output_stream.connect(self.command_output.emit, Qt.QueuedConnection)
        self._exec_worker.start()

    def diagnose_error(self, command: str, stdout: str, stderr: str, exit_code: int) -> None:
        """对执行失败的命令触发 AI 诊断。

        Args:
            command: 失败的命令
            stdout: 标准输出
            stderr: 标准错误
            exit_code: 退出码
        """
        self._is_diagnosing = True
        diag_prompt = (
            f"刚才执行的命令失败了，请帮我诊断原因并给出修复建议。\n\n"
            f"命令: {command}\n"
            f"退出码: {exit_code}\n"
        )
        if stdout:
            diag_prompt += f"标准输出:\n{stdout[:2000]}\n"
        if stderr:
            diag_prompt += f"标准错误:\n{stderr[:2000]}\n"
        diag_prompt += (
            f"\n用户的原始任务是：{self._original_goal}\n"
            f"请分析问题原因并提供修复方案，确保最终完成用户的任务。"
            f"如果需要执行修复命令，请使用 execute_ssh_commands 工具。"
        )

        self.process_user_input(diag_prompt)

    def stop(self) -> None:
        """停止当前正在运行的 AI 请求或命令执行。"""
        if self._ai_worker and self._ai_worker.isRunning():
            self._ai_worker.request_stop()
        if self._exec_worker and self._exec_worker.isRunning():
            self._exec_worker.request_stop()
        # 双保险：直接取消 terminal executor 中可能仍在 wait 的交互命令
        try:
            self._terminal_executor.cancel()
        except Exception:
            pass

    def shutdown(self, wait_ms: int = 2000) -> None:
        """退出时安全关闭：请求停止 + wait 线程结束，避免 'QThread: Destroyed while thread is still running'。"""
        self.stop()
        try:
            if self._ai_worker and self._ai_worker.isRunning():
                if not self._ai_worker.wait(wait_ms):
                    self._ai_worker.terminate()
                    self._ai_worker.wait(500)
        except Exception:
            pass
        try:
            if self._exec_worker and self._exec_worker.isRunning():
                if not self._exec_worker.wait(wait_ms):
                    self._exec_worker.terminate()
                    self._exec_worker.wait(500)
        except Exception:
            pass

    def clear_conversation(self) -> None:
        """清空对话历史。"""
        self._conversation.clear()
        self._server_profile = None
        self._original_goal = ""
        self._is_diagnosing = False
        self._goal_verify_count = 0
        # 重建系统提示词
        self._conversation.system_prompt = self._build_system_prompt()

    def get_server_profile(self):
        """获取服务器画像。

        Returns:
            ServerProfile 实例或 None
        """
        try:
            self._server_profile = self._profile_builder.build()
            return self._server_profile
        except Exception as e:
            util.logger.error(f"获取服务器画像失败: {e}")
            return None

    # ──────────────────────────── 内部方法 ────────────────────────────

    def _build_system_prompt(self) -> str:
        """构建完整的系统提示词（角色定义 + 服务器画像 + 安全约束）。"""
        prompt = (
            "你是一个专业的 Linux 运维助手，可以帮助用户在远程服务器上执行操作。\n"
            "你的职责包括：系统管理、服务部署、故障诊断、性能优化等。\n"
            "请根据用户的需求，生成安全、高效的命令方案。\n"
        )

        # 【重要-权限规则】紧跟角色定义，确保 LLM 高权重关注
        if self._server_profile and self._server_profile.is_root:
            prompt += (
                "\n\n【重要-权限规则】你当前以 root 用户连接，拥有最高权限。"
                "所有命令直接执行，绝不添加 sudo。\n"
            )
        elif self._server_profile and self._server_profile.current_user:
            prompt += (
                f"\n\n【重要-权限规则】你当前以 {self._server_profile.current_user} 用户连接（非root），"
                "生成命令时必须遵守以下规则：\n"
                "1. 需要超级权限的操作前面必须加 sudo：包管理(apt/yum/dnf)、服务管理(systemctl/service)、"
                "权限修改(chmod/chown)、系统配置文件修改、创建系统目录等\n"
                "2. 只读查询类命令不加 sudo：ls、cat、ps、df、free、systemctl status、journalctl 等\n"
                "3. 同一批命令保持一致性\n"
            )

        # 服务器画像
        if self._server_profile:
            prompt += "\n" + self._profile_builder.build_system_context_prompt(self._server_profile)

        # 安全约束
        prompt += (
            "\n\n安全约束：\n"
            "1. 绝对禁止执行会导致数据丢失的危险命令（如 rm -rf /、dd 覆写磁盘等）\n"
            "2. 涉及服务重启、关机等操作前需明确告知用户风险\n"
            "3. 修改系统配置前建议先备份\n"
            "4. 优先使用只读命令获取信息后再决定操作方案\n"
            "5. 对于不确定的操作，先解释方案等待用户确认\n"
        )

        # 输出格式指示
        prompt += (
            "\n当用户请求执行操作时，请使用 execute_ssh_commands 工具来提供命令方案。\n"
            "每条命令需包含用途说明。如果某些命令允许失败（如检查命令），请设置 allow_failure 为 true。\n"
            "所有命令一律在用户当前的 SSH 终端窗口中执行，会天然支持密码、sudo、passphrase、y/n 等交互，\n"
            "你无需关心 interactive 字段（即使传了也会被忽略）。命令的退出码与输出会自动回填给你用于诊断。\n"
            "重要：不要生成会调起分页器的命令。例如：\n"
            "  - systemctl 请加 --no-pager（如 systemctl status xxx --no-pager）\n"
            "  - journalctl 请加 --no-pager\n"
            "  - git log/diff/show 请加 --no-pager 或 --oneline -n N\n"
            "  - 避免使用 less/more/man，如需查看详细信息请用 cat/head/tail\n"
            "如果用户只是提问或需要解释，直接用文本回复即可，不必使用工具。"
        )

        return prompt

    def _refresh_system_prompt(self) -> None:
        """刷新系统提示词（尝试更新服务器画像）。"""
        try:
            self._server_profile = self._profile_builder.build()
        except Exception as e:
            util.logger.debug(f"刷新服务器画像失败: {e}")

        self._conversation.system_prompt = self._build_system_prompt()

    def _async_refresh_profile(self):
        """异步刷新服务器画像（不阻塞主线程），刷新结果供下次对话使用。"""
        if hasattr(self, '_profile_thread') and self._profile_thread and self._profile_thread.isRunning():
            return  # 避免重复刷新

        self._profile_thread = _ProfileRefreshThread(self._profile_builder, parent=self)
        self._profile_thread.done.connect(self._on_profile_refreshed, Qt.QueuedConnection)
        self._profile_thread.start()

    def _on_profile_refreshed(self, profile):
        """画像刷新完成回调。"""
        if profile:
            self._server_profile = profile

    def _on_ai_delta(self, reasoning: str, content: str):
        """转发 AI 增量输出到 UI。"""
        self.ai_message.emit(reasoning, content)

    def _on_ai_result(self, result: dict) -> None:
        """处理 AI 响应结果。"""
        content = result.get("content", "")
        tool_calls = result.get("tool_calls")

        if tool_calls:
            # 解析 Function Calling 结果
            commands = self._parse_tool_calls(tool_calls)
            if commands is not None:
                # 对命令进行安全检查
                checked_commands = self._check_commands_safety(commands)
                # 将 AI 响应添加到对话历史
                if content:
                    self._conversation.add_assistant_message(content)
                    self.ai_message.emit("", content)
                self.command_ready.emit(checked_commands)
                return

        # 没有工具调用，尝试从文本中提取命令（fallback）
        if content:
            self._conversation.add_assistant_message(content)

            # 尝试正则提取命令
            fallback_commands = self._extract_commands_from_text(content)
            if fallback_commands:
                checked_commands = self._check_commands_safety(fallback_commands)
                self.ai_message.emit("", content)
                self.command_ready.emit(checked_commands)
            else:
                # 纯文本回复
                self.ai_message.emit("", content)

    def _on_ai_error(self, error_msg: str) -> None:
        """处理 AI 调用错误。"""
        self.error_occurred.emit(error_msg)

    def _on_ai_worker_finished(self) -> None:
        """AI 工作线程结束。"""
        self.thinking_finished.emit()

    def _on_exec_started(self, cmd: str) -> None:
        """命令开始执行。"""
        self.execution_started.emit(cmd)

    def _on_exec_finished(self, result: dict) -> None:
        """单条命令执行完成。"""
        cmd = result["cmd"]
        stdout = result["stdout"]
        stderr = result["stderr"]
        exit_code = result["exit_code"]
        description = result.get("description", "")
        duration_ms = result.get("duration_ms", 0)

        # 添加到对话上下文
        self._conversation.add_command_result(
            command=cmd,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            description=description,
        )

        # 记录审计日志
        self._log_audit(cmd, result)

        # 发射完成信号
        self.execution_finished.emit(result)

    def _on_all_exec_finished(self, results: list) -> None:
        """全部命令执行完毕，生成总结并检查是否需要自动诊断或目标验证。"""
        if not results:
            return

        total = len(results)
        success_count = sum(
            1 for r in results
            if r["exit_code"] == 0 or r.get("allow_failure", False)
        )
        fail_count = total - success_count

        # 计算被跳过的命令数（原始命令总数 - 实际执行数）
        original_total = len(self._exec_worker._commands) if self._exec_worker else total
        skipped = original_total - total

        if fail_count == 0:
            summary = f"全部 {total} 条命令执行成功"
            self.task_summary.emit(summary)

            # ── 目标验证闭环 ──
            # 命令全部成功不代表任务完成，触发 AI 验证原始目标
            if self._original_goal and self._goal_verify_count < self._MAX_VERIFY_ROUNDS:
                self._goal_verify_count += 1
                self._verify_goal_completion()
            else:
                # 达到最大验证轮数或无原始目标，结束流程
                self._is_diagnosing = False
        else:
            parts = [f"{original_total} 条命令中 {success_count} 条成功、{fail_count} 条失败"]
            if skipped > 0:
                parts.append(f"（后续 {skipped} 条未执行）")
            parts.append("，正在自动分析失败原因...")
            summary = "".join(parts)
            self.task_summary.emit(summary)

            # 找到第一条失败命令并触发诊断
            failed = next(
                (r for r in results if r["exit_code"] != 0 and not r.get("allow_failure", False)),
                None
            )
            if failed:
                self.diagnosing_started.emit()
                self.diagnose_error(
                    command=failed["cmd"],
                    stdout=failed["stdout"],
                    stderr=failed["stderr"],
                    exit_code=failed["exit_code"],
                )

    def _verify_goal_completion(self) -> None:
        """命令执行成功后，让 AI 验证原始任务是否真正完成。"""
        self._is_diagnosing = True
        verify_prompt = (
            f"命令已执行成功。现在请验证用户的原始任务是否真正完成。\n\n"
            f"用户的原始任务：{self._original_goal}\n\n"
            f"请执行必要的验证命令（如检查版本号、检查服务状态等）来确认任务实际完成。\n"
            f"如果任务已完成，请给出最终确认消息。\n"
            f"如果任务未完成，请继续执行剩余步骤直到完成。"
        )
        self.process_user_input(verify_prompt)

    def _on_exec_error(self, error_msg: str) -> None:
        """命令执行过程出错。"""
        self.error_occurred.emit(error_msg)

    def _parse_tool_calls(self, tool_calls) -> Optional[list[dict]]:
        """解析 Function Calling 的 tool_calls 结构。

        支持两种格式：
        - 流式聚合后的 dict 列表 (来自 stream=True)
        - 非流式的对象列表 (带 .function 属性)

        Args:
            tool_calls: LLM 返回的 tool_calls 列表

        Returns:
            命令列表，解析失败返回 None
        """
        try:
            for call in tool_calls:
                # 兼容 dict 格式（流式聚合）和对象格式
                if isinstance(call, dict):
                    func = call.get("function", {})
                    name = func.get("name", "") if isinstance(func, dict) else getattr(func, "name", "")
                    arguments = func.get("arguments", "") if isinstance(func, dict) else getattr(func, "arguments", "")
                else:
                    func = getattr(call, "function", None)
                    if func is None:
                        continue
                    name = getattr(func, "name", "")
                    arguments = getattr(func, "arguments", "")

                if name == "execute_ssh_commands":
                    if isinstance(arguments, str):
                        data = json.loads(arguments)
                    else:
                        data = arguments

                    commands = data.get("commands", [])
                    explanation = data.get("explanation", "")

                    # 将 explanation 作为 AI 消息发出
                    if explanation:
                        self.ai_message.emit("", explanation)

                    return commands
        except (json.JSONDecodeError, AttributeError, TypeError) as e:
            util.logger.error(f"解析 tool_calls 失败: {e}")

        return None

    def _extract_commands_from_text(self, text: str) -> list[dict]:
        """从 AI 文本回复中通过正则提取命令（fallback 策略）。

        仅接受明确标记 bash/shell/sh 语言的代码块，并对代码块内的行做严格过滤：
        跳过空行/注释/markdown 列表项（- * + > 或 "1. "）/含中文的总结性文本。

        背景：AI 在做“日志分析/安全总结”类输出时常会用 ``` 包裹 markdown
        列表（如 "- 05:21-05:26 多次 sudo 认证失败”），原实现会把这些误识为 shell
        命令打包到“AI 命令确认”弹框中，需要过滤。

        Args:
            text: AI 回复的文本内容

        Returns:
            提取的命令列表，未找到返回空列表
        """
        commands = []
        # 仅识别明确声明语言为 bash/shell/sh 的代码块；不带语言标识的 ``` 块
        # 可能是日志/表格/总结文本，容易误提取。
        pattern = r'```(?:bash|shell|sh)\s*\n(.*?)```'
        matches = re.findall(pattern, text, re.DOTALL)

        # CJK 字符（中日韩表意文字）：shell 命令几乎不会出现中文，
        # 出现则极可能是中文注释/总结行。
        cjk_re = re.compile(r'[\u4e00-\u9fff]')
        # markdown 有序列表 "1. xxx" / "2) xxx"
        ordered_list_re = re.compile(r'^\d+[\.\)]\s')

        for block in matches:
            for raw in block.strip().splitlines():
                line = raw.strip()
                if not line:
                    continue
                # 跳过 shell 注释、markdown 无序列表项、引用块
                if line.startswith(("#", "- ", "* ", "+ ", "> ")):
                    continue
                # 跳过 "-”、“*”、“+” 独占一行的分隔符
                if line in ("-", "*", "+"):
                    continue
                # 跳过 markdown 有序列表项
                if ordered_list_re.match(line):
                    continue
                # 跳过含中文字符的行（shell 命令不会含 CJK，出现即为总结/注释）
                if cjk_re.search(line):
                    continue
                commands.append({
                    "cmd": line,
                    "description": "从 AI 回复中提取的命令",
                    "allow_failure": False,
                })

        return commands

    def _check_commands_safety(self, commands: list[dict]) -> list[dict]:
        """对命令列表进行安全检查，附加安全检查结果。

        Args:
            commands: 原始命令列表

        Returns:
            附加了安全检查结果的命令列表
        """
        checked = []
        for cmd_info in commands:
            cmd = cmd_info.get("cmd", "")
            result = self._safety_checker.check(cmd)
            checked.append({
                **cmd_info,
                "safety": {
                    "risk_level": result.risk_level.value,
                    "is_allowed": result.is_allowed,
                    "reason": result.reason,
                    "warnings": result.warnings,
                },
            })
        return checked

    def _log_audit(self, cmd: str, result: dict) -> None:
        """记录审计日志。"""
        try:
            # 获取主机信息
            host = getattr(self._ssh_client, "host", "unknown")
            port = getattr(self._ssh_client, "port", 22)
            username = getattr(self._ssh_client, "username", "unknown")

            # 确定风险等级
            safety_result = self._safety_checker.check(cmd)
            risk_value = safety_result.risk_level.value
            # audit 只接受 safe/low/medium/high，将 critical 映射为 high
            if risk_value == "critical":
                risk_value = "high"

            self._audit_logger.log_command(
                session_id=self._session_id,
                host=host,
                port=int(port) if port else 22,
                username=username,
                command=cmd,
                source="ai_confirmed",
                risk_level=risk_value,
                exit_code=result.get("exit_code"),
                stdout_snippet=result.get("stdout", "")[:500],
                stderr_snippet=result.get("stderr", "")[:500],
                ai_model=self._prefs.model,
                duration_ms=result.get("duration_ms", 0),
            )
        except Exception as e:
            util.logger.error(f"记录审计日志失败: {e}")
