"""
命令安全检查器模块。

对用户（或 AI）即将在远程 SSH 会话中执行的命令进行风险评估，
根据预定义的黑名单、白名单和风险规则返回 SafetyCheckResult，
由调用方决定是否放行、提示还是阻止。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar


# ──────────────────────────── 风险等级枚举 ────────────────────────────


class RiskLevel(Enum):
    """命令风险等级，由低到高。"""

    SAFE = "safe"          # 只读查询，自动执行
    LOW = "low"            # 低风险，提示后自动执行
    MEDIUM = "medium"      # 中等风险，需要用户确认
    HIGH = "high"          # 高风险，强制确认 + 二次确认
    CRITICAL = "critical"  # 危险操作，直接阻止


# ──────────────────────────── 检查结果 ────────────────────────────────


@dataclass
class SafetyCheckResult:
    """单条命令的安全检查结果。"""

    risk_level: RiskLevel
    is_allowed: bool       # 是否允许执行
    reason: str            # 检查结论说明
    warnings: list[str] = field(default_factory=list)  # 警告信息


# ──────────────────────────── 安全检查器 ────────────────────────────────


class CommandSafetyChecker:
    """
    命令安全检查器。

    通过 CRITICAL 黑名单、SAFE 白名单和一组风险评估规则，
    对任意 shell 命令进行静态风险评估。

    * 所有正则均在类加载时预编译，保证线程安全与性能。
    * 实例无状态，可安全地跨线程复用。
    """

    # ────────── CRITICAL 黑名单（正则，绝对阻止） ──────────

    _CRITICAL_PATTERNS: ClassVar[list[tuple[re.Pattern, str]]] = [
        (re.compile(r"\brm\s+(-[a-zA-Z]*f[a-zA-Z]*\s+)?-[a-zA-Z]*r[a-zA-Z]*\s+/(\s|$|\*)"),
         "递归强制删除根目录"),
        (re.compile(r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*\s+)?-[a-zA-Z]*f[a-zA-Z]*\s+/(\s|$|\*)"),
         "递归强制删除根目录"),
        (re.compile(r"\bdd\s+.*if=.*of=/dev/"),
         "直接写入块设备，可能销毁磁盘数据"),
        (re.compile(r"\bmkfs\b"),
         "格式化文件系统"),
        (re.compile(r"\bwipefs\b"),
         "擦除文件系统签名"),
        (re.compile(r":\(\)\s*\{\s*:\|:\s*&\s*\}\s*;\s*:"),
         "Fork 炸弹，将耗尽系统资源"),
        (re.compile(r"\bchmod\s+(-[a-zA-Z]*R[a-zA-Z]*\s+)?777\s+/(\s|$)"),
         "递归修改根目录权限为 777"),
        (re.compile(r"\bchown\s+.*-[a-zA-Z]*R[a-zA-Z]*\s+.*\s+/(\s|$)"),
         "递归修改根目录所有者"),
        (re.compile(r">\s*/dev/sd[a-z]"),
         "覆写块设备"),
    ]

    # ────────── HIGH 风险命令（需确认但不直接阻止） ──────────

    _HIGH_PATTERNS: ClassVar[list[tuple[re.Pattern, str]]] = [
        (re.compile(r"\bshutdown\b"),   "关机命令"),
        (re.compile(r"\breboot\b"),     "重启命令"),
        (re.compile(r"\bhalt\b"),       "停机命令"),
        (re.compile(r"\bpoweroff\b"),   "关机命令"),
        (re.compile(r"\biptables\b"),   "防火墙规则修改"),
        (re.compile(r"\bufw\b"),        "防火墙配置修改"),
        (re.compile(r"\bifconfig\b.*\b(up|down)\b"), "网络接口配置修改"),
        (re.compile(r"\bip\s+link\s+set\b"),         "网络链路配置修改"),
        (re.compile(r"\bip\s+addr\s+(add|del)\b"),   "网络地址配置修改"),
        (re.compile(r"\bip\s+route\s+(add|del)\b"),  "路由表修改"),
        (re.compile(r"\bnmcli\b.*\bmod"),            "NetworkManager 配置修改"),
    ]

    # ────────── SAFE 白名单（只读命令前缀，自动执行） ──────────

    _SAFE_PREFIXES: ClassVar[tuple[str, ...]] = (
        # 文件查看
        "ls", "cat", "head", "tail", "grep", "find",
        # 磁盘与内存
        "df", "du", "free",
        # 进程与系统
        "top", "htop", "ps", "uptime", "uname", "whoami", "hostname", "date",
        # 文本处理（只读）
        "wc", "sort", "uniq",
        # 网络查看
        "ss", "netstat", "ip addr", "ip route",
        "ping", "traceroute", "dig", "nslookup",
        # 服务状态查看
        "systemctl status", "journalctl",
        # 命令查询
        "which", "type", "file",
    )

    # ────────── MEDIUM 风险规则（正则 + 说明） ──────────

    _MEDIUM_PATTERNS: ClassVar[list[tuple[re.Pattern, str]]] = [
        (re.compile(r"\bsudo\b"),
         "使用 sudo 提权"),
        # 写操作
        (re.compile(r"[^|]\s*>\s*[^>]"),
         "输出重定向（覆写文件）"),
        (re.compile(r">>"),
         "输出追加重定向"),
        (re.compile(r"\btee\b"),
         "tee 写文件"),
        (re.compile(r"\bsed\s+.*-i\b"),
         "sed 原地编辑文件"),
        # 服务管理
        (re.compile(r"\bsystemctl\s+(stop|restart|disable)\b"),
         "服务管理操作"),
        (re.compile(r"\bservice\s+\S+\s+(stop|restart)\b"),
         "服务管理操作"),
        # 包管理
        (re.compile(r"\b(apt|apt-get|yum|dnf|pacman|zypper)\s+.*(install|remove|purge)\b"),
         "包管理操作"),
        (re.compile(r"\bpip\s+install\b"),
         "Python 包安装"),
        (re.compile(r"\bnpm\s+install\b"),
         "Node.js 包安装"),
    ]

    # ────────── 公共接口 ──────────

    def check(self, command: str) -> SafetyCheckResult:
        """
        对单条命令进行安全检查。

        :param command: 待检查的 shell 命令字符串
        :return: SafetyCheckResult 实例
        """
        cmd = command.strip()
        if not cmd:
            return SafetyCheckResult(
                risk_level=RiskLevel.SAFE,
                is_allowed=True,
                reason="空命令",
            )

        # 1) CRITICAL 黑名单 —— 直接阻止
        for pattern, desc in self._CRITICAL_PATTERNS:
            if pattern.search(cmd):
                return SafetyCheckResult(
                    risk_level=RiskLevel.CRITICAL,
                    is_allowed=False,
                    reason=f"命令被阻止：{desc}",
                    warnings=[f"匹配危险模式: {desc}"],
                )

        # 2) HIGH 风险 —— 允许但强制确认
        high_warnings: list[str] = []
        for pattern, desc in self._HIGH_PATTERNS:
            if pattern.search(cmd):
                high_warnings.append(desc)

        if high_warnings:
            return SafetyCheckResult(
                risk_level=RiskLevel.HIGH,
                is_allowed=True,
                reason=f"高风险操作，需二次确认：{'; '.join(high_warnings)}",
                warnings=high_warnings,
            )

        # 3) SAFE 白名单 —— 自动放行
        if self._is_safe_command(cmd):
            return SafetyCheckResult(
                risk_level=RiskLevel.SAFE,
                is_allowed=True,
                reason="只读查询命令，自动执行",
            )

        # 4) MEDIUM 风险规则
        medium_warnings: list[str] = []
        for pattern, desc in self._MEDIUM_PATTERNS:
            if pattern.search(cmd):
                medium_warnings.append(desc)

        # sudo 出现时，即使其它规则也命中，等级至少为 MEDIUM
        if medium_warnings:
            # 含 sudo 且同时命中其它规则 → 仍为 MEDIUM（sudo 本身已是 MEDIUM）
            return SafetyCheckResult(
                risk_level=RiskLevel.MEDIUM,
                is_allowed=True,
                reason=f"中等风险操作，需用户确认：{'; '.join(medium_warnings)}",
                warnings=medium_warnings,
            )

        # 5) 默认归为 LOW —— 提示后自动执行
        return SafetyCheckResult(
            risk_level=RiskLevel.LOW,
            is_allowed=True,
            reason="未匹配已知风险模式，按低风险处理",
        )

    def check_batch(self, commands: list[str]) -> list[SafetyCheckResult]:
        """
        批量检查多条命令。

        :param commands: 命令字符串列表
        :return: 与输入顺序对应的 SafetyCheckResult 列表
        """
        return [self.check(cmd) for cmd in commands]

    # ────────── 内部辅助 ──────────

    def _is_safe_command(self, cmd: str) -> bool:
        """判断命令是否匹配 SAFE 白名单前缀。"""
        # 去除开头可能的环境变量赋值，如 "LC_ALL=C ls"
        effective = self._strip_env_prefix(cmd)
        for prefix in self._SAFE_PREFIXES:
            if effective == prefix or effective.startswith(prefix + " "):
                return True
        return False

    @staticmethod
    def _strip_env_prefix(cmd: str) -> str:
        """
        移除命令前的环境变量赋值部分。

        例如 ``LC_ALL=C LANG=en_US ls -la`` → ``ls -la``
        """
        parts = cmd.split()
        idx = 0
        for part in parts:
            if "=" in part and not part.startswith("="):
                idx += 1
            else:
                break
        return " ".join(parts[idx:]) if idx < len(parts) else cmd
