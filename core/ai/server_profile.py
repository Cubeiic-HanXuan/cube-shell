"""
服务器画像模块

提供 ServerProfile 数据类和 ServerProfileBuilder 构建器，
用于收集远程服务器的系统信息、运行状态和环境信息，
并生成可注入 AI system prompt 的上下文描述。
"""

import re
import time
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ServerProfile:
    """服务器状态画像"""

    # 基础信息
    os_id: str = ""              # "ubuntu", "centos", "debian" 等
    os_version: str = ""         # "22.04", "7", "12" 等
    os_pretty_name: str = ""     # "Ubuntu 22.04.3 LTS"
    arch: str = ""               # "x86_64", "aarch64"
    has_systemd: bool = True     # 是否使用 systemd
    kernel_version: str = ""     # 内核版本

    # 包管理器
    package_manager: str = ""    # "apt", "yum", "dnf", "zypper", "apk", "pacman"

    # 运行状态
    cpu_usage: float = 0.0       # CPU 使用率 (%)
    memory_usage: float = 0.0    # 内存使用率 (%)
    memory_total_mb: int = 0     # 总内存 (MB)
    disk_usage: float = 0.0      # 根分区使用率 (%)

    # 环境信息
    running_services: list = field(default_factory=list)  # 运行中的服务列表
    open_ports: list = field(default_factory=list)        # 开放端口
    shell_type: str = "bash"     # 默认 shell
    python_version: str = ""     # Python 版本（若有）
    docker_installed: bool = False  # Docker 是否已安装

    # 用户身份
    current_user: str = ""          # 当前 SSH 连接用户名
    is_root: bool = False           # 是否为 root 用户

    # 元信息
    last_updated: float = 0.0    # 上次更新时间戳


class ServerProfileBuilder:
    """服务器画像构建器"""

    TTL_SECONDS = 300  # 5 分钟缓存

    def __init__(self, ssh_client):
        """
        初始化构建器。

        Args:
            ssh_client: 任何具有 exec(cmd, pty) 方法的对象（鸭子类型，
                        通常为 function/ssh_func.py 中的 SshClient 实例）
        """
        self._ssh = ssh_client
        self._cache: ServerProfile | None = None
        self._cache_time: float = 0

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def build(self, force_refresh: bool = False) -> ServerProfile:
        """构建/获取服务器画像（带缓存）

        Args:
            force_refresh: 为 True 时强制刷新，忽略缓存

        Returns:
            ServerProfile 实例
        """
        now = time.time()
        if (
            not force_refresh
            and self._cache is not None
            and (now - self._cache_time) < self.TTL_SECONDS
        ):
            return self._cache

        profile = ServerProfile()

        # 检测 OS 基础信息
        os_info = self._detect_os_info()
        profile.os_id = os_info.get("id", "")
        profile.os_version = os_info.get("version_id", "")
        profile.os_pretty_name = os_info.get("pretty_name", "")
        profile.arch = os_info.get("arch", "")
        profile.has_systemd = os_info.get("has_systemd", True)
        profile.kernel_version = os_info.get("kernel_version", "")

        # 检测包管理器
        profile.package_manager = self._detect_package_manager(
            os_info.get("id", ""), os_info.get("id_like", "")
        )

        # 获取运行时状态（CPU / 内存 / 磁盘）
        runtime = self._detect_runtime_stats()
        profile.cpu_usage = runtime.get("cpu_usage", 0.0)
        profile.memory_usage = runtime.get("memory_usage", 0.0)
        profile.memory_total_mb = runtime.get("memory_total_mb", 0)
        profile.disk_usage = runtime.get("disk_usage", 0.0)

        # 检测运行中的服务
        profile.running_services = self._detect_running_services(profile.has_systemd)

        # 检测开放端口
        profile.open_ports = self._detect_open_ports()

        # 检测 Shell 类型
        profile.shell_type = self._detect_shell_type()

        # 检测 Python 版本
        profile.python_version = self._detect_python_version()

        # 检测 Docker 是否安装
        profile.docker_installed = self._detect_docker_installed()

        # 获取当前连接用户身份
        username = getattr(self._ssh, 'username', '') or ''
        profile.current_user = username
        profile.is_root = (username == 'root')

        profile.last_updated = time.time()

        # 更新缓存
        self._cache = profile
        self._cache_time = profile.last_updated

        return profile

    def build_system_context_prompt(self, profile: ServerProfile | None = None) -> str:
        """
        构建系统上下文 prompt 片段，用于注入到 AI system prompt 中。

        Args:
            profile: 可选的 ServerProfile 实例；为 None 时自动调用 build()

        Returns:
            格式化后的系统上下文字符串
        """
        if profile is None:
            profile = self.build()

        lines: list[str] = ["你正在操作以下服务器:"]

        # 系统信息
        os_desc = profile.os_pretty_name or profile.os_id or "未知"
        if profile.arch:
            os_desc += f" ({profile.arch})"
        lines.append(f"- 系统: {os_desc}")

        if profile.kernel_version:
            lines.append(f"- 内核: {profile.kernel_version}")

        if profile.package_manager:
            lines.append(f"- 包管理器: {profile.package_manager}")

        # 服务管理方式
        svc_mgr = "systemctl" if profile.has_systemd else "service"
        lines.append(f"- 服务管理: {svc_mgr}")

        # 运行状态
        lines.append(
            f"- CPU: {profile.cpu_usage:.1f}%  "
            f"内存: {profile.memory_usage:.1f}% ({profile.memory_total_mb}MB)  "
            f"磁盘: {profile.disk_usage:.1f}%"
        )

        # 已安装服务
        if profile.running_services:
            services_str = ", ".join(profile.running_services)
            lines.append(f"- 已安装服务: {services_str}")

        # 开放端口
        if profile.open_ports:
            ports_str = ", ".join(str(p) for p in profile.open_ports)
            lines.append(f"- 开放端口: {ports_str}")

        # Docker
        docker_status = "已安装" if profile.docker_installed else "未安装"
        lines.append(f"- Docker: {docker_status}")

        # Python
        if profile.python_version:
            lines.append(f"- Python: {profile.python_version}")

        # 约束提示
        lines.append("")
        lines.append("约束:")
        constraint_idx = 1
        if profile.package_manager:
            lines.append(f"{constraint_idx}. 使用 {profile.package_manager} 安装软件")
            constraint_idx += 1
        if profile.has_systemd:
            lines.append(f"{constraint_idx}. 使用 systemctl 管理服务")
        else:
            lines.append(f"{constraint_idx}. 使用 service 命令管理服务")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 内部检测方法
    # ------------------------------------------------------------------

    def _safe_exec(self, cmd: str) -> str:
        """安全执行远程命令，异常时返回空字符串

        Args:
            cmd: 要执行的 shell 命令

        Returns:
            命令输出或空字符串
        """
        try:
            result = self._ssh.exec(cmd=cmd, pty=False)
            return (result or "").strip()
        except Exception as e:
            logger.debug(f"远程命令执行失败 [{cmd}]: {e}")
            return ""

    def _detect_os_info(self) -> dict:
        """检测 OS 信息（通过 /etc/os-release 和 uname）

        Returns:
            包含 id, version_id, pretty_name, arch, has_systemd, kernel_version 等的字典
        """
        info: dict[str, str] = {}

        # --- 解析 /etc/os-release ---
        out = self._safe_exec("cat /etc/os-release 2>/dev/null || true")
        if out:
            for line in out.splitlines():
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = (k or "").strip()
                v = (v or "").strip().strip('"').strip("'")
                if k:
                    info[k.lower()] = v

        # --- 备用: /etc/redhat-release ---
        if not info.get("id"):
            out2 = self._safe_exec("cat /etc/redhat-release 2>/dev/null || true")
            txt = (out2 or "").strip()
            if txt:
                info["pretty_name"] = info.get("pretty_name") or txt
                low = txt.lower()
                if "centos" in low:
                    info["id"] = "centos"
                elif "red hat" in low or "rhel" in low:
                    info["id"] = "rhel"
                m = re.search(r"release\s+(\d+)", low)
                if m:
                    info["version_id"] = info.get("version_id") or m.group(1)

        # --- 架构 ---
        arch_out = self._safe_exec("uname -m 2>/dev/null || true")
        if arch_out:
            info["arch"] = arch_out.strip()

        # --- 内核版本 ---
        kernel_out = self._safe_exec("uname -r 2>/dev/null || true")
        if kernel_out:
            info["kernel_version"] = kernel_out.strip()

        # --- systemd 检测 ---
        systemd_out = self._safe_exec(
            "command -v systemctl >/dev/null 2>&1 && echo 'yes' || echo 'no'"
        )
        info["has_systemd"] = "yes" in systemd_out.lower() if systemd_out else False

        return info

    def _detect_package_manager(self, os_id: str = "", id_like: str = "") -> str:
        """检测包管理器类型

        优先通过 os_id / id_like 快速判断，若无法确定则逐一探测命令是否存在。

        Args:
            os_id:   发行版 ID（如 "ubuntu"）
            id_like: 发行版族（如 "debian"）

        Returns:
            包管理器名称，如 "apt", "dnf", "yum" 等
        """
        os_id_lower = os_id.lower()
        id_like_lower = id_like.lower()

        # 根据发行版快速匹配
        if os_id_lower in {"ubuntu", "debian"} or "debian" in id_like_lower:
            return "apt"
        if os_id_lower == "fedora" or "fedora" in id_like_lower:
            return "dnf"
        if os_id_lower in {"centos", "rhel", "rocky", "almalinux", "ol"}:
            # CentOS 8+ / RHEL 8+ 使用 dnf
            dnf_check = self._safe_exec("command -v dnf 2>/dev/null && echo 'found'")
            if "found" in dnf_check:
                return "dnf"
            return "yum"
        if os_id_lower in {"opensuse", "sles"} or "suse" in id_like_lower:
            return "zypper"
        if os_id_lower == "alpine":
            return "apk"
        if os_id_lower in {"arch", "manjaro"} or "arch" in id_like_lower:
            return "pacman"

        # 回退: 按优先级逐一探测
        candidates = ["apt", "dnf", "yum", "zypper", "apk", "pacman"]
        for mgr in candidates:
            check = self._safe_exec(f"command -v {mgr} 2>/dev/null && echo 'found'")
            if "found" in check:
                return mgr

        return ""

    def _detect_running_services(self, has_systemd: bool = True) -> list[str]:
        """获取运行中的服务列表（前 20 个）

        Args:
            has_systemd: 是否使用 systemd

        Returns:
            服务名列表，如 ["nginx", "mysql", "redis"]
        """
        services: list[str] = []

        if has_systemd:
            out = self._safe_exec(
                "systemctl list-units --type=service --state=running "
                "--no-pager --plain 2>/dev/null"
            )
            if out:
                for line in out.splitlines():
                    line = line.strip()
                    if not line or line.startswith("UNIT") or line.startswith("LOAD"):
                        continue
                    # 格式示例: nginx.service loaded active running ...
                    parts = line.split()
                    if parts:
                        svc_name = parts[0]
                        # 去掉 .service 后缀
                        svc_name = re.sub(r"\.service$", "", svc_name)
                        # 过滤掉系统内部服务，只保留常见应用服务
                        if not self._is_system_service(svc_name):
                            services.append(svc_name)
                    if len(services) >= 20:
                        break
        else:
            # 非 systemd 系统使用 service --status-all
            out = self._safe_exec("service --status-all 2>/dev/null")
            if out:
                for line in out.splitlines():
                    line = line.strip()
                    # 格式示例: [ + ]  nginx
                    if "[ + ]" in line:
                        parts = line.split("]", 1)
                        if len(parts) > 1:
                            svc_name = parts[1].strip()
                            if svc_name and not self._is_system_service(svc_name):
                                services.append(svc_name)
                    if len(services) >= 20:
                        break

        return services

    @staticmethod
    def _is_system_service(name: str) -> bool:
        """判断是否为系统内部服务（用于过滤）

        Args:
            name: 服务名

        Returns:
            True 表示是系统内部服务，应过滤
        """
        # 常见系统内部服务前缀/关键字
        system_prefixes = (
            "systemd-", "dbus", "polkit", "accounts-daemon",
            "udisks", "upower", "colord", "rtkit",
            "avahi", "ModemManager", "NetworkManager-wait",
            "plymouth", "getty", "serial-getty",
            "user@", "user-runtime-dir@", "session-",
        )
        return any(name.startswith(p) for p in system_prefixes)

    def _detect_open_ports(self) -> list[int]:
        """检测开放的监听端口

        Returns:
            端口号列表（已排序去重），如 [22, 80, 443, 3306]
        """
        ports: set[int] = set()

        # 优先使用 ss
        out = self._safe_exec("ss -tlnp 2>/dev/null")
        if not out or "State" not in out:
            # 回退到 netstat
            out = self._safe_exec("netstat -tlnp 2>/dev/null")

        if out:
            for line in out.splitlines():
                line = line.strip()
                # 跳过标题行
                if not line or line.startswith("State") or line.startswith("Proto"):
                    continue
                # 从本地地址列提取端口
                # ss 格式:  LISTEN  0  128  0.0.0.0:22  0.0.0.0:*
                # netstat:  tcp  0  0  0.0.0.0:22  0.0.0.0:*  LISTEN
                parts = line.split()
                for part in parts:
                    # 匹配 *:port, 0.0.0.0:port, :::port, [::]:port 等
                    m = re.search(r":(\d+)$", part)
                    if m:
                        port = int(m.group(1))
                        if 1 <= port <= 65535:
                            ports.add(port)
                        break  # 只取第一个地址列

        return sorted(ports)

    def _detect_runtime_stats(self) -> dict:
        """获取实时运行状态

        复用 SshClient 的 get_cpu_stats / get_memory_stats / get_disk_stats（若有），
        否则通过轻量命令获取。

        Returns:
            包含 cpu_usage, memory_usage, memory_total_mb, disk_usage 的字典
        """
        stats: dict = {
            "cpu_usage": 0.0,
            "memory_usage": 0.0,
            "memory_total_mb": 0,
            "disk_usage": 0.0,
        }

        # --- 内存 ---
        if hasattr(self._ssh, "get_memory_stats"):
            try:
                mem = self._ssh.get_memory_stats()
                stats["memory_usage"] = mem.get("usage_percent", 0.0)
                stats["memory_total_mb"] = mem.get("total", 0)
            except Exception:
                self._fallback_memory_stats(stats)
        else:
            self._fallback_memory_stats(stats)

        # --- 磁盘 ---
        if hasattr(self._ssh, "get_disk_stats"):
            try:
                disk = self._ssh.get_disk_stats()
                stats["disk_usage"] = disk.get("root_usage", 0.0)
            except Exception:
                self._fallback_disk_stats(stats)
        else:
            self._fallback_disk_stats(stats)

        # --- CPU（轻量获取，避免 get_cpu_stats 的 2 秒阻塞） ---
        self._fallback_cpu_stats(stats)

        return stats

    def _fallback_cpu_stats(self, stats: dict) -> None:
        """通过 /proc/loadavg 快速获取 CPU 负载替代精确使用率"""
        out = self._safe_exec("nproc 2>/dev/null && cat /proc/loadavg 2>/dev/null")
        if out:
            lines = out.strip().splitlines()
            if len(lines) >= 2:
                try:
                    nproc = int(lines[0].strip())
                    load1 = float(lines[1].split()[0])
                    # 将 1 分钟负载转换为近似使用率百分比
                    stats["cpu_usage"] = round(min(load1 / nproc * 100, 100.0), 1)
                except (ValueError, IndexError):
                    pass

    def _fallback_memory_stats(self, stats: dict) -> None:
        """通过 free -m 获取内存信息"""
        out = self._safe_exec("free -m 2>/dev/null")
        if out:
            for line in out.splitlines():
                if line.strip().lower().startswith("mem:"):
                    parts = line.split()
                    if len(parts) >= 3:
                        try:
                            total = int(parts[1])
                            used = int(parts[2])
                            stats["memory_total_mb"] = total
                            if total > 0:
                                stats["memory_usage"] = round(used / total * 100, 1)
                        except (ValueError, IndexError):
                            pass
                    break

    def _fallback_disk_stats(self, stats: dict) -> None:
        """通过 df 获取根分区使用率"""
        out = self._safe_exec("df / 2>/dev/null | tail -1")
        if out:
            parts = out.split()
            # 寻找百分比列
            for part in parts:
                m = re.match(r"(\d+)%", part)
                if m:
                    stats["disk_usage"] = float(m.group(1))
                    break

    def _detect_shell_type(self) -> str:
        """检测默认 shell 类型

        Returns:
            shell 名称，如 "bash", "zsh", "sh"
        """
        out = self._safe_exec("echo $SHELL 2>/dev/null")
        if out:
            # /bin/bash -> bash
            shell = out.strip().rsplit("/", 1)[-1]
            if shell:
                return shell
        return "bash"

    def _detect_python_version(self) -> str:
        """检测 Python 版本（若已安装）

        Returns:
            版本号字符串（如 "3.11.6"），未安装则返回空字符串
        """
        # 优先 python3，再 python
        out = self._safe_exec(
            "python3 --version 2>/dev/null || python --version 2>/dev/null || true"
        )
        if out:
            m = re.search(r"Python\s+(\d+\.\d+\.\d+)", out, re.IGNORECASE)
            if m:
                return m.group(1)
        return ""

    def _detect_docker_installed(self) -> bool:
        """检测 Docker 是否已安装

        Returns:
            True 表示已安装
        """
        out = self._safe_exec("command -v docker 2>/dev/null && echo 'found'")
        return "found" in out
