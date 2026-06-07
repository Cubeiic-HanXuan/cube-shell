"""
URL Scheme 自动注册模块

首次启动时自动注册 jms:// 和 cubeshell:// URL Scheme，让浏览器点击链接能唤起 CubeShell。
- macOS: 由 Info.plist 处理，此模块不做额外操作
- Windows: 写入 HKCU\\Software\\Classes\\jms 和 HKCU\\Software\\Classes\\cubeshell 注册表
- Linux: 创建 .desktop 文件 + xdg-mime 注册
"""

import os
import sys
import platform
import subprocess


def _get_exe_path() -> str:
    """获取当前可执行文件的路径"""
    # Nuitka 编译环境：sys.executable 就是 exe 本身
    if getattr(sys, 'frozen', False) or '__compiled__' in dir():
        return os.path.abspath(sys.executable)
    # Python 源码运行：sys.executable 是 python 解释器，用 sys.argv[0]
    return os.path.abspath(sys.argv[0])


def _is_registered_windows() -> bool:
    """检查 Windows 下 jms:// 和 cubeshell:// URL Scheme 是否已正确注册"""
    try:
        import winreg
        exe_path = _get_exe_path()
        for scheme in ("jms", "cubeshell"):
            key_path = rf"Software\Classes\{scheme}\shell\open\command"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                value, _ = winreg.QueryValueEx(key, "")
                # 注册表中的命令格式为 "exe_path" "%1"
                if exe_path.lower() not in value.lower():
                    return False
        return True
    except (FileNotFoundError, OSError, ImportError):
        return False


def _is_registered_linux() -> bool:
    """检查 Linux 下 jms:// 和 cubeshell:// URL Scheme 是否已正确注册"""
    desktop_path = os.path.expanduser(
        "~/.local/share/applications/cube-shell-url-handler.desktop"
    )
    if not os.path.exists(desktop_path):
        return False
    try:
        with open(desktop_path, "r", encoding="utf-8") as f:
            content = f.read()
        exe_path = _get_exe_path()
        # 同时检查 exe 路径和 cubeshell scheme 是否已注册
        return exe_path in content and "x-scheme-handler/cubeshell" in content
    except (IOError, OSError):
        return False


def is_registered() -> bool:
    """
    检测当前平台 URL Scheme 是否已注册。

    Returns:
        True 表示已注册或无需注册（macOS），False 表示未注册
    """
    system = platform.system()
    if system == "Darwin":
        return True
    elif system == "Windows":
        return _is_registered_windows()
    elif system == "Linux":
        return _is_registered_linux()
    return False


def _register_windows_scheme(exe_path: str, scheme: str, description: str) -> bool:
    """Windows 平台注册单个 URL Scheme 到当前用户注册表"""
    try:
        import winreg

        base_path = rf"Software\Classes\{scheme}"

        # 创建协议根键
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base_path) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f"URL:{description}")
            winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")

        # 创建 DefaultIcon
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, f"{base_path}\\DefaultIcon") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'"{exe_path}",0')

        # 创建 shell\open\command
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, f"{base_path}\\shell\\open\\command") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'"{exe_path}" "%1"')

        return True
    except (ImportError, OSError, Exception):
        return False


def _register_windows(exe_path: str) -> bool:
    """Windows 平台注册 jms:// 和 cubeshell:// URL Scheme 到当前用户注册表"""
    success_jms = _register_windows_scheme(exe_path, "jms", "CubeShell JMS Protocol")
    success_cubeshell = _register_windows_scheme(exe_path, "cubeshell", "CubeShell Local Terminal")
    return success_jms and success_cubeshell


def _register_linux(exe_path: str) -> bool:
    """Linux 平台注册 jms:// 和 cubeshell:// URL Scheme 通过 .desktop 文件"""
    try:
        applications_dir = os.path.expanduser("~/.local/share/applications")
        os.makedirs(applications_dir, exist_ok=True)

        desktop_path = os.path.join(applications_dir, "cube-shell-url-handler.desktop")

        desktop_content = f"""[Desktop Entry]
Name=CubeShell URL Handler
Comment=Handle jms:// and cubeshell:// URLs for CubeShell
Exec={exe_path} %u
Terminal=false
Type=Application
NoDisplay=true
MimeType=x-scheme-handler/jms;x-scheme-handler/cubeshell;
Categories=Network;
"""

        with open(desktop_path, "w", encoding="utf-8") as f:
            f.write(desktop_content)

        # 注册为 jms:// 协议的默认处理程序
        subprocess.run(
            ["xdg-mime", "default", "cube-shell-url-handler.desktop", "x-scheme-handler/jms"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # 注册为 cubeshell:// 协议的默认处理程序
        subprocess.run(
            ["xdg-mime", "default", "cube-shell-url-handler.desktop", "x-scheme-handler/cubeshell"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # 更新桌面数据库
        subprocess.run(
            ["update-desktop-database", applications_dir],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        return True
    except (IOError, OSError, Exception):
        return False


def register(exe_path: str = None) -> bool:
    """
    注册 jms:// 和 cubeshell:// URL Scheme。

    Args:
        exe_path: 可执行文件路径，为 None 时自动获取

    Returns:
        True 注册成功，False 注册失败或无需注册
    """
    if exe_path is None:
        exe_path = _get_exe_path()

    system = platform.system()
    if system == "Darwin":
        return True
    elif system == "Windows":
        return _register_windows(exe_path)
    elif system == "Linux":
        return _register_linux(exe_path)
    return False


def ensure_registered() -> None:
    """
    主入口函数，应用启动时调用。

    检查 jms:// 和 cubeshell:// URL Scheme 是否已注册，未注册则自动注册。
    整个过程静默执行，绝不影响应用正常启动。
    """
    try:
        if is_registered():
            return
        success = register()
        if success:
            print("[CubeShell] URL Schemes (jms://, cubeshell://) registered successfully.")
        else:
            print("[CubeShell] Warning: Failed to register URL Schemes.")
    except Exception as e:
        print(f"[CubeShell] Warning: URL Scheme registration skipped: {e}")
