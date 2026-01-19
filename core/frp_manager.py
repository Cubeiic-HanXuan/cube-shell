"""
FRP 管理器模块
负责按需下载和管理 frp 客户端/服务端二进制文件
"""
import logging
import os
import platform
import shutil
import stat
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Optional, Callable
from urllib.request import urlretrieve

logger = logging.getLogger(__name__)

# FRP 版本和下载地址配置
FRP_VERSION = "0.61.1"
FRP_GITHUB_BASE = f"https://github.com/fatedier/frp/releases/download/v{FRP_VERSION}"

# 各平台下载地址映射
FRP_DOWNLOADS = {
    # (系统, 架构): (客户端文件名, 服务端文件名, 下载包名)
    ("Darwin", "x86_64"): f"frp_{FRP_VERSION}_darwin_amd64.tar.gz",
    ("Darwin", "arm64"): f"frp_{FRP_VERSION}_darwin_arm64.tar.gz",
    ("Linux", "x86_64"): f"frp_{FRP_VERSION}_linux_amd64.tar.gz",
    ("Linux", "aarch64"): f"frp_{FRP_VERSION}_linux_arm64.tar.gz",
    ("Linux", "armv7l"): f"frp_{FRP_VERSION}_linux_arm.tar.gz",
    ("Windows", "AMD64"): f"frp_{FRP_VERSION}_windows_amd64.zip",
    ("Windows", "x86"): f"frp_{FRP_VERSION}_windows_386.zip",
}

# 服务器架构映射（通过 arch 命令获取）
SERVER_ARCH_MAP = {
    "x86_64": f"frp_{FRP_VERSION}_linux_amd64.tar.gz",
    "amd64": f"frp_{FRP_VERSION}_linux_amd64.tar.gz",
    "aarch64": f"frp_{FRP_VERSION}_linux_arm64.tar.gz",
    "arm64": f"frp_{FRP_VERSION}_linux_arm64.tar.gz",
    "armv7l": f"frp_{FRP_VERSION}_linux_arm.tar.gz",
}


def get_frp_dir() -> Path:
    """获取 frp 存储目录（用户数据目录下）"""
    if platform.system() == "Darwin":
        frp_dir = Path.home() / "Library" / "Application Support" / "cube-shell" / "frp"
    elif platform.system() == "Windows":
        frp_dir = Path(os.environ.get("APPDATA", "")) / "cube-shell" / "frp"
    else:
        frp_dir = Path.home() / ".cube-shell" / "frp"

    frp_dir.mkdir(parents=True, exist_ok=True)
    return frp_dir


def get_local_frpc_path() -> Path:
    """获取本地 frpc 客户端路径"""
    frp_dir = get_frp_dir()
    if platform.system() == "Windows":
        return frp_dir / "frpc.exe"
    return frp_dir / "frpc"


def get_local_frps_path() -> Path:
    """获取本地 frps 服务端路径（用于上传到服务器）"""
    frp_dir = get_frp_dir()
    return frp_dir / "frps"


def is_frpc_installed() -> bool:
    """检查本地 frpc 是否已安装"""
    frpc_path = get_local_frpc_path()
    return frpc_path.exists() and os.access(frpc_path, os.X_OK)


def get_platform_key() -> Optional[tuple]:
    """获取当前平台的下载key"""
    system = platform.system()
    machine = platform.machine()

    # 标准化架构名称
    if system == "Darwin":
        if machine == "arm64":
            return ("Darwin", "arm64")
        return ("Darwin", "x86_64")
    elif system == "Linux":
        if machine in ("x86_64", "AMD64"):
            return ("Linux", "x86_64")
        elif machine in ("aarch64", "arm64"):
            return ("Linux", "aarch64")
        elif machine.startswith("arm"):
            return ("Linux", "armv7l")
    elif system == "Windows":
        if machine == "AMD64":
            return ("Windows", "AMD64")
        return ("Windows", "x86")

    return None


def download_with_progress(url: str, dest_path: str,
                           progress_callback: Optional[Callable[[int, int], None]] = None) -> bool:
    """
    下载文件并显示进度
    
    Args:
        url: 下载地址
        dest_path: 目标路径
        progress_callback: 进度回调函数 (downloaded_bytes, total_bytes)
    
    Returns:
        是否下载成功
    """

    def report_hook(block_num, block_size, total_size):
        if progress_callback and total_size > 0:
            downloaded = block_num * block_size
            progress_callback(downloaded, total_size)

    try:
        urlretrieve(url, dest_path, reporthook=report_hook if progress_callback else None)
        return True
    except Exception as e:
        logger.error(f"下载失败: {e}")
        return False


def extract_archive(archive_path: str, extract_dir: str) -> bool:
    """解压归档文件"""
    try:
        if archive_path.endswith(".tar.gz") or archive_path.endswith(".tgz"):
            with tarfile.open(archive_path, "r:gz") as tar:
                tar.extractall(extract_dir)
        elif archive_path.endswith(".zip"):
            with zipfile.ZipFile(archive_path, "r") as zip_ref:
                zip_ref.extractall(extract_dir)
        else:
            logger.error(f"不支持的归档格式: {archive_path}")
            return False
        return True
    except Exception as e:
        logger.error(f"解压失败: {e}")
        return False


def download_frpc(progress_callback: Optional[Callable[[int, int], None]] = None,
                  status_callback: Optional[Callable[[str], None]] = None) -> bool:
    """
    下载并安装 frpc 客户端
    
    Args:
        progress_callback: 下载进度回调 (downloaded, total)
        status_callback: 状态消息回调
    
    Returns:
        是否安装成功
    """
    platform_key = get_platform_key()
    if platform_key is None:
        logger.error("不支持的平台")
        if status_callback:
            status_callback("不支持的平台")
        return False

    package_name = FRP_DOWNLOADS.get(platform_key)
    if not package_name:
        logger.error(f"未找到对应平台的下载包: {platform_key}")
        return False

    download_url = f"{FRP_GITHUB_BASE}/{package_name}"
    frp_dir = get_frp_dir()

    if status_callback:
        status_callback(f"正在下载 frpc (v{FRP_VERSION})...")

    # 创建临时目录进行下载和解压
    with tempfile.TemporaryDirectory() as tmp_dir:
        archive_path = os.path.join(tmp_dir, package_name)

        # 下载
        if not download_with_progress(download_url, archive_path, progress_callback):
            return False

        if status_callback:
            status_callback("正在解压...")

        # 解压
        if not extract_archive(archive_path, tmp_dir):
            return False

        # 查找解压后的 frpc 文件
        extract_folder = os.path.join(tmp_dir, package_name.replace(".tar.gz", "").replace(".zip", ""))

        if platform.system() == "Windows":
            src_frpc = os.path.join(extract_folder, "frpc.exe")
            src_frps = os.path.join(extract_folder, "frps.exe")
        else:
            src_frpc = os.path.join(extract_folder, "frpc")
            src_frps = os.path.join(extract_folder, "frps")

        # 复制到目标目录
        if os.path.exists(src_frpc):
            dest_frpc = get_local_frpc_path()
            shutil.copy2(src_frpc, dest_frpc)
            # 设置可执行权限
            if platform.system() != "Windows":
                os.chmod(dest_frpc, os.stat(dest_frpc).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            logger.info(f"frpc 已安装到: {dest_frpc}")
        else:
            logger.error(f"未找到 frpc 文件: {src_frpc}")
            return False

        # 同时保存 frps（用于上传到服务器）
        if os.path.exists(src_frps):
            dest_frps = get_local_frps_path()
            shutil.copy2(src_frps, dest_frps)
            if platform.system() != "Windows":
                os.chmod(dest_frps, os.stat(dest_frps).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            logger.info(f"frps 已保存到: {dest_frps}")

    if status_callback:
        status_callback("安装完成")

    return True


def get_remote_home_dir(ssh_conn) -> str:
    """获取远程服务器的用户 home 目录"""
    try:
        result = ssh_conn.exec(cmd="echo $HOME", pty=False)
        return result.strip() if result else ""
    except Exception as e:
        logger.error(f"获取远程 home 目录失败: {e}")
        return ""


def download_frps_for_server(ssh_conn, sftp, server_arch: str,
                             progress_callback: Optional[Callable[[int, int], None]] = None,
                             status_callback: Optional[Callable[[str], None]] = None) -> bool:
    """
    下载并部署 frps 到远程服务器
    
    Args:
        ssh_conn: SSH 连接对象
        sftp: SFTP 连接对象
        server_arch: 服务器架构 (通过 arch 命令获取)
        progress_callback: 下载进度回调
        status_callback: 状态消息回调
    
    Returns:
        是否部署成功
    """
    # 获取用户 home 目录
    home_dir = get_remote_home_dir(ssh_conn)
    if not home_dir:
        logger.error("无法获取远程用户 home 目录")
        if status_callback:
            status_callback("无法获取远程用户 home 目录")
        return False
    
    remote_frp_dir = f"{home_dir}/frp"
    
    # 获取对应架构的下载包
    package_name = SERVER_ARCH_MAP.get(server_arch.strip())
    if not package_name:
        logger.error(f"不支持的服务器架构: {server_arch}")
        if status_callback:
            status_callback(f"不支持的服务器架构: {server_arch}")
        return False

    download_url = f"{FRP_GITHUB_BASE}/{package_name}"

    if status_callback:
        status_callback(f"正在下载 frps (v{FRP_VERSION}) for {server_arch}...")

    with tempfile.TemporaryDirectory() as tmp_dir:
        archive_path = os.path.join(tmp_dir, package_name)

        # 下载
        if not download_with_progress(download_url, archive_path, progress_callback):
            return False

        if status_callback:
            status_callback("正在上传到服务器...")

        # 先创建目录
        try:
            ssh_conn.exec(cmd=f"mkdir -p {home_dir}", pty=False)
        except:
            pass

        # 上传到服务器的用户目录
        remote_archive = f"{home_dir}/{package_name}"
        try:
            sftp.put(archive_path, remote_archive)
        except Exception as e:
            logger.error(f"上传失败: {e}")
            return False

        if status_callback:
            status_callback("正在服务器上解压...")

        # 在服务器上解压到用户目录
        extract_folder = package_name.replace(".tar.gz", "").replace(".zip", "")
        cmd = f"cd {home_dir} && tar -xzf {package_name} && rm -rf frp && mv {extract_folder} frp && rm -f {package_name}"
        try:
            ssh_conn.exec(cmd=cmd, pty=False)
        except Exception as e:
            logger.error(f"服务器解压失败: {e}")
            return False

    if status_callback:
        status_callback("frps 部署完成")

    return True


def get_server_arch(ssh_conn) -> Optional[str]:
    """获取服务器架构"""
    try:
        result = ssh_conn.exec(cmd="arch", pty=False)
        return result.strip() if result else None
    except Exception as e:
        logger.error(f"获取服务器架构失败: {e}")
        return None


class FRPInstallError(Exception):
    """FRP 安装错误"""
    pass


class FRPManager:
    """
    FRP 管理器类
    封装了 frp 客户端和服务端的下载、安装、启动等功能
    """

    def __init__(self):
        self.frp_dir = get_frp_dir()
        self._download_in_progress = False

    @property
    def frpc_path(self) -> Path:
        return get_local_frpc_path()

    @property
    def frps_path(self) -> Path:
        return get_local_frps_path()

    def is_frpc_ready(self) -> bool:
        """检查 frpc 是否就绪"""
        return is_frpc_installed()

    def ensure_frpc(self, progress_callback=None, status_callback=None) -> bool:
        """
        确保 frpc 已安装，如未安装则自动下载
        
        Returns:
            是否就绪
        """
        if self.is_frpc_ready():
            return True

        if self._download_in_progress:
            return False

        self._download_in_progress = True
        try:
            return download_frpc(progress_callback, status_callback)
        finally:
            self._download_in_progress = False

    def ensure_frps_on_server(self, ssh_conn, sftp,
                              progress_callback=None,
                              status_callback=None) -> bool:
        """
        确保服务器上的 frps 已安装
        
        Args:
            ssh_conn: SSH 连接
            sftp: SFTP 连接
        
        Returns:
            是否就绪
        """
        # 检查服务器上是否已存在 frps（使用 $HOME/frp）
        try:
            result = ssh_conn.exec(cmd="test -f $HOME/frp/frps && echo 'exists'", pty=False)
            if result and "exists" in result:
                return True
        except:
            pass

        # 获取服务器架构
        server_arch = get_server_arch(ssh_conn)
        if not server_arch:
            raise FRPInstallError("无法获取服务器架构")

        # 下载并部署
        return download_frps_for_server(ssh_conn, sftp, server_arch,
                                        progress_callback, status_callback)


# 全局单例
_frp_manager: Optional[FRPManager] = None


def get_frp_manager() -> FRPManager:
    """获取 FRP 管理器单例"""
    global _frp_manager
    if _frp_manager is None:
        _frp_manager = FRPManager()
    return _frp_manager
