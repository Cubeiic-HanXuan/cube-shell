"""
Claude Code 集成抽象层
提供 LocalBackend 和 RemoteBackend 两种实现，
分别用于本地和通过 SSH 远程访问 claude CLI / 配置文件。
"""

import json
import logging
import os
import shlex
import shutil
import subprocess
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


def _find_claude_bin() -> str:
    """查找 claude 可执行文件路径，兼容 GUI 应用无 PATH 的情况。

    优先级：
    1. shutil.which("claude")
    2. ~/.claude/bin/claude
    3. /usr/local/bin/claude
    4. /opt/homebrew/bin/claude
    5. ~/.local/bin/claude
    """
    found = shutil.which("claude")
    if found:
        return found

    home = os.path.expanduser("~")
    candidates = [
        os.path.join(home, ".claude", "bin", "claude"),
        "/usr/local/bin/claude",
        "/opt/homebrew/bin/claude",
        os.path.join(home, ".local", "bin", "claude"),
    ]
    for path in candidates:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path

    # 都找不到就返回裸命令名，让后续报错更明确
    return "claude"


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
    def stop_session(self, session_id: str) -> tuple[bool, str]:
        """停止后台会话"""
        ...

    @abstractmethod
    def remove_session(self, session_id: str) -> tuple[bool, str]:
        """删除后台会话"""
        ...

    @abstractmethod
    def start_background_task(self, prompt: str) -> tuple[bool, str]:
        """启动后台任务（claude --bg "prompt"）"""
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
    def read_mcp_config(self) -> dict:
        """读取 MCP 配置"""
        ...

    @abstractmethod
    def write_mcp_config(self, config: dict) -> tuple[bool, str]:
        """写入 MCP 配置"""
        ...


class LocalBackend(ClaudeCodeBackend):
    """本地 Claude Code 后端实现，直接通过本地文件系统和子进程操作"""

    def __init__(self):
        self._claude_bin = _find_claude_bin()
        self._claude_home = os.path.expanduser("~/.claude")

    def run_command(self, args: list, timeout: int = 30) -> tuple[int, str, str]:
        try:
            result = subprocess.run(
                [self._claude_bin] + args,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if result.returncode != 0:
                logger.warning(
                    f"claude CLI 返回非零退出码: {result.returncode}, "
                    f"stderr: {result.stderr.strip()}"
                )
            return result.returncode, result.stdout, result.stderr
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
        returncode, stdout, stderr = self.run_command(["daemon", "status"])
        if returncode == 0 and stdout.strip():
            try:
                return json.loads(stdout)
            except json.JSONDecodeError:
                # 文本输出，尝试简单解析
                return {"raw": stdout.strip(), "running": "running" in stdout.lower()}
        return {"running": False}

    def list_sessions(self) -> list:
        returncode, stdout, stderr = self.run_command(["agents", "--json"])
        if returncode == 0 and stdout.strip():
            try:
                data = json.loads(stdout)
                return data if isinstance(data, list) else []
            except json.JSONDecodeError:
                logger.warning(f"解析 agents JSON 失败: {stdout[:200]}")
        return []

    def stop_session(self, session_id: str) -> tuple[bool, str]:
        returncode, stdout, stderr = self.run_command(["agents", "stop", session_id])
        if returncode == 0:
            return True, stdout.strip()
        return False, stderr.strip() or stdout.strip()

    def remove_session(self, session_id: str) -> tuple[bool, str]:
        returncode, stdout, stderr = self.run_command(["agents", "remove", session_id])
        if returncode == 0:
            return True, stdout.strip()
        return False, stderr.strip() or stdout.strip()

    def start_background_task(self, prompt: str) -> tuple[bool, str]:
        returncode, stdout, stderr = self.run_command(["--bg", prompt], timeout=60)
        if returncode == 0:
            return True, stdout.strip()
        return False, stderr.strip() or stdout.strip()

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

    def read_mcp_config(self) -> dict:
        mcp_path = os.path.join(self._claude_home, "mcp.json")
        try:
            if not os.path.isfile(mcp_path):
                return {}
            with open(mcp_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.warning(f"解析 mcp.json 失败: {e}")
            return {}
        except Exception as e:
            logger.error(f"读取 mcp.json 失败: {e}")
            return {}

    def write_mcp_config(self, config: dict) -> tuple[bool, str]:
        mcp_path = os.path.join(self._claude_home, "mcp.json")
        try:
            os.makedirs(self._claude_home, exist_ok=True)
            with open(mcp_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            return True, ""
        except Exception as e:
            logger.error(f"写入 mcp.json 失败: {e}")
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
        if returncode == 0 and stdout.strip():
            try:
                return json.loads(stdout)
            except json.JSONDecodeError:
                return {"raw": stdout.strip(), "running": "running" in stdout.lower()}
        return {"running": False}

    def list_sessions(self) -> list:
        returncode, stdout, stderr = self.run_command(["agents", "--json"])
        if returncode == 0 and stdout.strip():
            try:
                data = json.loads(stdout)
                return data if isinstance(data, list) else []
            except json.JSONDecodeError:
                logger.warning(f"远程解析 agents JSON 失败: {stdout[:200]}")
        return []

    def stop_session(self, session_id: str) -> tuple[bool, str]:
        returncode, stdout, stderr = self.run_command(["agents", "stop", session_id])
        if returncode == 0:
            return True, stdout.strip()
        return False, stderr.strip() or stdout.strip()

    def remove_session(self, session_id: str) -> tuple[bool, str]:
        returncode, stdout, stderr = self.run_command(["agents", "remove", session_id])
        if returncode == 0:
            return True, stdout.strip()
        return False, stderr.strip() or stdout.strip()

    def start_background_task(self, prompt: str) -> tuple[bool, str]:
        returncode, stdout, stderr = self.run_command(["--bg", prompt], timeout=60)
        if returncode == 0:
            return True, stdout.strip()
        return False, stderr.strip() or stdout.strip()

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

    def read_mcp_config(self) -> dict:
        try:
            result = self.ssh_conn.exec("cat ~/.claude/mcp.json", pty=False)
            if result and result.strip():
                return json.loads(result)
        except json.JSONDecodeError as e:
            logger.warning(f"远程解析 mcp.json 失败: {e}")
        except Exception as e:
            logger.error(f"远程读取 mcp.json 失败: {e}")
        return {}

    def write_mcp_config(self, config: dict) -> tuple[bool, str]:
        try:
            content = json.dumps(config, indent=2, ensure_ascii=False)
            escaped = content.replace("\\", "\\\\").replace("'", "'\\''")
            cmd = f"mkdir -p ~/.claude && printf '%s' '{escaped}' > ~/.claude/mcp.json"
            self.ssh_conn.exec(cmd, pty=False)
            return True, ""
        except Exception as e:
            logger.error(f"远程写入 mcp.json 失败: {e}")
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
