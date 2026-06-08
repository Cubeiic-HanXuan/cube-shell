"""
Windows 文件夹右键菜单集成模块

通过注册表在 Windows 资源管理器文件夹右键菜单添加
"在 CubeShell 中打开终端" 选项。
"""
import os
import sys
import platform
import logging

logger = logging.getLogger(__name__)


def is_supported():
    """是否为支持的平台（仅 Windows）"""
    return platform.system() == 'Windows'


def is_installed():
    """检查右键菜单项是否已注册"""
    try:
        import winreg
    except ImportError:
        return False

    try:
        winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Classes\Directory\shell\OpenInCubeShell"
        )
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def _is_frozen():
    """
    判断是否为 Nuitka 编译的打包环境。
    使用多种检测方式，按可靠性排序。
    """
    # 方法1: sys.argv[0] 以 .exe 结尾（Nuitka 中 argv[0] 就是 exe 本身）
    if sys.argv and sys.argv[0].lower().endswith('.exe'):
        return True
    # 方法2: 通过 __file__ 定位 dist 根目录，检查 cube-shell.exe 是否存在
    module_dir = os.path.dirname(os.path.abspath(__file__))
    dist_root = os.path.dirname(module_dir)  # 从 core/ 上一级
    if os.path.isfile(os.path.join(dist_root, 'cube-shell.exe')):
        return True
    # 方法3: sys.executable 本身不是 python 解释器
    exe_basename = os.path.basename(sys.executable).lower()
    if not exe_basename.startswith('python'):
        return True
    return False


def _get_exe_path():
    """
    获取 cube-shell.exe 的实际路径。
    使用多种方法定位，按可靠性排序。
    """
    # 方法1: sys.argv[0] 就是 exe（Nuitka 编译后 argv[0] = exe 完整路径）
    if sys.argv and sys.argv[0].lower().endswith('.exe'):
        return os.path.abspath(sys.argv[0])
    # 方法2: 通过 __file__ 定位（本模块在 core/ 下，exe 在上一级）
    module_dir = os.path.dirname(os.path.abspath(__file__))
    dist_root = os.path.dirname(module_dir)
    exe_path = os.path.join(dist_root, 'cube-shell.exe')
    if os.path.isfile(exe_path):
        return exe_path
    # 方法3: sys.executable 不是 python 解释器时，它就是 exe
    exe_basename = os.path.basename(sys.executable).lower()
    if not exe_basename.startswith('python'):
        return os.path.abspath(sys.executable)
    # 开发环境 fallback
    return os.path.abspath(sys.argv[0]) if sys.argv else os.path.abspath(sys.executable)


def _get_command_template(path_var):
    """
    获取注册表 command 值。

    Args:
        path_var: 路径变量，%1 或 %V

    Returns:
        str: 完整的命令字符串
    """
    if _is_frozen():
        # Nuitka 编译环境：exe 直接接收路径参数
        exe_path = _get_exe_path()
        return f'"{exe_path}" "{path_var}"'
    else:
        # 开发环境：使用 pythonw.exe 避免弹出控制台黑窗口
        python_path = sys.executable
        if python_path.endswith('python.exe'):
            pythonw_path = python_path[:-len('python.exe')] + 'pythonw.exe'
            if os.path.exists(pythonw_path):
                python_path = pythonw_path
        script_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', 'cube-shell.py')
        )
        return f'"{python_path}" "{script_path}" "{path_var}"'


def _get_icon_path():
    """
    获取菜单项图标路径。

    Returns:
        str: 图标路径字符串
    """
    if _is_frozen():
        exe_path = _get_exe_path()
        return f'"{exe_path}",0'
    else:
        icon_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', 'icons', 'logo.ico')
        )
        return f'"{icon_path}"'


def install():
    """
    安装 Windows 右键菜单项。

    注册表结构：
    HKCU\\Software\\Classes\\Directory\\shell\\OpenInCubeShell
        (Default) = "在 CubeShell 中打开终端"
        Icon = "exe_path,0"
        command\\(Default) = "exe_path" "%1"

    同时注册 Background（在文件夹空白处右键）：
    HKCU\\Software\\Classes\\Directory\\Background\\shell\\OpenInCubeShell
        (Default) = "在 CubeShell 中打开终端"
        Icon = "exe_path,0"
        command\\(Default) = "exe_path" "%V"

    Returns:
        tuple: (success: bool, error_message: str or None)
    """
    try:
        import winreg
    except ImportError:
        return False, "winreg 模块不可用（仅 Windows 支持）"

    display_name = "在 CubeShell 中打开终端"

    try:
        command_1 = _get_command_template("%1")
        command_v = _get_command_template("%V")
        icon_value = _get_icon_path()

        # 注册 Directory\shell（右键点击文件夹时）
        _create_context_menu_entry(
            winreg,
            r"Software\Classes\Directory\shell\OpenInCubeShell",
            display_name, icon_value, command_1
        )

        # 注册 Directory\Background\shell（在文件夹空白处右键时）
        _create_context_menu_entry(
            winreg,
            r"Software\Classes\Directory\Background\shell\OpenInCubeShell",
            display_name, icon_value, command_v
        )

        logger.info("Windows 右键菜单注册成功, command=%s", command_1)
        return True, f"注册命令: {command_1}"
    except Exception as e:
        logger.error("安装 Windows 右键菜单失败: %s", e)
        return False, str(e)


def _create_context_menu_entry(winreg, base_path, display_name, icon_value, command):
    """创建单个注册表菜单项"""
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base_path) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, display_name)
        winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, icon_value)

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, f"{base_path}\\command") as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, command)


def uninstall():
    """
    卸载 Windows 右键菜单项。

    Returns:
        tuple: (success: bool, error_message: str or None)
    """
    try:
        import winreg
    except ImportError:
        return False, "winreg 模块不可用（仅 Windows 支持）"

    try:
        # 删除 Directory\shell 条目
        _delete_registry_tree(winreg, r"Software\Classes\Directory\shell\OpenInCubeShell")
        # 删除 Directory\Background\shell 条目
        _delete_registry_tree(winreg, r"Software\Classes\Directory\Background\shell\OpenInCubeShell")
        logger.info("Windows 右键菜单已卸载")
        return True, None
    except Exception as e:
        logger.error("卸载 Windows 右键菜单失败: %s", e)
        return False, str(e)


def _delete_registry_tree(winreg, path):
    """递归删除注册表键"""
    try:
        # 先删除子键 command
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, f"{path}\\command")
        except FileNotFoundError:
            pass
        except OSError:
            pass
        # 再删除主键
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
    except FileNotFoundError:
        pass  # 本来就不存在，视为成功
    except OSError:
        pass
