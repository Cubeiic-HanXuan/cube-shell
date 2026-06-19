"""
按平台/架构匹配 release asset,并确定下载落盘目录。

复用 ``core.frp_manager.get_platform_key()`` 得到标准化的 ``(system, arch)``
元组,再按打包产物命名约定(Windows=.exe / macOS=.dmg / Linux=.tar.gz)评分
匹配。

匹配策略:扩展名 + 平台关键词 + 架构关键词评分,选**唯一最高分**;零匹配或
同分歧义返回 ``None``,由上层走兜底(打开 Release 页手动下载),绝不自动装错
架构。
"""
import os
from typing import List, Optional

import appdirs

from core.frp_manager import get_platform_key

from .github_api import AssetInfo

# (system, arch) -> (平台关键词列表, 扩展名候选元组(按优先级), 架构关键词列表)
# 扩展名按优先级排列:首选格式排前面,评分时给首选加分。
# 统一约定:macOS 与 Windows 都下载 .zip,Linux 下载 .tar.xz。
# 实际产物命名(见 GitHub V2.7.0 release):
#   Windows = cube-shell-windows-X86_64.zip / cube-shell-windows-arm64.zip(也可能是未来的 Inno .exe)
#   macOS   = cube-shell-macOS-arm64.zip / .dmg
#   Linux   = cube-shell-linux-x86_64.tar.xz / cube-shell-linux-arm64.tar.xz
_PLATFORM_RULES = {
    ("Windows", "AMD64"): (["windows", "win", "win64"], (".zip", ".exe"), ["x86_64", "x64", "amd64"]),
    ("Windows", "x86"):    (["windows", "win", "win32"], (".zip", ".exe"), ["x86", "386", "32"]),
    ("Darwin", "arm64"):   (["macos", "mac", "darwin"], (".zip", ".dmg"), ["arm64", "aarch64", "apple"]),
    ("Darwin", "x86_64"):  (["macos", "mac", "darwin"], (".zip", ".dmg"), ["x86_64", "x64", "amd64", "intel"]),
    ("Linux", "x86_64"):   (["linux"], (".tar.xz", ".tar.gz"), ["x86_64", "x64", "amd64"]),
    ("Linux", "aarch64"):  (["linux"], (".tar.xz", ".tar.gz"), ["aarch64", "arm64"]),
    ("Linux", "armv7l"):   (["linux"], (".tar.xz", ".tar.gz"), ["armv7", "arm", "armhf"]),
}

# 所有可能出现的架构标识,用于判断 asset 名是否带了架构后缀
_ALL_ARCH_TOKENS = [
    "arm64", "aarch64", "x86_64", "x64", "amd64", "386", "x86",
    "armv7", "armhf", "intel", "apple", "win32", "win64",
]


def select_asset(assets: List[AssetInfo], platform_key: Optional[tuple]) -> Optional[AssetInfo]:
    """从 release assets 选出当前平台的安装包。

    :return: 唯一最佳匹配;未匹配到或同分歧义返回 ``None``(走兜底)
    """
    if not platform_key or platform_key not in _PLATFORM_RULES:
        return None
    plat_kw, exts, arch_kw = _PLATFORM_RULES[platform_key]
    primary_ext = exts[0]  # 首选扩展名,评分时加分

    scored = []
    for a in assets:
        n = (a.name or "").lower()
        # 扩展名命中任一候选即可
        matched_ext = next((e for e in exts if n.endswith(e)), None)
        if not matched_ext:
            continue
        if not any(k in n for k in plat_kw):
            continue
        # 若 asset 名带架构标识,则必须命中当前架构关键词,否则跳过(别的架构)
        has_arch_token = any(k in n for k in _ALL_ARCH_TOKENS)
        if has_arch_token and not any(k in n for k in arch_kw):
            continue
        # 评分:平台命中 +1,架构命中 +2,优先同名(cube-shell) +1,首选格式 +2
        # (macOS 同架构有 .dmg 与 .zip,首选 .dmg;Windows 未来 .exe 优于 .zip)
        score = (1
                 + (2 if any(k in n for k in arch_kw) else 0)
                 + (1 if "cube-shell" in n else 0)
                 + (2 if matched_ext == primary_ext else 0))
        scored.append((score, a))

    if not scored:
        return None
    scored.sort(key=lambda t: t[0], reverse=True)
    top = scored[0][0]
    # 同分歧义(多于一个最高分)→ 不确定,返回 None 走兜底,避免装错架构
    if sum(1 for s, _ in scored if s == top) > 1:
        return None
    return scored[0][1]


def get_download_dir() -> str:
    """下载落盘目录。

    用 appdirs 用户数据目录(跨平台、可写、非临时),便于断点续传与兜底
    "打开已下载安装包手动安装"——临时目录会随进程退出被删除,不合适。
    """
    base = appdirs.user_data_dir("cube-shell", appauthor=False)
    d = os.path.join(base, "updates")
    os.makedirs(d, exist_ok=True)
    return d


def build_download_path(asset: AssetInfo) -> str:
    """组装 asset 的本地落盘完整路径。"""
    return os.path.join(get_download_dir(), asset.name)
