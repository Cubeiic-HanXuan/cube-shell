"""
Hermes Agent 数据访问抽象层
提供 LocalBackend 和 RemoteBackend 两种实现，
分别用于本地和通过 SSH 远程访问 hermes CLI / 文件系统 / SQLite。
"""

import os
import shutil
import sqlite3
import subprocess
from abc import ABC, abstractmethod

from function.util import logger


def _find_hermes_bin() -> str:
    """查找 hermes 可执行文件的完整路径，兼容 GUI 应用无 PATH 的情况"""
    # 先尝试标准 which 查找
    found = shutil.which("hermes")
    if found:
        return found
    # GUI 应用可能缺少用户 PATH，搜索常见安装位置
    home = os.path.expanduser("~")
    candidates = [
        os.path.join(home, ".local", "bin", "hermes"),
        "/usr/local/bin/hermes",
        "/opt/homebrew/bin/hermes",
        os.path.join(home, ".hermes", "bin", "hermes"),
    ]
    for path in candidates:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    # 都找不到就返回裸命令名，让后续报错更明确
    return "hermes"


class HermesBackend(ABC):
    """Hermes Agent 数据访问抽象层基类"""

    @abstractmethod
    def exec_cli(self, args: list[str], timeout: int = 30) -> str:
        """执行 hermes CLI 命令，返回 stdout"""
        ...

    @abstractmethod
    def read_file(self, path: str) -> str:
        """读取文件内容"""
        ...

    @abstractmethod
    def write_file(self, path: str, content: str):
        """写入文件"""
        ...

    @abstractmethod
    def list_dir(self, path: str) -> list[str]:
        """列出目录内容"""
        ...

    @abstractmethod
    def read_sqlite(self, db_path: str, sql: str) -> list:
        """执行 SQLite 查询，返回结果列表"""
        ...

    @abstractmethod
    def get_hermes_home(self) -> str:
        """获取 ~/.hermes 路径"""
        ...

    @abstractmethod
    def file_exists(self, path: str) -> bool:
        """检查文件是否存在"""
        ...

    @abstractmethod
    def delete_file(self, path: str):
        """删除文件"""
        ...


class LocalBackend(HermesBackend):
    """本地 Hermes 后端实现，直接通过本地文件系统和子进程操作"""

    def __init__(self):
        self._hermes_bin = _find_hermes_bin()

    def exec_cli(self, args: list[str], timeout: int = 30) -> str:
        try:
            result = subprocess.run(
                [self._hermes_bin] + args,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            if result.returncode != 0:
                logger.warning(f"hermes CLI 返回非零退出码: {result.returncode}, stderr: {result.stderr}")
            return result.stdout
        except Exception as e:
            logger.error(f"执行 hermes CLI 失败: {e}")
            return ""

    def read_file(self, path: str) -> str:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logger.error(f"读取文件失败 [{path}]: {e}")
            return ""

    def write_file(self, path: str, content: str):
        try:
            dir_path = os.path.dirname(path)
            if dir_path and not os.path.exists(dir_path):
                os.makedirs(dir_path, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
        except Exception as e:
            logger.error(f"写入文件失败 [{path}]: {e}")

    def list_dir(self, path: str) -> list[str]:
        try:
            return os.listdir(path)
        except Exception as e:
            logger.error(f"列出目录失败 [{path}]: {e}")
            return []

    def read_sqlite(self, db_path: str, sql: str) -> list:
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(sql)
            rows = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return rows
        except Exception as e:
            logger.error(f"SQLite 查询失败 [{db_path}]: {e}")
            return []

    def get_hermes_home(self) -> str:
        return os.path.expanduser("~/.hermes")

    def file_exists(self, path: str) -> bool:
        try:
            return os.path.exists(path)
        except Exception as e:
            logger.error(f"检查文件存在失败 [{path}]: {e}")
            return False

    def delete_file(self, path: str):
        try:
            os.remove(path)
        except Exception as e:
            logger.error(f"删除文件失败 [{path}]: {e}")
            raise

    def get_api_server_url(self) -> str:
        """获取 Hermes API Server 地址"""
        import yaml
        hermes_home = self.get_hermes_home()
        config_path = os.path.join(hermes_home, "config.yaml")
        try:
            content = self.read_file(config_path)
            if content:
                config = yaml.safe_load(content)
                platforms = config.get("platforms", {})
                api_server = platforms.get("api_server", {})
                extra = api_server.get("extra", {})
                host = extra.get("host", "127.0.0.1")
                port = extra.get("port", 8642)
                return f"http://{host}:{port}"
        except Exception:
            pass
        return "http://127.0.0.1:8642"

    def get_api_server_key(self) -> str:
        """获取 Hermes API Server 认证 Key"""
        import yaml
        hermes_home = self.get_hermes_home()
        # 先从 .env 读取
        env_path = os.path.join(hermes_home, ".env")
        env_content = self.read_file(env_path)
        if env_content:
            for line in env_content.splitlines():
                line = line.strip()
                if line.startswith("API_SERVER_KEY="):
                    return line.split("=", 1)[1].strip()
        # 再从 config.yaml 读取
        config_path = os.path.join(hermes_home, "config.yaml")
        try:
            content = self.read_file(config_path)
            if content:
                config = yaml.safe_load(content)
                platforms = config.get("platforms", {})
                api_server = platforms.get("api_server", {})
                key = api_server.get("key", "")
                if key:
                    return key
        except Exception:
            pass
        return "change-me-local-dev"

    def list_profiles(self) -> list:
        """获取可用 profiles 列表"""
        hermes_home = self.get_hermes_home()
        profiles_dir = os.path.join(hermes_home, "profiles")
        profiles = [{"name": "default", "active": True}]
        try:
            if os.path.isdir(profiles_dir):
                for name in sorted(os.listdir(profiles_dir)):
                    if name.startswith('.'):
                        continue
                    if name != "default":
                        profiles.append({"name": name, "active": False})
        except Exception:
            pass
        return profiles


class RemoteBackend(HermesBackend):
    """远程 Hermes 后端实现，通过 SSH 连接操作远程主机"""

    def __init__(self, ssh_conn):
        """
        Args:
            ssh_conn: SshClient 实例（来自 function/ssh_func.py）
        """
        self.ssh_conn = ssh_conn

    def exec_cli(self, args: list[str], timeout: int = 30) -> str:
        try:
            cmd = f"hermes {' '.join(args)}"
            result = self.ssh_conn.exec(cmd, pty=False, timeout=timeout)
            return result if result else ""
        except Exception as e:
            logger.error(f"远程执行 hermes CLI 失败: {e}")
            return ""

    def read_file(self, path: str) -> str:
        try:
            sftp = self.ssh_conn.open_sftp()
            with sftp.file(path, 'r') as f:
                content = f.read()
            return content.decode('utf-8') if isinstance(content, bytes) else content
        except Exception as e:
            logger.error(f"远程读取文件失败 [{path}]: {e}")
            return ""

    def write_file(self, path: str, content: str):
        try:
            sftp = self.ssh_conn.open_sftp()
            with sftp.file(path, 'w') as f:
                f.write(content)
        except Exception as e:
            logger.error(f"远程写入文件失败 [{path}]: {e}")

    def list_dir(self, path: str) -> list[str]:
        try:
            sftp = self.ssh_conn.open_sftp()
            return sftp.listdir(path)
        except Exception as e:
            logger.error(f"远程列出目录失败 [{path}]: {e}")
            return []

    def read_sqlite(self, db_path: str, sql: str) -> list:
        try:
            # 通过 SSH 执行 sqlite3 命令，使用 | 分隔符和 header 便于解析
            escaped_sql = sql.replace('"', '\\"')
            cmd = f'sqlite3 -separator "|" -header "{db_path}" "{escaped_sql}"'
            result = self.ssh_conn.exec(cmd, pty=False)
            if not result or not result.strip():
                return []
            lines = result.strip().split('\n')
            if len(lines) < 2:
                return []
            headers = lines[0].split('|')
            rows = []
            for line in lines[1:]:
                values = line.split('|')
                row = dict(zip(headers, values))
                rows.append(row)
            return rows
        except Exception as e:
            logger.error(f"远程 SQLite 查询失败 [{db_path}]: {e}")
            return []

    def get_hermes_home(self) -> str:
        try:
            result = self.ssh_conn.exec("echo $HOME", pty=False)
            home = result.strip() if result else ""
            if home:
                return f"{home}/.hermes"
            return "~/.hermes"
        except Exception as e:
            logger.error(f"获取远程 hermes home 失败: {e}")
            return "~/.hermes"

    def file_exists(self, path: str) -> bool:
        try:
            result = self.ssh_conn.exec(f'test -f "{path}" && echo exists', pty=False)
            return result is not None and "exists" in result
        except Exception as e:
            logger.error(f"远程检查文件存在失败 [{path}]: {e}")
            return False

    def delete_file(self, path: str):
        try:
            self.ssh_conn.exec(f'rm -f "{path}"', pty=False)
        except Exception as e:
            logger.error(f"远程删除文件失败 [{path}]: {e}")
            raise

    def get_api_server_url(self) -> str:
        """获取远程 Hermes API Server 地址（通过 SSH 读取配置）"""
        import yaml
        hermes_home = self.get_hermes_home()
        config_path = f"{hermes_home}/config.yaml"
        try:
            content = self.read_file(config_path)
            if content:
                config = yaml.safe_load(content)
                platforms = config.get("platforms", {})
                api_server = platforms.get("api_server", {})
                extra = api_server.get("extra", {})
                host = extra.get("host", "127.0.0.1")
                port = extra.get("port", 8642)
                return f"http://{host}:{port}"
        except Exception:
            pass
        return "http://127.0.0.1:8642"

    def get_api_server_key(self) -> str:
        """获取远程 Hermes API Server 认证 Key"""
        import yaml
        hermes_home = self.get_hermes_home()
        # 先从 .env 读取
        env_path = f"{hermes_home}/.env"
        env_content = self.read_file(env_path)
        if env_content:
            for line in env_content.splitlines():
                line = line.strip()
                if line.startswith("API_SERVER_KEY="):
                    return line.split("=", 1)[1].strip()
        # 再从 config.yaml 读取
        config_path = f"{hermes_home}/config.yaml"
        try:
            content = self.read_file(config_path)
            if content:
                config = yaml.safe_load(content)
                platforms = config.get("platforms", {})
                api_server = platforms.get("api_server", {})
                key = api_server.get("key", "")
                if key:
                    return key
        except Exception:
            pass
        return "change-me-local-dev"

    def list_profiles(self) -> list:
        """获取远程可用 profiles 列表"""
        hermes_home = self.get_hermes_home()
        profiles_dir = f"{hermes_home}/profiles"
        profiles = [{"name": "default", "active": True}]
        try:
            names = self.list_dir(profiles_dir)
            for name in sorted(names):
                if name.startswith('.'):
                    continue
                if name != "default":
                    profiles.append({"name": name, "active": False})
        except Exception:
            pass
        return profiles
