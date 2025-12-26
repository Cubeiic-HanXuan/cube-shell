import json
import os
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set, Tuple

from prompt_toolkit.completion import Completer, Completion


def _default_linux_commands_path() -> str:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(repo_root, "conf", "linux_commands.json")


def _extract_options(option_text: str) -> Set[str]:
    if not option_text:
        return set()
    opts: Set[str] = set()
    for m in re.finditer(r"(?m)^\s*(--?[A-Za-z0-9][\w\-]*)", option_text):
        opts.add(m.group(1))
    for m in re.finditer(r"\b(--?[A-Za-z0-9][\w\-]*)\b", option_text):
        opts.add(m.group(1))
    return opts


def _walk_tree(nodes: List[dict]) -> Iterable[dict]:
    for n in nodes or []:
        yield n
        children = n.get("children") or []
        if isinstance(children, list):
            yield from _walk_tree(children)


def load_linux_commands(path: Optional[str] = None) -> Dict[str, object]:
    builtin_commands = {
        # 基础文件/目录操作
        "ls", "cd", "pwd", "cat", "echo", "touch", "mkdir", "rm", "rmdir", "cp", "mv", "ln", "find",
        "tail", "head", "less", "more", "wc", "du", "df", "file", "diff", "sed", "awk", "sort", "uniq",
        # 压缩/解压缩
        "tar", "zip", "unzip", "gzip", "gunzip", "bzip2", "bunzip2", "xz", "unxz",
        # 网络操作
        "ssh", "scp", "rsync", "ping", "traceroute", "mtr", "curl", "wget", "nc", "telnet", "ss", "netstat", "ip", "ifconfig",
        # 权限/用户管理
        "chmod", "chown", "chgrp", "sudo", "su", "useradd", "userdel", "groupadd", "passwd",
        # 进程/系统管理
        "ps", "kill", "killall", "pkill", "systemctl", "journalctl", "top", "htop", "free", "vmstat", "iostat", "uptime", "who", "w",
        # 容器/版本控制
        "docker", "git", "podman",
        # 包管理
        "apt", "apt-get", "apt-cache", "dpkg", "yum", "dnf", "rpm",
        # 编程语言/工具
        "python3", "python", "pip", "pip3", "node", "npm", "java", "javac", "gcc", "make",
        # 系统配置/日志
        "hostname", "hostnamectl", "timedatectl", "logrotate", "dmesg", "lsblk", "mount", "umount",
        # 文本处理
        "cut", "paste", "tr", "grep", "egrep", "fgrep"
    }

    builtin_options = {
        # 基础命令补充
        "ls": {"-l", "-a", "-h", "-t", "-r", "-S", "-R", "-d", "-1", "--color=auto"},
        "rm": {"-f", "-r", "-i", "-v"},
        "cp": {"-r", "-f", "-i", "-v", "-p"},
        "mv": {"-f", "-i", "-v", "-u"},
        "mkdir": {"-p", "-v", "-m"},
        "find": {"-name", "-type", "-size", "-mtime", "-exec", "-print", "-iname", "-maxdepth"},
        "wc": {"-l", "-w", "-c", "-m"},
        "du": {"-h", "-s", "-c", "-x"},
        "df": {"-h", "-T", "-i"},

        # 文本处理命令补充
        "grep": {"-n", "-i", "-r", "-E", "-F", "-C", "-v", "-l", "-c", "-w", "--color=auto"},
        "sed": {"-i", "-e", "-f", "-n"},
        "awk": {"-F", "-v", "-f"},
        "sort": {"-n", "-r", "-k", "-u", "-t"},
        "uniq": {"-c", "-d", "-u"},

        # 压缩命令补充
        "tar": {"-x", "-c", "-v", "-f", "-z", "-j", "-J", "-C", "--exclude", "-p"},
        "zip": {"-r", "-q", "-u", "-d"},
        "unzip": {"-d", "-l", "-q", "-o"},

        # 网络命令补充
        "tail": {"-n", "-f", "-F", "-q", "-v"},
        "head": {"-n", "-q", "-v"},
        "ssh": {"-p", "-i", "-o", "-t", "-v", "-X", "-Y", "-N", "-f"},
        "scp": {"-P", "-i", "-r", "-v", "-p", "-C"},
        "curl": {"-L", "-I", "-s", "-S", "-o", "-O", "-X", "-H", "-d", "-u", "-k", "-v"},
        "wget": {"-O", "-q", "--no-check-certificate", "-c", "-r", "-np", "-P", "-b"},
        "ping": {"-c", "-i", "-s", "-W"},
        "ip": {"addr", "link", "route", "neigh", "s", "a"},
        "netstat": {"-t", "-u", "-l", "-n", "-p", "-a"},
        "ss": {"-t", "-u", "-l", "-n", "-p", "-a", "-s"},

        # 进程管理补充
        "ps": {"-ef", "-aux", "-eLf", "-u", "-p", "-f", "-l"},
        "kill": {"-9", "-15", "-TERM", "-KILL", "-HUP"},
        "top": {"-d", "-p", "-u", "-n"},
        "free": {"-h", "-m", "-g", "-s"},

        # 系统管理补充
        "chmod": {"-R", "-v", "-c"},
        "chown": {"-R", "-v", "-c"},
        "systemctl": {"start", "stop", "restart", "status", "enable", "disable", "reload", "is-active", "is-enabled"},
        "journalctl": {"-f", "-n", "-u", "-p", "--since", "--until", "-o short-iso"},

        # 容器/版本控制补充
        "docker": {"ps", "images", "pull", "run", "exec", "logs", "compose", "build", "rm", "stop", "start", "restart",
                   "inspect"},
        "git": {"status", "add", "commit", "push", "pull", "clone", "branch", "checkout", "merge", "log"},

        # 包管理补充
        "apt": {"update", "upgrade", "install", "remove", "autoremove", "search", "show"},
        "yum": {"install", "remove", "update", "list", "search", "clean all", "makecache"},
    }
    commands: Set[str] = set()
    options: Dict[str, Set[str]] = {}
    json_path = path or _default_linux_commands_path()
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        tree = data.get("treeData") or []
        for node in _walk_tree(tree):
            cmd = (node.get("command") or "").strip()
            if not cmd:
                continue
            if " " in cmd:
                continue
            if cmd in {"文件管理", "网络管理", "系统管理", "磁盘管理", "进程管理", "文本处理", "用户管理", "权限管理"}:
                continue
            commands.add(cmd)
            opt_text = node.get("option") or ""
            opt_set = _extract_options(opt_text)
            if opt_set:
                options.setdefault(cmd, set()).update(opt_set)
    except Exception:
        pass

    commands.update(builtin_commands)
    for k, v in builtin_options.items():
        options.setdefault(k, set()).update(v)
    return {"commands": sorted(commands), "options": {k: sorted(v) for k, v in options.items()}}


@dataclass
class RemoteContext:
    client: object
    cwd: str = "/"


class SSHPromptCompleter(Completer):
    def __init__(self, ctx: RemoteContext, index: Dict[str, object]):
        self.ctx = ctx
        self._commands: List[str] = list(index.get("commands") or [])
        raw_opts = index.get("options") or {}
        self._options: Dict[str, List[str]] = {k: list(v) for k, v in raw_opts.items()}

    def _split(self, text: str) -> Tuple[str, str]:
        s = text.lstrip()
        if not s:
            return "", ""
        parts = s.split()
        cmd = parts[0] if parts else ""
        return cmd, s

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        cmd, s = self._split(text)
        if not s:
            for c in self._commands:
                yield Completion(c, start_position=0)
            return

        if " " not in s:
            prefix = s
            for c in self._commands:
                if c.startswith(prefix):
                    yield Completion(c, start_position=-len(prefix))
            return

        last = s.split()[-1]
        if last.startswith("-") and cmd in self._options:
            for o in self._options.get(cmd, []):
                if o.startswith(last):
                    yield Completion(o, start_position=-len(last))
            return
