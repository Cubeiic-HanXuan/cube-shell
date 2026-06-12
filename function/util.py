import json
import os
import shutil
import socket
import logging

import yaml
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QFileIconProvider, QMessageBox

# 小于展示字节，大于或等于展示KB
MAX_BYTES_SIZE = 1024
# 小于展示KB，大于或等于展示MB
MAX_KB_SIZE = 1024 * 1024
# 小于展示MB，大于或等于展示GB
MAX_MB_SIZE = 1024 * 1024 * 1024

BANNER = """
               _                         _            _  _ 
              | |                       | |          | || |
   ___  _   _ | |__    ___  ______  ___ | |__    ___ | || |
  / __|| | | || '_ \  / _ \|______|/ __|| '_ \  / _ \| || |
 | (__ | |_| || |_) ||  __/        \__ \| | | ||  __/| || |
  \___| \__,_||_.__/  \___|        |___/|_| |_| \___||_||_|\n 
欢迎使用 cube-shell SSH 服务器远程管理工具 如有疑问请在项目主页联系作者\n                                            
"""

# 主题
THEME = None

# 应用名
APP_NAME = "cube-shell"

# 日志记录
logger = logging.getLogger(__name__)


# 文件夹图标缓存：QFileIconProvider 创建开销大，全局只创建一次
_FOLDER_ICON_CACHE = None


def get_default_folder_icon():
    """
    # 获取系统默认文件夹图标（带全局缓存）
    :return:
    """
    global _FOLDER_ICON_CACHE
    if _FOLDER_ICON_CACHE is None:
        icon_provider = QFileIconProvider()
        _FOLDER_ICON_CACHE = icon_provider.icon(QFileIconProvider.IconType.Folder)
    return _FOLDER_ICON_CACHE


# 扩展名 → 图标资源路径映射（模块级，仅创建一次）
_EXT_ICON_MAP = {
    ".sh": ':icons8-ssh-48.png',
    ".sql": ':icons8-sql-48.png',
    ".py": ':icons8-python-48.png',
    ".java": ':icons8-java-48.png',
    ".go": ':icons8-golang-48.png',
    ".c": ':icons8-c-48.png',
    ".cpp": ':icons8-c-48.png',
    ".js": ':icons8-js-48.png',
    ".vue": ':icons8-vuejs-48.png',
    ".html": ':icons8-html-48.png',
    ".css": ':icons8-css-48.png',
    ".exe": ':icons8-windows-48.png',
    ".dmg": ':icons8-dmg-48.png',
    ".bat": ':icons8-bat-48.png',
    ".vbs": ':icons8-bat-48.png',
    ".ini": ':icons8-ini-48.png',
    ".tsx": ':icons8-react-48.png',
    ".ts": ':icons8-ts-48.png',
    ".editorconfig": ':icons8-editorconfig-48.png',
    ".jar": ':icons8-jar-48.png',  # 原逻辑中 .jar elif 先于元组匹配，使用专用 jar 图标
    ".so": ':icons8-linux-48.png',
    ".tar": ':icons8-zip-48.png',
    ".gz": ':icons8-zip-48.png',
    ".zip": ':icons8-zip-48.png',
    ".cfg": ':icons8-settings-40.png',
    ".gitconfig": ':icons8-settings-40.png',
    ".conf": ':icons8-settings-40.png',
    ".png": ':icons8-png-48.png',
    ".gif": ':icons8-gif-48.png',
    ".jpg": ':icons8-jpg-48.png',
    ".jpeg": ':icons8-jpg-48.png',
    ".license": ':icons8-license-48.png',
    ".json": ':icons8-json-48.png',
    ".txt": ':icons8-txt-48.png',
    ".gitignore": ':icons8-gitignore-48.png',
    ".md": ':icons8-md-48.png',
    ".yaml": ':icons8-yaml-48.png',
    ".yml": ':icons8-yaml-48.png',
    ".properties": ':icons8-properties-48.png',
    ".log": ':icons-log-48.png',
    ".toml": ':icons-toml-48.png',
    ".xml": ':xml-48.png',
}

# 文件名前缀（如 .env、.eslintrc）→ 图标路径：保留原 startswith 语义
_PREFIX_ICON_MAP = (
    (".eslintrc", ':icons8-eslintrc-48.png'),  # 必须在 .env 之前匹配（避免 .eslintrc.js 走到 .env）
    (".env", ':icons8-env-48.png'),
)

# QIcon 对象缓存：避免每次 QIcon(path) 重复加载
_FILE_ICON_CACHE = {}
_DEFAULT_FILE_ICON = None


# 获取系统默认文件图标（带缓存与字典查询，避免 40+ elif 与重复对象创建）
def get_default_file_icon(qt_str):
    global _DEFAULT_FILE_ICON

    # 1) 先按文件名前缀匹配（保留原 startswith 语义，如 .env / .eslintrc）
    for prefix, icon_path in _PREFIX_ICON_MAP:
        if qt_str.startswith(prefix):
            cached = _FILE_ICON_CACHE.get(prefix)
            if cached is None:
                cached = QIcon(icon_path)
                _FILE_ICON_CACHE[prefix] = cached
            return cached

    # 2) 按扩展名查表
    dot_idx = qt_str.rfind('.')
    ext = qt_str[dot_idx:].lower() if dot_idx != -1 else ""

    if ext in _FILE_ICON_CACHE:
        return _FILE_ICON_CACHE[ext]

    icon_path = _EXT_ICON_MAP.get(ext)
    if icon_path:
        icon = QIcon(icon_path)
        _FILE_ICON_CACHE[ext] = icon
        return icon

    # 3) 兜底：系统默认文件图标（缓存）
    if _DEFAULT_FILE_ICON is None:
        icon_provider = QFileIconProvider()
        _DEFAULT_FILE_ICON = icon_provider.icon(QFileIconProvider.IconType.File)
    return _DEFAULT_FILE_ICON


def format_file_size(size_in_bytes):
    """
    根据文件大小返回适当的单位展示文件大小。
    :param size_in_bytes: 文件大小（以字节为单位）
    :return: 格式化的文件大小字符串
    """
    if size_in_bytes < MAX_BYTES_SIZE:
        return f"{size_in_bytes} 字节"
    elif size_in_bytes < MAX_KB_SIZE:
        size_in_kb = size_in_bytes / 1024
        return f"{size_in_kb:.2f} KB"
    elif size_in_bytes < MAX_MB_SIZE:
        size_in_mb = size_in_bytes / (1024 * 1024)
        return f"{size_in_mb:.2f} MB"
    else:
        size_in_gb = size_in_bytes / (1024 * 1024 * 1024)
        return f"{size_in_gb:.3f} GB"


def has_valid_suffix(filename):
    """
    检测是否包含以下类型文件
    :param filename:文件名
    :return: 包含返回true
    """
    return filename.endswith(('.db', '.exe', '.bin', '.jar', '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt',
                              '.pptx', '.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.iso', '.img', '.dmg', '.apk',
                              '.ipa', '.deb', '.rpm', '.msi', '.jar', '.war', '.ear', '.dmp', '.phd', '.trc',
                              '.Xauthority'))


def check_remote_directory_exists(sftp, directory):
    """
    判断文件夹是否存在
    :param sftp:
    :param directory:
    :return:
    """
    try:
        sftp.stat(directory)
        return True
    except FileNotFoundError:
        return False


def check_remote_frp_exists(ssh_conn):
    """
    检查远程服务器上的 frps 是否存在（使用 $HOME/frp）
    :param ssh_conn: SSH 连接对象
    :return: 是否存在
    """
    try:
        result = ssh_conn.exec(cmd="test -f $HOME/frp/frps && echo 'exists'", pty=False)
        return result and "exists" in result
    except:
        return False


def read_json_file(file_path):
    """
    读取json文件
    :param file_path: 文件地址
    :return:返回json对象
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            data = json.load(file)
            return data
    except FileNotFoundError:
        print(f"Error: The file '{file_path}' was not found.")
    except json.JSONDecodeError:
        print(f"Error: The file '{file_path}' is not a valid JSON file.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

    return None


def load_yml_config(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {
                'version': '3.8',
                'services': {},
                'volumes': {},
                'networks': {}
            }
    except Exception as e:
        print(f"An unexpected error occurred: {e}")


def get_compose_service(file_path):
    """
    从YAML文件中获取服务名称列表
    :param file_path: YAML文件路径
    :return: 服务名称列表
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            compose_data = yaml.safe_load(f) or {
                'version': '3.8',
                'services': {},
                'volumes': {},
                'networks': {}
            }

        # 获取 services 字典的所有键（服务名称）
        return compose_data.get('services', {})

    except FileNotFoundError:
        print(f"错误：文件 {file_path} 不存在")
        return []
    except yaml.YAMLError as e:
        print(f"YAML 解析错误: {str(e)}")
        return []
    except Exception as e:
        print(f"未知错误: {str(e)}")
        return []


def update_has_attribute(services_dict, containers):
    """
    根据容器 Names 字段是否包含服务键名，动态添加 has 属性

    :param services_dict: 服务配置字典（格式如问题描述）
    :param containers: 容器数据列表（必须包含 Names 字段）
    :return: 修改后的服务配置字典
    """
    # 提取所有容器的 Names 字段（过滤无效数据）
    names_list = [str(c.get('Names', '')).strip() for c in containers if c.get('Names')]

    # 遍历服务配置字典
    for service_key, config in services_dict.items():
        # 检查是否存在包含键名的 Names
        config['has'] = any(service_key in name for name in names_list)

    return services_dict


# 函数：清空QGridLayout中的所有widget
def clear_grid_layout(layout):
    while layout.count():
        layout_item = layout.takeAt(0)
        if layout_item.widget():
            layout_item.widget().deleteLater()
        elif layout_item.layout():
            clear_grid_layout(layout_item.layout())  # 递归清空子布局
            layout_item.layout().deleteLater()


# 删除文件夹
def deleteFolder(sftp, path):
    """
        递归删除远程服务器上的文件夹及其内容
        :param sftp: 远程服务器的连接对象
        :param path: 待删除的文件夹路径
        """
    try:
        # 获取文件夹中的文件和子文件夹列表
        files = sftp.listdir(path)
    except IOError:
        # The path does not exist or is not a directory
        return
    # 遍历文件和子文件夹列表
    for file in files:
        # 拼接完整的文件或文件夹路径
        filepath = f"{path}/{file}"
        try:
            # 检查路径是否存在
            sftp.stat(filepath)
        except IOError as e:
            print(f"Failed to remove: {e}")
            continue
        try:
            # 删除文件
            sftp.remove(filepath)  # Delete file
        except IOError:
            # 递归调用deleteFolder函数删除子文件夹及其内容
            deleteFolder(sftp, filepath)
    # 最后删除空文件夹
    sftp.rmdir(path)


def remove_special_lines(text):
    # 拆分文本为行
    lines = text.split('\n')
    # 用于存储过滤后的行
    filtered_lines = []

    for line in lines:
        # 去掉行首和行尾的空白字符
        stripped_line = line.strip()
        # 如果行不只包含波浪号或空格，则保留
        if stripped_line and any(char != '~' for char in stripped_line):
            filtered_lines.append(line)

    # 重新组合过滤后的行
    result = '\n'.join(filtered_lines)
    return result


def is_ipv6_address(address: str) -> bool:
    """
    判断给定的地址是否为 IPv6 地址。

    :param address: IP 地址字符串（不含端口号，可以含方括号）
    :return: 如果是 IPv6 地址返回 True，否则返回 False
    """
    # 去除可能存在的方括号
    clean_addr = address.strip('[]')
    try:
        socket.inet_pton(socket.AF_INET6, clean_addr)
        return True
    except (socket.error, OSError):
        return False


def parse_host_port(host_str: str) -> tuple:
    """
    解析 host:port 字符串，兼容 IPv4 和 IPv6 地址。

    支持的格式：
    - IPv4:       "192.168.1.1:22"        → ("192.168.1.1", 22)
    - IPv6:       "[fdb2:2c26::bc9c]:22"   → ("fdb2:2c26::bc9c", 22)
    - 主机名:     "example.com:22"         → ("example.com", 22)
    - 裸 IPv6:    "fdb2:2c26::bc9c"        → ("fdb2:2c26::bc9c", 22)（无端口，默认 22）
    - 纯主机名:   "example.com"            → ("example.com", 22)（无端口，默认 22）

    注意：裸 IPv6 + 端口（如 "fdb2::bc9c:22"）格式不可解析，
    因为无法区分 IPv6 地址尾部与端口号，IPv6 带端口必须使用方括号格式。

    :param host_str: host:port 格式字符串
    :return: (host, port) 元组，port 为 int 类型
    """
    if not host_str:
        raise ValueError("host_str 不能为空")

    # IPv6 格式：[ipv6_addr]:port
    if host_str.startswith('['):
        bracket_end = host_str.find(']')
        if bracket_end == -1:
            raise ValueError(f"无效的 IPv6 地址格式: {host_str}")
        host = host_str[1:bracket_end]
        # ]:port 部分
        rest = host_str[bracket_end + 1:]
        if rest.startswith(':'):
            port = int(rest[1:])
        else:
            port = 22  # 默认 SSH 端口
        return host, port

    # 检查是否包含冒号
    colon_count = host_str.count(':')
    if colon_count == 1:
        # IPv4 或主机名格式：host:port
        parts = host_str.rsplit(':', 1)
        return parts[0], int(parts[1])
    elif colon_count > 1:
        # 裸 IPv6 地址（没有方括号，也没有端口号）
        return host_str, 22
    else:
        # 没有冒号，只有主机名
        return host_str, 22


def format_host_port(ip: str, port) -> str:
    """
    将 IP 地址和端口格式化为 host:port 字符串，自动处理 IPv6。

    - IPv4: ("192.168.1.1", 22) → "192.168.1.1:22"
    - IPv6: ("fdb2:2c26::bc9c", 22) → "[fdb2:2c26::bc9c]:22"

    :param ip: IP 地址或主机名
    :param port: 端口号
    :return: 格式化后的 host:port 字符串
    """
    ip = ip.strip().strip('[]')  # 去除用户可能输入的方括号
    if is_ipv6_address(ip):
        return f"[{ip}]:{port}"
    else:
        return f"{ip}:{port}"


def check_server_accessibility(hostname, port):
    """
    快速检查服务器在指定端口上的可访问性。

    :param hostname: 服务器地址
    :param port: 端口号
    :return: 如果可访问返回 True，否则返回 False
    """
    try:
        # 使用 socket.create_connection 检查服务器可访问性
        # socket.create_connection 内部会自动处理 IPv6 地址
        with socket.create_connection((hostname, port), timeout=1):
            return True
    except (socket.timeout, socket.error) as e:
        print(f"Connection failed: {e}")
        return False


def read_json(file_path):
    """
    读取json文件
    :param file_path:
    :return:
    """
    with open(file_path, 'r', encoding='utf-8') as file:
        data = json.load(file)
    return data


def write_json(file_path, data):
    """
    写入json文件
    indent=4 让文件具有可读性
    """
    with open(file_path, 'w', encoding='utf-8') as file:
        json.dump(data, file, indent=4)


# 速度格式化
def format_speed(speed):
    if speed >= 1024 * 1024:
        return f"{speed / (1024 * 1024):.2f} MB/s"
    elif speed >= 1024:
        return f"{speed / 1024:.2f} KB/s"
    else:
        return f"{speed:.0f} B/s"


# 拷贝文件到指定目录
def copy_file(src_path, dest_path):
    try:
        # 复制文件
        shutil.copy2(src_path, dest_path)
        print(f"File copied from {src_path} to {dest_path}")
    except FileNotFoundError:
        print(f"Source file not found: {src_path}")
    except PermissionError:
        print(f"Permission denied while copying to {dest_path}")
    except Exception as e:
        print(f"An error occurred: {e}")


def copy_config_to_conf(source_path: str, target_dir: str) -> None:
    try:
        # 确定目标文件的完整路径
        target_path = os.path.join(target_dir, os.path.basename(source_path))

        # 如果目标文件存在，则删除它
        if os.path.exists(target_path):
            os.remove(target_path)

        # 复制文件
        shutil.copy2(source_path, target_path)
        print(f"File copied from {source_path} to {target_path}")
    except FileNotFoundError:
        print(f"Source file not found: {source_path}")
    except PermissionError:
        print(f"Permission denied while copying to {target_path}")
    except Exception as e:
        print(f"An error occurred: {e}")


# 符号权限转八进制权限
def symbolic_to_octal(symbolic):
    # 排除第一个字符，它通常是文件类型
    user, group, others = symbolic[0:3], symbolic[3:6], symbolic[6:9]

    def calc_permission(perm):
        mapping = {'r': 4, 'w': 2, 'x': 1, '-': 0}
        return sum(mapping[char] for char in perm)

    return (
            calc_permission(user) * 100 +
            calc_permission(group) * 10 +
            calc_permission(others)
    )


def download_with_resume(sftp, remote_path, local_path, progress_callback):
    """
    断点续传下载服务器文件到本地
    :param sftp:一个活动的SFTP客户端会话。
    :param remote_path:远程文件的路径。
    :param local_path:指向本地文件的路径。
    :param progress_callback:更新进度的回调函数。
    """
    # 获取远程文件大小
    remote_file_size = sftp.stat(remote_path).st_size

    # 检查本地文件存在和大小
    if os.path.exists(local_path):
        local_file_size = os.path.getsize(local_path)
    else:
        local_file_size = 0

    # 如果本地文件已经完整，直接返回
    if local_file_size >= remote_file_size:
        print("File already downloaded.")
        return

    # 打开远程文件，定位到断点处
    with sftp.file(remote_path, 'r') as remote_file:
        remote_file.prefetch(local_file_size)

        # 打开本地文件
        with open(local_path, 'ab') as local_file:
            # 从断点处读取
            remote_file.seek(local_file_size)
            while True:
                data = remote_file.read(32768)  # 每次读取32KB
                if not data:
                    break
                local_file.write(data)
                local_file_size += len(data)

                # 更新进度条
                progress_callback(local_file_size, remote_file_size)


def resume_upload(sftp, local_path, remote_path, progress_callback):
    """
    上传文件到具有恢复功能的远程服务器。
    :param sftp:-个活动的SFTP客户端会话。
    :param local_path:指向本地文件的路径。
    :param remote_path:远程文件的路径。
    :param progress_callback:更新进度的回调函数。
    """
    file_size = os.path.getsize(local_path)
    try:
        remote_file_size = sftp.stat(remote_path).st_size
    except FileNotFoundError:
        remote_file_size = 0

    with open(local_path, 'rb') as f:
        f.seek(remote_file_size)
        with sftp.file(remote_path, 'ab' if remote_file_size > 0 else 'wb') as remote_file:
            while True:
                data = f.read(32768)  # Read in chunks
                if not data:
                    break
                remote_file.write(data)
                remote_file_size += len(data)
                progress_callback(int((remote_file_size / file_size) * 100))


def open_file_in_explorer(path: str) -> None:
    """
    跨平台打开文件资源管理器并定位到指定路径
    :param path: 文件或文件夹的绝对路径
    """
    import platform
    import subprocess

    try:
        if platform.system() == 'Darwin':  # macOS
            subprocess.run(['open', '-R', path], check=True)
        elif platform.system() == 'Linux':
            if shutil.which('nautilus'):
                subprocess.Popen(['nautilus', '--select', path])
            elif shutil.which('dolphin'):
                subprocess.Popen(['dolphin', '--select', path])
            elif shutil.which('thunar'):
                subprocess.Popen(['thunar', os.path.dirname(path)])
            elif shutil.which('xdg-open'):
                subprocess.Popen(['xdg-open', os.path.dirname(path)])
        elif platform.system() == 'Windows':
            subprocess.run(['explorer', '/select,', os.path.normpath(path)], check=True)
    except Exception as e:
        logger.error(f"Failed to open explorer for path {path}: {e}")
