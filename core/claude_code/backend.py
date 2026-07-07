"""
Claude Code 集成抽象层
提供 LocalBackend 和 RemoteBackend 两种实现，
分别用于本地和通过 SSH 远程访问 claude CLI / 配置文件。
"""

import glob
import json
import logging
import os
import shlex
import subprocess
import threading
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)


def build_cd_command(cwd: str, command: str) -> str:
    """构造"切换到 cwd 后执行 command"的终端命令字符串，按平台选择 shell 语法。

    - POSIX (bash/zsh): ``cd 'dir' && command``
    - Windows PowerShell（5.1 与 7 均兼容）: ``Set-Location -LiteralPath 'dir'; if ($?) { command }``
      Windows 终端默认走 pwsh/powershell，而 Windows PowerShell 5.1 不支持 ``&&``，
      故用 ``;`` + ``$?`` 实现"目录切换成功才执行命令"的等价语义。

    cwd 为空时直接返回 command。
    """
    if not cwd:
        return command
    if os.name == "nt":
        # PowerShell 单引号字符串内的单引号需写成两个单引号转义
        quoted = "'" + str(cwd).replace("'", "''") + "'"
        return f"Set-Location -LiteralPath {quoted}; if ($?) {{ {command} }}"
    return f"cd {shlex.quote(str(cwd))} && {command}"


def build_install_command() -> str:
    """构造安装 Claude Code 的终端命令字符串，按平台选择官方安装方式。

    - POSIX (macOS/Linux/WSL): 官方原生安装脚本
      ``curl -fsSL https://claude.ai/install.sh | bash``
    - Windows PowerShell: 官方原生安装脚本
      ``irm https://claude.ai/install.ps1 | iex``

    安装在真实终端里交互执行（而非后台子进程），便于用户查看进度、
    处理权限提示，并在安装后立即使用。
    """
    if os.name == "nt":
        return "irm https://claude.ai/install.ps1 | iex"
    return "curl -fsSL https://claude.ai/install.sh | bash"


# 缓存登录 shell 的 PATH，避免重复 fork shell（GUI 启动时会被多次调用）
_login_path_cache = None


def _which(cmd: str, path: Optional[str] = None) -> Optional[str]:
    """在 PATH 中查找可执行文件，返回首个匹配的完整路径，未找到返回 None。

    用以替代 shutil.which：typeshed 中 shutil.which 的 PathLike[str] 重载被标记
    为 @deprecated（Windows + Python<3.12 下 PathLike 形参会失败/返回 None），
    部分编辑器会对所有 shutil.which 调用报弃用告警。此处只接收纯 str，语义与
    shutil.which(cmd, path=...) 的 str 重载一致：遍历 PATH 各目录，取首个存在
    且可执行（Windows 额外匹配 PATHEXT 扩展名）的文件。
    """
    search_path = path if path is not None else os.environ.get("PATH", "")
    # Windows 下可执行文件按 PATHEXT 扩展名匹配（如 claude.exe / claude.cmd）；
    # 非 Windows 无扩展名概念，用单个空串表示"不加扩展名"。
    exts = (
        [e.strip().lower() for e in os.environ.get("PATHEXT", "").split(os.pathsep) if e.strip()]
        if os.name == "nt"
        else [""]
    )
    for dir_ in search_path.split(os.pathsep):
        if not dir_:
            continue
        for ext in exts:
            candidate = os.path.join(dir_, cmd + ext)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
    return None


def _get_login_shell_path() -> str:
    """通过用户登录 shell 读取完整 PATH。

    macOS/Linux 下从 Finder/Dock 启动的 GUI 应用不会加载用户的
    shell 配置（.zshrc/.bash_profile 等），导致 PATH 不完整，
    nvm/fnm/volta 等 node 版本管理器安装的 claude 无法被找到。
    这里显式拉起登录交互式 shell 取其 PATH。
    """
    global _login_path_cache
    if _login_path_cache is not None:
        return _login_path_cache
    _login_path_cache = ""  # 失败时缓存空串，避免重复尝试
    if os.name == "nt":
        return _login_path_cache
    shell = os.environ.get("SHELL") or "/bin/bash"
    try:
        result = subprocess.run(
            [shell, "-ilc", 'printf %s "$PATH"'],
            capture_output=True,
            text=True,
            timeout=5,
        )
        path = (result.stdout or "").strip()
        if path:
            _login_path_cache = path
    except Exception as e:  # 取 PATH 失败不应阻断后续候选路径查找
        logger.debug(f"读取登录 shell PATH 失败: {e}")
    return _login_path_cache


# 缓存 claude 可执行文件路径，避免每次 LocalBackend.__init__ 重复 which/glob
_claude_bin_cache = None


def _find_claude_bin() -> str:
    """查找 claude 可执行文件路径，兼容 GUI 应用无 PATH 的情况。

    优先级：
    1. 当前进程 PATH 下的 claude
    2. 登录 shell PATH 下的 claude（解决 Finder/Dock 启动无 PATH 问题）
    3. 常见安装目录 + nvm/fnm/volta/pnpm 等 node 版本管理器路径
    """
    global _claude_bin_cache
    if _claude_bin_cache is not None:
        return _claude_bin_cache

    # 1. 当前进程 PATH 下的 claude
    found = _which("claude")
    if found:
        _claude_bin_cache = found
        return found

    # 2. 用登录 shell 的完整 PATH 再找一次（解决 Finder/Dock 启动无 PATH 问题）
    login_path = _get_login_shell_path()
    if login_path:
        found = _which("claude", path=login_path)
        if found:
            _claude_bin_cache = found
            return found

    home = os.path.expanduser("~")
    candidates = [
        os.path.join(home, ".claude", "local", "claude"),  # 官方原生安装器
        os.path.join(home, ".claude", "bin", "claude"),
        "/usr/local/bin/claude",
        "/opt/homebrew/bin/claude",
        os.path.join(home, ".local", "bin", "claude"),
        os.path.join(home, ".npm-global", "bin", "claude"),
        os.path.join(home, ".volta", "bin", "claude"),
        os.path.join(home, "Library", "pnpm", "claude"),
    ]
    # node 版本管理器（nvm/fnm/n 等）安装路径，取最新版本优先
    glob_patterns = [
        os.path.join(home, ".nvm", "versions", "node", "*", "bin", "claude"),
        os.path.join(home, ".fnm", "node-versions", "*", "installation", "bin", "claude"),
        "/usr/local/n/versions/node/*/bin/claude",
    ]
    for pattern in glob_patterns:
        candidates.extend(sorted(glob.glob(pattern), reverse=True))

    for path in candidates:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            _claude_bin_cache = path
            return path

    # 都找不到就返回裸命令名，让后续报错更明确
    _claude_bin_cache = "claude"
    return "claude"


def _build_subprocess_env() -> dict:
    """构造运行 claude 时的环境变量，确保 PATH 包含 claude 及其依赖（node）。

    claude 自身可能是 node 脚本/依赖同目录的 node，故除了 claude
    所在目录外，还合入登录 shell 的完整 PATH。
    """
    env = os.environ.copy()
    extra_paths = []
    login_path = _get_login_shell_path()
    if login_path:
        extra_paths.append(login_path)
    if extra_paths:
        existing = env.get("PATH", "")
        merged = os.pathsep.join(p for p in [existing] + extra_paths if p)
        # 去重并保持顺序
        seen = set()
        ordered = []
        for p in merged.split(os.pathsep):
            if p and p not in seen:
                seen.add(p)
                ordered.append(p)
        env["PATH"] = os.pathsep.join(ordered)
    return env


def _parse_daemon_status(returncode: int, stdout: str) -> dict:
    """解析 claude daemon status 输出。

    - JSON 输出：直接解析。
    - 文本输出：未运行时退出码非 0 且首行为 "not running"。
      运行时输出包含 pid/version/uptime。
    """
    text = (stdout or "").strip()
    if text:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    if not text:
        return {"running": False}
    first_line = text.splitlines()[0].strip().lower()
    running = returncode == 0 and not first_line.startswith("not running")
    return {"raw": text, "running": running}


def _iso_to_ms(ts: str):
    """将 ISO8601 时间字符串（如 2026-06-13T17:06:19.651Z）转为毫秒时间戳。"""
    if not ts or not isinstance(ts, str):
        return None
    try:
        import datetime
        dt = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000)
    except (ValueError, OverflowError):
        return None


def _parse_transcript_head(path: str, max_lines: int = 80) -> dict:
    """读取会话 transcript（.jsonl）头部若干行，提取标题/cwd/首条时间戳。

    只读取头部，避免完整加载大文件。
    """
    name = ""
    cwd = ""
    first_ts = None
    first_user = ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= max_lines:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not cwd and d.get("cwd"):
                    cwd = d["cwd"]
                if not name and d.get("type") == "ai-title" and d.get("aiTitle"):
                    name = d["aiTitle"]
                if first_ts is None and d.get("timestamp"):
                    first_ts = d["timestamp"]
                if not first_user and d.get("type") == "user":
                    msg = d.get("message", {})
                    content = msg.get("content") if isinstance(msg, dict) else None
                    if isinstance(content, list):
                        content = " ".join(
                            x.get("text", "") for x in content
                            if isinstance(x, dict) and x.get("type") in (None, "text")
                        )
                    if isinstance(content, str) and content.strip():
                        first_user = content.strip()
                # 标题、cwd、首条时间都拿到即可提前结束（ai-title 通常在前几行）
                if name and cwd and first_ts is not None:
                    break
    except OSError:
        pass
    title = name or first_user
    title = " ".join(title.split())  # 折叠换行/多空格
    if len(title) > 80:
        title = title[:80] + "…"
    return {"name": title, "cwd": cwd, "_first_ts": first_ts}


class ClaudeCodeBackend(ABC):
    """Claude Code 数据访问抽象层基类"""

    @abstractmethod
    def run_command(self, args: list, timeout: int = 30) -> tuple[int, str, str]:
        """执行 claude CLI 命令，返回 (returncode, stdout, stderr)"""
        ...

    @abstractmethod
    def get_version(self) -> str:
        """获取 claude 版本（claude --version）"""
        ...

    @abstractmethod
    def get_auth_status(self) -> dict:
        """获取认证状态（claude auth status --text），解析返回 dict"""
        ...

    @abstractmethod
    def get_daemon_status(self) -> dict:
        """获取守护进程状态（claude daemon status），解析返回 dict"""
        ...

    @abstractmethod
    def list_sessions(self) -> list:
        """列出后台会话（claude agents --json），返回 session 列表"""
        ...

    @abstractmethod
    def read_settings(self) -> dict:
        """读取 ~/.claude/settings.json"""
        ...

    @abstractmethod
    def write_settings(self, settings: dict) -> tuple[bool, str]:
        """写入 ~/.claude/settings.json"""
        ...

    @abstractmethod
    def read_mcp_config(self, scope: str = "user",
                        project_path: Optional[str] = None) -> dict:
        """读取 MCP 配置（scope: user=~/.claude.json, project=<path>/.mcp.json）"""
        ...

    @abstractmethod
    def write_mcp_config(self, config: dict, scope: str = "user",
                         project_path: Optional[str] = None) -> tuple[bool, str]:
        """写入 MCP 配置（scope: user=~/.claude.json, project=<path>/.mcp.json）"""
        ...


class LocalBackend(ClaudeCodeBackend):
    """本地 Claude Code 后端实现，直接通过本地文件系统和子进程操作"""

    def __init__(self):
        self._claude_bin = _find_claude_bin()
        self._claude_home = os.path.expanduser("~/.claude")
        # env 惰性构建：_build_subprocess_env() 会 fork 登录 shell 取 PATH（~0.7s），
        # 放在构造期会在 UI 线程阻塞。推迟到首次 run_command（在 QThread worker 内）
        # 才构建，使 LocalBackend() 构造纯内存、UI 线程零子进程。
        self._env = None
        self._env_lock = threading.Lock()

    def _ensure_env(self) -> dict:
        """首次调用时构建子进程环境变量（含登录 shell PATH），之后复用缓存。

        加锁防止 StatusWorker 并行调用多个 run_command 时重复 fork 登录 shell。
        """
        if self._env is None:
            with self._env_lock:
                if self._env is None:  # double-check，避免多线程重复构建
                    self._env = _build_subprocess_env()
        return self._env

    def run_command(self, args: list, timeout: int = 30) -> tuple[int, str, str]:
        try:
            kwargs = dict(
                capture_output=True,
                text=True,
                timeout=timeout,
                env=self._ensure_env(),
            )
            # Windows GUI 应用下防止弹出控制台黑窗口
            if os.name == 'nt':
                kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
            result = subprocess.run(
                [self._claude_bin] + args,
                **kwargs
            )
            # subprocess 在某些平台/调用下 stdout/stderr 可能为 None，统一归一为空串，
            # 避免调用方对返回值执行 .strip() 等操作时抛 AttributeError。
            stdout = result.stdout or ""
            stderr = result.stderr or ""
            if result.returncode != 0:
                logger.warning(
                    f"claude CLI 返回非零退出码: {result.returncode}, "
                    f"stderr: {stderr.strip()}"
                )
            return result.returncode, stdout, stderr
        except subprocess.TimeoutExpired:
            logger.error(f"claude CLI 执行超时 ({timeout}s): {args}")
            return -1, "", "Command timed out"
        except FileNotFoundError:
            logger.error(f"claude 可执行文件未找到: {self._claude_bin}")
            return -1, "", f"claude binary not found: {self._claude_bin}"
        except Exception as e:
            logger.error(f"执行 claude CLI 失败: {e}")
            return -1, "", str(e)

    def get_version(self) -> str:
        returncode, stdout, stderr = self.run_command(["--version"])
        if returncode == 0:
            return stdout.strip()
        return ""

    def get_auth_status(self) -> dict:
        returncode, stdout, stderr = self.run_command(["auth", "status", "--json"])
        if returncode == 0 and stdout.strip():
            try:
                return json.loads(stdout)
            except json.JSONDecodeError:
                logger.warning(f"解析 auth status JSON 失败: {stdout[:200]}")
        # 回退：尝试文本模式解析
        returncode, stdout, stderr = self.run_command(["auth", "status", "--text"])
        if returncode == 0 and stdout.strip():
            return self._parse_auth_text(stdout)
        return {}

    def get_daemon_status(self) -> dict:
        # claude daemon status：未运行时退出码为 1，首行为 "not running"；
        # 运行时输出 pid/version/uptime。不能用 "running" 子串判断（"not running" 也含该词）。
        returncode, stdout, stderr = self.run_command(["daemon", "status"])
        return _parse_daemon_status(returncode, stdout)

    def list_sessions(self) -> list:
        """列出全部可恢复会话。

        会话历史存储在 ~/.claude/projects/<cwd编码>/<sessionId>.jsonl，
        每个 .jsonl 即一个可 --resume 的会话。这里读取这些 transcript，
        并叠加 agents --json 报告的“运行中”状态。
        """
        sessions = self._read_transcript_sessions()
        # 叠加正在运行的 agent 状态
        live = self._live_agent_status()
        for s in sessions:
            sid = s.get("sessionId")
            if sid in live:
                s["status"] = live[sid]
                s["running"] = True
        return sessions

    def _live_agent_status(self) -> dict:
        """返回 {sessionId: status} 的运行中会话映射。"""
        result = {}
        returncode, stdout, stderr = self.run_command(["agents", "--json", "--all"])
        if returncode == 0 and stdout.strip():
            try:
                for a in json.loads(stdout):
                    sid = a.get("sessionId")
                    if sid:
                        result[sid] = a.get("status", "running")
            except (json.JSONDecodeError, AttributeError, TypeError):
                logger.warning(f"解析 agents JSON 失败: {stdout[:200]}")
        return result

    def _read_transcript_sessions(self) -> list:
        projects_dir = os.path.join(self._claude_home, "projects")
        if not os.path.isdir(projects_dir):
            return []
        results = []
        for proj in os.listdir(projects_dir):
            proj_path = os.path.join(projects_dir, proj)
            if not os.path.isdir(proj_path):
                continue
            for fn in os.listdir(proj_path):
                if not fn.endswith(".jsonl"):
                    continue
                path = os.path.join(proj_path, fn)
                try:
                    mtime = os.path.getmtime(path)
                except OSError:
                    continue
                meta = _parse_transcript_head(path)
                started = _iso_to_ms(meta.get("_first_ts")) or int(mtime * 1000)
                results.append({
                    "sessionId": fn[:-len(".jsonl")],
                    "name": meta.get("name", ""),
                    "cwd": meta.get("cwd", ""),
                    "status": "saved",
                    "running": False,
                    "startedAt": started,
                    "_mtime": mtime,
                })
        # 最近活动的排在前面
        # 按创建时间（与“创建时间”列一致）降序，最新的在前
        results.sort(key=lambda x: x.get("startedAt", 0), reverse=True)
        return results

    def read_settings(self) -> dict:
        settings_path = os.path.join(self._claude_home, "settings.json")
        try:
            if not os.path.isfile(settings_path):
                return {}
            with open(settings_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.warning(f"解析 settings.json 失败: {e}")
            return {}
        except Exception as e:
            logger.error(f"读取 settings.json 失败: {e}")
            return {}

    def write_settings(self, settings: dict) -> tuple[bool, str]:
        settings_path = os.path.join(self._claude_home, "settings.json")
        try:
            os.makedirs(self._claude_home, exist_ok=True)
            with open(settings_path, "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)
            return True, ""
        except Exception as e:
            logger.error(f"写入 settings.json 失败: {e}")
            return False, str(e)

    def _mcp_config_path(self, scope: str, project_path: Optional[str]) -> str:
        """根据作用域返回 Claude Code 实际读取的 MCP 配置文件路径。

        - user:    ~/.claude.json （顶层 mcpServers，对所有项目生效）
        - project: <project_path>/.mcp.json （仅对该项目生效，可随仓库共享）
        """
        if scope == "project":
            base = project_path or os.getcwd()
            return os.path.join(os.path.expanduser(base), ".mcp.json")
        return os.path.expanduser("~/.claude.json")

    def read_mcp_config(self, scope: str = "user",
                        project_path: Optional[str] = None) -> dict:
        path = self._mcp_config_path(scope, project_path)
        try:
            if not os.path.isfile(path):
                return {"mcpServers": {}}
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            servers = data.get("mcpServers", {}) if isinstance(data, dict) else {}
            return {"mcpServers": servers if isinstance(servers, dict) else {}}
        except json.JSONDecodeError as e:
            logger.warning(f"解析 MCP 配置失败 ({path}): {e}")
            return {"mcpServers": {}}
        except Exception as e:
            logger.error(f"读取 MCP 配置失败 ({path}): {e}")
            return {"mcpServers": {}}

    def write_mcp_config(self, config: dict, scope: str = "user",
                         project_path: Optional[str] = None) -> tuple[bool, str]:
        path = self._mcp_config_path(scope, project_path)
        servers = config.get("mcpServers", {}) if isinstance(config, dict) else {}
        try:
            # 读-改-写：只替换 mcpServers 键，保留文件中的其它配置，避免覆盖
            existing: dict = {}
            if os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        loaded = json.load(f)
                    if isinstance(loaded, dict):
                        existing = loaded
                except json.JSONDecodeError as e:
                    logger.warning(f"现有 MCP 配置无法解析，将重建 ({path}): {e}")
            existing["mcpServers"] = servers

            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2, ensure_ascii=False)
            return True, ""
        except Exception as e:
            logger.error(f"写入 MCP 配置失败 ({path}): {e}")
            return False, str(e)

    @staticmethod
    def _parse_auth_text(text: str) -> dict:
        """解析 claude auth status --text 的文本输出为 dict"""
        result = {}
        for line in text.strip().splitlines():
            line = line.strip()
            if ":" in line:
                key, _, value = line.partition(":")
                result[key.strip().lower().replace(" ", "_")] = value.strip()
        if not result:
            result["raw"] = text.strip()
        return result


class RemoteBackend(ClaudeCodeBackend):
    """远程 Claude Code 后端实现，通过 SSH 连接操作远程主机"""

    def __init__(self, ssh_conn):
        """
        Args:
            ssh_conn: SSH 连接对象（来自 cube-shell），需具有 exec(cmd) 方法返回字符串
        """
        self.ssh_conn = ssh_conn

    def run_command(self, args: list, timeout: int = 30) -> tuple[int, str, str]:
        try:
            # 构建远程命令，对参数进行安全转义
            escaped_args = " ".join(shlex.quote(str(a)) for a in args)
            cmd = f"claude {escaped_args}; echo \"__EXIT_CODE__$?\""
            result = self.ssh_conn.exec(cmd, pty=False, timeout=timeout)
            if result is None:
                return -1, "", "SSH exec returned None"

            # 解析退出码
            lines = result.rstrip("\n").split("\n")
            returncode = 0
            stdout_lines = []
            for line in lines:
                if line.startswith("__EXIT_CODE__"):
                    try:
                        returncode = int(line.replace("__EXIT_CODE__", ""))
                    except ValueError:
                        returncode = -1
                else:
                    stdout_lines.append(line)
            stdout = "\n".join(stdout_lines)
            return returncode, stdout, ""
        except Exception as e:
            logger.error(f"远程执行 claude CLI 失败: {e}")
            return -1, "", str(e)

    def get_version(self) -> str:
        returncode, stdout, stderr = self.run_command(["--version"])
        if returncode == 0:
            return stdout.strip()
        return ""

    def get_auth_status(self) -> dict:
        returncode, stdout, stderr = self.run_command(["auth", "status", "--json"])
        if returncode == 0 and stdout.strip():
            try:
                return json.loads(stdout)
            except json.JSONDecodeError:
                pass
        # 回退文本模式
        returncode, stdout, stderr = self.run_command(["auth", "status", "--text"])
        if returncode == 0 and stdout.strip():
            return self._parse_auth_text(stdout)
        return {}

    def get_daemon_status(self) -> dict:
        returncode, stdout, stderr = self.run_command(["daemon", "status"])
        return _parse_daemon_status(returncode, stdout)

    def list_sessions(self) -> list:
        """远程列出可恢复会话：扫描 ~/.claude/projects/*/*.jsonl。

        通过单条 shell 脚本提取 sessionId / mtime / aiTitle / cwd，
        再叠加 agents --json 报告的运行中状态。
        """
        sessions = self._read_remote_transcripts()
        live = self._live_agent_status()
        for s in sessions:
            sid = s.get("sessionId")
            if sid in live:
                s["status"] = live[sid]
                s["running"] = True
        return sessions

    def _live_agent_status(self) -> dict:
        result = {}
        returncode, stdout, stderr = self.run_command(["agents", "--json", "--all"])
        if returncode == 0 and stdout.strip():
            try:
                for a in json.loads(stdout):
                    sid = a.get("sessionId")
                    if sid:
                        result[sid] = a.get("status", "running")
            except (json.JSONDecodeError, AttributeError, TypeError):
                logger.warning(f"远程解析 agents JSON 失败: {stdout[:200]}")
        return result

    def _read_remote_transcripts(self) -> list:
        # 兼容 GNU/BSD stat；grep 提取首个 aiTitle 与非空 cwd
        script = (
            'for f in ~/.claude/projects/*/*.jsonl; do '
            '[ -f "$f" ] || continue; '
            'sid=$(basename "$f" .jsonl); '
            'mt=$(stat -c %Y "$f" 2>/dev/null || stat -f %m "$f" 2>/dev/null); '
            "title=$(grep -m1 -oE '\"aiTitle\": *\"[^\"]*\"' \"$f\" 2>/dev/null); "
            "cwd=$(grep -m1 -oE '\"cwd\": *\"[^\"]+\"' \"$f\" 2>/dev/null); "
            'printf \'%s\\t%s\\t%s\\t%s\\n\' "$sid" "$mt" "$title" "$cwd"; '
            'done'
        )
        try:
            out = self.ssh_conn.exec(script, pty=False)
        except Exception as e:
            logger.error(f"远程读取会话 transcript 失败: {e}")
            return []
        if not out:
            return []

        def _val(fragment: str) -> str:
            # fragment 形如 "aiTitle": "xxx"，取冒号后引号内的值
            try:
                return json.loads("{" + fragment + "}").popitem()[1]
            except (json.JSONDecodeError, KeyError, ValueError):
                return ""

        results = []
        for line in out.splitlines():
            parts = line.rstrip("\n").split("\t")
            if not parts or not parts[0]:
                continue
            sid = parts[0]
            try:
                mt = float(parts[1]) if len(parts) > 1 and parts[1] else 0.0
            except ValueError:
                mt = 0.0
            title = _val(parts[2]) if len(parts) > 2 and parts[2] else ""
            cwd = _val(parts[3]) if len(parts) > 3 and parts[3] else ""
            results.append({
                "sessionId": sid,
                "name": title,
                "cwd": cwd,
                "status": "saved",
                "running": False,
                "startedAt": int(mt * 1000),
                "_mtime": mt,
            })
        # 按创建时间（与“创建时间”列一致）降序，最新的在前
        results.sort(key=lambda x: x.get("startedAt", 0), reverse=True)
        return results

    def read_settings(self) -> dict:
        try:
            result = self.ssh_conn.exec("cat ~/.claude/settings.json", pty=False)
            if result and result.strip():
                return json.loads(result)
        except json.JSONDecodeError as e:
            logger.warning(f"远程解析 settings.json 失败: {e}")
        except Exception as e:
            logger.error(f"远程读取 settings.json 失败: {e}")
        return {}

    def write_settings(self, settings: dict) -> tuple[bool, str]:
        try:
            content = json.dumps(settings, indent=2, ensure_ascii=False)
            escaped = content.replace("\\", "\\\\").replace("'", "'\\''")
            cmd = f"mkdir -p ~/.claude && printf '%s' '{escaped}' > ~/.claude/settings.json"
            self.ssh_conn.exec(cmd, pty=False)
            return True, ""
        except Exception as e:
            logger.error(f"远程写入 settings.json 失败: {e}")
            return False, str(e)

    @staticmethod
    def _remote_mcp_path(scope: str, project_path: Optional[str]) -> str:
        """远程 MCP 配置路径（user=~/.claude.json, project=<path>/.mcp.json）"""
        if scope == "project":
            base = (project_path or ".").rstrip("/")
            return f"{base}/.mcp.json"
        return "~/.claude.json"

    def read_mcp_config(self, scope: str = "user",
                        project_path: Optional[str] = None) -> dict:
        path = self._remote_mcp_path(scope, project_path)
        try:
            result = self.ssh_conn.exec(f"cat {path} 2>/dev/null", pty=False)
            if result and result.strip():
                data = json.loads(result)
                servers = data.get("mcpServers", {}) if isinstance(data, dict) else {}
                return {"mcpServers": servers if isinstance(servers, dict) else {}}
        except json.JSONDecodeError as e:
            logger.warning(f"远程解析 MCP 配置失败 ({path}): {e}")
        except Exception as e:
            logger.error(f"远程读取 MCP 配置失败 ({path}): {e}")
        return {"mcpServers": {}}

    def write_mcp_config(self, config: dict, scope: str = "user",
                         project_path: Optional[str] = None) -> tuple[bool, str]:
        path = self._remote_mcp_path(scope, project_path)
        servers = config.get("mcpServers", {}) if isinstance(config, dict) else {}
        try:
            # 读-改-写：拉取远端现有配置，只替换 mcpServers，保留其它键
            existing: dict = {}
            try:
                raw = self.ssh_conn.exec(f"cat {path} 2>/dev/null", pty=False)
                if raw and raw.strip():
                    loaded = json.loads(raw)
                    if isinstance(loaded, dict):
                        existing = loaded
            except json.JSONDecodeError as e:
                logger.warning(f"远端现有 MCP 配置无法解析，将重建 ({path}): {e}")
            existing["mcpServers"] = servers

            content = json.dumps(existing, indent=2, ensure_ascii=False)
            escaped = content.replace("\\", "\\\\").replace("'", "'\\''")
            dir_part = path.rsplit("/", 1)[0] if "/" in path else "."
            cmd = f"mkdir -p {dir_part} && printf '%s' '{escaped}' > {path}"
            self.ssh_conn.exec(cmd, pty=False)
            return True, ""
        except Exception as e:
            logger.error(f"远程写入 MCP 配置失败 ({path}): {e}")
            return False, str(e)

    @staticmethod
    def _parse_auth_text(text: str) -> dict:
        """解析 claude auth status --text 的文本输出为 dict"""
        result = {}
        for line in text.strip().splitlines():
            line = line.strip()
            if ":" in line:
                key, _, value = line.partition(":")
                result[key.strip().lower().replace(" ", "_")] = value.strip()
        if not result:
            result["raw"] = text.strip()
        return result
