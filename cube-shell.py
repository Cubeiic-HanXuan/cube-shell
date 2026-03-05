import glob
import json
import logging
import os
import pickle
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from bisect import bisect_left
from collections import defaultdict
from pathlib import Path
from socket import socket

import PySide6
import appdirs
import qdarktheme
import toml

from qtermwidget.vt102_emulation import MODE_AppScreen

log_dir = os.path.expanduser("~/.cube-shell")
os.makedirs(log_dir, exist_ok=True)
if platform.system() == "Darwin":
    try:
        stdout_path = os.path.join(log_dir, "stdout.log")
        stderr_path = os.path.join(log_dir, "stderr.log")
        stdout_fd = os.open(stdout_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        stderr_fd = os.open(stderr_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        os.dup2(stdout_fd, 1)
        os.dup2(stderr_fd, 2)
        os.close(stdout_fd)
        os.close(stderr_fd)
    except Exception:
        pass

from PySide6.QtCore import QTimer, Signal, Qt, QPoint, QRect, QEvent, QObject, Slot, QUrl, QCoreApplication, \
    QSize, QThread, QMetaObject, Q_ARG, QProcessEnvironment
from PySide6.QtGui import QColor
from PySide6.QtGui import QIcon, QAction, QCursor, QCloseEvent, QInputMethodEvent, QPixmap, QKeySequence, QShortcut, \
    QDragEnterEvent, QDropEvent, QFont, QFontDatabase, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QApplication, QMainWindow, QMenu, QDialog, QMessageBox, QTreeWidgetItem, \
    QInputDialog, QFileDialog, QTreeWidget, QWidget, QVBoxLayout, QLabel, QHBoxLayout, QPushButton, QTableWidgetItem, \
    QHeaderView, QTabBar, QTextBrowser, QLineEdit, QScrollArea, QGridLayout, QProgressBar, QProgressDialog, \
    QDockWidget, QCheckBox, QFrame, QListWidget, QListWidgetItem
from deepdiff import DeepDiff
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import BashLexer

from core.docker.docker_compose_editor import DockerComposeEditor
from core.docker.docker_installer_ui import DockerInstallerWidget
from core.forwarder import ForwarderManager
from core.frequently_used_commands import TreeSearchApp
from core.uploader.progress_adapter import ProgressAdapter
from core.widgets.sparkline import SparklineWidget
from core.widgets.ring_gauge import RingGauge
from core.uploader.sftp_uploader_core import SFTPUploaderCore
from core.vars import ICONS, CONF_FILE, CMDS, KEYS
from function import util, about, theme, traversal
from function.ssh_func import SshClient
from function.util import format_file_size, has_valid_suffix
from qtermwidget.filter import HighlightFilter, PermissionHighlightFilter
from qtermwidget.qtermwidget import QTermWidget
from style.style import updateColor, InstalledButtonStyle, InstallButtonStyle
from ui import add_config, text_editor, confirm, main, docker_install, auth
from ui.add_tunnel_config import Ui_AddTunnelConfig
from ui.tunnel import Ui_Tunnel
from ui.compress_dialog import CompressDialog
from core.compressor import CompressThread, DecompressThread
from core.frp_manager import get_frp_manager
from ui.tunnel_config import Ui_TunnelConfig
from ui.code_editor import CodeEditor, Highlighter
from function.ssh_prompt_client import load_linux_commands
from core.ai import AISettingsDialog, open_ai_dialog
from i18n import get_language_manager, SUPPORTED_LANGUAGES

# 配置日志输出到文件
logging.basicConfig(
    filename=os.path.join(log_dir, "cube-shell.log"),
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)
logger = logging.getLogger("cube-shell")

# 将 stdout/stderr 重定向到文件，便于排查问题
try:
    sys.stdout = open(os.path.join(log_dir, 'stdout.log'), 'a', buffering=1, encoding='utf-8')
    sys.stderr = open(os.path.join(log_dir, 'stderr.log'), 'a', buffering=1, encoding='utf-8')
except Exception:
    pass

print("Cube-Shell Starting...")


def abspath(path):
    """
    获取当前脚本的绝对路径
    :param path:
    :return:
    """
    current_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(current_dir, 'conf', path)


class DockerInfoThread(QThread):
    """后台获取 Docker 信息的线程"""
    data_ready = Signal(dict, list)  # 分组信息, 容器列表

    # 使用表格格式，用特殊分隔符分隔，比 JSON 更快更轻量
    # 使用 ||| 作为分隔符，不太可能出现在容器信息中
    FIELD_SEPARATOR = '|||'
    # 字段：ID, Names, Image, State, CreatedAt, Ports
    DOCKER_PS_FORMAT = '{{.ID}}|||{{.Names}}|||{{.Image}}|||{{.State}}|||{{.CreatedAt}}|||{{.Ports}}'
    # compose 格式需要额外的 Project 和 Name 字段
    COMPOSE_PS_FORMAT = '{{.ID}}|||{{.Name}}|||{{.Image}}|||{{.State}}|||{{.CreatedAt}}|||{{.Ports}}|||{{.Project}}'

    def __init__(self, ssh_conn):
        super().__init__()
        self.ssh_conn = ssh_conn

    def _parse_container_line(self, line):
        """解析表格格式的容器信息"""
        parts = line.split(self.FIELD_SEPARATOR)
        if len(parts) >= 6:
            return {
                'ID': parts[0],
                'Names': parts[1],
                'Image': parts[2],
                'State': parts[3],
                'CreatedAt': parts[4],
                'Ports': parts[5] if len(parts) > 5 else ''
            }
        return None

    def _parse_compose_table_format(self, ls_output, groups, compose_container_ids):
        """回退方案：解析 docker compose ls 的表格输出"""
        lines = ls_output.strip().splitlines()
        for compose_ls in lines[1:]:  # 跳过表头
            # 解析格式: NAME  STATUS  CONFIG FILES
            # 使用正则分割多个空格
            parts = compose_ls.split()
            if len(parts) >= 3:
                # 最后一个部分是配置文件路径
                config = parts[-1]
                project_name = parts[0]

                if not config.endswith('.yml') and not config.endswith('.yaml'):
                    continue

                # 获取该项目的容器列表
                ps_cmd = f"docker compose --file {config} ps -a --format json 2>/dev/null"
                conn_exec = self.ssh_conn.sudo_exec(ps_cmd)

                if conn_exec and conn_exec.strip():
                    for line in conn_exec.strip().splitlines():
                        if line.strip():
                            try:
                                container = json.loads(line)
                                data = {
                                    'ID': container.get('ID', ''),
                                    'Name': container.get('Name', ''),
                                    'Image': container.get('Image', ''),
                                    'State': container.get('State', ''),
                                    'CreatedAt': container.get('CreatedAt', ''),
                                    'Ports': container.get('Ports', ''),
                                    'Project': container.get('Project', project_name)
                                }
                                if data['ID']:
                                    compose_container_ids.add(data['ID'])
                                    groups[data['Project']].append(data)
                            except json.JSONDecodeError:
                                pass

    def run(self):
        if not self.ssh_conn or not self.ssh_conn.active:
            self.data_ready.emit({}, [])
            return

        groups = defaultdict(list)
        container_list = []
        compose_container_ids = set()  # 记录所有 compose 管理的容器 ID

        try:
            # 获取 compose 项目列表（使用 JSON 格式，更可靠）
            ls = self.ssh_conn.sudo_exec("docker compose ls -a --format json 2>/dev/null")
            if ls and ls.strip():
                try:
                    # docker compose ls --format json 输出是 JSON 数组
                    compose_projects = json.loads(ls.strip())
                    for project in compose_projects:
                        project_name = project.get('Name', '')
                        config = project.get('ConfigFiles', '')
                        if not config or not project_name:
                            continue

                        # 获取该项目的容器列表（使用 JSON 格式）
                        ps_cmd = f"docker compose --file {config} ps -a --format json 2>/dev/null"
                        conn_exec = self.ssh_conn.sudo_exec(ps_cmd)

                        if conn_exec and conn_exec.strip():
                            # docker compose ps --format json 输出可能是每行一个 JSON 或 JSON 数组
                            for line in conn_exec.strip().splitlines():
                                if line.strip():
                                    try:
                                        container = json.loads(line)
                                        data = {
                                            'ID': container.get('ID', ''),
                                            'Name': container.get('Name', ''),
                                            'Image': container.get('Image', ''),
                                            'State': container.get('State', ''),
                                            'CreatedAt': container.get('CreatedAt', ''),
                                            'Ports': container.get('Ports', ''),
                                            'Project': container.get('Project', project_name)
                                        }
                                        if data['ID']:
                                            compose_container_ids.add(data['ID'])
                                            groups[data['Project']].append(data)
                                    except json.JSONDecodeError:
                                        pass
                except json.JSONDecodeError:
                    # JSON 解析失败，可能是旧版 docker compose，回退到表格解析
                    util.logger.warning("docker compose ls JSON parse failed, falling back to table parsing")
                    self._parse_compose_table_format(ls, groups, compose_container_ids)

            # 获取所有独立容器（使用表格格式提升性能）
            # 分两次获取：运行中 + 已停止，比直接 -a 更快
            standalone_containers = []

            # 1. 获取运行中的容器
            running_cmd = f"docker ps --format '{self.DOCKER_PS_FORMAT}' 2>/dev/null"
            conn_exec = self.ssh_conn.sudo_exec(running_cmd)
            if conn_exec:
                for ps in conn_exec.strip().splitlines():
                    if ps.strip():
                        data = self._parse_container_line(ps)
                        if data and data['ID'] and data['ID'] not in compose_container_ids:
                            standalone_containers.append(data)

            # 2. 获取已停止的容器
            exited_cmd = f"docker ps -f 'status=exited' -f 'status=created' -f 'status=dead' --format '{self.DOCKER_PS_FORMAT}' 2>/dev/null"
            conn_exec = self.ssh_conn.sudo_exec(exited_cmd)
            if conn_exec:
                for ps in conn_exec.strip().splitlines():
                    if ps.strip():
                        data = self._parse_container_line(ps)
                        if data and data['ID'] and data['ID'] not in compose_container_ids:
                            standalone_containers.append(data)

            # 独立容器统一放在一个分组（保持原有展示逻辑）
            if standalone_containers:
                groups['default'] = standalone_containers

            self.data_ready.emit(groups, container_list)

        except Exception as e:
            util.logger.error(f"Docker info fetch error: {e}")
            self.data_ready.emit({}, [])


class CommonContainersThread(QThread):
    """后台获取常用容器信息的线程"""
    data_ready = Signal(dict, bool)  # 服务配置, 是否安装Docker

    def __init__(self, ssh_conn, config_path):
        super().__init__()
        self.ssh_conn = ssh_conn
        self.config_path = config_path

    def run(self):
        if not self.ssh_conn or not self.ssh_conn.active:
            self.data_ready.emit({}, False)
            return

        try:
            data_ = self.ssh_conn.sudo_exec('docker --version')
            if not data_:
                self.data_ready.emit({}, False)
                return

            # 优化：只获取容器名称，不需要全部 JSON 信息
            # 这样在容器数量多时也能快速返回
            conn_exec = self.ssh_conn.sudo_exec("docker ps -a --format '{{.Names}}' 2>/dev/null")
            container_names = []
            if conn_exec and conn_exec.strip():
                container_names = [name.strip() for name in conn_exec.strip().splitlines() if name.strip()]

            services = util.get_compose_service(self.config_path)
            # 使用优化后的匹配逻辑
            services_config = self._update_has_attribute(services, container_names)

            self.data_ready.emit(services_config, True)

        except Exception as e:
            util.logger.error(f"Common containers fetch error: {e}")
            self.data_ready.emit({}, False)

    def _update_has_attribute(self, services_dict, container_names):
        """根据容器名称列表检查服务是否已安装"""
        for service_key, config in services_dict.items():
            config['has'] = any(service_key in name for name in container_names)
        return services_dict


class DockerOperationThread(QThread):
    """后台执行 Docker 容器操作的线程（停止、重启、删除等）"""
    # (成功与否, 操作类型, 容器信息字典 {id: {state, ports}})
    operation_finished = Signal(bool, str, dict)

    def __init__(self, ssh_conn, operation, container_ids):
        super().__init__()
        self.ssh_conn = ssh_conn
        self.operation = operation  # 'stop', 'restart', 'rm', 'start'
        self.container_ids = container_ids

    def run(self):
        if not self.ssh_conn or not self.ssh_conn.active:
            self.operation_finished.emit(False, self.operation, {})
            return

        try:
            for container_id in self.container_ids:
                cmd = f"docker {self.operation} {container_id}"
                # 使用 sudo_exec 并等待命令完成
                self.ssh_conn.sudo_exec(cmd)

            # 操作完成后，获取被操作容器的最新状态和端口信息
            container_info = {}
            if self.operation != 'rm':
                for container_id in self.container_ids:
                    # 查询容器最新状态和端口（使用 docker ps 格式，与列表一致）
                    result = self.ssh_conn.sudo_exec(
                        f"docker ps -a --filter 'id={container_id}' --format '{{{{.State}}}}|||{{{{.Ports}}}}' 2>/dev/null"
                    )
                    state = ''
                    ports_str = ''
                    if result and result.strip():
                        parts = result.strip().split('|||')
                        state = parts[0] if len(parts) > 0 else ''
                        ports_str = parts[1] if len(parts) > 1 else ''

                    container_info[container_id] = {
                        'state': state,
                        'ports': ports_str
                    }
            else:
                # 删除操作，标记为 removed
                for container_id in self.container_ids:
                    container_info[container_id] = {'state': 'removed', 'ports': ''}

            self.operation_finished.emit(True, self.operation, container_info)
        except Exception as e:
            util.logger.error(f"Docker {self.operation} error: {e}")
            self.operation_finished.emit(False, self.operation, {})


class FRPInstallThread(QThread):
    """后台下载和安装 FRP 的线程"""
    progress_updated = Signal(int)  # 进度百分比
    status_updated = Signal(str)  # 状态消息
    finished_signal = Signal(bool, str)  # (成功与否, 错误消息)

    def __init__(self, frp_manager, ssh_conn=None, sftp=None, install_client=True, install_server=False):
        super().__init__()
        self.frp_manager = frp_manager
        self.ssh_conn = ssh_conn
        self.sftp = sftp
        self.install_client = install_client
        self.install_server = install_server

    def run(self):
        try:
            # 安装客户端
            if self.install_client and not self.frp_manager.is_frpc_ready():
                self.status_updated.emit("正在下载 FRP 客户端...")

                def update_progress(downloaded, total):
                    if total > 0:
                        percent = int(downloaded * 100 / total)
                        self.progress_updated.emit(percent)

                def update_status(msg):
                    self.status_updated.emit(msg)

                success = self.frp_manager.ensure_frpc(
                    progress_callback=update_progress,
                    status_callback=update_status
                )

                if not success:
                    self.finished_signal.emit(False, "FRP 客户端下载失败，请检查网络连接后重试。")
                    return

            # 安装服务端
            if self.install_server and self.ssh_conn and self.sftp:
                self.status_updated.emit("正在部署 FRP 服务端...")
                self.progress_updated.emit(0)

                def update_progress(downloaded, total):
                    if total > 0:
                        percent = int(downloaded * 100 / total)
                        self.progress_updated.emit(percent)

                def update_status(msg):
                    self.status_updated.emit(msg)

                success = self.frp_manager.ensure_frps_on_server(
                    self.ssh_conn, self.sftp,
                    progress_callback=update_progress,
                    status_callback=update_status
                )

                if not success:
                    self.finished_signal.emit(False, "FRP 服务端部署失败，请检查网络连接后重试。")
                    return

            self.finished_signal.emit(True, "")

        except Exception as e:
            self.finished_signal.emit(False, str(e))


class FRPServiceThread(QThread):
    """后台启动/停止 FRP 服务的线程"""
    status_updated = Signal(str)  # 状态消息
    finished_signal = Signal(bool, str)  # (成功与否, 错误消息)

    def __init__(self, ssh_conn, host, token, ant_type, local_port, server_prot, frp_manager, action='start'):
        super().__init__()
        self.ssh_conn = ssh_conn
        self.host = host
        self.token = token
        self.ant_type = ant_type
        self.local_port = local_port
        self.server_prot = server_prot
        self.frp_manager = frp_manager
        self.action = action  # 'start' or 'stop'

    def run(self):
        try:
            if self.action == 'start':
                self._start_services()
            else:
                self._stop_services()
        except Exception as e:
            self.finished_signal.emit(False, str(e))

    def _start_services(self):
        # 检查服务端代理端口权限
        server_port = int(self.server_prot)
        if server_port <= 1024:
            try:
                whoami_result = self.ssh_conn.exec(cmd="whoami", pty=False)
                remote_user = whoami_result.strip() if whoami_result else ""
                if remote_user != "root":
                    self.finished_signal.emit(
                        False,
                        f"服务端代理端口 {server_port} 需要 root 权限。\n"
                        f"当前用户为: {remote_user}\n"
                        f"请使用大于 1024 的端口（如 1080、8888 等）"
                    )
                    return
            except:
                pass

        self.status_updated.emit("正在启动服务端...")

        # 先彻底杀死所有 frps 进程
        self.ssh_conn.conn.exec_command(timeout=2, command="killall -9 frps 2>/dev/null; pkill -9 frps 2>/dev/null",
                                        get_pty=False)
        time.sleep(2)  # 等待端口释放

        # 写入配置并启动 frps（使用 $HOME/frp）
        frps_config = traversal.frps(self.token, self.ant_type, self.server_prot)
        self.ssh_conn.exec(cmd=f"cat > $HOME/frp/frps.toml << 'EOF'\n{frps_config}\nEOF", pty=False)

        cmd1 = f"cd $HOME/frp && nohup ./frps -c frps.toml &> frps.log &"
        self.ssh_conn.conn.exec_command(timeout=1, command=cmd1, get_pty=False)
        time.sleep(2)

        # 检查 frps 是否启动成功
        check_result = self.ssh_conn.exec(cmd="pgrep -x frps", pty=False)
        if not check_result or not check_result.strip():
            self.finished_signal.emit(False, "服务端 frps 启动失败，请检查服务器日志")
            return

        self.status_updated.emit("正在启动客户端...")

        # 停止旧的 frpc
        if platform.system() == 'Darwin' or platform.system() == 'Linux':
            os.system("pkill -9 frpc 2>/dev/null")
        elif platform.system() == 'Windows':
            subprocess.run(['taskkill', '/f', '/im', 'frpc.exe'], capture_output=True, text=True)
        time.sleep(0.5)

        # 写入 frpc 配置
        frpc = traversal.frpc(self.host.split(':')[0], self.token, self.ant_type, self.local_port, self.server_prot)
        with open(abspath('frpc.toml'), 'w') as file:
            file.write(frpc)

        util.logger.info(
            f"FRP 配置: 服务器={self.host.split(':')[0]}, 服务端端口={self.server_prot}, 本地端口={self.local_port}")

        # 启动 frpc
        frpc_path = str(self.frp_manager.frpc_path)
        frp_log_dir = str(self.frp_manager.frpc_path.parent)
        frpc_config_path = abspath('frpc.toml')

        if platform.system() == 'Darwin' or platform.system() == 'Linux':
            cmd_u = f'cd "{frp_log_dir}" && nohup "{frpc_path}" -c "{frpc_config_path}" > frpc.log 2>&1 &'
            os.system(cmd_u)
        elif platform.system() == 'Windows':
            subprocess.Popen(
                [frpc_path, "-c", frpc_config_path],
                stdout=open(os.path.join(frp_log_dir, "frpc.log"), "a"),
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW
            )

        time.sleep(2)

        self.ssh_conn.close()
        self.finished_signal.emit(True, "")

    def _stop_services(self):
        self.status_updated.emit("正在停止服务...")

        self.ssh_conn.conn.exec_command(timeout=1, command="pkill -9 frps", get_pty=False)

        if platform.system() == 'Darwin' or platform.system() == 'Linux':
            os.system("pkill -9 frpc")
        elif platform.system() == 'Windows':
            subprocess.run(['taskkill', '/f', '/im', 'frpc.exe'], capture_output=True, text=True)

        self.ssh_conn.close()
        self.finished_signal.emit(True, "")


class FRPConnectThread(QThread):
    """后台处理整个 FRP 连接流程的线程"""
    status_updated = Signal(str)
    progress_updated = Signal(int)
    finished_signal = Signal(bool, str, bool)  # (成功与否, 错误消息, is_start_action)

    def __init__(self, params, is_stop, frp_manager):
        super().__init__()
        self.params = params
        self.is_stop = is_stop
        self.frp_manager = frp_manager

    def run(self):
        try:
            host = self.params['host']

            # 检查服务器可达性
            self.status_updated.emit("正在检查服务器连接...")
            if not util.check_server_accessibility(host.split(':')[0], int(host.split(':')[1])):
                self.finished_signal.emit(False, "服务器无法连接，请检查网络或服务器状态。", not self.is_stop)
                return

            # 建立 SSH 连接
            self.status_updated.emit("正在建立 SSH 连接...")
            ssh_conn = SshClient(
                host.split(':')[0], int(host.split(':')[1]),
                self.params['username'], self.params['password'],
                self.params['key_type'], self.params['key_file']
            )
            ssh_conn.connect()

            if self.is_stop:
                # 停止服务
                self._stop_services(ssh_conn)
            else:
                # 启动服务
                sftp = ssh_conn.open_sftp()
                self._start_services(ssh_conn, sftp)

        except Exception as e:
            util.logger.error(str(e))
            self.finished_signal.emit(False, str(e), not self.is_stop)

    def _start_services(self, ssh_conn, sftp):
        # 检查服务端代理端口权限
        server_port = int(self.params['server_prot'])
        if server_port <= 1024:
            # 检查远程用户是否为 root
            try:
                whoami_result = ssh_conn.exec(cmd="whoami", pty=False)
                remote_user = whoami_result.strip() if whoami_result else ""
                if remote_user != "root":
                    self.finished_signal.emit(
                        False,
                        f"服务端代理端口 {server_port} 需要 root 权限。\n"
                        f"当前用户为: {remote_user}\n"
                        f"请使用大于 1024 的端口（如 8088、8888 等）",
                        True
                    )
                    return
            except:
                pass

        # 检查是否需要安装
        need_client = not self.frp_manager.is_frpc_ready()
        need_server = not util.check_remote_frp_exists(ssh_conn)

        # 安装客户端
        if need_client:
            self.status_updated.emit("正在下载 FRP 客户端...")

            def update_progress(downloaded, total):
                if total > 0:
                    self.progress_updated.emit(int(downloaded * 100 / total))

            success = self.frp_manager.ensure_frpc(
                progress_callback=update_progress,
                status_callback=lambda msg: self.status_updated.emit(msg)
            )
            if not success:
                self.finished_signal.emit(False, "FRP 客户端下载失败", True)
                return

        # 安装服务端
        if need_server:
            self.status_updated.emit("正在部署 FRP 服务端...")
            self.progress_updated.emit(0)

            def update_progress(downloaded, total):
                if total > 0:
                    self.progress_updated.emit(int(downloaded * 100 / total))

            success = self.frp_manager.ensure_frps_on_server(
                ssh_conn, sftp,
                progress_callback=update_progress,
                status_callback=lambda msg: self.status_updated.emit(msg)
            )
            if not success:
                self.finished_signal.emit(False, "FRP 服务端部署失败", True)
                return

        # 启动服务端
        self.status_updated.emit("正在启动服务端...")
        # 先彻底杀死所有 frps 进程（包括可能在 /opt/frp 下的旧进程）
        ssh_conn.conn.exec_command(timeout=2, command="killall -9 frps 2>/dev/null; pkill -9 frps 2>/dev/null",
                                   get_pty=False)
        time.sleep(2)  # 等待端口释放

        frps_config = traversal.frps(self.params['token'], self.params['ant_type'], self.params['server_prot'])
        ssh_conn.exec(cmd=f"cat > $HOME/frp/frps.toml << 'EOF'\n{frps_config}\nEOF", pty=False)

        cmd1 = f"cd $HOME/frp && nohup ./frps -c frps.toml &> frps.log &"
        ssh_conn.conn.exec_command(timeout=1, command=cmd1, get_pty=False)
        time.sleep(2)

        check_result = ssh_conn.exec(cmd="pgrep -x frps", pty=False)
        if not check_result or not check_result.strip():
            self.finished_signal.emit(False, "服务端 frps 启动失败，请检查服务器日志", True)
            return

        # 启动客户端
        self.status_updated.emit("正在启动客户端...")

        if platform.system() == 'Darwin' or platform.system() == 'Linux':
            os.system("pkill -9 frpc 2>/dev/null")
        elif platform.system() == 'Windows':
            subprocess.run(['taskkill', '/f', '/im', 'frpc.exe'], capture_output=True, text=True)
        time.sleep(0.5)

        frpc = traversal.frpc(
            self.params['host'].split(':')[0],
            self.params['token'],
            self.params['ant_type'],
            self.params['local_port'],
            self.params['server_prot']
        )
        with open(abspath('frpc.toml'), 'w') as file:
            file.write(frpc)

        util.logger.info(
            f"FRP 配置: 服务器={self.params['host'].split(':')[0]}, 服务端端口={self.params['server_prot']}, 本地端口={self.params['local_port']}")

        frpc_path = str(self.frp_manager.frpc_path)
        frp_log_dir = str(self.frp_manager.frpc_path.parent)
        frpc_config_path = abspath('frpc.toml')

        if platform.system() == 'Darwin' or platform.system() == 'Linux':
            cmd_u = f'cd "{frp_log_dir}" && nohup "{frpc_path}" -c "{frpc_config_path}" > frpc.log 2>&1 &'
            os.system(cmd_u)
        elif platform.system() == 'Windows':
            subprocess.Popen(
                [frpc_path, "-c", frpc_config_path],
                stdout=open(os.path.join(frp_log_dir, "frpc.log"), "a"),
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW
            )

        time.sleep(2)
        ssh_conn.close()
        self.finished_signal.emit(True, "", True)

    def _stop_services(self, ssh_conn):
        self.status_updated.emit("正在停止服务...")

        ssh_conn.conn.exec_command(timeout=1, command="pkill -9 frps", get_pty=False)

        if platform.system() == 'Darwin' or platform.system() == 'Linux':
            os.system("pkill -9 frpc")
        elif platform.system() == 'Windows':
            subprocess.run(['taskkill', '/f', '/im', 'frpc.exe'], capture_output=True, text=True)

        ssh_conn.close()
        self.finished_signal.emit(True, "", False)


# 主界面逻辑
class TabCloseButton(QWidget):
    """
    自定义Tab关闭按钮组件
    - 默认显示绿色圆点（表示终端正常连接）
    - 鼠标悬浮到tab时显示关闭按钮（叉叉）
    """
    clicked = Signal()

    def __init__(self, parent=None, tab_bar=None):
        super().__init__(parent)
        self.setFixedSize(18, 18)
        self.tab_bar = tab_bar
        self._is_hovered = False

        # 创建布局
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 绿色圆点标签
        self.status_dot = QLabel(self)
        self.status_dot.setFixedSize(10, 10)
        self.status_dot.setStyleSheet("""
            QLabel {
                background-color: #4CAF50;
                border-radius: 5px;
            }
        """)

        # 关闭按钮 - 使用QLabel显示叉号，更清晰
        self.close_btn = QLabel(self)
        self.close_btn.setFixedSize(16, 16)
        self.close_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.close_btn.setAlignment(Qt.AlignCenter)
        self.close_btn.setText("✕")
        self.close_btn.setStyleSheet("""
            QLabel {
                background-color: transparent;
                color: #888;
                font-size: 14px;
                font-weight: bold;
            }
            QLabel:hover {
                background-color: #e81123;
                color: white;
                border-radius: 3px;
            }
        """)
        # 为QLabel添加点击事件
        self.close_btn.mousePressEvent = lambda e: self.clicked.emit()

        layout.addWidget(self.status_dot, 0, Qt.AlignCenter)
        layout.addWidget(self.close_btn, 0, Qt.AlignCenter)

        # 默认显示绿色圆点，隐藏关闭按钮
        self.close_btn.hide()
        self.status_dot.show()

        # 安装事件过滤器到tab_bar
        if self.tab_bar:
            self.tab_bar.installEventFilter(self)
            self.tab_bar.setMouseTracking(True)

    def getCurrentTabIndex(self):
        """动态获取当前TabCloseButton所在的tab索引"""
        if not self.tab_bar:
            return -1
        # 遍历所有tab，查找当前按钮对应的tab
        for i in range(self.tab_bar.count()):
            if self.tab_bar.tabButton(i, QTabBar.LeftSide) == self:
                return i
        return -1

    def eventFilter(self, obj, event):
        """监听tab bar的鼠标事件"""
        if obj == self.tab_bar:
            if event.type() == QEvent.MouseMove:
                # 获取鼠标所在的tab索引
                pos = event.pos()
                hovered_index = self.tab_bar.tabAt(pos)
                # 动态获取当前按钮所在的tab索引
                my_index = self.getCurrentTabIndex()
                if hovered_index == my_index and my_index >= 0:
                    if not self._is_hovered:
                        self._is_hovered = True
                        self.showCloseButton()
                else:
                    if self._is_hovered:
                        self._is_hovered = False
                        self.showStatusDot()
            elif event.type() == QEvent.Leave:
                # 鼠标离开tab bar
                if self._is_hovered:
                    self._is_hovered = False
                    self.showStatusDot()
        return super().eventFilter(obj, event)

    def showCloseButton(self):
        """显示关闭按钮"""
        self.status_dot.hide()
        self.close_btn.show()

    def showStatusDot(self):
        """显示状态圆点"""
        self.close_btn.hide()
        self.status_dot.show()

    def setConnected(self, connected):
        """设置连接状态"""
        if connected:
            self.status_dot.setStyleSheet("""
                QLabel {
                    background-color: #4CAF50;
                    border-radius: 5px;
                }
            """)
        else:
            self.status_dot.setStyleSheet("""
                QLabel {
                    background-color: #f44336;
                    border-radius: 5px;
                }
            """)


class MainDialog(QMainWindow):
    initSftpSignal = Signal()
    # 信号：成功结果 (命令, 输出)
    finished = Signal(str, str)
    # 信号：错误 (命令, 错误信息)
    error = Signal(str, str)
    # 新增：主题切换信号，参数：is_dark_theme
    themeChanged = Signal(bool)

    # 异步更新UI信号
    update_file_tree_signal = Signal(str, str, list)  # 连接ID, 当前目录, 文件列表
    update_process_list_signal = Signal(str, list)  # 连接ID, 进程列表

    def __init__(self, qt_app):
        super().__init__()
        self.app = qt_app  # 将 app 传递并设置为类属性
        self.ui = main.Ui_MainWindow()
        self.ui.setupUi(self)
        self.setWindowIcon(QIcon(":logo.ico"))

        # 连接异步信号
        self.update_file_tree_signal.connect(self.handle_file_tree_updated)
        self.update_process_list_signal.connect(self.handle_process_list_updated)
        # macOS 下禁用输入法相关属性，避免 TUINSRemoteViewController 报错
        self.setAttribute(Qt.WA_InputMethodEnabled, False)
        self.setAttribute(Qt.WA_KeyCompression, True)
        self.setFocusPolicy(Qt.WheelFocus)
        self.Shell = None
        self.update_timer = None
        # 存储 SSH 客户端实例，用于管理后台连接
        self.ssh_clients = {}
        icon = QIcon(":index.png")
        self.ui.ShellTab.tabBar().setTabIcon(0, icon)

        # 确保配置目录存在并迁移现有配置文件（仅首次运行时）
        migrate_existing_configs(util.APP_NAME)

        # 保存所有 QLineEdit 的列表
        self.line_edits = []

        init_config()
        util.THEME = util.read_json(abspath('theme.json'))
        self.applyAppearance(util.THEME.get("appearance"))
        self.index_pwd()

        # 隧道管理
        self.data = None
        self.tunnels = []
        self.tunnel_refresh()
        self.nat_traversal()

        # 进程管理
        self.search_text = ""
        self.all_processes = []
        self.filtered_processes = []

        # 设置拖放行为
        self.setAcceptDrops(True)

        # 菜单栏
        self.menuBarController()
        self.dir_tree_now = []
        self.file_name = ''
        self.fileEvent = ''
        self.active_upload_threads = []

        self.ui.discButton.clicked.connect(self.disc_off)
        self.ui.theme.clicked.connect(self.theme)
        # 🔧 连接主题切换信号
        self.themeChanged.connect(self.on_system_theme_changed)
        self.ui.treeWidget.customContextMenuRequested.connect(self.treeRight)
        self.ui.treeWidget.doubleClicked.connect(self.cd)
        self.ui.ShellTab.currentChanged.connect(self.shell_tab_current_changed)
        # 连接信号
        self.ui.tabWidget.currentChanged.connect(self.on_tab_changed)
        # 设置选择模式为多选模式
        self.ui.treeWidget.setSelectionMode(QTreeWidget.ExtendedSelection)
        # 优化左侧图标显示间距
        self.ui.treeWidget.setStyleSheet("""
            QTreeWidget::item {
                padding-left: 5px;
            }
        """)
        # 添加事件过滤器
        self.ui.treeWidget.viewport().installEventFilter(self)

        # 用于拖动选择的变量
        self.is_left_selecting = False
        self.start_pos = QPoint()
        self.selection_rect = QRect()

        # 安装事件过滤器来监控标签移动事件
        self.ui.ShellTab.tabBar().installEventFilter(self)
        self.homeTabPressed = False
        # 用于存储拖动开始时的标签索引
        self.originalIndex = -1

        self.ui.treeWidgetDocker.customContextMenuRequested.connect(self.treeDocker)

        # 创建SSH连接器
        self.ssh_connector = SSHConnector()
        self.ssh_connector.connected.connect(self.on_ssh_connected)
        self.ssh_connector.failed.connect(self.on_ssh_failed)

        self.isConnected = False

        # 连接信号和槽
        self.initSftpSignal.connect(self.on_initSftpSignal)
        # #  操作docker 成功,发射信号
        # self.finished.connect(self.on_ssh_docker_finished)

        self.NAT = False
        self.NAT_lod()
        self.ui.pushButton.clicked.connect(self.on_NAT_traversal)

        # 记录当前文件树显示的连接ID
        self.current_displayed_connection_id = None

        # 连接状态防抖
        self.is_connecting_lock = False
        self._last_connect_attempt_ts = 0
        self.is_closing = False

        self._move_monitor_and_process_to_bottom_tabs()

    def _move_monitor_and_process_to_bottom_tabs(self):
        try:
            tab_widget = getattr(self.ui, "tabWidget", None)
            if not tab_widget:
                return

            monitor_tab = QWidget()
            monitor_tab.setObjectName("tab_remote_monitor")
            monitor_layout = QHBoxLayout(monitor_tab)
            monitor_layout.setContentsMargins(12, 10, 12, 10)
            monitor_layout.setSpacing(20)

            try:
                appearance = str(getattr(util, "THEME", {}) or {}).lower()
            except Exception:
                appearance = "dark"
            is_light = "appearance" in appearance and "light" in appearance
            if not is_light:
                try:
                    is_light = str((getattr(util, "THEME", {}) or {}).get("appearance") or "").lower() == "light"
                except Exception:
                    is_light = False

            # High-Tech Styling
            monitor_tab.setStyleSheet(
                """
                QWidget#tab_remote_monitor {
                    background: transparent;
                }
                QFrame#monitorPanel {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(40, 44, 52, 240), stop:1 rgba(33, 37, 43, 255));
                    border: 1px solid rgba(255, 255, 255, 0.1);
                    border-radius: 12px;
                }
                QLabel {
                    color: #AAB2C0;
                    font-family: "Segoe UI", sans-serif;
                }
                QLabel#sectionTitle {
                    color: #E1E4E8;
                    font-weight: 700;
                    font-size: 12px;
                    background: transparent;
                }
                QLabel#valueText {
                    color: #FFFFFF;
                    font-weight: 600;
                    font-size: 13px;
                }
                """ if not is_light else
                """
                QWidget#tab_remote_monitor {
                    background: transparent;
                }
                QFrame#monitorPanel {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(245, 247, 250, 240), stop:1 rgba(255, 255, 255, 255));
                    border: 1px solid rgba(0, 0, 0, 0.08);
                    border-radius: 12px;
                }
                QLabel {
                    color: #4A5568;
                    font-family: "Segoe UI", sans-serif;
                }
                QLabel#sectionTitle {
                    color: #2D3748;
                    font-weight: 700;
                    font-size: 12px;
                    background: transparent;
                }
                QLabel#valueText {
                    color: #1A202C;
                    font-weight: 600;
                    font-size: 13px;
                }
                """
            )

            # --- Ring Gauges Section (CPU, RAM, Disk) ---
            def create_ring_section(layout, label_name, bar_name, color, title):
                # Hide original widgets but keep them updated
                orig_label = getattr(self.ui, label_name, None)
                orig_bar = getattr(self.ui, bar_name, None)
                if orig_bar:
                    orig_bar.setVisible(False)
                    orig_bar.setParent(monitor_tab)  # Reparent to keep alive
                if orig_label:
                    orig_label.setVisible(False)
                    orig_label.setParent(monitor_tab)

                container = QFrame()
                # container.setFixedWidth(80)
                vbox = QVBoxLayout(container)
                vbox.setContentsMargins(0, 0, 0, 0)
                vbox.setSpacing(4)

                # Ring Gauge
                ring = RingGauge(container, color=color, label=title)
                # ring.setFixedSize(80, 80)

                # Sparkline (Miniature below ring)
                spark = SparklineWidget(container)
                # spark.setFixedHeight(20)
                spark.setLineColor(QColor(color))

                vbox.addWidget(ring, 0, Qt.AlignCenter)
                vbox.addWidget(spark)

                layout.addWidget(container)

                # Store references and connect signals
                setattr(self.ui, bar_name.replace("Rate", "Ring"), ring)
                setattr(self.ui, bar_name.replace("Rate", "Sparkline"), spark)

                if orig_bar:
                    try:
                        orig_bar.valueChanged.connect(ring.setValue)
                        orig_bar.valueChanged.connect(spark.addPoint)
                    except:
                        pass

            # --- Network Section ---
            def create_network_section(layout):
                container = QFrame()
                container.setObjectName("monitorPanel")
                container.setFrameShape(QFrame.StyledPanel)
                vbox = QVBoxLayout(container)
                vbox.setContentsMargins(12, 10, 12, 10)
                vbox.setSpacing(8)

                title = QLabel(self.tr("NETWORK I/O"), container)
                title.setObjectName("sectionTitle")
                vbox.addWidget(title)

                # Up
                up_layout = QHBoxLayout()
                up_icon = QLabel("▲", container)
                up_icon.setStyleSheet("color: #E05B00;" if is_light else "color: #FF9F43;")
                up_val = getattr(self.ui, "networkUpload", None)
                if up_val:
                    up_val.setParent(container)
                    up_val.setFrame(False)
                    up_val.setAttribute(Qt.WA_TransparentForMouseEvents)
                    up_val.setStyleSheet("background: transparent; color: " + (
                        "#2D3748" if is_light else "#E1E4E8") + "; font-weight: bold; border: none; font-family: 'Consolas', 'Courier New', monospace;")
                    # up_val.setFixedWidth(120)
                    # up_val.setFixedHeight(24)
                    up_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

                up_spark = SparklineWidget(container)
                # up_spark.setFixedHeight(24)
                up_spark.setLineColor(QColor("#E05B00") if is_light else QColor("#FF9F43"))
                setattr(self.ui, "networkUploadSparkline", up_spark)

                up_layout.addWidget(up_icon)
                up_layout.addWidget(up_spark, 1)
                if up_val: up_layout.addWidget(up_val)
                vbox.addLayout(up_layout)

                # Down
                down_layout = QHBoxLayout()
                down_icon = QLabel("▼", container)
                down_icon.setStyleSheet("color: #00A1FF;" if is_light else "color: #48DBFB;")
                down_val = getattr(self.ui, "networkDownload", None)
                if down_val:
                    down_val.setParent(container)
                    down_val.setFrame(False)
                    down_val.setAttribute(Qt.WA_TransparentForMouseEvents)
                    down_val.setStyleSheet("background: transparent; color: " + (
                        "#2D3748" if is_light else "#E1E4E8") + "; font-weight: bold; border: none; font-family: 'Consolas', 'Courier New', monospace;")
                    # down_val.setFixedWidth(120)
                    # down_val.setFixedHeight(24)
                    down_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

                down_spark = SparklineWidget(container)
                down_spark.setFixedHeight(24)
                down_spark.setLineColor(QColor("#00A1FF") if is_light else QColor("#48DBFB"))
                setattr(self.ui, "networkDownloadSparkline", down_spark)

                down_layout.addWidget(down_icon)
                down_layout.addWidget(down_spark, 1)
                if down_val: down_layout.addWidget(down_val)
                vbox.addLayout(down_layout)

                layout.addWidget(container, 2)  # Stretch factor equal to system section

            # --- System Info Section ---
            def create_sys_section(layout):
                container = QFrame()
                container.setObjectName("monitorPanel")
                container.setFrameShape(QFrame.StyledPanel)
                # Ensure minimum width for full info display
                container.setMinimumWidth(260)

                vbox = QVBoxLayout(container)
                vbox.setContentsMargins(12, 10, 12, 10)
                vbox.setSpacing(4)

                title = QLabel(self.tr("SYSTEM INFO"), container)
                title.setObjectName("sectionTitle")
                vbox.addWidget(title)

                info_grid = QGridLayout()
                info_grid.setHorizontalSpacing(10)
                info_grid.setVerticalSpacing(2)

                def add_info_row(row, label_widget_name, val_widget_name, icon_char):
                    lbl = getattr(self.ui, label_widget_name, None)
                    val = getattr(self.ui, val_widget_name, None)
                    if lbl and val:
                        lbl.setParent(container)
                        val.setParent(container)
                        lbl.setVisible(False)  # Hide original label text, use icon

                        icon = QLabel(icon_char, container)
                        icon.setStyleSheet("color: #A0AEC0; font-size: 14px;")

                        val.setFrame(False)
                        val.setAttribute(Qt.WA_TransparentForMouseEvents)
                        # Monospace font for values for better alignment and tech feel
                        val.setStyleSheet("background: transparent; color: " + (
                            "#4A5568" if is_light else "#CBD5E0") + "; border: none; font-family: 'Consolas', 'Courier New', monospace;")
                        val.setFixedHeight(20)

                        info_grid.addWidget(icon, row, 0)
                        info_grid.addWidget(val, row, 1)

                add_info_row(0, "label_4", "operatingSystem", "🖥")
                add_info_row(1, "label_8", "kernel", "⚙")
                add_info_row(2, "label_10", "kernelVersion", "#")

                vbox.addLayout(info_grid)
                layout.addWidget(container, 2)  # Higher stretch factor

            # Build Layout
            # Left: Rings
            rings_layout = QHBoxLayout()
            rings_layout.setSpacing(15)
            create_ring_section(rings_layout, "label", "cpuRate", "#FF6B6B" if not is_light else "#E05B00", "CPU")
            create_ring_section(rings_layout, "label_2", "memRate", "#54A0FF" if not is_light else "#00A1FF", "MEM")
            create_ring_section(rings_layout, "label_3", "diskRate", "#2ECC71", "DISK")

            # Combine
            monitor_layout.addLayout(rings_layout)
            create_network_section(monitor_layout)
            create_sys_section(monitor_layout)

            # Process Tab (unchanged logic, just reparenting)
            process_tab = QWidget()
            process_tab.setObjectName("tab_process_manager")
            process_layout = QVBoxLayout(process_tab)
            process_layout.setContentsMargins(6, 6, 6, 6)
            process_layout.setSpacing(6)
            for w in (getattr(self.ui, "search_box", None), getattr(self.ui, "result", None)):
                if w:
                    w.setParent(process_tab)
                    process_layout.addWidget(w)

            tab_widget.addTab(monitor_tab, self.tr("远程监控"))
            tab_widget.addTab(process_tab, self.tr("进程管理"))

            # Default select Remote Monitor tab
            tab_widget.setCurrentWidget(monitor_tab)

            # Hide original middle area
            middle = getattr(self.ui, "gridLayoutWidget_2", None)
            if middle: middle.setVisible(False)

            # Adjust splitters
            splitter = getattr(self.ui, "splitter_255", None)
            if splitter and splitter.count() >= 2:
                sizes = splitter.sizes()
                if sizes:
                    sizes[0] = 0
                    sizes[1] = max(1, sizes[1])
                    splitter.setSizes(sizes)

            main_splitter = getattr(self.ui, "splitter", None)
            if main_splitter and main_splitter.count() >= 2:
                sizes = main_splitter.sizes()
                if sizes and sizes[1] > 180:  # Compact height
                    sizes[0] = sizes[0] + (sizes[1] - 180)
                    sizes[1] = 180
                    main_splitter.setSizes(sizes)

        except Exception as e:
            print(f"Error in UI setup: {e}")

    def on_NAT_traversal(self):
        device = self.ui.comboBox.currentText()
        server_prot = self.ui.lineEdit_3.text()
        ant_type = self.ui.comboBox_3.currentText()
        local_port = self.ui.lineEdit_2.text()
        token = self.ui.lineEdit.text()

        with open(get_config_path('config.dat'), 'rb') as c:
            conf = pickle.loads(c.read())[device]
            c.close()

        username, password, host, key_type, key_file = '', '', '', '', ''

        if len(conf) == 3:
            username, password, host = conf[0], conf[1], conf[2]
        else:
            username, password, host, key_type, key_file = conf[0], conf[1], conf[2], conf[3], conf[4]

        # 显示进度对话框
        self._frp_progress = QProgressDialog(
            self.tr("正在连接服务器...") if not self.NAT else self.tr("正在停止服务..."),
            None, 0, 0, self
        )
        self._frp_progress.setWindowTitle(self.tr("内网穿透"))
        self._frp_progress.setWindowModality(Qt.WindowModal)
        self._frp_progress.setMinimumDuration(0)
        self._frp_progress.setCancelButton(None)
        self._frp_progress.setMinimumWidth(300)
        self._frp_progress.show()
        QApplication.processEvents()

        # 保存参数供后续使用
        self._frp_params = {
            'host': host,
            'username': username,
            'password': password,
            'key_type': key_type,
            'key_file': key_file,
            'token': token,
            'ant_type': ant_type,
            'local_port': local_port,
            'server_prot': server_prot,
        }

        # 启动后台线程处理连接和服务
        self._frp_connect_thread = FRPConnectThread(
            self._frp_params,
            self.NAT,  # is_stop
            get_frp_manager()
        )
        self._frp_connect_thread.status_updated.connect(self._on_frp_status_updated)
        self._frp_connect_thread.progress_updated.connect(self._on_frp_progress_updated)
        self._frp_connect_thread.finished_signal.connect(self._on_frp_connect_finished)
        self._frp_connect_thread.start()

    def _on_frp_progress_updated(self, percent):
        if hasattr(self, '_frp_progress') and self._frp_progress:
            self._frp_progress.setValue(percent)

    def _on_frp_status_updated(self, msg):
        if hasattr(self, '_frp_progress') and self._frp_progress:
            self._frp_progress.setLabelText(msg)

    def _on_frp_connect_finished(self, success, error_msg, is_start):
        """FRP 连接线程完成回调"""
        if hasattr(self, '_frp_progress') and self._frp_progress:
            self._frp_progress.close()
            self._frp_progress = None

        if not success:
            QMessageBox.warning(self, self.tr("错误"), error_msg)
            return

        if is_start:
            # 启动成功
            icon1 = QIcon()
            icon1.addFile(u":off.png", QSize(), QIcon.Mode.Normal, QIcon.State.Off)
            self.ui.pushButton.setIcon(icon1)
            self.NAT = True
            self.NAT_lod()
            QMessageBox.information(self, self.tr("完成"), self.tr("FRP 内网穿透已成功启动！"))
        else:
            # 停止成功
            icon1 = QIcon()
            icon1.addFile(u":open.png", QSize(), QIcon.Mode.Normal, QIcon.State.Off)
            self.ui.pushButton.setIcon(icon1)
            self.NAT = False
            self.NAT_lod()

    # 刷新内网穿透页面
    def NAT_lod(self):
        with open(abspath('frpc.toml'), 'r') as file:
            config = toml.load(file)
        if 'auth' in config:
            auth_token = config['auth']['token']
            self.ui.comboBox.setCurrentText(config['serverAddr'])
            self.ui.lineEdit.setText(auth_token)
            proxies = config['proxies']
            for proxy in proxies:
                self.ui.comboBox_3.setCurrentText(proxy['type'].upper())
                self.ui.lineEdit_2.setText(str(proxy['localPort']))
                if 'remotePort' in proxy:
                    self.ui.lineEdit_3.setText(str(proxy['remotePort']))
                break

    # 删除标签页
    def _delete_tab(self):  # 删除标签页
        current_index = self.ui.ShellTab.currentIndex()
        current_index1 = self.ui.ShellTab.tabText(current_index)
        if current_index1 != self.tr("首页"):
            # 1. 获取并关闭终端组件
            shell = self.get_text_browser_from_tab(current_index)
            if shell:
                try:
                    shell.close()
                    # 关键：处理挂起的事件，确保closeEvent被完整执行，进程被清理
                    QApplication.processEvents()
                except Exception as e:
                    util.logger.error(f"Failed to delete tab: {e}")
                    pass

            # 2. 获取 Widget 引用
            widget = self.ui.ShellTab.widget(current_index)

            # 3. 移除标签页
            self.ui.ShellTab.removeTab(current_index)

            # 4. 显式销毁 Widget
            if widget:
                widget.deleteLater()

    # 根据标签页名字删除标签页
    def _remove_tab_by_name(self, name):
        for i in range(self.ui.ShellTab.count()):
            if self.ui.ShellTab.tabText(i) == name:
                # 1. 获取并关闭终端组件
                shell = self.get_text_browser_from_tab(i)
                if shell:
                    try:
                        shell.close()
                        QApplication.processEvents()
                    except Exception as e:
                        util.logger.error(f"Failed to delete tab: {e}")
                        pass

                # 2. 获取 Widget 引用
                widget = self.ui.ShellTab.widget(i)

                # 3. 移除标签页
                self.ui.ShellTab.removeTab(i)

                # 4. 显式销毁 Widget
                if widget:
                    widget.deleteLater()
                break

    # 增加标签页 - 修改为支持 QTermWidget
    def add_new_tab(self, name=None):
        if name is None:
            focus = self.ui.treeWidget.currentIndex().row()
            if focus != -1:
                name = self.ui.treeWidget.topLevelItem(focus).text(0)
            else:
                return -1, None

        self.tab = QWidget()
        self.tab.setObjectName("tab")

        self.verticalLayout_index = QVBoxLayout(self.tab)
        self.verticalLayout_index.setSpacing(0)
        self.verticalLayout_index.setObjectName(u"verticalLayout_index")
        self.verticalLayout_index.setContentsMargins(0, 0, 0, 0)

        self.verticalLayout_shell = QVBoxLayout()
        self.verticalLayout_shell.setObjectName(u"verticalLayout_shell")

        # 使用自定义的SSHQTermWidget，提供右键菜单支持
        self.Shell = SSHQTermWidget(self.tab)

        self.Shell.setObjectName(u"Shell")

        # 🔧 修复：使用addWidget并设置拉伸因子确保完全填充
        self.verticalLayout_shell.addWidget(self.Shell, 0)  # 拉伸因子1
        self.verticalLayout_index.addLayout(self.verticalLayout_shell, 0)  # 拉伸因子1

        tab_name = self.generate_unique_tab_name(name)
        tab_index = self.ui.ShellTab.addTab(self.tab, tab_name)
        self.ui.ShellTab.setCurrentIndex(tab_index)

        if tab_index > 0:
            tab_bar = self.ui.ShellTab.tabBar()
            close_button = TabCloseButton(self, tab_bar=tab_bar)
            close_button.clicked.connect(lambda: self.off(tab_index, tab_name))
            tab_bar.setTabButton(tab_index, QTabBar.LeftSide, close_button)
        else:
            self.ui.ShellTab.tabBar().setTabButton(tab_index, QTabBar.LeftSide, None)

        return tab_index, self.Shell

    # 生成标签名
    def generate_unique_tab_name(self, base_name):
        existing_names = [self.ui.ShellTab.tabText(i) for i in range(self.ui.ShellTab.count())]
        if base_name not in existing_names:
            return base_name

        # 如果名字相同，添加编号
        counter = 1
        new_name = f"{base_name} ({counter})"
        while new_name in existing_names:
            counter += 1
            new_name = f"{base_name} ({counter})"
        return new_name

    # 通过标签名获取标签页的 tabWhatsThis 属性
    def get_tab_whats_this_by_name(self, name):
        for i in range(self.ui.ShellTab.count()):
            if self.ui.ShellTab.tabText(i) == name:
                return self.ui.ShellTab.tabWhatsThis(i)
        return None

    def get_text_browser_from_tab(self, index):
        tab = self.ui.ShellTab.widget(index)
        if tab:
            # 先查找自定义的 SSHQTermWidget
            ssh_qtermwidget_instance = tab.findChild(SSHQTermWidget, "Shell")
            if ssh_qtermwidget_instance:
                return ssh_qtermwidget_instance

            # 再查找原始的 QTermWidget（备用）
            qtermwidget_instance = tab.findChild(QTermWidget, "Shell")
            if qtermwidget_instance:
                return qtermwidget_instance
        return None

    # 监听标签页切换
    def shell_tab_current_changed(self, index):
        current_index = self.ui.ShellTab.currentIndex()

        # 尝试恢复主题 (修复切换Tab主题丢失问题)
        try:
            terminal = self.get_text_browser_from_tab(current_index)
            if terminal and hasattr(terminal, 'current_theme_name'):
                terminal.setColorScheme(terminal.current_theme_name)
            elif terminal:
                # 如果没有记录主题，默认设置 Ubuntu
                terminal.setColorScheme("Ubuntu")
        except Exception as e:
            util.logger.error(f"Failed to changed shell tab: {e}")
            pass

        # 切换标签页时，先重置当前显示的连接ID，确保 refreshDirs 能强制刷新UI
        self.current_displayed_connection_id = None

        if self.ssh_clients:
            current_text = self.ui.ShellTab.tabText(index)
            this = self.ui.ShellTab.tabWhatsThis(current_index)
            if this and this in self.ssh_clients:
                ssh_conn = self.ssh_clients[this]
                if current_text == self.tr("首页"):
                    if ssh_conn:
                        ssh_conn.close_sig = 0
                    self.isConnected = False
                    self.ui.treeWidget.setColumnCount(1)
                    self.ui.treeWidget.setHeaderLabels([self.tr("设备列表")])
                    self.remove_last_line_edit()
                    self.ui.treeWidget.clear()
                    self.refreshConf()
                else:
                    if self.ssh_clients:
                        ssh_conn.close_sig = 1
                        self.isConnected = True
                        self.refreshDirs()
                        self.processInitUI()
            else:
                if current_text == self.tr("首页"):
                    self.isConnected = False
                    self.ui.treeWidget.setColumnCount(1)
                    self.ui.treeWidget.setHeaderLabels([self.tr("设备列表")])
                    self.remove_last_line_edit()
                    self.ui.treeWidget.clear()
                    self.refreshConf()

    def zoom_in(self):
        """增大字体 - 支持 QTermWidget"""
        current_index = self.ui.ShellTab.currentIndex()
        shell = self.get_text_browser_from_tab(current_index)
        if shell:
            # QTermWidget 字体设置
            if hasattr(shell, 'getTerminalFont'):
                font = shell.getTerminalFont()
            else:
                font = QFont("Monospace", util.THEME.get('font_size', 14))

            size = font.pointSize()
            if size < 28:  # 设置最大字体大小限制
                font.setPointSize(size + 1)
                shell.setTerminalFont(font)
                util.THEME['font_size'] = size + 1
                print(f"QTermWidget 字体增大到: {size + 1}")

    def zoom_out(self):
        """减小字体 - 支持 QTermWidget"""
        current_index = self.ui.ShellTab.currentIndex()
        shell = self.get_text_browser_from_tab(current_index)
        if shell:
            # QTermWidget 字体设置
            if hasattr(shell, 'getTerminalFont'):
                font = shell.getTerminalFont()
            else:
                font = QFont("Monospace", util.THEME.get('font_size', 14))

            size = font.pointSize()
            if size > 8:  # 设置最小字体大小限制
                font.setPointSize(size - 1)
                shell.setTerminalFont(font)
                util.THEME['font_size'] = size - 1
                print(f"QTermWidget 字体减小到: {size - 1}")

    def index_pwd(self):
        if platform.system() == 'Darwin':
            pass
        else:
            self.ui.label_7.setText(self.tr("添加配置 Shift+Ctrl+A"))
            self.ui.label_9.setText(self.tr("添加隧道 Shift+Ctrl+S"))
            self.ui.label_11.setText(self.tr("帮助 Shift+Ctrl+H"))
            self.ui.label_12.setText(self.tr("关于 Shift+Ctrl+B"))
            self.ui.label_13.setText(self.tr("查找命令行 Shift+Ctrl+C"))
            self.ui.label_14.setText(self.tr("导入配置 Shift+Ctrl+I"))
            self.ui.label_15.setText(self.tr("导出配置 Shift+Ctrl+E"))

    # 进程列表初始化
    def processInitUI(self):
        # 创建表格部件
        self.ui.result.setColumnCount(6)
        # 展示表头标签
        self.ui.result.horizontalHeader().setVisible(True)
        self.ui.result.setHorizontalHeaderLabels(
            ["PID", self.tr("用户"), self.tr("内存"), "CPU", self.tr("地址"), self.tr("命令行")])
        header = self.ui.result.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.Stretch)
        # 添加右键菜单
        self.ui.result.setContextMenuPolicy(Qt.CustomContextMenu)
        self.ui.result.customContextMenuRequested.connect(self.showContextMenu)

        # 搜索
        self.ui.search_box.textChanged.connect(self.apply_filter)
        self.update_process_list()

    # 进程管理开始
    def showContextMenu(self, position):
        context_menu = QMenu()
        refresh_action = QAction(self.tr("刷新进程列表"), self)
        refresh_action.triggered.connect(self.update_process_list)
        context_menu.addAction(refresh_action)

        # 如果已选择进程，添加终止进程选项
        if len(self.ui.result.selectedItems()) > 0:
            kill_action = QAction(self.tr("终止进程"), self)
            kill_action.triggered.connect(self.kill_selected_process)
            context_menu.addAction(kill_action)

        context_menu.exec_(self.ui.result.viewport().mapToGlobal(position))

    def update_process_list(self):
        """更新进程列表 - 异步优化版"""
        ssh_conn = self.ssh()
        if not ssh_conn: return

        # 1. 使用缓存立即显示
        if hasattr(ssh_conn, 'cached_processes'):
            self.all_processes = ssh_conn.cached_processes
        else:
            self.all_processes = []

        # 更新UI显示 (使用缓存或空列表)
        self.apply_filter(self.ui.search_box.text())

        # 2. 后台线程获取最新数据
        # 检查线程是否存在并运行
        if not hasattr(ssh_conn, 'process_thread') or not ssh_conn.process_thread.is_alive():
            ssh_conn.process_thread = threading.Thread(target=self.update_process_list_thread, args=(ssh_conn,),
                                                       daemon=True)
            ssh_conn.process_thread.start()

    def update_process_list_thread(self, ssh_conn):
        try:
            if self.is_closing or not ssh_conn or not ssh_conn.is_connected():
                return
            processes = self.get_filtered_process_list(ssh_conn)
            if self.is_closing:
                return
            try:
                self.update_process_list_signal.emit(ssh_conn.id, processes)
            except RuntimeError:
                return
        except Exception as e:
            if "Signal source has been deleted" not in str(e):
                util.logger.error(f"Failed to update process list: {e}")
            pass

    @Slot(str, list)
    def handle_process_list_updated(self, conn_id, processes):
        """处理进程列表更新信号"""
        # 更新缓存
        if conn_id in self.ssh_clients:
            self.ssh_clients[conn_id].cached_processes = processes

        # 检查是否是当前显示的Tab
        current_index = self.ui.ShellTab.currentIndex()
        this = self.ui.ShellTab.tabWhatsThis(current_index)
        if this != conn_id: return

        self.all_processes = processes
        # 重新应用过滤并显示
        self.apply_filter(self.ui.search_box.text())

    def display_processes(self):
        # 设置列头
        headers = ["PID", self.tr("用户"), self.tr("内存"), "CPU", self.tr("端口"), self.tr("命令行")]
        if self.ui.result.columnCount() != len(headers):
            self.ui.result.setColumnCount(len(headers))

        self.ui.result.setHorizontalHeaderLabels(headers)
        self.ui.result.horizontalHeader().setVisible(True)

        self.ui.result.setRowCount(0)
        for row_num, process in enumerate(self.filtered_processes):
            self.ui.result.insertRow(row_num)
            self.ui.result.setItem(row_num, 0, QTableWidgetItem(str(process['pid'])))
            self.ui.result.setItem(row_num, 1, QTableWidgetItem(process['user']))
            self.ui.result.setItem(row_num, 2, QTableWidgetItem(str(process['memory'])))
            self.ui.result.setItem(row_num, 3, QTableWidgetItem(str(process['cpu'])))
            self.ui.result.setItem(row_num, 4, QTableWidgetItem(process.get('port', '')))
            self.ui.result.setItem(row_num, 5, QTableWidgetItem(process['command']))
            self.ui.result.item(row_num, 0).setData(Qt.UserRole, str(process['pid']))

    @Slot(str)
    def apply_filter(self, text):
        self.search_text = text.lower()
        self.filtered_processes = [p for p in self.all_processes if any(text.lower() in v.lower() for v in p.values())]
        self.display_processes()

    def get_filtered_process_list(self, ssh_conn=None):
        try:
            if ssh_conn is None:
                ssh_conn = self.ssh()
                if not ssh_conn: return []
            if not ssh_conn.is_connected():
                return []

            # 1. 获取进程列表（安全包装）
            ps_text = ssh_conn.exec(cmd="ps aux --no-headers", pty=False) or ""
            ps_output = ps_text.splitlines()

            # 2. 获取端口信息 (使用 ss 命令)
            # -t: tcp, -u: udp, -l: listening, -n: numeric, -p: processes, -e: extended
            # 2>/dev/null 忽略错误输出
            ss_text = ssh_conn.exec(cmd="ss -tulnpe 2>/dev/null", pty=False) or ""
            ss_output = ss_text.splitlines()

            # 解析端口信息
            pid_ports = defaultdict(list)
            for line in ss_output:
                # 跳过标题行
                if line.startswith('Netid') or line.startswith('State'):
                    continue

                try:
                    fields = line.strip().split()
                    if len(fields) < 5: continue

                    # 获取本地地址:端口
                    local_addr = fields[4]
                    if ':' in local_addr:
                        port = local_addr.split(':')[-1]
                    else:
                        continue

                    # 获取 PID
                    # 格式示例: users:(("sshd",pid=123,fd=3))
                    if 'users:' in line:
                        # 使用正则提取所有 pid
                        pids = re.findall(r'pid=(\d+)', line)
                        for pid in pids:
                            if port not in pid_ports[pid]:
                                pid_ports[pid].append(port)
                except Exception:
                    pass

            # 解析进程列表
            process_list = []
            system_users = []
            for line in ps_output:
                try:
                    fields = line.strip().split()
                    if len(fields) < 11: continue

                    user = fields[0]
                    # 这里原本的逻辑似乎想过滤系统用户，但 system_users 列表是空的且只是被添加到列表中
                    # 并没有实际的过滤逻辑，所以保留原样
                    if user not in system_users:
                        pid = fields[1]
                        memory = fields[3]
                        cpu = fields[2]
                        # name = fields[-1] if len(fields[-1]) <= 15 else fields[-1][:12] + "..." # 原代码

                        # 获取端口
                        ports = pid_ports.get(pid, [])
                        port_str = ",".join(ports) if ports else ""

                        command = " ".join(fields[10:])

                        process_list.append({
                            'pid': pid,
                            'user': user,
                            'memory': memory,
                            'cpu': cpu,
                            'port': port_str,  # 替换 name 为 port
                            'command': command
                        })
                except Exception:
                    pass

            return process_list

        except Exception as e:
            util.logger.error(f"Failed to connect or retrieve process list: {e}")
            return []

    def kill_selected_process(self):
        if not self.ssh():
            self.warning("警告", "SSH客户端未设置，请先设置SSH客户端")
            return

        selected_rows = set(item.row() for item in self.ui.result.selectedItems())

        if not selected_rows:
            return

        pids_to_kill = []
        # 获取所选行的PID
        for row in selected_rows:
            pid_item = self.ui.result.item(row, 0)
            if pid_item:
                pids_to_kill.append(pid_item.text())

        if not pids_to_kill:
            return

        pid_str = ", ".join(pids_to_kill)

        reply = QMessageBox.question(
            self,
            self.tr("确认终止"),
            self.tr(f"确认要终止选中的 {len(pids_to_kill)} 个进程吗?\nPID: {pid_str}"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            # 批量执行终止命令
            try:
                # 使用 kill -15 (SIGTERM) 优雅终止，如果需要强制可以使用 kill -9
                # 使用空格分隔多个 PID
                pids_args = " ".join(pids_to_kill)
                command = f"kill -15 {pids_args}"

                # 使用独立的 QThread 处理终止任务，避免阻塞 UI 且代码更清晰
                self.kill_thread = KillProcessThread(self.ssh(), command, pids_args, pid_str)
                self.kill_thread.success_sig.connect(self.success)
                self.kill_thread.warning_sig.connect(self.warning)
                self.kill_thread.update_sig.connect(lambda: self.update_process_list_signal.emit(self.ssh().id, []))
                self.kill_thread.start()

            except Exception as e:
                self.warning("错误", f"无法启动终止任务: {e}")

    def showEvent(self, event):
        self.center()
        super().showEvent(event)

    def center(self):
        # 获取窗口的矩形框架
        qr = self.frameGeometry()
        # 获取屏幕的中心点
        screen = QGuiApplication.primaryScreen()
        screen_geometry = screen.availableGeometry()
        center_point = screen_geometry.center()
        # 将窗口的中心点设置为屏幕的中心点
        qr.moveCenter(center_point)
        # 将窗口移动到新的位置
        self.move(qr.topLeft())

    # 隧道刷新
    def tunnel_refresh(self):
        # self.data = util.read_json(abspath(CONF_FILE))
        file_path = get_config_path('tunnel.json')
        # 读取 JSON 文件内容
        self.data = util.read_json(file_path)

        self.tunnels = []

        # 展示ssh隧道列表
        if self.data:
            i = 0
            for i, name in enumerate(sorted(self.data.keys())):
                tunnel = Tunnel(name, self.data[name], self)
                self.tunnels.append(tunnel)
                self.ui.gridLayout_tunnel_tabs.addWidget(tunnel, i, 0)
            self.kill_button = QPushButton(self.tr("关闭所有隧道"))
            self.kill_button.setIcon(QIcon(ICONS.KILL_SSH))
            self.kill_button.setFocusPolicy(Qt.NoFocus)
            self.kill_button.clicked.connect(self.do_killall_ssh)
            self.ui.gridLayout_kill_all.addWidget(self.kill_button, i + 1, 0)

    # NAT穿透
    def nat_traversal(self):
        icon_ssh = QIcon()
        icon_ssh.addFile(u":icons8-ssh-48.png", QSize(), QIcon.Mode.Selected, QIcon.State.On)
        with open(get_config_path('config.dat'), 'rb') as c:
            dic = pickle.loads(c.read())
            c.close()
        for k in dic.keys():
            self.ui.comboBox.addItem(icon_ssh, k)

    def menuBarController(self):
        # 创建菜单栏
        menubar = self.menuBar()

        file_menu = menubar.addMenu(self.tr("文件"))
        # 创建"设置"菜单
        setting_menu = menubar.addMenu(self.tr("设置"))
        # 创建"帮助"菜单
        help_menu = menubar.addMenu(self.tr("帮助"))

        # 创建"新建"动作
        new_action = QAction(QIcon(":icons8-ssh-48.png"), self.tr("&新增配置"), self)
        new_action.setIconVisibleInMenu(True)
        new_action.setShortcut("Shift+Ctrl+A")
        new_action.setStatusTip(self.tr("添加配置"))
        file_menu.addAction(new_action)
        new_action.triggered.connect(self.showAddConfig)

        new_ssh_tunnel_action = QAction(QIcon(ICONS.TUNNEL), self.tr("&新增SSH隧道"), self)
        new_ssh_tunnel_action.setIconVisibleInMenu(True)
        new_ssh_tunnel_action.setShortcut("Shift+Ctrl+S")
        new_ssh_tunnel_action.setStatusTip(self.tr("新增SSH隧道"))
        file_menu.addAction(new_ssh_tunnel_action)
        new_ssh_tunnel_action.triggered.connect(self.showAddSshTunnel)

        export_configuration = QAction(QIcon(':export.png'), self.tr("&导出设备配置"), self)
        export_configuration.setIconVisibleInMenu(True)
        export_configuration.setShortcut("Shift+Ctrl+E")
        export_configuration.setStatusTip(self.tr("导出设备配置"))
        file_menu.addAction(export_configuration)
        export_configuration.triggered.connect(self.export_configuration)

        import_configuration = QAction(QIcon(':import.png'), self.tr("&导入设备配置"), self)
        import_configuration.setIconVisibleInMenu(True)
        import_configuration.setShortcut("Shift+Ctrl+I")
        import_configuration.setStatusTip(self.tr("导入设备配置"))
        file_menu.addAction(import_configuration)
        import_configuration.triggered.connect(self.import_configuration)

        # 创建"主题设置"动作
        theme_action = QAction(QIcon(":undo.png"), self.tr("&主题设置"), self)
        theme_action.setShortcut("Shift+Ctrl+T")
        theme_action.setStatusTip(self.tr("设置主题"))
        setting_menu.addAction(theme_action)
        theme_action.triggered.connect(self.theme)

        ai_setting_action = QAction(QIcon(":settings.png"), self.tr("&AI 设置"), self)
        ai_setting_action.setStatusTip(self.tr("配置 GLM-4.7 AI 能力"))
        setting_menu.addAction(ai_setting_action)
        ai_setting_action.triggered.connect(self.show_ai_settings)

        # 语言设置
        language_action = QAction(QIcon(":settings.png"), self.tr("&语言设置"), self)
        language_action.setShortcut("Shift+Ctrl+L")
        language_action.setStatusTip(self.tr("设置应用程序语言"))
        setting_menu.addAction(language_action)
        language_action.triggered.connect(self.show_language_settings)
        #
        # 创建"重做"动作
        # docker_action = QAction(QIcon(":redo.png"), "&容器编排", self)
        # docker_action.setShortcut("Shift+Ctrl+D")
        # docker_action.setStatusTip(self.tr("容器编排"))
        # setting_menu.addAction(docker_action)
        # docker_action.triggered.connect(self.container_orchestration)

        # 创建"关于"动作
        about_action = QAction(self.tr("&关于"), self)
        about_action.setIconVisibleInMenu(True)
        about_action.setMenuRole(QAction.MenuRole.NoRole)  # 防止 macOS 自动移动到应用程序菜单
        about_action.setShortcut("Shift+Ctrl+B")
        about_action.setStatusTip(self.tr("cubeShell 有关信息"))
        help_menu.addAction(about_action)
        about_action.triggered.connect(self.about)

        linux_action = QAction(self.tr("&Linux常用命令"), self)
        linux_action.setIconVisibleInMenu(True)
        linux_action.setShortcut("Shift+Ctrl+P")
        linux_action.setStatusTip(self.tr("最常用的Linux命令查找"))
        help_menu.addAction(linux_action)
        linux_action.triggered.connect(self.linux)

        help_action = QAction(self.tr("&帮助"), self)
        help_action.setIconVisibleInMenu(True)
        help_action.setShortcut("Shift+Ctrl+H")
        help_action.setStatusTip(self.tr("cubeShell使用说明"))
        help_menu.addAction(help_action)
        help_action.triggered.connect(self.help)

    # 关于
    def about(self):
        self.about_dialog = about.AboutDialog()
        self.about_dialog.show()

    def theme(self):
        self.theme_dialog = theme.MainWindow(self)
        self.theme_dialog.show()

    def show_ai_settings(self):
        dialog = AISettingsDialog(self)
        dialog.exec()

    def show_language_settings(self):
        """显示语言设置对话框"""
        dialog = LanguageSettingsDialog(self)
        if dialog.exec() == QDialog.Accepted:
            selected_lang = dialog.get_selected_language()
            if selected_lang:
                # 保存语言设置到配置文件
                try:
                    theme_file = abspath("theme.json")
                    data = util.read_json(theme_file)
                    data["language"] = selected_lang
                    util.write_json(theme_file, data)
                    util.THEME = data

                    # 提示用户重启应用
                    QMessageBox.information(
                        self,
                        self.tr("语言设置"),
                        self.tr("语言设置已更改，请重启应用程序以生效。")
                    )
                except Exception as e:
                    util.logger.error(f"保存语言设置失败: {e}")
                    QMessageBox.warning(self, self.tr("错误"), f"保存语言设置失败: {e}")

    # linux 常用命令
    def linux(self):
        self.tree_search_app = TreeSearchApp()

        # 读取 JSON 数据并填充模型
        self.tree_search_app.load_data_from_json(abspath('linux_commands.json'))
        self.tree_search_app.show()

    # 帮助
    def help(self):
        url = QUrl(
            "https://mp.weixin.qq.com/s?__biz=MzA5ODQ5ODgxOQ==&mid=2247485218&idx=1&sn"
            "=f7774a9a56c1f1ae6c73d6bf6460c155&chksm"
            "=9091e74ea7e66e5816daad88313c8c559eb1d60f8da8b1d38268008ed7cff9e89225b8fe32fd&token=1771342232&lang"
            "=zh_CN#rd")
        QDesktopServices.openUrl(url)

    def eventFilter(self, source, event):
        """
        重写事件过滤器：
        treeWidget 处理鼠标左键长按拖动和鼠标左键单击
        :param source: 作用对象，这里为treeWidget
        :param event: 事件，这里为鼠标按钮按键事件
        :return:
        """
        if source is self.ui.treeWidget.viewport():
            if event.type() == QEvent.MouseButtonPress:
                if event.button() == Qt.LeftButton:
                    self.start_pos = event.position().toPoint()
                    # 记录左键按下时间
                    self.left_click_time = event.timestamp()
                    return False  # 允许左键单击和双击事件继续处理
            elif event.type() == QEvent.MouseMove:
                if self.is_left_selecting:
                    self.selection_rect.setBottomRight(event.position().toPoint())
                    self.selectItemsInRect(self.selection_rect)
                    return True
            elif event.type() == QEvent.MouseButtonRelease:
                if event.button() == Qt.LeftButton:
                    if event.timestamp() - self.left_click_time < 200:  # 判断是否为单击
                        self.is_left_selecting = False
                        item = self.ui.treeWidget.itemAt(event.position().toPoint())
                        if item:
                            self.ui.treeWidget.clearSelection()
                            item.setSelected(True)
                        return False  # 允许左键单击事件继续处理
                    self.is_left_selecting = False
                    return True
        if source == self.ui.ShellTab.tabBar():
            if event.type() == QEvent.MouseButtonPress:
                self.originalIndex = self.ui.ShellTab.tabBar().tabAt(event.position().toPoint())
                if self.ui.ShellTab.tabText(self.originalIndex) == self.tr("首页"):
                    self.homeTabPressed = True
                else:
                    self.homeTabPressed = False
            elif event.type() == QEvent.MouseMove:
                if self.homeTabPressed:
                    return True  # 忽略拖动事件
            elif event.type() == QEvent.MouseButtonRelease:
                target_index = self.ui.ShellTab.tabBar().tabAt(event.position().toPoint())
                if target_index == 0 and self.originalIndex != 0:
                    # 恢复原始位置
                    self.ui.ShellTab.tabBar().moveTab(self.ui.ShellTab.currentIndex(), self.originalIndex)
                self.homeTabPressed = False
        if event.type() == QEvent.KeyPress:
            print("测试以下")
            return True

        return super().eventFilter(source, event)

    # 在矩形内选择项目
    def selectItemsInRect(self, rect):
        # 清除所有选择
        for i in range(self.ui.treeWidget.topLevelItemCount()):
            item = self.ui.treeWidget.topLevelItem(i)
            item.setSelected(False)

        # 选择矩形内的项目
        rect = self.ui.treeWidget.visualRect(self.ui.treeWidget.indexAt(rect.topLeft()))
        rect = rect.united(self.ui.treeWidget.visualRect(self.ui.treeWidget.indexAt(rect.bottomRight())))
        for i in range(self.ui.treeWidget.topLevelItemCount()):
            item = self.ui.treeWidget.topLevelItem(i)
            if self.ui.treeWidget.visualItemRect(item).intersects(rect):
                item.setSelected(True)

    # 连接服务器
    def run(self, name=None, terminal=None) -> int:
        if name is None:
            focus = self.ui.treeWidget.currentIndex().row()
            if focus != -1:
                name = self.ui.treeWidget.topLevelItem(focus).text(0)
            else:
                self.alarm(self.tr('请选择一台设备！'))
                return 0

        if str(name) == self.tr("本机终端"):
            # 本机模式：
            # - 不走 SSH/Paramiko；只启动一个本地终端 (QTermWidget)
            # - 同时构造一个 LocalClient 后端对象，复用现有“文件树 + SFTP 操作”代码路径
            # - LocalClient 只实现项目里会用到的最小接口（open_sftp / stat / file / mkdir...）
            try:
                if terminal is None:
                    current_index = self.ui.ShellTab.currentIndex()
                    terminal = self.get_text_browser_from_tab(current_index)
                return self._connect_local_with_qtermwidget(terminal, str(name))
            except Exception as e:
                util.logger.error(f"本机终端启动失败: {e}")
                return 0

        with open(get_config_path('config.dat'), 'rb') as c:
            conf = pickle.loads(c.read())[name]
            c.close()

        username, password, host, key_type, key_file = '', '', '', '', ''

        if len(conf) == 3:
            username, password, host = conf[0], conf[1], conf[2]
        else:
            username, password, host, key_type, key_file = conf[0], conf[1], conf[2], conf[3], conf[4]

        try:
            if terminal is None:
                current_index = self.ui.ShellTab.currentIndex()
                terminal = self.get_text_browser_from_tab(current_index)

            # 🔧 修复：使用记录的主题，而不是硬编码
            if hasattr(terminal, 'current_theme_name'):
                terminal.setColorScheme(terminal.current_theme_name)
            else:
                terminal.setColorScheme("Ubuntu")

            # 🔧 修正：分离主机地址和端口
            host_ip = host.split(':')[0]  # 纯IP地址
            host_port = int(host.split(':')[1])  # 端口号
            return self._connect_with_qtermwidget(host_ip, host_port, username, password, key_type,
                                                  key_file, terminal)

        except Exception as e:
            util.logger.error(str(e))
            if terminal and hasattr(terminal, "setPlaceholderText"):
                terminal.setPlaceholderText(str(e))
            return False

    def _connect_local_with_qtermwidget(self, terminal, label: str, start_dir: str = "") -> int:
        if not terminal:
            return 0

        # 本机默认工作目录：用户 Home 目录
        # - macOS/Linux: /Users/<user> 或 /home/<user>
        # - Windows: C:\\Users\\<user>
        # Path.home() 是跨平台的，额外做目录存在校验，避免异常环境返回不可用路径
        home_dir = str(Path.home())
        try:
            if not os.path.isdir(home_dir):
                home_dir = os.path.expanduser("~")
        except Exception:
            home_dir = os.path.expanduser("~")
        work_dir = home_dir
        if start_dir:
            try:
                if os.path.isdir(start_dir):
                    work_dir = start_dir
            except Exception:
                pass
        if hasattr(terminal, 'setWorkingDirectory'):
            terminal.setWorkingDirectory(work_dir)

        shell_program = ""
        shell_args = []
        sys_name = platform.system()
        if sys_name == "Windows":
            # Windows 下优先 pwsh (PowerShell 7)，其次 powershell (Windows PowerShell)，再退回 cmd
            shell_program = "powershell"
            try:
                if shutil.which("pwsh"):
                    shell_program = "pwsh"
                elif shutil.which("powershell"):
                    shell_program = "powershell"
                else:
                    shell_program = "cmd"
            except Exception:
                shell_program = "cmd"
        else:
            # macOS/Linux 下尽量使用用户默认 SHELL
            # 如果环境变量缺失，再按系统给一个合理默认值
            shell_program = os.environ.get("SHELL") or ("/bin/zsh" if sys_name == "Darwin" else "/bin/bash")
            if sys_name == "Darwin":
                base = os.path.basename(shell_program or "")
                if base in ("zsh", "bash"):
                    shell_args = ["-l"]

        terminal.setShellProgram(shell_program)
        terminal.setArgs(shell_args)
        terminal.startShellProgram()

        # 将本地后端对象注册进 ssh_clients：
        # - 复用 self.ssh() 取“当前 Tab 后端”的机制
        # - 复用 initSftp() / refreshDirs() 的目录刷新逻辑
        # - 通过 tabWhatsThis 绑定 tab 与后端连接 id
        current_index = self.ui.ShellTab.currentIndex()
        local_conn = LocalClient(pwd=work_dir, name=label)
        local_conn.Shell = terminal
        self.ui.ShellTab.setTabWhatsThis(current_index, local_conn.id)
        self.ssh_clients[local_conn.id] = local_conn
        self.current_displayed_connection_id = local_conn.id
        self.initSftpSignal.emit()
        try:
            self._release_connecting_state()
        except Exception:
            pass
        return terminal.getIsRunning()

    def _attach_ssh_auto_responder(self, terminal, password: str, timeout_ms: int = 5000) -> None:
        if not terminal or not password:
            return
        if not hasattr(terminal, "receivedData") or not hasattr(terminal, "sendText"):
            return

        state = {"done": False, "pw": False, "yes": False}
        buf = {"text": ""}

        def cleanup():
            try:
                terminal.receivedData.disconnect(on_chunk)
            except Exception:
                pass

        def on_chunk(chunk: str):
            if state["done"]:
                return
            try:
                buf["text"] = (buf["text"] + (chunk or ""))[-4096:]
                text = buf["text"].lower()
                if (not state["yes"]) and ("are you sure you want to continue connecting" in text):
                    state["yes"] = True
                    terminal.sendText("yes\n")
                    return
                if (not state["pw"]) and re.search(r"password[^\n]{0,80}:", text):
                    state["pw"] = True
                    state["done"] = True
                    cleanup()
                    terminal.sendText(password + "\n")
            except Exception:
                pass

        try:
            terminal.receivedData.connect(on_chunk)
            QTimer.singleShot(int(timeout_ms), cleanup)
        except Exception:
            pass

    def _connect_with_qtermwidget(self, host, port, username, password, key_type, key_file, terminal) -> int:
        """使用 QTermWidget 直接处理 SSH 连接"""
        try:
            util.logger.info(f"Connecting to {host}:{port} via QTermWidget...")

            # 设置终端程序为bash
            # terminal.setShellProgram("/bin/bash")

            # 设置工作目录
            if hasattr(terminal, 'setWorkingDirectory'):
                terminal.setWorkingDirectory(os.path.expanduser("~"))

            env = QProcessEnvironment.systemEnvironment()

            # # Fix PATH for macOS
            # current_path = env.value("PATH", "")
            # extra_paths = ["/usr/local/bin", "/opt/homebrew/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
            # new_path = current_path
            # for p in extra_paths:
            #     if p not in new_path:
            #         new_path += os.pathsep + p
            # env.insert("PATH", new_path)
            # print(f"Using PATH: {new_path}")

            # # 核心颜色设置
            # env.insert("TERM", "xterm-256color")
            # env.insert("COLORTERM", "truecolor")
            # env.insert("CLICOLOR", "1")
            # env.insert("CLICOLOR_FORCE", "1")  # 强制颜色输出

            # terminal.setEnvironment(env.toStringList())

            # 使用sshpass
            ssh_command = "ssh"
            ssh_args = [
                "-o", "ConnectTimeout=10",  # 连接超时设置
                "-o", "ServerAliveInterval=30",
                "-o", "ServerAliveCountMax=3",
                "-o", "TCPKeepAlive=yes",
                "-t"
            ]
            # 构建SSH命令
            if port != 22:
                ssh_args.extend(["-p", str(port)])
            if key_type and key_file:
                # 密钥认证：验证密钥文件并设置正确权限
                key_file_path = os.path.expanduser(key_file)  # 展开~路径
                if os.path.exists(key_file_path):
                    # 设置密钥文件权限为600
                    try:
                        os.chmod(key_file_path, 0o600)
                    except Exception as e:
                        util.logger.error(f"设置密钥权限失败: {e}")

                    ssh_args.extend(["-i", key_file_path])
            else:
                ssh_args.extend(["-o", "StrictHostKeyChecking=no",  # 跳过主机密钥检查
                                 "-o", "PreferredAuthentications=password",
                                 "-o", "PubkeyAuthentication=no",
                                 "-o", "UserKnownHostsFile=/dev/null"  # 不保存主机密钥文件
                                 ])

            ssh_args.append(f"{username}@{host}")
            terminal.setShellProgram(ssh_command)
            terminal.setArgs(ssh_args)
            if not key_type and not key_file and password:
                self._attach_ssh_auto_responder(terminal, password, timeout_ms=5000)

            terminal.startShellProgram()

            if hasattr(terminal, "setSuppressProgramBackgroundColors"):
                terminal.setSuppressProgramBackgroundColors(True)

            # 为了支持 SFTP 等功能，建立后台 SSH 连接
            util.logger.info("建立后台 SSH 连接用于 SFTP...")
            self._establish_background_ssh(host, port, username, password, key_type, key_file)

            return terminal.getIsRunning()

        except Exception as e2:
            util.logger.error(f"QTermWidget SSH 连接失败: {e2}")
            return False

    def _establish_background_ssh(self, host, port, username, password, key_type, key_file):
        """建立后台 SSH 连接用于 SFTP 等功能"""
        try:
            # SSHConnector 内部已封装了线程，这里直接调用即可，既简洁又非阻塞
            self.ssh_connector.connect_ssh(host, port, username, password, key_type, key_file)
        except Exception as e:
            util.logger.error(f"建立后台 SSH 连接失败: {e}")

    def on_ssh_connected(self, ssh_conn):
        """SSH连接成功回调 - 区分 QTermWidget 模式和传统模式"""
        # 由于现在是同步调用，一定在主线程，不需要 invokeMethod 检查

        current_index = self.ui.ShellTab.currentIndex()
        ssh_conn.Shell = self.Shell
        self.ui.ShellTab.setTabWhatsThis(current_index, ssh_conn.id)

        # 将连接实例存储到本地字典，替代 mux
        self.ssh_clients[ssh_conn.id] = ssh_conn

        # 修复：保存当前连接 ID，以便 refreshDirs 能通过安全检查
        self.current_displayed_connection_id = ssh_conn.id

        # 初始化 SFTP
        self.initSftpSignal.emit()
        # 释放连接锁
        self._release_connecting_state()

    @Slot(str, str)  # 将其标记为槽
    def warning(self, title, message):
        # 修复：确保在主线程中执行 UI 操作
        if QThread.currentThread() != QCoreApplication.instance().thread():
            QMetaObject.invokeMethod(self, "warning", Qt.QueuedConnection, Q_ARG(str, title), Q_ARG(str, message))
            return
        QMessageBox.warning(self, self.tr(title), self.tr(message))

    # 初始化sftp和控制面板
    def initSftp(self):
        ssh_conn = self.ssh()
        if not ssh_conn:
            return

        self.isConnected = True
        self.ui.discButton.setEnabled(True)
        self.ui.result.setEnabled(True)
        self.ui.theme.setEnabled(True)

        self.refreshDirs()
        if getattr(ssh_conn, "is_local", False):
            return

        self.processInitUI()

        if not hasattr(ssh_conn, 'flush_sys_info_thread') or not ssh_conn.flush_sys_info_thread.is_alive():
            ssh_conn.flush_sys_info_thread = threading.Thread(target=ssh_conn.get_datas, args=(ssh_conn,), daemon=True)
            ssh_conn.flush_sys_info_thread.start()
            self.flushSysInfo()

    def on_initSftpSignal(self):
        self.initSftp()

    # 后台获取信息，不打印至程序界面
    @Slot(str, bool)
    def getData2(self, cmd='', pty=False):
        try:
            ssh_conn = self.ssh()
            ack = ssh_conn.exec(cmd=cmd, pty=pty)
            # 发送成功信号
            self.finished.emit(cmd, ack)
            return ack
        except socket.timeout:
            self.error.emit(cmd, "Error: Connection or execution timeout.")
        except Exception as e:
            util.logger.error(f"Failed to get data: {e}")
            return 'error'

    #  操作docker 成功
    def on_ssh_docker_finished(self, cmd, output):
        print("")
        # self.refreshDokerInfo()
        # self.refresh_docker_common_containers()

    def on_tab_changed(self, index):
        """标签切换事件处理"""
        try:
            ssh_conn = self.ssh()
            if ssh_conn and getattr(ssh_conn, "is_local", False):
                return
        except Exception:
            return
        if index == 0:
            # self.handle_tab1()
            self.refreshDokerInfo()
        elif index == 1:
            self.refresh_docker_common_containers()
        elif index == 2:
            print("")

    def start_async_task(self, cmd):
        thread = threading.Thread(target=self.getData2, args=(cmd,))
        thread.start()

    def _set_connecting_ui(self, connecting: bool):
        try:
            self.ui.treeWidget.setEnabled(not connecting)
        except Exception:
            pass
        try:
            if connecting:
                QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
            else:
                QApplication.restoreOverrideCursor()
        except Exception:
            pass

    def _release_connecting_state(self):
        self.is_connecting_lock = False
        self._set_connecting_ui(False)

    # 选择文件夹
    def cd(self):
        if self.isConnected:
            ssh_conn = self.ssh()

            # 关键安全检查：
            # 如果当前显示的连接ID与实际操作的连接ID不一致（说明UI显示的是旧数据），则阻止操作
            if self.current_displayed_connection_id != ssh_conn.id:
                return

            focus = self.ui.treeWidget.currentIndex().row()
            if not getattr(ssh_conn, "_dir_tree_ready", False):
                return
            if not isinstance(getattr(self, "dir_tree_now", None), list):
                return
            if focus < 0 or focus >= len(self.dir_tree_now):
                return
            if focus != -1 and self.dir_tree_now[focus][0].startswith('d'):
                if getattr(ssh_conn, "is_local", False):
                    target = self.ui.treeWidget.topLevelItem(focus).text(0)
                    if target == "..":
                        ssh_conn.pwd = os.path.dirname(
                            os.path.abspath(os.path.expanduser(ssh_conn.pwd))) or ssh_conn.pwd
                    else:
                        ssh_conn.pwd = os.path.abspath(os.path.join(os.path.expanduser(ssh_conn.pwd), target))
                    self.refreshDirs()
                else:
                    ssh_conn.pwd = self.getData2(
                        'cd ' + ssh_conn.pwd + '/' + self.ui.treeWidget.topLevelItem(focus).text(0) +
                        ' && pwd')[:-1]
                    self.refreshDirs()
            else:
                self.editFile()
        elif not self.isConnected:
            # 防抖：如果正在连接中，忽略本次点击；快速点击节流500ms
            now_ms = int(time.time() * 1000)
            if self.is_connecting_lock:
                try:
                    self._connect_click_blocked_count = int(getattr(self, "_connect_click_blocked_count", 0) or 0) + 1
                except Exception:
                    self._connect_click_blocked_count = 1
                return
            if now_ms - getattr(self, "_last_connect_attempt_ts", 0) < 800:
                return

            # 获取选中的设备名称
            focus = self.ui.treeWidget.currentIndex().row()
            if focus != -1:
                name = self.ui.treeWidget.topLevelItem(focus).text(0)

                # 标记开始连接
                self.is_connecting_lock = True
                self._last_connect_attempt_ts = now_ms
                self._connect_click_blocked_count = 0
                self._set_connecting_ui(True)

                # 创建新 Tab 并立即启动连接
                try:
                    tab_index, terminal = self.add_new_tab(name)
                    if tab_index == -1:
                        self._release_connecting_state()
                        return
                    self.run(name, terminal)
                    try:
                        QTimer.singleShot(10000,
                                          lambda: self._release_connecting_state() if self.is_connecting_lock else None)
                    except Exception:
                        pass
                except Exception:
                    self._release_connecting_state()
                    raise

            else:
                return

    # 回车获取目录
    def on_return_pressed(self):
        # 获取布局中小部件的数量
        count = self.ui.gridLayout.count()
        # 获取最后一个小部件
        if count > 0:
            latest_widget = self.ui.gridLayout.itemAt(count - 1).widget()
            # 检查是否为 QLineEdit
            if isinstance(latest_widget, QLineEdit):
                ssh_conn = self.ssh()
                text = latest_widget.text()
                ssh_conn.pwd = text
                self.refreshDirs()

    # 断开服务器
    def _off(self, name):
        try:
            this = self.get_tab_whats_this_by_name(name)
            if this in self.ssh_clients:
                ssh_conn = self.ssh_clients[this]
                ssh_conn.term_data = b''
                ssh_conn.pwd = ''
                ssh_conn.close()
                del self.ssh_clients[this]
        except Exception as e:
            util.logger.error(f"Failed to off ssh client: {e}")
            pass

        self.isConnected = False
        self.ssh_username, self.ssh_password, self.ssh_ip, self.key_type, self.key_file = None, None, None, None, None
        self.ui.networkUpload.setText('')
        self.ui.networkDownload.setText('')
        self.ui.operatingSystem.setText('')
        self.ui.kernel.setText('')
        self.ui.kernelVersion.setText('')

        self.ui.treeWidget.setColumnCount(1)
        self.ui.treeWidget.setHeaderLabels([self.tr("设备列表")])
        self.remove_last_line_edit()

        self.ui.treeWidgetDocker.clear()
        self.ui.result.clear()
        # 隐藏顶部的列头
        self.ui.result.horizontalHeader().setVisible(False)
        self.ui.result.setRowCount(0)  # 设置行数为零

        util.clear_grid_layout(self.ui.gridLayout_7)

        self.ui.cpuRate.setValue(0)
        self.ui.diskRate.setValue(0)
        self.ui.memRate.setValue(0)

        self.refreshConf()

    # 断开服务器并删除tab
    def off(self, index, name):
        self._off(name)
        self._remove_tab_by_name(name)

    # 关闭当前连接
    def disc_off(self):
        current_index = self.ui.ShellTab.currentIndex()
        name = self.ui.ShellTab.tabText(current_index)
        if name != self.tr("首页"):
            self._off(name)
            self._remove_tab_by_name(name)

    def send(self, data):
        """发送数据到终端 - 支持 QTermWidget"""
        # 只要有任何活动的 SSH 连接（后台连接），或者处于连接状态，就允许发送
        # 注意：对于 QTermWidget，直接发送到组件即可，它会处理
        current_index = self.ui.ShellTab.currentIndex()
        terminal = self.get_text_browser_from_tab(current_index)

        if terminal:
            # QTermWidget 直接发送文本
            if isinstance(data, bytes):
                text = data.decode('utf-8', errors='ignore')
            else:
                text = str(data)
            terminal.sendText(text)

    def do_killall_ssh(self):
        for tunnel in self.tunnels:
            tunnel.stop_tunnel()
        if os.name == 'nt':
            os.system(CMDS.SSH_KILL_WIN)
        else:
            os.system(CMDS.SSH_KILL_NIX)

    def closeEvent(self, event):
        try:
            # 尝试关闭所有终端组件，给它们机会清理进程
            if hasattr(self.ui, 'ShellTab'):
                total_tabs = self.ui.ShellTab.count()
                for tab_index in range(total_tabs):
                    shell = self.get_text_browser_from_tab(tab_index)
                    if shell:
                        try:
                            shell.close()
                        except Exception as e:
                            util.logger.error(f"Failed to close all ShellTab: {e}")
                            pass

            # 停止上传线程
            if hasattr(self, 'upload_thread') and isinstance(self.upload_thread,
                                                             QThread) and self.upload_thread.isRunning():
                self.upload_thread.quit()
                if not self.upload_thread.wait(1000):
                    self.upload_thread.terminate()
                    self.upload_thread.wait()

            """
             窗口关闭事件 当存在通道的时候关闭通道
             不存在时结束多路复用器的监听
            :param event: 关闭事件
            :return: None
            """
            # 清理SSH连接
            # 使用线程异步关闭连接，避免阻塞UI
            if self.ssh_clients:
                # 先停止定时器 (在主线程操作，避免跨线程操作UI组件/定时器)
                connections = list(self.ssh_clients.values())
                for ssh_conn in connections:
                    if ssh_conn:
                        try:
                            pass
                            # 等待并清理后台刷新线程
                            if hasattr(ssh_conn, 'refresh_thread') and ssh_conn.refresh_thread.is_alive():
                                # 注意：不能join()因为这是在主线程，可能会卡死。
                                # 由于是 daemon 线程，主程序退出时会自动结束，这里主要确保不再有新的操作
                                pass
                            if hasattr(ssh_conn, 'process_thread') and ssh_conn.process_thread.is_alive():
                                pass
                        except Exception as e:
                            util.logger.error(f"Failed to close all client: {e}")
                            pass

                def cleanup_ssh_connections(conns):
                    for conn in conns:
                        try:
                            if conn:
                                conn.close()
                        except Exception as e1:
                            util.logger.error(f"Failed to cleanup conn: {e1}")
                            pass

                threading.Thread(target=cleanup_ssh_connections, args=(connections,), daemon=True).start()
                self.ssh_clients.clear()
            if self.update_timer:
                try:
                    self.update_timer.stop()
                except Exception:
                    pass

            """
            该函数处理窗口关闭事件，主要功能包括：
            遍历所有隧道（tunnel）并收集其配置信息。
            检查收集到的配置与原始数据是否有差异。
            如果有差异，则备份当前配置文件，并将新配置写入。
            限制备份文件数量不超过10个，多余备份将被删除。
            最终接受关闭事件。
            :param event:
            :return:
            """
            data = {}
            for tunnel in self.tunnels:
                name = tunnel.ui.name.text()
                data[name] = tunnel.tunnelconfig.as_dict()

            # DeepDiff 库用于比较两个复杂数据结构（如字典、列表、集合等）之间的差异，
            # 能够识别并报告添加、删除或修改的数据项。
            # 它支持多级嵌套结构的深度比较，适用于调试或数据同步场景。
            changed = DeepDiff(self.data, data, ignore_order=True)
            if changed:
                timestamp = int(time.time())
                tunnel_json_path = abspath(CONF_FILE)
                shutil.copy(tunnel_json_path, F"{tunnel_json_path}-{timestamp}")
                with open(tunnel_json_path, "w") as fp:
                    json.dump(data, fp)

                # 清理过多的备份
                backup_configs = glob.glob(F"{tunnel_json_path}-*")
                if len(backup_configs) > 10:
                    for config in sorted(backup_configs, reverse=True)[10:]:
                        os.remove(config)
        except Exception as e:
            util.logger.error(f"Error during close: {e}")
        finally:
            event.accept()

    def inputMethodEvent(self, a0: QInputMethodEvent) -> None:
        cmd = a0.commitString()
        if cmd != '':
            self.send(cmd.encode('utf8'))

    # 创建左侧列表树右键菜单函数
    def treeRight(self):
        if not self.isConnected:
            # 菜单对象
            self.ui.tree_menu = QMenu(self)
            self.ui.tree_menu.setStyleSheet("""
                QMenu::item {
                    padding-left: 5px;  /* 调整图标和文字之间的间距 */
                }
                QMenu::icon {
                    padding-right: 0px; /* 设置图标右侧的间距 */
                }
            """)
            # 创建菜单选项对象
            self.ui.action = QAction(QIcon(':addConfig.png'), self.tr('添加配置'), self)
            self.ui.action.setIconVisibleInMenu(True)
            self.ui.action1 = QAction(QIcon(':addConfig.png'), self.tr('编辑配置'), self)
            self.ui.action1.setIconVisibleInMenu(True)
            self.ui.action2 = QAction(QIcon(':delConf.png'), self.tr('删除配置'), self)
            self.ui.action2.setIconVisibleInMenu(True)
            # 把动作选项对象添加到菜单self.groupBox_menu上
            self.ui.tree_menu.addAction(self.ui.action)
            self.ui.tree_menu.addAction(self.ui.action1)
            self.ui.tree_menu.addAction(self.ui.action2)
            # 将动作A触发时连接到槽函数 button
            self.ui.action.triggered.connect(self.showAddConfig)

            selected_items = self.ui.treeWidget.selectedItems()
            is_local_item = False
            try:
                if selected_items and selected_items[0].text(0) == self.tr("本机终端"):
                    is_local_item = True
            except Exception:
                is_local_item = False

            if selected_items and not is_local_item:
                self.ui.action.setVisible(False)
                self.ui.action1.setVisible(True)
                self.ui.action2.setVisible(True)
            else:
                self.ui.action.setVisible(True)
                self.ui.action1.setVisible(False)
                self.ui.action2.setVisible(False)

            self.ui.action1.triggered.connect(self.editConfig)
            self.ui.action2.triggered.connect(self.delConf)

            # 声明当鼠标在groupBox控件上右击时，在鼠标位置显示右键菜单   ,exec_,popup两个都可以，
            self.ui.tree_menu.popup(QCursor.pos())
        elif self.isConnected:
            self.ui.tree_menu = QMenu(self)
            # 设置菜单样式表来调整图标和文字之间的间距
            self.ui.tree_menu.setStyleSheet("""
                QMenu::item {
                    padding-left: 5px;  /* 调整图标和文字之间的间距 */
                }
                QMenu::icon {
                    padding-right: 0px; /* 设置图标右侧的间距 */
                }
            """)

            self.ui.action1 = QAction(QIcon(':Download.png'), self.tr('下载文件'), self)
            self.ui.action1.setIconVisibleInMenu(True)
            self.ui.action2 = QAction(QIcon(':Upload.png'), self.tr('上传文件'), self)
            self.ui.action2.setIconVisibleInMenu(True)
            self.ui.action3 = QAction(QIcon(':Edit.png'), self.tr('编辑文本'), self)
            self.ui.action3.setIconVisibleInMenu(True)
            self.ui.action4 = QAction(QIcon(':createdirector.png'), self.tr('创建文件夹'), self)
            self.ui.action4.setIconVisibleInMenu(True)
            self.ui.action5 = QAction(QIcon(':createfile.png'), self.tr('创建文件'), self)
            self.ui.action5.setIconVisibleInMenu(True)
            self.ui.action6 = QAction(QIcon(':refresh.png'), self.tr('刷新'), self)
            self.ui.action6.setIconVisibleInMenu(True)
            ssh_conn = self.ssh()
            self.ui.action_new_local_terminal = None
            if ssh_conn and getattr(ssh_conn, "is_local", False):
                self.ui.action_new_local_terminal = QAction(
                    QIcon(':Localhost.png'),
                    self.tr('新建位于文件夹位置的终端窗口'),
                    self
                )
                self.ui.action_new_local_terminal.setIconVisibleInMenu(True)
            self.ui.action7 = QAction(QIcon(':remove.png'), self.tr('删除'), self)
            self.ui.action7.setIconVisibleInMenu(True)
            self.ui.action8 = QAction(QIcon(':icons-rename-48.png'), self.tr('重命名'), self)
            self.ui.action8.setIconVisibleInMenu(True)

            self.ui.action9 = QAction(QIcon(':icons-unzip-48.png'), self.tr('解压'), self)
            self.ui.action9.setIconVisibleInMenu(True)
            self.ui.action10 = QAction(QIcon(':icons8-zip-48.png'), self.tr('新建压缩'), self)
            self.ui.action10.setIconVisibleInMenu(True)

            self.ui.tree_menu.addAction(self.ui.action1)
            self.ui.tree_menu.addAction(self.ui.action2)
            self.ui.tree_menu.addAction(self.ui.action3)
            self.ui.tree_menu.addAction(self.ui.action4)
            self.ui.tree_menu.addAction(self.ui.action5)
            self.ui.tree_menu.addAction(self.ui.action6)
            if self.ui.action_new_local_terminal is not None:
                self.ui.tree_menu.addAction(self.ui.action_new_local_terminal)

            # 在子菜单中添加动作
            file_action = QAction(self.tr("权限"), self)
            file_action.setIcon(QIcon(":permissions-48.png"))
            file_action.setIconVisibleInMenu(True)
            file_action.triggered.connect(self.show_auth)
            self.ui.tree_menu.addAction(file_action)

            # 添加分割线,做标记区分
            bottom_separator = QAction(self)
            bottom_separator.setSeparator(True)
            self.ui.tree_menu.addAction(bottom_separator)
            self.ui.tree_menu.addAction(self.ui.action7)
            self.ui.tree_menu.addAction(self.ui.action8)

            # 添加分割线,做标记区分
            bottom_separator = QAction(self)
            bottom_separator.setSeparator(True)
            self.ui.tree_menu.addAction(bottom_separator)

            self.ui.tree_menu.addAction(self.ui.action9)
            self.ui.tree_menu.addAction(self.ui.action10)

            self.ui.action1.triggered.connect(self.downloadFile)
            self.ui.action2.triggered.connect(self.uploadFile)
            self.ui.action3.triggered.connect(self.editFile)
            self.ui.action4.triggered.connect(self.createDir)
            self.ui.action5.triggered.connect(self.createFile)
            self.ui.action6.triggered.connect(self.refresh)
            if self.ui.action_new_local_terminal is not None:
                self.ui.action_new_local_terminal.triggered.connect(self.open_local_terminal_in_selected_folder)
            self.ui.action7.triggered.connect(self.remove)
            self.ui.action8.triggered.connect(self.rename)
            self.ui.action9.triggered.connect(self.unzip)
            self.ui.action10.triggered.connect(self.zip)

            # 声明当鼠标在groupBox控件上右击时，在鼠标位置显示右键菜单   ,exec_,popup两个都可以，
            self.ui.tree_menu.popup(QCursor.pos())

    def open_local_terminal_in_selected_folder(self):
        ssh_conn = self.ssh()
        if not ssh_conn or not getattr(ssh_conn, "is_local", False):
            return

        target_dir = getattr(ssh_conn, "pwd", "") or str(Path.home())
        try:
            selected_items = self.ui.treeWidget.selectedItems()
            if selected_items:
                item = selected_items[0]
                name = (item.text(0) or "").strip()
                perm = (item.text(3) or "").strip()
                if name and perm.startswith("d"):
                    target_dir = os.path.normpath(os.path.join(target_dir, name))
        except Exception:
            pass

        base = os.path.basename(target_dir) or target_dir
        tab_name = f"{self.tr('本机终端')} - {base}"
        tab_index, terminal = self.add_new_tab(tab_name)
        if tab_index < 0 or not terminal:
            return

        try:
            self._connect_local_with_qtermwidget(terminal, tab_name, start_dir=target_dir)
            self.isConnected = True
            self.refreshDirs()
            self.processInitUI()
        except Exception as e:
            util.logger.error(f"新建本机终端失败: {e}")

    # 创建docker列表树右键菜单函数
    def treeDocker(self, position):
        if self.isConnected:
            # 获取点击位置的项
            item = self.ui.treeWidgetDocker.itemAt(position)

            self.ui.tree_menu = QMenu(self)
            self.ui.tree_menu.setStyleSheet("""
                QMenu::item {
                    padding-left: 5px;  /* 调整图标和文字之间的间距 */
                }
                QMenu::icon {
                    padding-right: 0px; /* 设置图标右侧的间距 */
                }
            """)
            self.ui.action1 = QAction(QIcon(':stop.png'), self.tr('停止'), self)
            self.ui.action1.setIconVisibleInMenu(True)
            self.ui.action2 = QAction(QIcon(':restart.png'), self.tr('重启'), self)
            self.ui.action2.setIconVisibleInMenu(True)
            self.ui.action3 = QAction(QIcon(':remove.png'), self.tr('删除'), self)
            self.ui.action3.setIconVisibleInMenu(True)
            self.ui.action_terminal = QAction(QIcon(':icons8-linux-48.png'), self.tr('终端'), self)
            self.ui.action_terminal.setIconVisibleInMenu(True)
            self.ui.action_logs = QAction(QIcon(':icons-log-48.png'), self.tr('日志'), self)
            self.ui.action_logs.setIconVisibleInMenu(True)

            self.ui.tree_menu.addAction(self.ui.action1)
            self.ui.tree_menu.addAction(self.ui.action2)
            self.ui.tree_menu.addAction(self.ui.action3)
            self.ui.tree_menu.addSeparator()
            self.ui.tree_menu.addAction(self.ui.action_terminal)
            self.ui.tree_menu.addAction(self.ui.action_logs)

            # 鼠标右键获取 treeWidgetDocker 上的容器Id
            # 判断是父级还是子级
            if item.parent() is None:  # 父级
                # 获取父级下的所有容器ID
                container_ids = []
                for i in range(item.childCount()):
                    child = item.child(i)
                    container_id = child.text(1)  # 容器ID在第二列
                    if container_id:
                        container_ids.append(container_id)

                self.ui.action1.triggered.connect(lambda: self.stopDockerContainer(container_ids))
                self.ui.action2.triggered.connect(lambda: self.restartDockerContainer(container_ids))
                self.ui.action3.triggered.connect(lambda: self.rmDockerContainer(container_ids))
                # 父级菜单禁用终端和日志功能（不能同时查看多个容器）
                self.ui.action_terminal.setEnabled(False)
                self.ui.action_logs.setEnabled(False)
            # self.ui.action4.triggered.connect(self.rmDockerContainer)
            else:  # 子级
                container_id = item.text(1)  # 容器ID在第二列
                self.ui.action1.triggered.connect(lambda: self.stopDockerContainer([container_id]))
                self.ui.action2.triggered.connect(lambda: self.restartDockerContainer([container_id]))
                self.ui.action3.triggered.connect(lambda: self.rmDockerContainer([container_id]))
                self.ui.action_terminal.triggered.connect(lambda: self.execDockerTerminal(container_id))
                self.ui.action_logs.triggered.connect(lambda: self.viewDockerLogs(container_id))

            # 声明当鼠标在groupBox控件上右击时，在鼠标位置显示右键菜单,exec_,popup两个都可以，
            self.ui.tree_menu.popup(QCursor.pos())

    def execDockerTerminal(self, container_id):
        """向当前 SSH 终端发送 docker exec 命令进入容器"""
        current_index = self.ui.ShellTab.currentIndex()
        terminal = self.get_text_browser_from_tab(current_index)

        if terminal:
            # 发送 docker exec 命令
            cmd = f"docker exec -ti {container_id} /bin/bash\n"
            terminal.sendText(cmd)

    def viewDockerLogs(self, container_id):
        """向当前 SSH 终端发送 docker logs 命令查看容器日志"""
        current_index = self.ui.ShellTab.currentIndex()
        terminal = self.get_text_browser_from_tab(current_index)

        if terminal:
            # 发送 docker logs 命令（-f 跟踪日志，-t 显示时间戳，--tail=1000 显示最后1000行）
            cmd = f"docker logs -n 100 -f {container_id}\n"
            terminal.sendText(cmd)

    # 打开增加配置界面
    def showAddConfig(self):
        self.ui.addconfwin = AddConfigUi()
        self.ui.addconfwin.show()
        self.ui.addconfwin.dial.pushButton.clicked.connect(self.refreshConf)
        self.ui.addconfwin.dial.pushButton_2.clicked.connect(self.ui.addconfwin.close)

    # 打开编辑配置界面
    def editConfig(self):
        selected_items = self.ui.treeWidget.selectedItems()
        self.ui.addconfwin = AddConfigUi()
        # 检查是否有选中的项
        if selected_items:
            if len(selected_items) > 1:
                QMessageBox.warning(self, self.tr('警告'), self.tr('只能编辑一个设备'))
                return
            # 遍历选中的项
            for item in selected_items:
                # 获取项的内容
                name = item.text(0)
                with open(get_config_path('config.dat'), 'rb') as c:
                    conf = pickle.loads(c.read())[name]

                if len(conf) == 3:
                    username, password, host = conf[0], conf[1], conf[2]
                else:
                    username, password, host, key_type, key_file = conf[0], conf[1], conf[2], conf[3], conf[4]
                    self.ui.addconfwin.dial.comboBox.setCurrentText(key_type)
                    self.ui.addconfwin.dial.lineEdit.setText(key_file)

                self.ui.addconfwin.dial.configName.setText(name)
                self.ui.addconfwin.dial.usernamEdit.setText(username)
                self.ui.addconfwin.dial.passwordEdit.setText(password)
                self.ui.addconfwin.dial.ipEdit.setText(host.split(':')[0])
                self.ui.addconfwin.dial.protEdit.setText(host.split(':')[1])

        self.ui.addconfwin.show()
        self.ui.addconfwin.dial.pushButton.clicked.connect(self.refreshConf)
        self.ui.addconfwin.dial.pushButton_2.clicked.connect(self.ui.addconfwin.close)

    # 打开增加隧道界面
    def showAddSshTunnel(self):
        self.add = AddTunnelConfig(self)
        self.add.setModal(True)
        self.add.show()

    # 导出配置
    def export_configuration(self):
        src_path = get_config_path('config.dat')
        # 选择保存文件夹
        directory = QFileDialog.getExistingDirectory(
            None,  # 父窗口，这里为None表示没有父窗口
            self.tr('选择保存文件夹'),  # 对话框标题
            '',  # 默认打开目录
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks  # 显示选项
        )
        if directory:
            os.makedirs(f'{directory}/config', exist_ok=True)
            # 复制文件
            shutil.copy2(str(src_path), f'{directory}/config/config.dat')
            self.success(self.tr("导出成功"))

    # 导入配置
    def import_configuration(self):
        config = get_config_path('config.dat')

        file_name, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("选择文件"),
            "",
            self.tr("所有文件 (*);;json 文件 (*.json)"),
        )
        if file_name:
            # 如果目标文件存在，则删除它
            if os.path.exists(config):
                os.remove(config)
            # 复制文件
            shutil.copy2(str(file_name), str(config))

        self.refreshConf()

    # 刷新设备列表
    def refreshConf(self):
        config = get_config_path('config.dat')
        with open(config, 'rb') as c:
            dic = pickle.loads(c.read())
            c.close()
        i = 0
        self.ui.treeWidget.clear()

        self.ui.treeWidget.headerItem().setText(0, QCoreApplication.translate("MainWindow", "设备列表"))

        # 将“本机”作为固定入口插入到设备列表顶部：
        # - 用户无需新增配置即可打开本地终端与本地文件树
        # - 本机入口不允许被“编辑配置/删除配置”等操作影响
        local_label = self.tr("本机终端")
        self.ui.treeWidget.addTopLevelItem(QTreeWidgetItem(0))
        bold_font = QFont()
        bold_font.setPointSize(14)
        if platform.system() == 'Darwin':
            bold_font.setPointSize(15)
            bold_font.setBold(True)
        self.ui.treeWidget.topLevelItem(i).setFont(0, bold_font)
        self.ui.treeWidget.topLevelItem(i).setText(0, local_label)
        try:
            self.ui.treeWidget.topLevelItem(i).setIcon(0, QIcon(':Localhost.png'))
        except Exception:
            self.ui.treeWidget.topLevelItem(i).setIcon(0, QIcon(':icons8-linux-48.png'))
        i += 1

        for k in dic.keys():
            self.ui.treeWidget.addTopLevelItem(QTreeWidgetItem(0))
            # 设置字体为加粗
            bold_font = QFont()
            bold_font.setPointSize(14)  # 设置字体大小为16
            # Mac 系统设置，其他系统不设置，否则会很大
            if platform.system() == 'Darwin':
                # 设置字体为加粗
                bold_font.setPointSize(15)  # 设置字体大小为16
                bold_font.setBold(True)
            self.ui.treeWidget.topLevelItem(i).setFont(0, bold_font)
            self.ui.treeWidget.topLevelItem(i).setText(0, k)
            self.ui.treeWidget.topLevelItem(i).setIcon(0, QIcon(':icons8-ssh-48.png'))
            i += 1

    def add_line_edit(self, q_str):
        if self.line_edits:
            line_edit = self.line_edits[-1]
            old_block = line_edit.blockSignals(True)
            line_edit.setText(q_str)
            line_edit.blockSignals(old_block)
            return

        line_edit = QLineEdit()
        line_edit.setFocusPolicy(Qt.ClickFocus)
        line_edit.setText(q_str)
        self.line_edits.append(line_edit)
        self.ui.gridLayout.addWidget(line_edit, 0, 0, 1, 1)
        line_edit.returnPressed.connect(self.on_return_pressed)

    # 删除 QLineEdit
    def remove_last_line_edit(self):
        if self.line_edits:
            for line_edit in self.line_edits:
                self.ui.gridLayout.removeWidget(line_edit)
                line_edit.deleteLater()
            # 清空 QLineEdit 列表
            self.line_edits.clear()

    # 当前目录列表刷新
    def refreshDirs(self):
        """刷新目录列表 - 异步优化版"""
        ssh_conn = self.ssh()
        if not ssh_conn:
            return
        try:
            ssh_conn._dir_tree_ready = False
        except Exception:
            pass

        # 1. 如果有缓存数据，且与当前目录一致，立即显示
        # 关键修正：只有当缓存的路径与当前连接的路径一致时才使用缓存，否则说明切换了目录，不应显示旧数据
        if hasattr(ssh_conn, 'cached_pwd') and hasattr(ssh_conn, 'cached_files'):
            if ssh_conn.cached_pwd == ssh_conn.pwd:
                self.handle_file_tree_updated(ssh_conn.id, ssh_conn.cached_pwd, ssh_conn.cached_files)
            else:
                # 路径不一致，说明是新目录，不使用旧缓存，也不清空（避免闪烁），等待新数据
                pass
        else:
            # 无缓存时也不清空，避免出现空白闪烁，等待后台数据覆盖
            pass

        # 2. 启动后台线程获取最新数据
        # 检查线程是否存在并运行
        if not hasattr(ssh_conn, 'refresh_thread') or not ssh_conn.refresh_thread.is_alive():
            ssh_conn.refresh_thread = threading.Thread(target=self.refreshDirs_thread, args=(ssh_conn,), daemon=True)
            ssh_conn.refresh_thread.start()

    def refreshDirs_thread(self, ssh_conn):
        """后台线程获取目录数据"""
        try:
            # 检查连接是否有效
            if not ssh_conn or not ssh_conn.active or not ssh_conn.is_connected():
                return

            # 使用线程安全的方式调用
            # 注意：这里是在子线程中运行，self 是 MainDialog (QObject)
            # 发送信号是线程安全的

            # 尝试获取数据
            result = self.getDirNow(ssh_conn)
            if not result:
                return

            pwd, files = result

            # 再次检查连接状态（因为获取数据是耗时操作）
            if not ssh_conn.active:
                return

            if pwd:  # 确保获取成功
                # 检查 MainDialog 是否还在运行
                # 在 C++ / PySide 中，很难直接检查 self 是否被销毁，
                # 但可以通过捕获 RuntimeError 来处理
                self.update_file_tree_signal.emit(ssh_conn.id, pwd, files[1:])

        except RuntimeError:
            # 捕获 "wrapped C/C++ object of type MainDialog has been deleted"
            pass
        except Exception as e:
            # 忽略特定的运行时错误
            if "Signal source has been deleted" in str(e):
                pass
            else:
                util.logger.error(f"Error in refreshDirs_thread: {e}")

    @Slot(str, str, list)
    def handle_file_tree_updated(self, conn_id, pwd, files):
        """处理文件树更新信号"""
        # 更新缓存
        if conn_id in self.ssh_clients:
            ssh_conn = self.ssh_clients[conn_id]

            # 检查数据是否变化
            is_data_same = False
            if hasattr(ssh_conn, 'cached_pwd') and hasattr(ssh_conn, 'cached_files'):
                if ssh_conn.cached_pwd == pwd and ssh_conn.cached_files == files:
                    is_data_same = True

            ssh_conn.cached_pwd = pwd
            ssh_conn.cached_files = files

            # 如果当前显示的连接就是此连接，且数据未变，则跳过刷新
            if self.current_displayed_connection_id == conn_id and is_data_same:
                return

        # 检查当前显示的标签页是否对应此连接
        current_index = self.ui.ShellTab.currentIndex()
        this = self.ui.ShellTab.tabWhatsThis(current_index)
        if this != conn_id:
            return

        # 更新当前显示的连接ID
        self.current_displayed_connection_id = conn_id

        try:
            # 阻止UI更新
            self.ui.treeWidget.setUpdatesEnabled(False)
            # 清除现有项
            self.ui.treeWidget.clear()

            self.dir_tree_now = files
            ssh_conn = self.ssh_clients[conn_id]
            ssh_conn.pwd = pwd  # 更新连接对象的 pwd

            # 设置表头
            self.ui.treeWidget.setHeaderLabels(
                [self.tr("文件名"), self.tr("文件大小"), self.tr("修改日期"), self.tr("权限"),
                 self.tr("所有者/组")])

            # 更新路径编辑框
            self.add_line_edit(pwd)

            # 批量创建项目
            items = []
            for i, n in enumerate(files):
                if len(n) < 9: continue  # 简单校验防止索引越界
                item = QTreeWidgetItem()
                item.setText(0, n[8])
                size_in_bytes = int(n[4].replace(",", ""))
                item.setText(1, format_file_size(size_in_bytes))
                item.setText(2, f"{n[5]} {n[6]} {n[7]}")
                item.setText(3, n[0])
                item.setText(4, n[3])

                # 设置图标
                if n[0].startswith('d'):
                    item.setIcon(0, util.get_default_folder_icon())
                elif n[0][0] in ['l', '-', 's']:
                    if n[0] in ("-rwxr-xr-x", "-r-xr-xr-x", "-rwsr-xr-x", "-rwxr-xr-x.", "-r-xr-xr-x.", "-rwxr-x---."):
                        # 可执行文件图标
                        item.setIcon(0, QIcon(':icons8-exec-48.png'))
                    else:
                        item.setIcon(0, util.get_default_file_icon(n[8]))

                items.append(item)

            # 批量添加项目
            self.ui.treeWidget.addTopLevelItems(items)

            # 恢复UI更新
            self.ui.treeWidget.setUpdatesEnabled(True)
            try:
                ssh_conn._dir_tree_ready = True
            except Exception:
                pass

        except Exception as e:
            util.logger.error(f"Error refreshing directories UI: {e}")

    # 旧的同步方法已废弃，保留 getDirNow

    # 获取当前目录列表
    def getDirNow(self, ssh_conn=None):
        if ssh_conn is None:
            ssh_conn = self.ssh()
            if not ssh_conn:
                return "", []
            if getattr(ssh_conn, "is_local", False):
                # 本机模式：直接读取本地文件系统，返回一个“类 ls -al”结构，
                # 使得后续 handle_file_tree_updated 仍能复用既有渲染逻辑（n[0] 权限、n[4] 大小等）
                return self._get_local_dir_now(ssh_conn)
            pwd = self.getData2('cd ' + ssh_conn.pwd.replace("//", "/") + ' && pwd')
            dir_info = self.getData2(cmd='cd ' + ssh_conn.pwd.replace("//", "/") + ' && ls -al').split('\n')
        else:
            if getattr(ssh_conn, "is_local", False):
                return self._get_local_dir_now(ssh_conn)
            try:
                pwd = ssh_conn.exec('cd ' + ssh_conn.pwd.replace("//", "/") + ' && pwd')
                dir_info = ssh_conn.exec(cmd='cd ' + ssh_conn.pwd.replace("//", "/") + ' && ls -al').split('\n')
            except Exception as e:
                util.logger.error(f"Error in getDirNow background fetch: {e}")
                return "", []

        dir_n_info = []
        for d in dir_info:
            d_list = ssh_conn.del_more_space(d)
            if d_list:
                dir_n_info.append(d_list)
            else:
                pass
        return pwd[:-1], dir_n_info

    def _get_local_dir_now(self, ssh_conn):
        # 将本地目录转换成“远程 ls -al”兼容的列表结构：
        # [权限, 链接数, 所有者, 组, 大小, 月, 日, 时间/年, 文件名]
        # 这样整个 UI 渲染与右键逻辑可以与远程保持一致，尽量少改动上层代码。
        import stat as _stat
        import time as _time
        try:
            import pwd as _pwd
        except Exception:
            _pwd = None
        try:
            import grp as _grp
        except Exception:
            _grp = None

        raw_pwd = (ssh_conn.pwd or os.path.expanduser("~")).strip()
        if raw_pwd in (".", ""):
            raw_pwd = os.path.expanduser("~")
        pwd_abs = os.path.abspath(os.path.expanduser(raw_pwd))
        if not os.path.isdir(pwd_abs):
            pwd_abs = os.path.expanduser("~")

        def _owner_name(uid: int) -> str:
            if _pwd:
                try:
                    return _pwd.getpwuid(uid).pw_name
                except Exception:
                    pass
            return str(uid)

        def _group_name(gid: int) -> str:
            if _grp:
                try:
                    return _grp.getgrgid(gid).gr_name
                except Exception:
                    pass
            return str(gid)

        now = _time.time()
        entries = []
        entries.append([
            "drwxr-xr-x",
            "1",
            _owner_name(os.getuid()) if hasattr(os, "getuid") else "",
            _group_name(os.getgid()) if hasattr(os, "getgid") else "",
            "0",
            _time.strftime("%b", _time.localtime(now)),
            str(_time.localtime(now).tm_mday),
            _time.strftime("%H:%M", _time.localtime(now)),
            ".",
        ])
        parent = os.path.dirname(pwd_abs.rstrip(os.sep)) or pwd_abs
        entries.append([
            "drwxr-xr-x",
            "1",
            _owner_name(os.getuid()) if hasattr(os, "getuid") else "",
            _group_name(os.getgid()) if hasattr(os, "getgid") else "",
            "0",
            _time.strftime("%b", _time.localtime(now)),
            str(_time.localtime(now).tm_mday),
            _time.strftime("%H:%M", _time.localtime(now)),
            "..",
        ])

        try:
            names = os.listdir(pwd_abs)
        except Exception:
            names = []

        def _sort_key(n: str):
            p = os.path.join(pwd_abs, n)
            try:
                st = os.lstat(p)
                is_dir = _stat.S_ISDIR(st.st_mode)
            except Exception:
                is_dir = False
            return (0 if is_dir else 1, n.lower())

        for name in sorted(names, key=_sort_key):
            p = os.path.join(pwd_abs, name)
            try:
                st = os.lstat(p)
            except Exception:
                continue
            perm = _stat.filemode(st.st_mode)
            links = str(getattr(st, "st_nlink", 1))
            owner = _owner_name(getattr(st, "st_uid", 0))
            group = _group_name(getattr(st, "st_gid", 0))
            size = str(getattr(st, "st_size", 0))
            mtime = float(getattr(st, "st_mtime", now))
            tm = _time.localtime(mtime)
            month = _time.strftime("%b", tm)
            day = str(tm.tm_mday)
            if abs(now - mtime) > 15552000:
                time_or_year = str(tm.tm_year)
            else:
                time_or_year = _time.strftime("%H:%M", tm)
            entries.append([perm, links, owner, group, size, month, day, time_or_year, name])

        # 将规范化后的绝对路径回写到连接对象上，保证后续 cd/上传/下载等拼路径一致
        ssh_conn.pwd = pwd_abs
        return pwd_abs, entries

    # 打开文件编辑窗口
    def editFile(self):
        items = self.ui.treeWidget.selectedItems()
        if len(items) > 1:
            self.alarm(self.tr('只能编辑一个文件！'))
            return
        focus = self.ui.treeWidget.currentIndex().row()
        if focus != -1 and self.dir_tree_now[focus][0].startswith('-'):
            self.file_name = self.ui.treeWidget.currentItem().text(0)
            if has_valid_suffix(self.file_name):
                self.alarm(self.tr('不支持编辑此文件！'))
                return
            ssh_conn = self.ssh()
            if getattr(ssh_conn, "is_local", False):
                try:
                    # 本机编辑：直接读本地文件内容（TextEditor 复用同一套 UI）
                    # errors="replace" 保障遇到非 UTF-8 文件也不会直接崩溃
                    local_path = os.path.join(os.path.expanduser(ssh_conn.pwd), self.file_name)
                    with open(local_path, "r", encoding="utf-8", errors="replace") as f:
                        text = f.read()
                except Exception:
                    text = "error"
            else:
                text = self.getData2('cat ' + ssh_conn.pwd + '/' + self.file_name)
            if text != 'error' and text != '\n':
                self.ui.addTextEditWin = TextEditor(title=self.file_name, old_text=text)
                self.ui.addTextEditWin.show()
                self.ui.addTextEditWin.save_tex.connect(self.getNewText)
            elif text == 'error' or text == '\n':
                self.alarm(self.tr('无法编辑文件，请确认！'))
        elif focus != -1 and self.dir_tree_now[focus][0].startswith('lr'):
            self.alarm(self.tr('此文件不能直接编辑！'))
        else:
            self.alarm(self.tr('文件夹不能被编辑！'))

    def createDir(self):
        ssh_conn = self.ssh()
        dialog = QInputDialog(self)
        dialog.setWindowTitle(self.tr('创建文件夹'))
        dialog.setLabelText(self.tr('文件夹名字:'))
        dialog.setFixedSize(400, 150)

        # 显示对话框并获取结果
        ok = dialog.exec()
        text = dialog.textValue()

        if ok:
            sftp = ssh_conn.open_sftp()
            pwd_text = ssh_conn.pwd + '/' + text

            # 如果路径不存在，则创建目录
            if not util.check_remote_directory_exists(sftp, pwd_text):
                try:
                    # 目录不存在，创建目录
                    sftp.mkdir(pwd_text)
                    self.refreshDirs()
                except Exception as create_error:
                    if "Permission denied" in str(create_error):
                        self.alarm(self.tr('当前文件夹权限不足，请设置权限之后再操作'))
                    else:
                        util.logger.error(f"An error occurred: {create_error}")
                        self.alarm(self.tr('创建文件夹失败，请联系开发作者'))
            else:
                self.alarm(self.tr('文件夹已存在'))

    # 创建文件
    def createFile(self):
        ssh_conn = self.ssh()
        dialog = QInputDialog(self)
        dialog.setWindowTitle(self.tr('创建文件'))
        dialog.setLabelText(self.tr('文件名字:'))
        dialog.setFixedSize(400, 150)

        # 显示对话框并获取结果
        ok = dialog.exec()
        text = dialog.textValue()

        if ok:
            sftp = ssh_conn.open_sftp()
            pwd_text = ssh_conn.pwd + '/' + text
            try:
                with sftp.file(pwd_text, 'w'):
                    pass  # 不写入任何内容
                self.refreshDirs()
            except IOError as e:
                if "Permission denied" in str(e):
                    self.alarm(self.tr('当前文件夹权限不足，请设置权限之后再操作'))
                else:
                    util.logger.error(f"An error occurred: {e}")
                    self.alarm(self.tr('创建文件失败，请联系开发作者'))

    # 保存内容到远程文件
    def save_file(self, path, content):
        try:
            ssh_conn = self.ssh()
            if ssh_conn and getattr(ssh_conn, "is_local", False):
                # 本机保存：
                # - 使用 Python 文件 IO 写入（文本模式写 str，避免写 bytes 导致 TypeError）
                # - path 这里沿用上层调用的“ssh_conn.pwd + '/' + filename”拼接方式，
                #   因此需要 expanduser + normpath 做一次标准化
                local_path = os.path.normpath(os.path.expanduser(str(path)))
                with open(local_path, "w", encoding="utf-8") as f:
                    f.write(content if isinstance(content, str) else content.decode("utf-8", errors="replace"))
                return True, ""

            # 远程保存：走 SFTP 写入
            sftp = ssh_conn.open_sftp() if ssh_conn else None
            if not sftp:
                return False, "No active connection"
            with sftp.file(path, 'w') as f:
                data = content if isinstance(content, (bytes, bytearray)) else str(content).encode('utf-8')
                f.write(data)
            return True, ""
        except Exception as e:
            return False, str(e)

    # 获取返回信息，并保存文件
    def getNewText(self, new_list):
        ssh_conn = self.ssh()
        nt, sig = new_list[0], new_list[1]
        if sig == 0:
            self.save_file(ssh_conn.pwd + '/' + self.file_name, nt)
            self.ui.addTextEditWin.new_text = self.ui.addTextEditWin.old_text
            self.ui.addTextEditWin.te.chk.close()
            self.ui.addTextEditWin.close()
        elif sig == 1:
            self.save_file(ssh_conn.pwd + '/' + self.file_name, nt)
            self.ui.addTextEditWin.old_text = nt

    # 删除设备配置文件
    def delConf(self):
        # 创建消息框
        reply = QMessageBox()
        reply.setWindowTitle(self.tr('确认删除'))
        reply.setText(self.tr('您确定要删除选中设备吗？这将无法恢复！'))
        reply.setStandardButtons(QMessageBox.Yes | QMessageBox.No)

        # 设置按钮文本为中文
        yes_button = reply.button(QMessageBox.Yes)
        no_button = reply.button(QMessageBox.No)
        yes_button.setText(self.tr("确定"))
        no_button.setText(self.tr("取消"))
        # 显示对话框并等待用户响应
        reply.exec()
        if reply.clickedButton() == yes_button:
            selected_items = self.ui.treeWidget.selectedItems()
            # 检查是否有选中的项
            if selected_items:
                # 遍历选中的项
                for item in selected_items:
                    # 获取项的内容
                    name = item.text(0)
                    config = get_config_path('config.dat')
                    with open(config, 'rb') as c:
                        conf = pickle.loads(c.read())
                    with open(config, 'wb') as c:
                        del conf[name]
                        c.write(pickle.dumps(conf))
                self.refreshConf()

    # 建议修改为
    def flushSysInfo(self):
        try:
            ssh_conn = self.ssh()
            if ssh_conn and hasattr(ssh_conn, "timer1") and ssh_conn.timer1:
                # 兼容历史版本：
                # 旧实现会把 QTimer 挂在 ssh_conn.timer1 上，并且由于判断条件写错可能重复创建，
                # 导致多个定时器在主线程同时刷新 UI，最终表现为“越来越卡/卡死”。
                # 这里主动 stop + deleteLater，避免旧 timer 残留。
                try:
                    ssh_conn.timer1.stop()
                    ssh_conn.timer1.deleteLater()
                except Exception:
                    pass
                ssh_conn.timer1 = None

            if self.update_timer and self.update_timer.isActive():
                # 全局定时器已在跑，不要重复创建/重复 start
                return

            if not self.update_timer:
                # 修复后的设计：MainDialog 级别只维护一个 update_timer
                # - 以 self 作为 parent，生命周期跟随窗口，避免泄漏
                # - timeout 只做“从当前 tab 的后端取值 → 更新 UI”，不做耗时 IO
                self.update_timer = QTimer(self)
                self.update_timer.timeout.connect(self.refreshSysInfo)
            self.update_timer.start(1000)
        except Exception as e:
            util.logger.error(f"Error setting up system info update: {e}")

    # 刷新设备状态信息功能
    def refreshSysInfo(self):
        if self.isConnected:
            current_index = self.ui.ShellTab.currentIndex()
            this = self.ui.ShellTab.tabWhatsThis(current_index)
            if this and this in self.ssh_clients:
                ssh_conn = self.ssh_clients[this]
                if getattr(ssh_conn, "is_local", False):
                    # 本机模式不具备远程采集线程（get_datas）产出的系统信息字段，
                    # 因此直接跳过，避免 KeyError/AttributeError 导致频繁异常。
                    return
                system_info_dict = getattr(ssh_conn, "system_info_dict", None) or {}
                cpu_use = getattr(ssh_conn, "cpu_use", 0)
                mem_use = getattr(ssh_conn, "mem_use", 0)
                dissk_use = getattr(ssh_conn, "disk_use", 0)
                # 上行
                transmit_speed = getattr(ssh_conn, "transmit_speed", 0)
                # 下行
                receive_speed = getattr(ssh_conn, "receive_speed", 0)

                self.ui.cpuRate.setValue(cpu_use)
                self.ui.cpuRate.setStyleSheet(updateColor(cpu_use))
                self.ui.memRate.setValue(mem_use)
                self.ui.memRate.setStyleSheet(updateColor(mem_use))
                self.ui.diskRate.setValue(dissk_use)
                self.ui.diskRate.setStyleSheet(updateColor(dissk_use))
                # 自定义显示格式
                self.ui.networkUpload.setText(util.format_speed(transmit_speed))
                self.ui.networkDownload.setText(util.format_speed(receive_speed))
                self.ui.operatingSystem.setText(system_info_dict.get('Operating System', ''))
                self.ui.kernelVersion.setText(system_info_dict.get('Kernel', ''))
                if 'Firmware Version' in system_info_dict:
                    self.ui.kernel.setText(system_info_dict['Firmware Version'])
                else:
                    self.ui.kernel.setText(self.tr("无"))

        else:
            self.ui.cpuRate.setValue(0)
            self.ui.memRate.setValue(0)
            self.ui.diskRate.setValue(0)
            if hasattr(self.ui, "networkUploadSparkline"):
                try:
                    self.ui.networkUploadSparkline.addPoint(0)
                except Exception:
                    pass
            if hasattr(self.ui, "networkDownloadSparkline"):
                try:
                    self.ui.networkDownloadSparkline.addPoint(0)
                except Exception:
                    pass

    # 获取容器列表
    def compose_container_list(self):
        ssh_conn = self.ssh()
        groups = defaultdict(list)
        # 获取 compose 项目和配置文件列表
        ls = ssh_conn.sudo_exec("docker compose ls -a")
        lines = ls.strip().splitlines()

        # 获取compose 项目下的所有容器
        for compose_ls in lines[1:]:
            # 从右边开始分割，比如 rsplit，只分割最后一次空格
            # 这样最后一列可以拿出来
            parts = compose_ls.rsplit(None, 1)  # 从右边切一次空白字符
            config = parts[-1]
            ps_cmd = f"docker compose --file {config} ps -a --format '{{{{json .}}}}'"
            # 执行docker compose ps
            conn_exec = ssh_conn.sudo_exec(ps_cmd)
            container_list = []
            for ps in conn_exec.strip().splitlines():
                if ps.strip():
                    data = json.loads(ps)
                    container_list.append(data)

            for item in container_list:
                # 使用项目进行分组
                project_name = item.get('Project', '未知')  # 取值，如果没有则使用'未知'
                groups[project_name].append(item)

        return groups

    # 获取docker容器列表
    # compose 获取不到数据的时候使用此方法获取容器数据
    def docker_container_list(self):
        ssh_conn = self.ssh()
        conn_exec = ssh_conn.exec("docker ps -a --format '{{json .}}'")
        container_list = []
        for ps in conn_exec.strip().splitlines():
            if ps.strip():
                data = json.loads(ps)
                container_list.append(data)

        return container_list

    def refreshDokerInfo(self):
        if self.isConnected:
            current_index = self.ui.ShellTab.currentIndex()
            this = self.ui.ShellTab.tabWhatsThis(current_index)
            if this:
                self.ui.treeWidgetDocker.clear()
                self.ui.treeWidgetDocker.headerItem().setText(0, self.tr("docker容器管理") + '：')
                self.ui.treeWidgetDocker.setHeaderLabels(
                    [self.tr("#"), self.tr("容器ID"), self.tr("容器"), self.tr("镜像"), self.tr("状态"),
                     self.tr("创建时间"), self.tr("端口")
                     ])

                # 设置表头居中
                header = self.ui.treeWidgetDocker.header()
                header.setDefaultAlignment(Qt.AlignCenter)
                # 允许表头拖动
                header.setSectionsMovable(True)
                # 允许调整列宽
                header.setSectionResizeMode(QHeaderView.Interactive)

                # 显示加载状态
                loading_item = QTreeWidgetItem()
                loading_item.setText(0, "正在加载 Docker 信息...")
                self.ui.treeWidgetDocker.addTopLevelItem(loading_item)

                # 启动后台线程
                # 如果已有线程正在运行，先停止它（可选，或者忽略新请求）
                # 这里选择忽略新请求如果正在加载
                if hasattr(self, 'docker_thread') and self.docker_thread.isRunning():
                    return

                self.docker_thread = DockerInfoThread(self.ssh())
                self.docker_thread.data_ready.connect(self.update_docker_ui)
                # 关键修复：不要在 finished 信号中调用 deleteLater，因为线程可能还在处理事件循环
                # 使用 cleanup_thread 仅解除引用，让 Python GC 处理（或者手动安全管理）
                # self.docker_thread.finished.connect(lambda: self.cleanup_thread('docker_thread'))
                self.docker_thread.start()

        else:
            self.ui.treeWidgetDocker.clear()
            self.ui.treeWidgetDocker.addTopLevelItem(QTreeWidgetItem(0))
            self.ui.treeWidgetDocker.topLevelItem(0).setText(0, self.tr('没有可用的docker容器'))

    @Slot(dict, list)
    def update_docker_ui(self, groups, container_list):
        """更新 Docker UI (槽函数)"""
        self.ui.treeWidgetDocker.clear()

        if groups:
            # 有项目的情况
            for project, containers in groups.items():
                # 创建项目顶层节点
                project_item = QTreeWidgetItem()
                project_item.setText(0, project)
                bold_font = QFont()
                bold_font.setBold(True)
                project_item.setFont(0, bold_font)
                # 设置项目名称居中
                for i in range(self.ui.treeWidgetDocker.columnCount()):
                    project_item.setTextAlignment(i, Qt.AlignCenter)
                self.ui.treeWidgetDocker.addTopLevelItem(project_item)

                if containers:  # 有容器，添加子节点
                    for c in containers:
                        self._add_container_item(c, project_item)
        elif container_list:
            # 只有容器的情况
            for c in container_list:
                self._add_container_item(c, None)
        else:
            self.ui.treeWidgetDocker.addTopLevelItem(QTreeWidgetItem(0))
            self.ui.treeWidgetDocker.topLevelItem(0).setText(0, self.tr('服务器还没有安装docker容器'))

        # 展开所有节点
        self.ui.treeWidgetDocker.expandAll()

        # 更新完成后，安全停止线程
        if hasattr(self, 'docker_thread') and self.docker_thread:
            # 不再强制删除，而是等待下一次刷新时覆盖或GC回收
            pass

    def _add_container_item(self, c, parent_item):
        """添加容器项到树"""
        container_item = QTreeWidgetItem()
        container_item.setText(1, c.get('ID', ""))
        container_item.setText(2, c.get('Name', "") or c.get('Names', ""))  # 兼容不同格式
        container_item.setText(3, c.get('Image', ""))
        container_item.setText(4, c.get('State', ""))
        container_item.setText(5, c.get('CreatedAt', ""))
        container_item.setText(6, c.get('Ports', ""))
        container_item.setIcon(0, QIcon(":icons8-docker-48.png"))

        # 设置居中
        for i in range(self.ui.treeWidgetDocker.columnCount()):
            container_item.setTextAlignment(i, Qt.AlignCenter)

        if parent_item:
            parent_item.addChild(container_item)
        else:
            self.ui.treeWidgetDocker.addTopLevelItem(container_item)

    def cleanup_thread(self, thread_name):
        """清理线程资源"""
        # 这个方法现在主要用于强制清理，不再自动连接到 finished 信号
        if hasattr(self, thread_name):
            thread = getattr(self, thread_name)
            if thread and thread.isRunning():
                thread.quit()
                thread.wait()
            setattr(self, thread_name, None)

    # 刷新docker常用容器信息
    def refresh_docker_common_containers(self):
        if self.isConnected:
            util.clear_grid_layout(self.ui.gridLayout_7)

            # 显示加载状态
            loading_label = QLabel("正在加载常用容器信息...")
            loading_label.setAlignment(Qt.AlignCenter)
            loading_label.setStyleSheet("font-size: 16px; color: #666;")
            self.ui.gridLayout_7.addWidget(loading_label)

            if hasattr(self, 'common_docker_thread') and self.common_docker_thread.isRunning():
                return

            config_path = abspath('docker-compose-full.yml')
            self.common_docker_thread = CommonContainersThread(self.ssh(), config_path)
            self.common_docker_thread.data_ready.connect(self.update_common_containers_ui)
            self.common_docker_thread.start()

    @Slot(dict, bool)
    def update_common_containers_ui(self, services_config, has_docker):
        """更新常用容器 UI"""
        ssh_conn = self.ssh()  # CustomWidget 需要 ssh_conn
        util.clear_grid_layout(self.ui.gridLayout_7)

        if has_docker:
            # 每行最多四个小块 (原文是8，注释写每行最多四个但变量是8，保留原逻辑)
            max_columns = 8

            # 创建滚动区域
            scroll_area = QScrollArea()
            scroll_area.setWidgetResizable(True)  # 允许内容自适应大小
            scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)  # 始终显示垂直滚动条

            # 创建滚动内容容器
            scroll_content = QWidget()
            scroll_area.setWidget(scroll_content)

            # 使用网格布局管理滚动内容
            grid_layout = QGridLayout(scroll_content)
            grid_layout.setContentsMargins(0, 0, 0, 0)  # 设置布局边距
            grid_layout.setHorizontalSpacing(2)  # 设置水平间距
            grid_layout.setVerticalSpacing(2)  # 设置垂直间距

            # 将滚动区域添加到原布局位置（替换原来的gridLayout_7）
            self.ui.gridLayout_7.addWidget(scroll_area)

            # 遍历列表创建小块
            for index, (key, item) in enumerate(services_config.items()):
                row = index // max_columns
                col = index % max_columns

                # 创建外层容器
                container_widget = QWidget()
                container_widget.setFixedSize(95, 143)  # 固定每个小块的尺寸
                container_layout = QVBoxLayout(container_widget)
                container_layout.setContentsMargins(0, 0, 0, 0)  # 移除内边距

                # 创建自定义组件
                widget = CustomWidget(key, item, ssh_conn)
                container_layout.addWidget(widget)

                # 添加到网格布局
                grid_layout.addWidget(container_widget, row, col)
        else:
            # 创建外部容器
            container_widget = QWidget()
            container_layout = QVBoxLayout()
            container_widget.setLayout(container_layout)
            container_layout.setContentsMargins(0, 0, 0, 0)  # 去掉布局的内边距
            container_widget.setStyleSheet("background-color: rgb(187, 232, 221);")

            text_browser = QTextBrowser(container_widget)
            text_browser.append("\n")
            text_browser.append("\n")
            text_browser.append("\n")
            text_browser.append(self.tr("服务器还没有安装docker容器"))
            # 设置内容居中对齐
            text_browser.setAlignment(Qt.AlignCenter)

            install_button = QPushButton("服务器还没有安装docker容器，开始安装")
            install_button.clicked.connect(self.start_installation)

            self.ui.gridLayout_7.addWidget(install_button)

    def start_installation(self):
        docker_installer = DockerInstallerWidget(self.ssh())
        self.ui.tabWidget.addTab(docker_installer, self.tr('docker安装'))
        # 切换到Docker安装器标签页
        self.ui.tabWidget.setCurrentWidget(docker_installer)

    # 下载文件
    def downloadFile(self):
        try:
            # 选择保存文件夹
            directory = QFileDialog.getExistingDirectory(
                None,  # 父窗口，这里为None表示没有父窗口
                self.tr('选择保存文件夹'),  # 对话框标题
                '',  # 默认打开目录
                QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks  # 显示选项
            )
            if directory:
                ssh_conn = self.ssh()
                items = self.ui.treeWidget.selectedItems()
                sftp = ssh_conn.open_sftp()
                for item in items:
                    item_text = item.text(0)

                    # 获取远程文件大小
                    remote_file_size = sftp.stat(ssh_conn.pwd + '/' + item_text).st_size
                    self.ui.download_with_resume1.setVisible(True)
                    # 转换为 KB
                    self.ui.download_with_resume1.setMaximum(remote_file_size // 1024)

                    # 设置 SSH 会话保持活跃
                    # 每30秒发送一次保持活跃的消息
                    ssh_conn.conn.get_transport().set_keepalive(30)

                    # 使用断点续传下载文件
                    util.download_with_resume(sftp, ssh_conn.pwd + '/' + item_text, f'{directory}/{item_text}',
                                              self.download_update_progress_bar)

                    self.ui.download_with_resume1.setVisible(False)

            self.success(self.tr("下载文件"))
        except Exception as e:
            util.logger.error("Failed to download file:" + str(e))
            self.alarm(self.tr('无法下载文件，请确认！'))

    # 下载更新进度条
    def download_update_progress_bar(self, current, total):
        self.ui.download_with_resume1.setValue(current // 1024)
        QApplication.processEvents()  # 更新 GUI 事件循环

    def uploadFile(self):
        """优化的文件上传功能"""
        ssh_conn = self.ssh()

        # 使用QFileDialog获取文件
        files, _ = QFileDialog.getOpenFileNames(self, self.tr("选择文件"), "", self.tr("所有文件 (*)"))
        if not files:
            return

        self._start_uploads(ssh_conn, files)

    def on_upload_completed(self, file_id, filename):
        """上传完成时隐藏进度条"""
        if file_id in self.progress_bars:
            ssh_conn = self.ssh()
            # 获取进度条对象
            progress_bar = self.progress_bars[file_id]

            # 设置完成状态
            progress_bar.setValue(100)
            progress_bar.setFormat("完成")

            # 更新文件状态
            if file_id in ssh_conn.active_uploads:
                ssh_conn.active_uploads.remove(file_id)
                ssh_conn.completed_uploads.add(file_id)

            # 检查是否所有文件都完成了
            self.check_all_uploads_completed()
            self.refreshDirs()

    def on_upload_failed(self, file_id, filename, error):
        """上传失败时标记进度条为失败状态"""
        if file_id in self.progress_bars:
            ssh_conn = self.ssh()
            # 获取进度条对象
            progress_bar = self.progress_bars[file_id]

            # 设置失败状态
            progress_bar.setFormat("失败")
            progress_bar.setStyleSheet("""
                QProgressBar {
                    border: 1px solid #bdc3c7;
                    border-radius: 3px;
                    background-color: #ecf0f1;
                    text-align: center;
                }

                QProgressBar::chunk {
                    background-color: #e74c3c; /* 红色 */
                    border-radius: 2px;
                }
            """)

            # 更新文件状态
            if file_id in ssh_conn.active_uploads:
                ssh_conn.active_uploads.remove(file_id)
                ssh_conn.failed_uploads.add(file_id)

            # 检查是否所有文件都完成了
            self.check_all_uploads_completed()

    def check_all_uploads_completed(self):
        ssh_conn = self.ssh()
        """检查是否所有上传都已完成，如果是则清理界面"""
        if not ssh_conn.active_uploads and (ssh_conn.completed_uploads or ssh_conn.failed_uploads):
            # 所有上传都已完成或失败，延迟一段时间后清理界面
            from PySide6.QtCore import QTimer
            QTimer.singleShot(1500, self.clear_all_progress)  # 1.5秒后清理

    def clear_all_progress(self):
        """清除所有进度条和相关组件"""
        util.clear_grid_layout(self.ui.download_with_resume)
        ssh_conn = self.ssh()
        # 重置状态
        ssh_conn.active_uploads.clear()
        ssh_conn.completed_uploads.clear()
        ssh_conn.failed_uploads.clear()

    # 上传更新进度条
    def upload_update_progress(self, value):
        self.ui.download_with_resume1.setValue(value)
        if value >= 100:
            self.ui.download_with_resume1.setVisible(False)
            self.refreshDirs()

    # 刷新
    def refresh(self):
        self.refreshDirs()

    def show_auth(self):
        self.ui.auth = Auth(self)
        selected_items = self.ui.treeWidget.selectedItems()
        # 先取出所有选中项目
        for item in selected_items:
            # 去掉第一个字符
            trimmed_str = item.text(3)[1:]
            # 转换为列表
            permission_list = list(trimmed_str)
            self.ui.auth.dial.checkBoxUserR.setChecked(permission_list[0] != '-')
            self.ui.auth.dial.checkBoxUserW.setChecked(permission_list[1] != '-')
            self.ui.auth.dial.checkBoxUserX.setChecked(permission_list[2] != '-')
            self.ui.auth.dial.checkBoxGroupR.setChecked(permission_list[3] != '-')
            self.ui.auth.dial.checkBoxGroupW.setChecked(permission_list[4] != '-')
            self.ui.auth.dial.checkBoxGroupX.setChecked(permission_list[5] != '-')
            self.ui.auth.dial.checkBoxOtherR.setChecked(permission_list[6] != '-')
            self.ui.auth.dial.checkBoxOtherW.setChecked(permission_list[7] != '-')
            self.ui.auth.dial.checkBoxOtherX.setChecked(permission_list[8] != '-')
            break
        self.ui.auth.show()

    # 删除
    def remove(self):
        ssh_conn = self.ssh()
        # 创建消息框
        reply = QMessageBox()
        reply.setWindowTitle(self.tr('确认删除'))
        reply.setText(self.tr('确定删除选中项目吗？这将无法恢复！'))
        reply.setStandardButtons(QMessageBox.Yes | QMessageBox.No)

        # 设置按钮文本为中文
        yes_button = reply.button(QMessageBox.Yes)
        no_button = reply.button(QMessageBox.No)
        yes_button.setText(self.tr("是"))
        no_button.setText(self.tr("否"))
        # 显示对话框并等待用户响应
        reply.exec()

        if reply.clickedButton() == yes_button:
            rm_dict = dict()
            selected_items = self.ui.treeWidget.selectedItems()
            # 先取出所有选中项目
            for item in selected_items:
                # key：为文件名 value：是否为文件夹
                rm_dict[item.text(0)] = item.text(3).startswith('d')
            sftp = ssh_conn.open_sftp()
            # 批量删除
            for key, value in rm_dict.items():
                try:
                    if value:
                        util.deleteFolder(sftp, ssh_conn.pwd + '/' + key)
                    else:
                        sftp.remove(ssh_conn.pwd + '/' + key)
                except IOError as e:
                    util.logger.error(f"Failed to remove file: {e}")
            rm_dict.clear()
            self.refreshDirs()

    # 压缩
    def zip(self):
        ssh_conn = self.ssh()
        if not ssh_conn:
            return

        selected_items = self.ui.treeWidget.selectedItems()
        if not selected_items:
            return

        # 获取第一个选中项作为默认文件名基础
        first_item_text = selected_items[0].text(0)
        # 去掉前面的点（如果是隐藏文件）
        s = str(first_item_text).lstrip('.')
        base_name = os.path.splitext(s)[0]

        # 弹出对话框
        dialog = CompressDialog(self, base_name)
        if dialog.exec():
            filename, format_type = dialog.get_settings()

            if not filename:
                self.warning(self.tr("错误"), self.tr("文件名不能为空"))
                return

            # 补全后缀
            if format_type == ".tar.gz":
                if not filename.endswith(".tar.gz") and not filename.endswith(".tgz"):
                    if filename.endswith(".tar"):
                        filename += ".gz"
                    else:
                        filename += ".tar.gz"
            elif format_type == ".zip":
                if not filename.endswith(".zip"):
                    filename += ".zip"

            files = [item.text(0) for item in selected_items]

            # 启动线程
            self.compress_thread = CompressThread(ssh_conn, files, filename, format_type, ssh_conn.pwd)
            self.compress_thread.finished_sig.connect(self.on_compress_finished)

            # 进度对话框
            self.progress_dialog = QProgressDialog(self.tr("正在压缩..."), self.tr("取消"), 0, 0, self)
            self.progress_dialog.setWindowTitle(self.tr("请稍候"))
            self.progress_dialog.setWindowModality(Qt.WindowModal)
            self.progress_dialog.setMinimumDuration(0)  # 立即显示
            self.progress_dialog.canceled.connect(self.compress_thread.requestInterruption)

            # 线程结束时关闭对话框
            self.compress_thread.finished_sig.connect(lambda: self.progress_dialog.close())

            self.compress_thread.start()

    def on_compress_finished(self, success, msg):
        if success:
            self.success(self.tr("压缩任务已完成"))
            self.refreshDirs()
        else:
            # 如果是用户取消，可能 msg 为空或特定消息
            if not self.progress_dialog.wasCanceled():
                QMessageBox.warning(self, self.tr("压缩失败"), msg)

    def rename(self):
        ssh_conn = self.ssh()
        selected_items = self.ui.treeWidget.selectedItems()
        for item in selected_items:
            item_text = item.text(0)
            new_name = QInputDialog.getText(self, self.tr('重命名'), self.tr('请输入新的文件名') + '：',
                                            QLineEdit.Normal, item_text)
            if new_name[1]:
                new_name = new_name[0]
                if getattr(ssh_conn, "is_local", False):
                    old_path = os.path.join(os.path.expanduser(ssh_conn.pwd), item_text)
                    new_path = os.path.join(os.path.expanduser(ssh_conn.pwd), new_name)
                    os.rename(old_path, new_path)
                else:
                    ssh_conn.exec(f'mv {ssh_conn.pwd}/{item_text} {ssh_conn.pwd}/{new_name}')
                self.refreshDirs()

    # 解压
    def unzip(self):
        ssh_conn = self.ssh()
        if not ssh_conn:
            return

        selected_items = self.ui.treeWidget.selectedItems()
        if not selected_items:
            return

        files = []
        for item in selected_items:
            item_text = item.text(0)
            # 使用完整路径，确保解压工具能找到文件
            files.append(f"{ssh_conn.pwd}/{item_text}")

        # 启动线程
        self.decompress_thread = DecompressThread(ssh_conn, files, ssh_conn.pwd)
        self.decompress_thread.finished_sig.connect(self.on_decompress_finished)

        # 进度对话框
        self.progress_dialog = QProgressDialog(self.tr("正在解压..."), self.tr("取消"), 0, 0, self)
        self.progress_dialog.setWindowTitle(self.tr("请稍候"))
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.setMinimumDuration(0)
        self.progress_dialog.canceled.connect(self.decompress_thread.requestInterruption)

        # 线程结束时关闭对话框
        self.decompress_thread.finished_sig.connect(lambda: self.progress_dialog.close())

        self.decompress_thread.start()

    def on_decompress_finished(self, success, msg):
        if success:
            self.success(self.tr("解压任务已完成"))
            self.refreshDirs()
        else:
            if not self.progress_dialog.wasCanceled():
                QMessageBox.warning(self, self.tr("解压失败"), msg)

    # 停止docker容器
    def stopDockerContainer(self, container_ids):
        if container_ids:
            self._start_docker_operation('stop', container_ids)

    # 重启docker容器
    def restartDockerContainer(self, container_ids):
        if container_ids:
            self._start_docker_operation('restart', container_ids)

    # 删除docker容器
    def rmDockerContainer(self, container_ids):
        if container_ids:
            self._start_docker_operation('rm', container_ids)

    # 启动docker容器
    def startDockerContainer(self, container_ids):
        if container_ids:
            self._start_docker_operation('start', container_ids)

    def _start_docker_operation(self, operation, container_ids):
        """启动 Docker 操作线程，操作完成后局部刷新"""
        operation_names = {
            'stop': '停止',
            'restart': '重启',
            'rm': '删除',
            'start': '启动'
        }
        op_name = operation_names.get(operation, operation)

        # 先标记被操作的容器为“操作中”状态
        self._mark_containers_operating(container_ids, f"{op_name}中...")

        # 启动操作线程
        self.docker_op_thread = DockerOperationThread(self.ssh(), operation, container_ids)
        self.docker_op_thread.operation_finished.connect(self._on_docker_operation_finished)
        self.docker_op_thread.start()

    def _mark_containers_operating(self, container_ids, status_text):
        """标记容器为操作中状态（黄色高亮）"""
        tree = self.ui.treeWidgetDocker

        for i in range(tree.topLevelItemCount()):
            project_item = tree.topLevelItem(i)

            # 检查子容器
            for j in range(project_item.childCount()):
                container_item = project_item.child(j)
                if container_item.text(1) in container_ids:
                    container_item.setText(4, status_text)
                    container_item.setBackground(4, QColor(255, 193, 7, 80))

            # 检查顶层容器
            if project_item.text(1) in container_ids:
                project_item.setText(4, status_text)
                project_item.setBackground(4, QColor(255, 193, 7, 80))

    def _update_container_info_in_tree(self, container_info):
        """局部更新容器状态和端口信息"""
        tree = self.ui.treeWidgetDocker

        for i in range(tree.topLevelItemCount()):
            project_item = tree.topLevelItem(i)

            # 检查子容器
            for j in range(project_item.childCount()):
                container_item = project_item.child(j)
                item_id = container_item.text(1)

                if item_id in container_info:
                    info = container_info[item_id]
                    # 更新状态列（第 5 列，索引 4）
                    container_item.setText(4, info['state'])
                    # 更新端口列（第 7 列，索引 6）
                    container_item.setText(6, info['ports'])
                    # 清除高亮背景
                    container_item.setBackground(4, QColor(0, 0, 0, 0))

            # 检查顶层容器
            item_id = project_item.text(1)
            if item_id in container_info:
                info = container_info[item_id]
                project_item.setText(4, info['state'])
                project_item.setText(6, info['ports'])
                project_item.setBackground(4, QColor(0, 0, 0, 0))

    def _remove_containers_from_tree(self, container_ids):
        """从树中移除已删除的容器"""
        tree = self.ui.treeWidgetDocker
        items_to_remove = []

        # 收集要删除的项
        for i in range(tree.topLevelItemCount()):
            project_item = tree.topLevelItem(i)

            # 检查子容器
            for j in range(project_item.childCount() - 1, -1, -1):
                container_item = project_item.child(j)
                if container_item.text(1) in container_ids:
                    items_to_remove.append((project_item, j))

            # 检查顶层容器
            if project_item.text(1) in container_ids:
                items_to_remove.append((None, i))

        # 从后往前删除，避免索引变化
        for parent, index in reversed(items_to_remove):
            if parent:
                parent.removeChild(parent.child(index))
            else:
                tree.takeTopLevelItem(index)

        # 清理空的项目组
        for i in range(tree.topLevelItemCount() - 1, -1, -1):
            project_item = tree.topLevelItem(i)
            # 如果项目组没有子容器且不是独立容器，删除它
            if project_item.childCount() == 0 and not project_item.text(1):
                tree.takeTopLevelItem(i)

    @Slot(bool, str, dict)
    def _on_docker_operation_finished(self, success, operation, container_info):
        """容器操作完成后的回调 - 局部刷新状态和端口"""
        operation_names = {
            'stop': '停止',
            'restart': '重启',
            'rm': '删除',
            'start': '启动'
        }
        op_name = operation_names.get(operation, operation)

        if success:
            if operation == 'rm':
                # 删除操作：从列表中移除容器
                self._remove_containers_from_tree(list(container_info.keys()))
            else:
                # 其他操作：更新状态和端口
                self._update_container_info_in_tree(container_info)
        else:
            # 操作失败，恢复显示并提示错误
            for cid in container_info.keys() if container_info else []:
                self._mark_containers_operating([cid], '操作失败')
            self.alarm(f"容器{op_name}失败")

    # 删除文件夹
    def removeDir(self):
        ssh_conn = self.ssh()
        focus = self.ui.treeWidget.currentIndex().row()
        if focus != -1:
            text = self.ui.treeWidget.topLevelItem(focus).text(0)
            sftp = ssh_conn.open_sftp()
            try:
                sftp.rmdir(ssh_conn.pwd + '/' + text)
                self.refreshDirs()
            except IOError as e:
                util.logger.error(f"Failed to remove directory: {e}")
        pass

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    # 拖拉拽上传文件
    def dropEvent(self, event: QDropEvent):
        try:
            if hasattr(self, 'drag_overlay'):
                self.drag_overlay.hide()
            mime_data = event.mimeData()
            files = []
            if mime_data.hasUrls():
                for url in mime_data.urls():
                    local_path = url.toLocalFile()
                    if os.path.isfile(local_path):
                        files.append(local_path)
            if files:
                # 统一走批量上传接口（与普通上传一致）
                self._start_batch_upload(files)
        except Exception as e:
            util.logger.error(f"dropEvent error: {e}")
            QMessageBox.critical(self, self.tr("上传失败"), self.tr(f"文件上传失败: {e}"))

    def _on_upload_thread_finished(self, thread):
        try:
            if thread in self.active_upload_threads:
                self.active_upload_threads.remove(thread)
        finally:
            try:
                thread.deleteLater()
            except Exception as e:
                util.logger.error(f"Failed to upload file: {e}")
                pass

    def _start_batch_upload(self, files):
        ssh_conn = self.ssh()
        if not ssh_conn or not files:
            return
        self._start_uploads(ssh_conn, files)

    def _start_uploads(self, ssh_conn, files):
        if not hasattr(ssh_conn, 'active_uploads'):
            ssh_conn.active_uploads = set()
        if not hasattr(ssh_conn, 'completed_uploads'):
            ssh_conn.completed_uploads = set()
        if not hasattr(ssh_conn, 'failed_uploads'):
            ssh_conn.failed_uploads = set()

        self.uploader = SFTPUploaderCore(ssh_conn.open_sftp())
        self.progress_adapter = ProgressAdapter()
        self.progress_adapter.connect_signals(self.uploader)

        upload_tasks = []
        progress_bars = {}

        self.ui.download_with_resume.blockSignals(True)

        for local_path in files:
            file_id = str(uuid.uuid4())
            filename = os.path.basename(local_path)
            remote_path = f"{ssh_conn.pwd}/{filename}"

            ssh_conn.active_uploads.add(file_id)

            progress_group = QWidget()
            progress_layout = QHBoxLayout(progress_group)
            progress_layout.setContentsMargins(1, 1, 1, 1)

            label = QLabel(filename)
            progress_bar = QProgressBar()
            progress_bar.setRange(0, 100)

            progress_layout.addWidget(label, 1)
            progress_layout.addWidget(progress_bar, 2)

            self.ui.download_with_resume.addWidget(progress_group)

            progress_bars[file_id] = progress_bar
            self.progress_adapter.register_pyside_progress_bar(file_id, progress_bar, label)

            upload_tasks.append((file_id, local_path, remote_path))

        self.ui.download_with_resume.blockSignals(False)

        for file_id, local_path, remote_path in upload_tasks:
            self.uploader.upload_file(file_id, local_path, remote_path)

        self.progress_bars = progress_bars
        self.uploader.upload_completed.connect(self.on_upload_completed)
        self.uploader.upload_failed.connect(self.on_upload_failed)

    # 信息提示窗口
    def alarm(self, alart):
        """
            创建一个错误消息框，并设置自定义图标
            """
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(self.tr('操作失败'))
        msg_box.setText(f'{alart}')

        # 加载自定义图标
        custom_icon = QIcon(':icons8-fail-48.png')
        pixmap = QPixmap(custom_icon.pixmap(32, 32))

        # 设置消息框图标
        msg_box.setIconPixmap(pixmap)

        # 显示消息框
        msg_box.exec()

    # 成功提示窗口
    @Slot(str)
    def success(self, alart):
        """
        创建一个成功消息框，并设置自定义图标
        """
        if QThread.currentThread() != QCoreApplication.instance().thread():
            QMetaObject.invokeMethod(self, "success", Qt.QueuedConnection, Q_ARG(str, alart))
            return

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(self.tr('操作成功'))
        msg_box.setText(f'{alart}' + self.tr('成功'))

        # 加载自定义图标
        custom_icon = QIcon(':icons8-success-48.png')  # 替换为你的图标路径
        pixmap = QPixmap(custom_icon.pixmap(32, 32))

        # 设置消息框图标
        msg_box.setIconPixmap(pixmap)

        # 显示消息框
        msg_box.exec()

    # 设置主题
    def setDarkTheme(self):
        # self.app.setStyleSheet(qdarkstyle.load_stylesheet(palette=DarkPalette))
        self.app.setStyleSheet(
            qdarktheme.load_stylesheet(
                custom_colors={
                    "[dark]": {
                        "primary": "#00A1FF",
                    }
                },
            )
        )

    def setLightTheme(self):
        # self.app.setStyleSheet(qdarkstyle.load_stylesheet(palette=LightPalette))
        self.app.setStyleSheet(
            qdarktheme.load_stylesheet(
                theme="light",
                custom_colors={
                    "[light]": {
                        "primary": "#E05B00",
                    }
                },
            )
        )

    def applyAppearance(self, appearance: str):
        if str(appearance).lower() == "light":
            self.setLightTheme()
            self.themeChanged.emit(False)
            return
        self.setDarkTheme()
        self.themeChanged.emit(True)

    def toggleTheme(self):
        data = util.read_json(abspath("theme.json"))
        appearance = str(data.get("appearance") or "dark").lower()
        data["appearance"] = "light" if appearance != "light" else "dark"
        util.write_json(abspath("theme.json"), data)
        util.THEME = data
        self.applyAppearance(data["appearance"])

    def _reapply_all_terminal_themes(self):
        for index in range(self.ui.ShellTab.count()):
            terminal = self.get_text_browser_from_tab(index)
            if not terminal or not hasattr(terminal, 'setColorScheme'):
                continue
            # if hasattr(terminal, '_schedule_reapply_color_scheme'):
            #     terminal._schedule_reapply_color_scheme()
            elif hasattr(terminal, 'current_theme_name'):
                terminal.setColorScheme(terminal.current_theme_name)
            else:
                terminal.setColorScheme("Ubuntu")

    def sync_terminal_theme(self, theme_name, exclude_terminal=None):
        """
        同步终端主题到所有打开的终端
        
        :param theme_name: 要应用的主题名称
        :param exclude_terminal: 要排除的终端实例（通常是触发切换的终端，已经应用了主题）
        """
        try:
            for index in range(self.ui.ShellTab.count()):
                terminal = self.get_text_browser_from_tab(index)
                if not terminal or not hasattr(terminal, 'setColorScheme'):
                    continue
                # 跳过触发切换的终端（已经应用了主题）
                if exclude_terminal and terminal is exclude_terminal:
                    continue
                # 更新终端的当前主题名并应用
                terminal.current_theme_name = theme_name
                terminal.setColorScheme(theme_name)
        except Exception as e:
            util.logger.error(f"同步终端主题失败: {e}")

    def on_system_theme_changed(self, is_dark_theme):
        """系统主题切换时，重新应用终端主题"""
        try:
            # 这里写两次是为了避免设置全局主题导致背景不一致而出现闪烁现象
            QTimer.singleShot(0, self._reapply_all_terminal_themes)
            QTimer.singleShot(50, self._reapply_all_terminal_themes)
        except Exception as e:
            util.logger.error(f"Failed to changed system theme: {e}")

    def on_ssh_failed(self, error_msg):
        """SSH连接失败回调"""
        # 确保 UI 操作在主线程
        if QThread.currentThread() != QCoreApplication.instance().thread():
            QMetaObject.invokeMethod(self, "on_ssh_failed", Qt.QueuedConnection, Q_ARG(str, error_msg))
            return

        self._release_connecting_state()
        try:
            QMessageBox.warning(self, self.tr("后台连接失败"),
                                self.tr("后台SSH连接失败，文件管理/监控功能不可用，但终端仍可用。"))
        except Exception:
            pass

    # 获取当前标签页的backend
    def ssh(self):
        current_index = self.ui.ShellTab.currentIndex()
        this = self.ui.ShellTab.tabWhatsThis(current_index)
        if this and this in self.ssh_clients:
            return self.ssh_clients[this]
        return None


class _LocalTransport:
    def set_keepalive(self, _seconds: int):
        return


class _LocalConn:
    def get_transport(self):
        return _LocalTransport()


class _LocalFile:
    def __init__(self, fp):
        self._fp = fp

    def prefetch(self, _offset: int = 0):
        return

    def __getattr__(self, item):
        return getattr(self._fp, item)

    def __enter__(self):
        self._fp.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return self._fp.__exit__(exc_type, exc_val, exc_tb)


class LocalSFTPClient:
    # LocalSFTPClient 用来“模拟” Paramiko SFTPClient 的最小子集，复用项目中现有的：
    # - 下载/上传（download_with_resume / SFTPUploaderCore）
    # - 创建/删除/重命名
    # - 文件读写（sftp.file/sftp.open）
    # 这里不追求 100% API 一致，只覆盖当前代码用到的接口即可。
    def _p(self, path: str) -> str:
        # 把路径统一成当前 OS 的规范路径：
        # - expanduser: 展开 ~
        # - 兼容上层逻辑可能拼出来的 "/" 或 "\\" 分隔符
        # - normpath: 处理 .. 和多余分隔符
        p = os.path.expanduser(str(path))
        p = p.replace("\\", os.sep).replace("/", os.sep)
        return os.path.normpath(p)

    def stat(self, path: str):
        return os.stat(self._p(path))

    def listdir(self, path: str):
        return os.listdir(self._p(path))

    def remove(self, path: str):
        os.remove(self._p(path))

    def rmdir(self, path: str):
        os.rmdir(self._p(path))

    def mkdir(self, path: str):
        os.mkdir(self._p(path))

    def rename(self, oldpath: str, newpath: str):
        os.rename(self._p(oldpath), self._p(newpath))

    def open(self, path: str, mode: str = "rb"):
        return _LocalFile(open(self._p(path), mode))

    def file(self, path: str, mode: str = "rb"):
        return self.open(path, mode)


class LocalClient:
    def __init__(self, pwd: str, name: str = ""):
        self.id = str(uuid.uuid4())
        # 本机连接默认目录使用用户 Home，避免落在项目目录导致体验不一致
        home_dir = str(Path.home())
        self.pwd = pwd or home_dir
        try:
            if not os.path.isdir(self.pwd):
                self.pwd = home_dir
        except Exception:
            self.pwd = home_dir
        self.active = True
        self.close_sig = 1
        self.is_local = True
        self.conn = _LocalConn()
        self._sftp = LocalSFTPClient()
        self._ssh_config_name = name or "local"

    def is_connected(self):
        return bool(self.active)

    def open_sftp(self):
        return self._sftp

    def exec(self, cmd: str = "", pty: bool = False):
        # 注意：LocalClient 不提供“执行任意命令”的能力（不像远程 SSH）。
        # 目前本机模式的需求是：本地终端交互 + 文件树文件操作（走 LocalSFTPClient）。
        # 如果未来需要本机 exec，可在这里实现 subprocess 调用并做好安全限制。
        raise RuntimeError("LocalClient.exec is not supported for generic commands")

    def close(self):
        self.active = False


class SSHConnector(QObject):
    """SSH 连接器 - 内部使用线程实现异步连接"""
    connected = Signal(object)  # 连接成功信号
    failed = Signal(str)  # 连接失败信号

    def __init__(self):
        super().__init__()

    def connect_ssh(self, host, port, username, password, key_type, key_file):
        # 内部启动线程，对外非阻塞，保持调用方代码整洁
        threading.Thread(
            target=self._do_connect,
            args=(host, port, username, password, key_type, key_file),
            daemon=True
        ).start()

    def _do_connect(self, host, port, username, password, key_type, key_file):
        """实际执行连接的线程函数"""
        try:
            ssh_conn = SshClient(host, port, username, password, key_type, key_file)
            ssh_conn.connect()
            self.connected.emit(ssh_conn)
        except Exception as e:
            self.failed.emit(str(e))


# 权限确认
class Auth(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.dial = auth.Ui_Dialog()
        if platform.system() == 'Darwin':
            # 保持弹窗置顶
            # Mac 不设置，弹层会放主窗口的后面
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.dial.setupUi(self)
        self.setWindowIcon(QIcon("Resources/icon.ico"))
        # 同意
        self.dial.buttonBox.accepted.connect(self.ok_auth)
        self.dial.buttonBox.rejected.connect(self.reject)

    # 确认权限
    def ok_auth(self):
        ssh_conn = self.parent().ssh()

        user_r = "r" if self.dial.checkBoxUserR.isChecked() else "-"
        user_w = "w" if self.dial.checkBoxUserW.isChecked() else "-"
        user_x = "x" if self.dial.checkBoxUserX.isChecked() else "-"
        group_r = "r" if self.dial.checkBoxGroupR.isChecked() else "-"
        group_w = "w" if self.dial.checkBoxGroupW.isChecked() else "-"
        group_x = "x" if self.dial.checkBoxGroupX.isChecked() else "-"
        other_r = "r" if self.dial.checkBoxOtherR.isChecked() else "-"
        other_w = "w" if self.dial.checkBoxOtherW.isChecked() else "-"
        other_x = "x" if self.dial.checkBoxOtherX.isChecked() else "-"

        trimmed_new = user_r + user_w + user_x + group_r + group_w + group_x + other_r + other_w + other_x
        # 转换为八进制
        octal = util.symbolic_to_octal(trimmed_new)

        selected_items = self.parent().ui.treeWidget.selectedItems()
        decompress_commands = []
        trimmed_old = ""
        # 先取出所有选中项目
        for item in selected_items:
            # 名字
            item_text = item.text(0)
            # 权限
            trimmed_old = item.text(3)[1:]
            decompress_commands.append(f"chmod {octal} {ssh_conn.pwd}/{item_text}")

        # 有修改才更新
        if trimmed_new != trimmed_old:
            if getattr(ssh_conn, "is_local", False):
                try:
                    mode = int(str(octal), 8)
                except Exception:
                    mode = 0
                for item in selected_items:
                    item_text = item.text(0)
                    try:
                        p = os.path.join(os.path.expanduser(ssh_conn.pwd), item_text)
                        os.chmod(p, mode)
                    except Exception:
                        pass
            else:
                combined_command = " && ".join(decompress_commands)
                ssh_conn.exec(combined_command)
        self.close()
        self.parent().refreshDirs()


# 增加配置逻辑
class AddConfigUi(QDialog):

    def __init__(self):
        super().__init__()
        self.dial = add_config.Ui_addConfig()
        self.dial.setupUi(self)
        if platform.system() == 'Darwin':
            # 保持弹窗置顶
            # Mac 不设置，弹层会放主窗口的后面
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.dial.pushButton_3.setEnabled(False)
        self.dial.lineEdit.setEnabled(False)
        self.setWindowIcon(QIcon("Resources/icon.ico"))
        self.dial.pushButton.clicked.connect(self.addDev)
        self.dial.pushButton_3.clicked.connect(self.addKeyFile)

        self.dial.comboBox.currentIndexChanged.connect(self.handleComboBox)

    def addDev(self):
        name, username, password, ip, prot, private_key_file, private_key_type = self.dial.configName.text(), \
            self.dial.usernamEdit.text(), self.dial.passwordEdit.text(), self.dial.ipEdit.text(), \
            self.dial.protEdit.text(), self.dial.lineEdit.text(), self.dial.comboBox.currentText()

        if name == '':
            self.alarm(self.tr('配置名称不能为空！'))
        elif username == '':
            self.alarm(self.tr('用户名不能为空！'))
        elif password == '' and private_key_type == '':
            self.alarm(self.tr('密码或者密钥必须提供一个！'))
        elif private_key_type != '' and private_key_file == '':
            self.alarm(self.tr('请上传私钥文件！'))
        elif ip == '':
            self.alarm(self.tr('ip地址不能为空！'))
        else:
            config = get_config_path('config.dat')
            with open(config, 'rb') as c:
                conf = pickle.loads(c.read())
                c.close()
            with open(config, 'wb') as c:
                conf[name] = [username, password, f"{ip}:{prot}", private_key_type, private_key_file]
                c.write(pickle.dumps(conf))
                c.close()
            self.close()

    def addKeyFile(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("选择文件"),
            "",
            self.tr("所有文件 (*);;Python 文件 (*.py);;文本文件 (*.txt)"),
        )
        if file_name:
            self.dial.lineEdit.setText(file_name)

    def handleComboBox(self):
        if self.dial.comboBox.currentText():
            self.dial.pushButton_3.setEnabled(True)
            self.dial.lineEdit.setEnabled(True)
        else:
            self.dial.pushButton_3.setEnabled(False)
            self.dial.lineEdit.clear()
            self.dial.lineEdit.setEnabled(False)

    def alarm(self, alart):
        # 修复：确保在主线程中创建 QMessageBox
        if QThread.currentThread() != QCoreApplication.instance().thread():
            QMetaObject.invokeMethod(self, "alarm", Qt.QueuedConnection, Q_ARG(str, alart))
            return

        self.dial.alarmbox = QMessageBox(self)  # 指定父对象
        self.dial.alarmbox.setWindowIcon(QIcon("Resources/icon.ico"))
        self.dial.alarmbox.setText(alart)
        self.dial.alarmbox.setWindowTitle(self.tr('错误提示'))
        self.dial.alarmbox.show()


# 在线文本编辑
class TextEditor(QMainWindow):
    save_tex = Signal(list)

    def __init__(self, title: str, old_text: str):
        super().__init__()
        self.te = text_editor.Ui_MainWindow()
        self.te.setupUi(self)
        self.setWindowIcon(QIcon("Resources/icon.ico"))
        self.setWindowTitle(title)

        self.old_text = old_text

        # 用 CodeEditor 替换原来的 QTextEdit
        self.te.gridLayout.removeWidget(self.te.textEdit)
        self.te.textEdit.deleteLater()

        self.editor = CodeEditor(self)
        self.te.gridLayout.addWidget(self.editor, 0, 0, 1, 1)

        # 初始化语法高亮
        self.highlighter = Highlighter(self.editor.document())

        # 设置初始文本
        self.editor.setPlainText(old_text)
        self.new_text = old_text

        # 初始化查找/替换 UI
        self.setupSearchUI()

        self.timer1 = None
        self.flushNewText()

        self.te.action.triggered.connect(lambda: self.saq(1))
        self.te.action_2.triggered.connect(lambda: self.daq(1))

    def setupSearchUI(self):
        self.searchDock = QDockWidget("查找与替换", self)
        self.searchDock.setAllowedAreas(Qt.BottomDockWidgetArea | Qt.TopDockWidgetArea)

        searchWidget = QWidget()
        layout = QGridLayout(searchWidget)

        self.findInput = QLineEdit()
        self.findInput.setPlaceholderText("查找内容...")
        self.replaceInput = QLineEdit()
        self.replaceInput.setPlaceholderText("替换为...")

        self.caseSensCheck = QCheckBox("区分大小写")
        self.regexCheck = QCheckBox("正则表达式")

        findBtn = QPushButton("查找下一个")
        findBtn.clicked.connect(self.findNext)

        replaceBtn = QPushButton("替换")
        replaceBtn.clicked.connect(self.replace)

        replaceAllBtn = QPushButton("全部替换")
        replaceAllBtn.clicked.connect(self.replaceAll)

        layout.addWidget(QLabel("查找:"), 0, 0)
        layout.addWidget(self.findInput, 0, 1)
        layout.addWidget(findBtn, 0, 2)

        layout.addWidget(QLabel("替换:"), 1, 0)
        layout.addWidget(self.replaceInput, 1, 1)
        layout.addWidget(replaceBtn, 1, 2)
        layout.addWidget(replaceAllBtn, 1, 3)

        layout.addWidget(self.caseSensCheck, 2, 0, 1, 2)
        layout.addWidget(self.regexCheck, 2, 2)

        self.searchDock.setWidget(searchWidget)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.searchDock)

    def findNext(self):
        text = self.findInput.text()
        if not text:
            return
        found = self.editor.find_text(text, self.regexCheck.isChecked(), self.caseSensCheck.isChecked())
        if not found:
            QMessageBox.information(self, self.tr("查找"), self.tr("未找到匹配项"))

    def replace(self):
        text = self.findInput.text()
        new_text = self.replaceInput.text()
        if not text:
            return
        self.editor.replace_text(text, new_text, self.regexCheck.isChecked(), self.caseSensCheck.isChecked())

    def replaceAll(self):
        text = self.findInput.text()
        new_text = self.replaceInput.text()
        if not text:
            return
        count = self.editor.replace_all(text, new_text, self.regexCheck.isChecked(), self.caseSensCheck.isChecked())
        QMessageBox.information(self, self.tr("替换"), self.tr("已替换 {count} 处匹配项").format(count=count))

    def flushNewText(self):
        self.timer1 = QTimer()
        self.timer1.start(100)
        self.timer1.timeout.connect(self.autosave)

    def autosave(self):
        text = self.editor.toPlainText()
        self.new_text = text

    def closeEvent(self, a0: QCloseEvent) -> None:
        if self.new_text != self.old_text:
            a0.ignore()
            self.te.chk = Confirm()
            self.te.chk.cfm.save.clicked.connect(lambda: self.saq(0))
            self.te.chk.cfm.drop.clicked.connect(lambda: self.daq(0))
            self.te.chk.show()
        else:
            pass

    def saq(self, sig):
        self.save_tex.emit([self.new_text, sig])

    def daq(self, sig):
        if sig == 0:
            self.new_text = self.old_text
            self.te.chk.close()
            self.close()
        elif sig == 1:
            self.close()


# 文本编辑确认框
class Confirm(QDialog):
    def __init__(self):
        super().__init__()
        self.cfm = confirm.Ui_confirm()
        self.cfm.setupUi(self)
        self.setWindowIcon(QIcon("Resources/icon.ico"))


class Communicate(QObject):
    # 定义一个无参数的信号，用于通知父窗口刷新
    refresh_parent = Signal()


# 批量结束进程线程
class KillProcessThread(QThread):
    success_sig = Signal(str)
    warning_sig = Signal(str, str)
    update_sig = Signal()

    def __init__(self, ssh, command, pids_args, original_pids):
        super().__init__()
        self.ssh = ssh
        self.command = command
        self.pids_args = pids_args
        self.original_pids = original_pids

    def run(self):
        try:
            if not self.ssh:
                return
            # 1. 发送终止信号
            self.ssh.conn.exec_command(self.command, timeout=10)

            # 2. 循环检测进程是否结束
            # 使用更通用的 shell 命令检测：遍历 PID，如果 kill -0 成功(进程存在)则输出该 PID
            # 这种方式兼容性更好，不仅限于支持 ps -p 的系统
            check_cmd = f"for pid in {self.pids_args}; do kill -0 $pid 2>/dev/null && echo $pid; done"

            # 初始化为 None，区分"未检测"和"空列表"
            remaining_pids = None

            # 使用 while 循环持续检测
            # 设置 30 秒超时保护，防止进程无法结束导致死循环
            start_time = time.time()
            timeout = 30

            while True:
                try:
                    stdin, stdout, stderr = self.ssh.conn.exec_command(check_cmd, timeout=5)
                    # 获取仍然存活的 PID
                    alive_output = stdout.read().decode('utf-8').strip()

                    if not alive_output:
                        # 没有输出意味着没有进程存活
                        remaining_pids = []
                        break

                    remaining_pids = alive_output.split()
                except Exception as e:
                    util.logger.error(f"Kill process error: {e}")
                    pass

                if time.time() - start_time > timeout:
                    break

                time.sleep(0.5)

            # 刷新列表
            self.update_sig.emit()

            if remaining_pids is None:
                # 无法确认进程状态（可能是检测命令执行失败）
                self.warning_sig.emit("无法验证进程状态", "无法确认进程是否已结束，请手动刷新列表查看。")
            elif not remaining_pids:
                # 所有进程都已消失，验证成功
                self.success_sig.emit(f"进程 {self.original_pids} 已成功终止")
            else:
                # 仍有进程存在
                alive_str = ", ".join(remaining_pids)
                self.warning_sig.emit("部分进程未结束", f"以下进程仍在运行 (可能需要强制结束): {alive_str}")

        except Exception as e:
            self.warning_sig.emit("执行终止命令失败", str(e))
            # 发生异常也要刷新
            self.update_sig.emit()


class CustomWidget(QWidget):
    def __init__(self, key, item, ssh_conn, parent=None):
        super().__init__(parent)

        self.docker = None

        self.layout = QVBoxLayout()

        # 创建图标标签
        icon_label = QLabel(self)
        icon = f":{key}_128.png"
        icon = QIcon(icon)  # 替换为你的图标路径
        pixmap = icon.pixmap(60, 60)  # 获取图标的 QPixmap
        icon_label.setPixmap(pixmap)
        icon_label.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(icon_label)

        # 创建按钮布局
        self.button_layout = QHBoxLayout()

        if not item['has']:
            # 安装按钮
            self.install_button = QPushButton(self.tr("安装"), self)
            self.install_button.setCursor(QCursor(Qt.PointingHandCursor))
            self.install_button.clicked.connect(lambda: self.container_orchestration(ssh_conn))
            self.install_button.setStyleSheet(InstallButtonStyle)
            self.button_layout.addWidget(self.install_button)
        else:
            # 安装按钮
            self.install_button = QPushButton(self.tr("已安装"), self)
            self.install_button.setCursor(QCursor(Qt.PointingHandCursor))
            self.install_button.setStyleSheet(InstalledButtonStyle)
            self.install_button.setDisabled(True)
            self.button_layout.addWidget(self.install_button)

        self.layout.addLayout(self.button_layout)
        self.setLayout(self.layout)

        # 设置样式表为小块添加边框
        self.setStyleSheet("""
            QWidget
            {
                border - radius: 5px;
            padding: 5
            px;
            }
            QPushButton
            {
                background - color: rgb(50, 115, 245);
            border - radius: 5
            px;
            padding: 5
            px;
            }
            QPushButton: pressed
            {
                background - color: darkgray;
            }
            """)

    def show_install_docker_window(self, item, ssh_conn):
        """
        点击安装按钮，展示安装docker窗口
        : param
        item: 数据对象
        :param
        ssh_conn: ssh
        连接对象
        :
    return:
    """

        self.docker = InstallDocker(item, ssh_conn)
        self.docker.dial.lineEdit_containerName.setText(item['containerName'])
        self.docker.dial.lineEdit_Image.setText(item['image'])

        volumes = ""
        environment_variables = ""
        labels = ""
        ports = ""
        for port in item['ports']:
            ports += "-p " + port['source'] + ":" + port['destination'] + " "
        self.docker.dial.lineEdit_ports.setText(ports)

        for bind in item['volumes']:
            volumes += "-v " + bind.get('destination') + ":" + bind.get('source') + " "
        self.docker.dial.lineEdit_volumes.setText(volumes)

        for env in item['environmentVariables']:
            environment_variables += "-e " + env.get('name') + "=" + env.get('value') + " "
        self.docker.dial.lineEdit_environmentVariables.setText(environment_variables)

        for label in item['labels']:
            labels += "--" + label.get('name') + "=" + label.get('value') + " "
        self.docker.dial.lineEdit_labels.setText(labels)

        if item['containerName']:
            self.docker.dial.checkBox_privileged.setChecked(True)

        self.docker.communicate.refresh_parent.connect(lambda: self.refresh(item, ssh_conn))
        self.docker.show()

    def container_orchestration(self, ssh_conn):
        compose = DockerComposeEditor(ssh=ssh_conn)
        compose.show()

    def refresh(self, item, ssh_conn):
        # 安装按钮
        self.install_button.setText(self.tr("已安装"))
        self.install_button.setStyleSheet("background-color: rgb(102, 221, 121);")
        self.install_button.setDisabled(True)


# docker容器安装
class InstallDocker(QDialog):
    def __init__(self, item, ssh_conn):
        super().__init__()
        self.dial = docker_install.Ui_Dialog()
        self.dial.setupUi(self)
        self.setWindowIcon(QIcon(":icons8-docker-48.png"))
        # 取消
        self.dial.buttonBoxDockerInstall.rejected.connect(self.reject)
        # 安装
        self.dial.buttonBoxDockerInstall.accepted.connect(lambda: self.installDocker(item, ssh_conn))

        # 创建一个 Communicate 实例
        self.communicate = Communicate()
        # 在对话框关闭时发射信号
        self.finished.connect(self.onFinished)

    @Slot(int)
    def onFinished(self, result):
        # 当对话框关闭时发射信号
        self.communicate.refresh_parent.emit()

    def installDocker(self, item, ssh_conn):
        try:
            container_name = self.dial.lineEdit_containerName.text()
            image = self.dial.lineEdit_Image.text()
            volumes = self.dial.lineEdit_volumes.text()
            environment = self.dial.lineEdit_environmentVariables.text()
            labels = self.dial.lineEdit_labels.text()
            ports = self.dial.lineEdit_ports.text()
            cmd_ = item['cmd']

            formatter = HtmlFormatter(style='rrt', noclasses=True)

            privileged = ""
            if self.dial.checkBox_privileged.isChecked():
                privileged = "--privileged=true"

            cmd1 = "docker pull " + image
            ack = ssh_conn.exec(cmd=cmd1, pty=False)
            highlighted = highlight(ack, BashLexer(), formatter)
            self.dial.textBrowserDockerInout.append(highlighted)
            if ack:
                #  创建宿主机挂载目录
                cmd_volumes = ""
                for bind in item['volumes']:
                    cmd_volumes += f"mkdir -p " + bind.get('destination') + " "
                ssh_conn.exec(cmd=cmd_volumes, pty=False)

                # 创建临时容器
                image_str = f"{image}".split(":", 1)
                ports_12_chars = f"{ports}"[:12]
                cmd2 = f"docker run {ports_12_chars} --name {container_name} -d {image_str[0]}"
                ack = ssh_conn.exec(cmd=cmd2, pty=False)
                # 睡眠一秒
                time.sleep(1)
                highlighted = highlight(ack, BashLexer(), formatter)
                self.dial.textBrowserDockerInout.append(highlighted)
                if ack:
                    for bind in item['volumes']:
                        source = bind.get('source')
                        cp = bind.get('cp')
                        cmd3 = f"docker cp {container_name}:{source}/ {cp}" + " "
                        ack = ssh_conn.exec(cmd=cmd3, pty=False)
                        highlighted = highlight(ack, BashLexer(), formatter)
                        self.dial.textBrowserDockerInout.append(highlighted)

                    cmd_stop = f"docker stop {container_name}"
                    ack = ssh_conn.exec(cmd=cmd_stop, pty=False)
                    # 删除临时容器
                    if ack:
                        cmd4 = f"docker rm {container_name}"
                        ack = ssh_conn.exec(cmd=cmd4, pty=False)
                        self.dial.textBrowserDockerInout.append(ack)

            cmd = f"docker run -d --name {container_name} {environment} {ports} {volumes} {labels} {privileged} {image} {cmd_}"
            ack = ssh_conn.exec(cmd=cmd, pty=False)
            highlighted = highlight(ack, BashLexer(), formatter)
            self.dial.textBrowserDockerInout.append(highlighted)

        except Exception as e:
            util.logger.error(f"安装失败：{e}")
            return 'error'


class TunnelConfig(QDialog):
    """

    初始化配置对话框并设置UI元素值；
    监听UI变化以更新SSH命令；
    提供复制SSH命令和保存配置功能
    """

    def __init__(self, parent, data):
        super(TunnelConfig, self).__init__(parent)

        # 保存隧道名称，用于保存时更新 JSON 文件
        self._tunnel_name = None

        self.ui = Ui_TunnelConfig()
        self.ui.setupUi(self)

        icon_ssh = QIcon()
        icon_ssh.addFile(u":icons8-ssh-48.png", QSize(), QIcon.Mode.Selected, QIcon.State.On)
        with open(get_config_path('config.dat'), 'rb') as c:
            dic = pickle.loads(c.read())
            c.close()
        for k in dic.keys():
            self.ui.comboBox_ssh.addItem(icon_ssh, k)

        tunnel_type = data.get(KEYS.TUNNEL_TYPE)
        self.ui.comboBox_tunnel_type.setCurrentText(tunnel_type)
        self.ui.comboBox_ssh.setCurrentText(data.get(KEYS.DEVICE_NAME))
        self.ui.remote_bind_address_edit.setText(data.get(KEYS.REMOTE_BIND_ADDRESS))
        if tunnel_type == "动态":
            self.ui.remote_bind_address_edit.hide()
            self.ui.label_remote_bind_address_edit.hide()
        else:
            self.ui.remote_bind_address_edit.show()
            self.ui.label_remote_bind_address_edit.show()
        self.ui.local_bind_address_edit.setText(data.get(KEYS.LOCAL_BIND_ADDRESS))
        self.ui.browser_open.setText(data.get(KEYS.BROWSER_OPEN))
        self.ui.copy.clicked.connect(self.do_copy_ssh_command)
        self.ui.comboBox_tunnel_type.currentIndexChanged.connect(self.readonly_remote_bind_address_edit)

        # 连接保存按钮到保存方法
        self.ui.buttonBox.accepted.disconnect()  # 断开原有的连接
        self.ui.buttonBox.accepted.connect(self.save_config)

    def set_tunnel_name(self, name):
        """设置隧道名称，用于保存时更新配置"""
        self._tunnel_name = name

    def save_config(self):
        """保存隧道配置到 JSON 文件"""
        if not self._tunnel_name:
            QMessageBox.warning(self, self.tr("保存失败"), self.tr("隧道名称未设置"))
            return

        # 验证本地绑定地址
        local = self.ui.local_bind_address_edit.text().strip()
        if not local or ':' not in local:
            QMessageBox.warning(self, self.tr("警告"), self.tr("本地绑定地址格式不正确，请使用 host:port 格式"))
            return

        # 验证远程绑定地址（非动态模式）
        tunnel_type = self.ui.comboBox_tunnel_type.currentText()
        remote = self.ui.remote_bind_address_edit.text().strip()
        if tunnel_type != "动态":
            if not remote or ':' not in remote:
                QMessageBox.warning(self, self.tr("警告"), self.tr("远程绑定地址格式不正确，请使用 host:port 格式"))
                return

        try:
            file_path = get_config_path('tunnel.json')
            # 读取 JSON 文件内容
            data = util.read_json(file_path)
            # 更新配置
            data[self._tunnel_name] = self.as_dict()
            # 将修改后的数据写回 JSON 文件
            util.write_json(file_path, data)

            # 关闭对话框
            self.accept()

            # 刷新父窗口的隧道列表
            parent = self.parent()
            if parent and hasattr(parent, 'parent') and parent.parent():
                main_window = parent.parent()
                if hasattr(main_window, 'tunnel_refresh'):
                    util.clear_grid_layout(main_window.ui.gridLayout_tunnel_tabs)
                    util.clear_grid_layout(main_window.ui.gridLayout_kill_all)
                    main_window.tunnel_refresh()

        except Exception as e:
            util.logger.error(f"Error saving tunnel config: {e}")
            QMessageBox.warning(self, self.tr("保存失败"), str(e))

    def readonly_remote_bind_address_edit(self):
        tunnel_type = self.ui.comboBox_tunnel_type.currentText()
        if tunnel_type == "动态":
            self.ui.remote_bind_address_edit.hide()
            self.ui.label_remote_bind_address_edit.hide()
        else:
            self.ui.remote_bind_address_edit.show()
            self.ui.label_remote_bind_address_edit.show()

    def render_ssh_command(self):
        text = self.ui.local_bind_address_edit.text()
        ssh = self.ui.comboBox_ssh.currentText()
        username, password, host, key_type, key_file = open_data(ssh)
        if not util.check_server_accessibility(host.split(':')[0], int(host.split(':')[1])):
            QMessageBox.warning(self, self.tr("连接超时"), self.tr("服务器无法连接，请检查网络或服务器状态"))
            return

        ssh_command = (f"ssh -L {int(text.split(':')[1])}:{self.ui.remote_bind_address_edit.text()} "
                       f"{username}@{host.split(':')[0]}")
        self.ui.ssh_command.setText(ssh_command)

    def do_copy_ssh_command(self):
        clipboard = QApplication.clipboard()
        clipboard.setText(self.ui.ssh_command.text())

    def as_dict(self):
        return {
            KEYS.TUNNEL_TYPE: self.ui.comboBox_tunnel_type.currentText(),
            KEYS.BROWSER_OPEN: self.ui.browser_open.text(),
            KEYS.DEVICE_NAME: self.ui.comboBox_ssh.currentText(),
            KEYS.REMOTE_BIND_ADDRESS: self.ui.remote_bind_address_edit.text(),
            KEYS.LOCAL_BIND_ADDRESS: self.ui.local_bind_address_edit.text(),
        }


class AddTunnelConfig(QDialog):
    """
    初始化配置对话框并设置UI元素值；
    监听UI变化以更新SSH命令；
    提供复制SSH命令和
    """

    def __init__(self, parent=None):
        super(AddTunnelConfig, self).__init__(parent)

        self.tunnel = Ui_AddTunnelConfig()
        self.tunnel.setupUi(self)

        icon_ssh = QIcon()
        icon_ssh.addFile(u":icons8-ssh-48.png", QSize(), QIcon.Mode.Selected, QIcon.State.On)
        with open(get_config_path('config.dat'), 'rb') as c:
            dic = pickle.loads(c.read())
            c.close()
        for k in dic.keys():
            self.tunnel.comboBox_ssh.addItem(icon_ssh, k)

        self.tunnel.add_tunnel.accepted.connect(self.addTunnel)
        self.tunnel.add_tunnel.rejected.connect(TunnelConfig.reject)
        self.tunnel.comboBox_tunnel_type.currentIndexChanged.connect(self.readonly_remote_bind_address_edit)

    def addTunnel(self):

        remote = self.tunnel.remote_bind_address_edit.text()
        tunnel_type = self.tunnel.comboBox_tunnel_type.currentText()
        if remote == '' and tunnel_type != '动态':
            QMessageBox.critical(self, self.tr("警告"), self.tr("请填写远程绑定地址"))
            return
        split = remote.split(':')
        if len(split) != 2 and tunnel_type != '动态':
            QMessageBox.critical(self, self.tr("警告"), self.tr("远程绑定地址格式不正确，请检查"))
            return

        local = self.tunnel.local_bind_address_edit.text()
        if local == '':
            QMessageBox.critical(self, self.tr("警告"), self.tr("请填写本地绑定地址"))
            return
        local_split = local.split(':')
        if len(local_split) != 2:
            QMessageBox.critical(self, self.tr("警告"), self.tr("本地绑定地址格式不正确，请检查"))
            return
        if self.tunnel.ssh_tunnel_name.text() == '':
            QMessageBox.critical(self, self.tr("警告"), self.tr("请填写隧道名称"))
            return

        dic = {
            KEYS.TUNNEL_TYPE: self.tunnel.comboBox_tunnel_type.currentText(),
            KEYS.BROWSER_OPEN: self.tunnel.browser_open.text(),
            KEYS.DEVICE_NAME: self.tunnel.comboBox_ssh.currentText(),
            KEYS.REMOTE_BIND_ADDRESS: self.tunnel.remote_bind_address_edit.text(),
            KEYS.LOCAL_BIND_ADDRESS: self.tunnel.local_bind_address_edit.text(),
        }

        file_path = get_config_path('tunnel.json')
        # 读取 JSON 文件内容
        data = util.read_json(file_path)
        data[self.tunnel.ssh_tunnel_name.text()] = dic

        # 将修改后的数据写回 JSON 文件
        util.write_json(file_path, data)
        self.close()

        util.clear_grid_layout(self.parent().ui.gridLayout_tunnel_tabs)
        util.clear_grid_layout(self.parent().ui.gridLayout_kill_all)

        self.parent().tunnel_refresh()

    def readonly_remote_bind_address_edit(self):
        tunnel_type = self.tunnel.comboBox_tunnel_type.currentText()
        if tunnel_type == "动态":
            self.tunnel.remote_bind_address_edit.hide()
            self.tunnel.label_remote_bind_address_edit.hide()
        else:
            self.tunnel.remote_bind_address_edit.show()
            self.tunnel.label_remote_bind_address_edit.show()


class Tunnel(QWidget):
    """
    创建单个隧道实例，包括启动、停止隧道以及打开浏览器的功能。
    """

    def __init__(self, name, data, parent=None):
        super(Tunnel, self).__init__(parent)

        self.ui = Ui_Tunnel()
        self.ui.setupUi(self)
        self.manager = ForwarderManager()

        self.tunnelconfig = TunnelConfig(self, data)
        self.tunnelconfig.set_tunnel_name(name)  # 设置隧道名称，用于保存配置
        self.tunnelconfig.setWindowTitle(name)
        self.tunnelconfig.setModal(True)
        self.ui.name.setText(name)

        self.tunnelconfig.icon = F":{name}.png"

        if not os.path.exists(self.tunnelconfig.icon):
            self.tunnelconfig.icon = ICONS.TUNNEL

        self.ui.icon.setPixmap(QPixmap(self.tunnelconfig.icon))
        self.ui.action_tunnel.clicked.connect(self.do_tunnel)
        self.ui.action_settings.clicked.connect(self.show_tunnel_config)
        self.ui.action_open.clicked.connect(self.do_open_browser)
        self.ui.delete_ssh.clicked.connect(lambda: self.delete_tunnel(parent))

        self.process = False

    # 打开修改页面
    def show_tunnel_config(self):
        self.tunnelconfig.render_ssh_command()
        self.tunnelconfig.show()

    def do_open_browser(self):
        browser_open = self.tunnelconfig.ui.browser_open.text()
        if browser_open:
            QDesktopServices.openUrl(QUrl(browser_open))

    def do_tunnel(self):
        if self.process:
            try:
                self.stop_tunnel()
            except Exception as e:
                util.logger.error(f"Error stopping tunnel: {e}")
                QMessageBox.warning(self, self.tr("停止隧道失败"), str(e))
        else:
            try:
                self.start_tunnel()
            except Exception as e:
                util.logger.error(f"Error starting tunnel: {e}")
                QMessageBox.warning(self, self.tr("启动隧道失败"), str(e))
        # 隧道操作完成后刷新 UI 状态
        self.update_ui()

    def update_ui(self):
        if self.process:
            self.ui.action_tunnel.setIcon(QIcon(ICONS.STOP))
        else:
            self.ui.action_tunnel.setIcon(QIcon(ICONS.START))

    def start_tunnel(self):
        type_ = self.tunnelconfig.ui.comboBox_tunnel_type.currentText()
        ssh = self.tunnelconfig.ui.comboBox_ssh.currentText()

        if not ssh:
            raise ValueError("请先选择 SSH 服务器")

        # 本地服务器地址
        local_bind_address = self.tunnelconfig.ui.local_bind_address_edit.text().strip()
        if not local_bind_address or ':' not in local_bind_address:
            raise ValueError("本地绑定地址格式错误，请使用 host:port 格式，例如 localhost:1080")

        try:
            local_host, local_port = local_bind_address.split(':')[0], int(local_bind_address.split(':')[1])
        except (ValueError, IndexError):
            raise ValueError("本地绑定地址端口必须是数字")

        # 获取SSH信息
        ssh_user, ssh_password, host, key_type, key_file = open_data(ssh)

        if not host or ':' not in host:
            raise ValueError(f"SSH 服务器配置错误，请检查 '{ssh}' 的配置")

        ssh_host, ssh_port = host.split(':')[0], int(host.split(':')[1])

        if not ssh_user:
            raise ValueError("用户名不能为空")

        tunnel, ssh_client, transport = None, None, None
        tunnel_id = self.ui.name.text()
        if type_ == '本地':
            remote_bind_address = self.tunnelconfig.ui.remote_bind_address_edit.text()
            remote_host, remote_port = remote_bind_address.split(':')[0], int(remote_bind_address.split(':')[1])
            # 启动本地转发隧道
            tunnel, ssh_client, transport = self.manager.start_tunnel(tunnel_id, 'local', local_host, local_port,
                                                                      remote_host, remote_port, ssh_host, ssh_port,
                                                                      ssh_user, ssh_password, key_type, key_file)
        if type_ == '远程':
            remote_bind_address = self.tunnelconfig.ui.remote_bind_address_edit.text()
            remote_host, remote_port = remote_bind_address.split(':')[0], int(remote_bind_address.split(':')[1])
            # 启动远程转发隧道
            tunnel, ssh_client, transport = self.manager.start_tunnel(tunnel_id, 'remote', local_host, local_port,
                                                                      remote_host, remote_port, ssh_host, ssh_port,
                                                                      ssh_user, ssh_password, key_type, key_file)
        if type_ == '动态':
            # 启动动态转发隧道
            tunnel, ssh_client, transport = self.manager.start_tunnel(tunnel_id, 'dynamic', local_host, local_port,
                                                                      ssh_host=ssh_host, ssh_port=ssh_port,
                                                                      ssh_user=ssh_user, ssh_password=ssh_password,
                                                                      key_type=key_type, key_file=key_file)

        self.manager.add_tunnel(tunnel_id, tunnel)
        self.manager.ssh_clients[ssh_client] = transport
        if transport:
            self.process = True

        self.ui.action_tunnel.setIcon(QIcon(ICONS.STOP))
        self.do_open_browser()

    def stop_tunnel(self):
        try:
            name_text = self.ui.name.text()
            self.manager.remove_tunnel(name_text)
            self.process = False

        except Exception as e:
            util.logger.error(f"Error stopping process: {e}")
        self.ui.action_tunnel.setIcon(QIcon(ICONS.START))

    # 删除隧道
    def delete_tunnel(self, parent):

        # 创建消息框
        reply = QMessageBox()
        reply.setWindowTitle(self.tr('确认删除'))
        reply.setText(self.tr('您确定要删除此隧道吗？这将无法恢复！'))
        reply.setStandardButtons(QMessageBox.Yes | QMessageBox.No)

        # 设置按钮文本为中文
        yes_button = reply.button(QMessageBox.Yes)
        no_button = reply.button(QMessageBox.No)
        yes_button.setText(self.tr("确定"))
        no_button.setText(self.tr("取消"))
        # 显示对话框并等待用户响应
        reply.exec()

        if reply.clickedButton() == yes_button:
            name_text = self.ui.name.text()
            file_path = get_config_path('tunnel.json')
            # 读取 JSON 文件内容
            data = util.read_json(file_path)
            del data[name_text]
            # 将修改后的数据写回 JSON 文件
            util.write_json(file_path, data)
            # 刷新隧道列表
            util.clear_grid_layout(parent.ui.gridLayout_tunnel_tabs)
            util.clear_grid_layout(parent.ui.gridLayout_kill_all)
            parent.tunnel_refresh()
        else:
            pass


def open_data(ssh):
    with open(get_config_path('config.dat'), 'rb') as c:
        conf = pickle.loads(c.read())[ssh]
    if len(conf) == 3:
        # 3 元素配置：username, password, host
        return conf[0], conf[1], conf[2], '', ''
    else:
        # 5 元素配置：username, password, host, key_type, key_file
        return conf[0], conf[1], conf[2], conf[3], conf[4]


# 初始化配置文件
def init_config():
    config = get_config_path('config.dat')
    if not os.path.exists(config):
        with open(config, 'wb') as c:
            start_dic = {}
            c.write(pickle.dumps(start_dic))
            c.close()


def get_config_directory(app_name):
    """
    获取用户配置目录并创建它（如果不存在）
    :param
    app_name: 应用名字
    :return:
    """
    # 使用 appdirs 获取跨平台的配置目录
    config_dir = appdirs.user_config_dir(app_name, appauthor=False)

    # 创建配置目录（如果不存在）
    os.makedirs(config_dir, exist_ok=True)

    return config_dir


def migrate_existing_configs(app_name):
    """
    迁移现有配置文件（初次运行）
    :param
    app_name: 应用名字
    :return:
    """
    current_dir = os.path.dirname(os.path.abspath(__file__))
    new_conf_dir = get_config_directory(app_name)

    # 列出要迁移的文件
    files_to_migrate = ["config.dat", "tunnel.json"]

    for file_name in files_to_migrate:
        old_file_path = os.path.join(current_dir, 'conf', file_name)
        new_file_path = os.path.join(new_conf_dir, file_name)

        if os.path.exists(old_file_path) and not os.path.exists(new_file_path):
            util.logger.info(f"Copying {old_file_path} to {new_file_path}")
            shutil.copy2(old_file_path, new_file_path)  # 使用 copy2 复制文件并保留元数据


def get_config_path(file_name):
    """
    获取配置文件
    :param
    file_name: 文件名
    :return:
    """
    return os.path.join(get_config_directory(util.APP_NAME), file_name)


# 自定义QTermWidget类，使用内置功能
class _SuggestionPopup(QFrame):
    def __init__(self, owner):
        """
        智能提示候选弹窗（非激活式）。

        设计目标：
        - 展示补全候选但不抢占终端焦点，避免 QMenu 抢焦点导致的闪烁与输入卡顿
        - 支持鼠标选择与键盘上下选择
        - 默认不选中任何候选，避免用户直接回车执行命令时误触发补全
        """
        super().__init__(None)
        # 轻量、非激活式的提示弹窗：展示补全候选但不抢占终端焦点，
        # 避免“弹窗抢焦点 -> 终端失焦 -> 弹窗关闭”的闪烁，并保证输入流畅。
        self._owner = owner
        self._interacting = False
        self._sig = None
        self._has_user_selection = False
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFrameShape(QFrame.Box)
        self.setLineWidth(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)

        self.list = QListWidget(self)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.list.setSelectionMode(QListWidget.SingleSelection)
        self.list.setFocusPolicy(Qt.NoFocus)
        self.list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.list)

        self.setStyleSheet("""
            QFrame {
                background-color: #2d2d30;
                color: #d4d4d4;
                border: 1px solid #3c3c3c;
                border-radius: 3px;
            }
            QListWidget {
                background-color: transparent;
                border: 0px;
                outline: 0px;
            }
            QListWidget::item {
                padding: 6px 10px;
            }
            QListWidget::item:selected {
                background-color: #094771;
                color: white;
            }
        """)

    def enterEvent(self, event):
        """鼠标移入弹窗时标记为交互中，用于暂停候选自动刷新。"""
        self._interacting = True
        return super().enterEvent(event)

    def leaveEvent(self, event):
        """鼠标移出弹窗时结束交互状态。"""
        self._interacting = False
        return super().leaveEvent(event)

    def isInteracting(self) -> bool:
        """是否处于用户交互状态（鼠标悬停在候选弹窗内）。"""
        return bool(self._interacting)

    def updateSuggestions(self, items: list[dict]):
        """
        更新候选列表内容。

        items: [{kind: "history"|"token", text: "..."}]
        """
        # 候选集合没变时不重建列表，减少 UI 更新开销。
        sig = tuple((str(it.get("kind") or ""), str(it.get("text") or "")) for it in items[:20])
        if sig == self._sig and self.isVisible():
            return
        self._sig = sig
        self._has_user_selection = False

        self.list.setUpdatesEnabled(False)
        try:
            self.list.clear()
            for it in items[:20]:
                text = str(it.get("text") or "")
                kind = str(it.get("kind") or "")
                label = text
                if kind == "history":
                    label = f"{text}"
                item = QListWidgetItem(label)
                item.setData(Qt.UserRole, it)
                self.list.addItem(item)
            # 不默认选中第一条，只有用户显式上下选择/点击后才选中。
            self.list.setCurrentRow(-1)
        finally:
            self.list.setUpdatesEnabled(True)

        fm = self.list.fontMetrics()
        max_w = 180
        for i in range(self.list.count()):
            t = self.list.item(i).text()
            max_w = max(max_w, fm.horizontalAdvance(t) + 36)
        visible_rows = min(8, max(1, self.list.count()))
        row_h = self.list.sizeHintForRow(0) if self.list.count() else fm.height() + 10
        self.list.setFixedHeight(visible_rows * row_h + 4)
        self.setFixedWidth(min(520, max_w))

    def hasUserSelection(self) -> bool:
        """是否存在用户显式选择的候选（鼠标点击或上下键导航）。"""
        try:
            if not self._has_user_selection:
                return False
            return self.list.currentRow() >= 0
        except Exception:
            return False

    def selectNext(self):
        # 弹窗可见时由终端按键处理触发，用于向下选择候选。
        if self.list.count() <= 0:
            return
        row = self.list.currentRow()
        if row < 0:
            row = 0
        else:
            row = min(self.list.count() - 1, row + 1)
        self._has_user_selection = True
        self.list.setCurrentRow(row)

    def selectPrev(self):
        # 弹窗可见时由终端按键处理触发，用于向上选择候选。
        if self.list.count() <= 0:
            return
        row = self.list.currentRow()
        if row < 0:
            row = self.list.count() - 1
        else:
            row = max(0, row - 1)
        self._has_user_selection = True
        self.list.setCurrentRow(row)

    def applyCurrentIfSelected(self) -> bool:
        """
        仅当用户显式选中过候选时应用当前候选。

        返回值：
        - True：应用了候选（需要消费回车事件）
        - False：没有用户选择（不应消费回车事件，让终端执行默认回车行为）
        """
        # 只有用户显式选中过候选（鼠标点击或上下键导航）才应用，避免回车误触发补全。
        if not self.hasUserSelection():
            return False
        item = self.list.currentItem()
        if not item:
            return False
        payload = item.data(Qt.UserRole) or {}
        self._owner._apply_suggestion(payload)
        self.hide()
        return True

    def popupAt(self, global_pos: QPoint):
        """在全局坐标位置弹出候选窗口。"""
        self.move(global_pos)
        self.show()
        self.raise_()

    def _on_item_clicked(self, item):
        """鼠标点击某条候选时应用该候选。"""
        try:
            self._has_user_selection = True
            payload = item.data(Qt.UserRole) or {}
            self._owner._apply_suggestion(payload)
        finally:
            self.hide()


class SSHQTermWidget(QTermWidget):
    """
    自定义QTermWidget，使用内置的右键菜单和复制粘贴功能
    """

    def __init__(self, parent=None):
        # startnow=0，不自动启动shell
        super().__init__(0, parent)

        # [New] Install event filter to intercept TerminalDisplay wheel events
        if hasattr(self, 'm_impl') and hasattr(self.m_impl, 'm_terminalDisplay'):
            self.m_impl.m_terminalDisplay.installEventFilter(self)

        # 缓存剪贴板
        self._clipboard = QApplication.clipboard()

        # 缓存图标
        self._action_icons = {
            'copy': QIcon(":copy.png"),
            'paste': QIcon(":paste.png"),
            'clear': QIcon(":clear.png")
        }

        # 记录当前主题 - 从配置文件读取持久化的主题，如果没有则使用默认值 "Ubuntu"
        self.current_theme_name = (util.THEME or {}).get("terminal_theme", "Ubuntu")
        self._theme_reapply_pending = False

        self._prompt_index = {"commands": [], "options": {}}
        self._prompt_commands = []
        self._prompt_options = {}
        self._prompt_completer = None
        self._prompt_commands_sorted = []
        self._prompt_options_sorted = {}
        self._input_buffer = ""
        self._last_delete_ts = 0.0
        self._suggest_timer = QTimer(self)
        self._suggest_timer.setSingleShot(True)
        self._suggest_timer.timeout.connect(self._auto_show_suggestions)
        self._suggest_popup = _SuggestionPopup(self)
        self._suggest_last_input = ""
        self._history_path = get_config_path("command_history.json")
        self._history_data = {"global": [], "by_profile": {}}
        try:
            self._history_data = self._load_history_data()
        except Exception:
            self._history_data = {"global": [], "by_profile": {}}
        try:
            self.termKeyPressed.connect(self._on_term_key_pressed)
        except Exception:
            pass
        try:
            self._prompt_index = load_linux_commands()
            self._prompt_commands = list(self._prompt_index.get("commands") or [])
            self._prompt_options = dict(self._prompt_index.get("options") or {})
            self._prompt_commands_sorted = sorted(self._prompt_commands)
            self._prompt_options_sorted = {}
            for k, v in self._prompt_options.items():
                if isinstance(v, list):
                    self._prompt_options_sorted[k] = sorted(v)
                elif isinstance(v, set):
                    self._prompt_options_sorted[k] = sorted(list(v))
                else:
                    self._prompt_options_sorted[k] = []
        except Exception as e:
            util.logger.error(f"加载命令索引失败: {e}")

        # 设置语法高亮支持
        self.setup_syntax_highlighting()

        # 初始化主题
        self.setColorScheme(self.current_theme_name)
        # 开启抑制程序背景色 （让应用的背景色不要覆盖终端背景，只保留前景色/少量高亮信息）。
        if hasattr(self, "setSuppressProgramBackgroundColors"):
            self.setSuppressProgramBackgroundColors(True)

        sys_name = platform.system()
        if sys_name == "Darwin":
            self._shortcut_copy = QShortcut(QKeySequence.Copy, self)
            self._shortcut_copy.setContext(Qt.WidgetWithChildrenShortcut)
            self._shortcut_copy.activated.connect(self._on_copy_shortcut)

            self._shortcut_paste = QShortcut(QKeySequence.Paste, self)
            self._shortcut_paste.setContext(Qt.WidgetWithChildrenShortcut)
            self._shortcut_paste.activated.connect(self._on_paste_shortcut)
        else:
            self._shortcut_copy = QShortcut(QKeySequence("Ctrl+Shift+C"), self)
            self._shortcut_copy.setContext(Qt.WidgetWithChildrenShortcut)
            self._shortcut_copy.activated.connect(self._on_copy_shortcut)

            self._shortcut_paste = QShortcut(QKeySequence("Ctrl+Shift+V"), self)
            self._shortcut_paste.setContext(Qt.WidgetWithChildrenShortcut)
            self._shortcut_paste.activated.connect(self._on_paste_shortcut)

    def eventFilter(self, obj, event):
        """事件过滤：处理 Ctrl+滚轮 缩放等终端显示层事件"""
        # Check if the event is from the internal terminal display
        if hasattr(self, 'm_impl') and hasattr(self.m_impl,
                                               'm_terminalDisplay') and obj == self.m_impl.m_terminalDisplay:
            if event.type() == QEvent.Wheel:
                if event.modifiers() & Qt.ControlModifier:
                    # Forward to main window for zoom
                    parent = self.window()
                    if hasattr(parent, 'zoom_in') and hasattr(parent, 'zoom_out'):
                        QTermWidget.setColorScheme(self, self.current_theme_name)
                        delta = event.angleDelta().y()
                        if delta > 0:
                            parent.zoom_in()
                        elif delta < 0:
                            parent.zoom_out()
                        return True  # 消费事件，避免继续传递给终端
            if event.type() == QEvent.KeyPress:
                try:
                    popup = getattr(self, "_suggest_popup", None)
                    if popup and popup.isVisible():
                        # 仅在提示弹窗可见时拦截“导航/选择”按键；隐藏时所有按键交给终端。
                        key = event.key()
                        if key == Qt.Key_Up:
                            popup.selectPrev()
                            it = popup.list.currentItem()
                            if it:
                                popup.list.scrollToItem(it)
                            return True
                        if key == Qt.Key_Down:
                            popup.selectNext()
                            it = popup.list.currentItem()
                            if it:
                                popup.list.scrollToItem(it)
                            return True
                        if key in (Qt.Key_Return, Qt.Key_Enter):
                            applied = popup.applyCurrentIfSelected()
                            if applied:
                                self._hide_suggestions_menu()
                                return True
                            self._hide_suggestions_menu()
                            return False
                        if key == Qt.Key_Escape:
                            self._hide_suggestions_menu()
                            return True
                except Exception:
                    pass
        return super().eventFilter(obj, event)

    def _on_copy_shortcut(self):
        try:
            if self.selectedText(True):
                self.copyClipboard()
        except Exception:
            pass

    def _on_paste_shortcut(self):
        try:
            self.pasteClipboard()
        except Exception:
            pass

    def _on_term_key_pressed(self, event):
        """
        终端按键事件（来自 QTermWidget.termKeyPressed）。

        只做与智能提示相关的“轻量输入跟踪”：
        - 维护 _input_buffer（尽力而为，不保证覆盖远端 shell 的所有编辑行为）
        - 控制提示弹窗显示/隐藏
        - 记录历史命令（优先从屏幕提取真实命令行）
        """
        try:
            if self._should_disable_command_suggestions():
                self._hide_suggestions_menu()
                return

            key = event.key()
            mods = event.modifiers()

            if (mods & Qt.ControlModifier) and key == Qt.Key_Space:
                self._show_suggestions_menu()
                return

            if key in (Qt.Key_Return, Qt.Key_Enter):
                cmdline = self._get_commandline_for_history()
                if cmdline:
                    self._add_history_entry(cmdline)
                self._input_buffer = ""
                self._hide_suggestions_menu()
                return

            if key in (Qt.Key_Backspace, Qt.Key_Delete):
                # 长按删除键会产生高频重复事件；此时持续计算/刷新提示会明显卡顿。
                # 直接隐藏弹窗并暂停提示计算，保证终端输入删除顺滑。
                self._input_buffer = self._input_buffer[:-1]
                self._last_delete_ts = time.time()
                self._hide_suggestions_menu()
                return

            if key == Qt.Key_Escape:
                self._hide_suggestions_menu()
                return

            if key in (
                    Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down, Qt.Key_Home, Qt.Key_End, Qt.Key_PageUp,
                    Qt.Key_PageDown):
                self._hide_suggestions_menu()
                return

            if mods & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
                self._hide_suggestions_menu()
                return

            text = event.text() or ""
            if text and text.isprintable():
                # 本地维护一个“尽力而为”的输入缓冲用于轻量提示。
                # 当远端 shell 自己做 Tab 补全时，本地缓冲可能偏离，稍后会从屏幕同步一次。
                self._input_buffer += text
                if text == " ":
                    self._hide_suggestions_menu()
                    return
                if time.time() - getattr(self, "_last_delete_ts", 0.0) > 0.25:
                    self._schedule_suggestions()
            elif key == Qt.Key_Tab and mods == Qt.NoModifier:
                # Tab 补全由远端 shell 完成；等待屏幕更新后，从渲染行同步本地缓冲。
                QTimer.singleShot(60, self._sync_input_buffer_from_screen)
        except Exception:
            pass

    def _should_disable_command_suggestions(self) -> bool:
        """
        是否需要禁用智能命令提示。

        当终端进入 alternate screen（如 vim/less/top 等全屏 TUI）时，
        不应弹出“命令补全”提示，避免干扰编辑/交互。
        """
        try:
            session = getattr(self.m_impl, "m_session", None)
            if not session:
                return False
            emu = session.emulation() if hasattr(session, "emulation") else None
            if emu and hasattr(emu, "getMode"):
                return bool(emu.getMode(MODE_AppScreen))
        except Exception:
            return False
        return False

    def _current_line_before_cursor(self) -> str:
        """
        获取光标所在行在光标前的文本。

        用于在远端 shell 通过 Tab 等方式修改输入后，从屏幕同步出“真实输入”。
        """
        try:
            display = self.m_impl.m_terminalDisplay
            line = display.inputMethodQuery(Qt.InputMethodQuery.ImSurroundingText) or ""
            cursor_x = display.inputMethodQuery(Qt.InputMethodQuery.ImCursorPosition)
            try:
                cursor_x = int(cursor_x)
            except Exception:
                cursor_x = len(line)
            if cursor_x < 0:
                cursor_x = 0
            return line[:cursor_x]
        except Exception:
            return ""

    def _extract_command_from_prompt(self, line_before_cursor: str) -> str:
        # 基于提示符的启发式剥离：从当前光标行提取“真实命令行”。
        # 当输入被远端 shell 功能（例如 Tab 补全）修改时，这能显著提升历史记录准确性。
        s = (line_before_cursor or "").rstrip("\r\n")
        if not s:
            return ""
        markers = ["$ ", "# ", "> ", "❯ ", "➜ "]
        best = -1
        best_len = 0
        for m in markers:
            i = s.rfind(m)
            if i > best:
                best = i
                best_len = len(m)
        if best >= 0:
            return s[best + best_len:].strip()
        return s.strip()

    def _get_commandline_for_history(self) -> str:
        """用于写入历史命令的命令行提取：优先从屏幕提取，失败再回退到本地缓冲。"""
        try:
            line = self._current_line_before_cursor()
            cmd = self._extract_command_from_prompt(line)
            if cmd:
                return cmd
        except Exception:
            pass
        return (self._input_buffer or "").strip()

    def _sync_input_buffer_from_screen(self):
        """从屏幕当前行同步本地输入缓冲，用于修正 Tab 补全等导致的偏差。"""
        try:
            line = self._current_line_before_cursor()
            cmd = self._extract_command_from_prompt(line)
            if cmd:
                self._input_buffer = cmd
        except Exception:
            pass

    def _get_history_key(self) -> str:
        """获取历史分组键：默认 global；如存在 ssh 配置名则按配置名分组。"""
        name = getattr(self, "_ssh_config_name", None)
        if not name:
            return "global"
        return str(name)

    def _load_history_data(self) -> dict:
        """加载本地历史命令 JSON 文件（不存在/异常时返回默认结构）。"""
        try:
            if not os.path.exists(self._history_path):
                return {"global": [], "by_profile": {}}
            with open(self._history_path, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            g = data.get("global") or []
            bp = data.get("by_profile") or {}
            if not isinstance(g, list):
                g = []
            if not isinstance(bp, dict):
                bp = {}
            return {"global": g, "by_profile": bp}
        except Exception:
            return {"global": [], "by_profile": {}}

    def _save_history_data(self):
        """持久化写入历史命令 JSON 文件。"""
        try:
            os.makedirs(os.path.dirname(self._history_path), exist_ok=True)
            with open(self._history_path, "w", encoding="utf-8") as f:
                json.dump(self._history_data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def _add_history_entry(self, cmdline: str):
        """新增一条历史命令（去重、头插、限制长度），同时写入全局与 profile 历史。"""
        try:
            cmd = (cmdline or "").strip()
            if not cmd:
                return
            data = self._history_data if isinstance(self._history_data, dict) else {"global": [], "by_profile": {}}
            g = data.get("global") or []
            if not isinstance(g, list):
                g = []
            g = [x for x in g if x != cmd]
            g.insert(0, cmd)
            g = g[:500]
            data["global"] = g

            key = self._get_history_key()
            bp = data.get("by_profile") or {}
            if not isinstance(bp, dict):
                bp = {}
            lst = bp.get(key) or []
            if not isinstance(lst, list):
                lst = []
            lst = [x for x in lst if x != cmd]
            lst.insert(0, cmd)
            lst = lst[:200]
            bp[key] = lst
            data["by_profile"] = bp

            self._history_data = data
            self._save_history_data()
        except Exception:
            pass

    def _history_suggestions(self, prefix: str) -> list[str]:
        """按前缀匹配历史命令候选（profile 优先，其次 global），并去重限制数量。"""
        p = (prefix or "").strip()
        if not p:
            return []
        data = self._history_data if isinstance(self._history_data, dict) else {"global": [], "by_profile": {}}
        key = self._get_history_key()
        bp = data.get("by_profile") or {}
        profile = bp.get(key) or []
        global_hist = data.get("global") or []
        out = []
        seen = set()
        for src in (profile, global_hist):
            for s in src:
                if not isinstance(s, str):
                    continue
                if not s.startswith(p):
                    continue
                if s == p:
                    continue
                if s in seen:
                    continue
                seen.add(s)
                out.append(s)
                if len(out) >= 20:
                    return out
        return out

    def _current_last_token(self) -> str:
        """提取当前输入最后一个 token（用于 token 级候选替换）。"""
        s = (self._input_buffer or "")
        if not s or s.endswith((" ", "\t")):
            return ""
        m = re.search(r"(\S+)$", s)
        return m.group(1) if m else ""

    def _apply_suggestion(self, payload: dict):
        """
        应用一条候选到终端输入。

        规则：
        - kind=history：替换整行输入（先退格清空，再写入完整历史命令）
        - kind=token：替换最后一个 token（退格删除 token，再写入候选）
        """
        try:
            kind = str(payload.get("kind") or "")
            value = str(payload.get("text") or "")
            if not value:
                return

            buf = self._input_buffer or ""

            if kind == "history":
                erase_len = len(buf)
                if erase_len:
                    self.sendText("\x7f" * erase_len)
                self.sendText(value)
                self._input_buffer = value
                return

            last_token = self._current_last_token()
            erase_len = len(last_token)
            if erase_len:
                self.sendText("\x7f" * erase_len)
                buf = buf[:-erase_len]
            self.sendText(value)
            self._input_buffer = f"{buf}{value}"

            stripped = (self._input_buffer or "").strip()
            if " " not in stripped and value in set(self._prompt_commands):
                self.sendText(" ")
                self._input_buffer += " "
        except Exception:
            pass

    def setColorScheme(self, name):
        """重写 setColorScheme，保存主题并在底层设置"""
        self.current_theme_name = name
        super().setColorScheme(name)

    def setup_syntax_highlighting(self):
        """设置语法高亮支持"""

        # 设置适合代码显示的字体
        self.setup_code_font()

        # 设置自定义高亮过滤器 (WindTerm 风格)
        self.setup_custom_filters()

    def setup_custom_filters(self):
        """设置自定义高亮过滤器"""
        try:

            display = self.m_impl.m_terminalDisplay
            filter_chain = display._filter_chain

            # 1. 权限字符串高亮 (drwxr-xr-x)
            perm_filter = PermissionHighlightFilter()
            filter_chain.addFilter(perm_filter)

            # 2. 数字高亮 (紫色)
            # 匹配独立的数字或者文件大小等，但不匹配包含数字的文件名（如 file1.txt, 123.log）
            number_filter = HighlightFilter(r'(?<!\S)\d+(?!\S)', QColor("#bd93f9"), None)
            filter_chain.addFilter(number_filter)

            # 3. 日期时间高亮 (绿色)
            # 匹配像 "Nov 29" 或 "11:30" 或 "2025-11-29"
            date_filter = HighlightFilter(
                r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d+\b|\b\d{2}:\d{2}\b|\b\d{4}-\d{2}-\d{2}\b',
                QColor("#50fa7b"), None
            )
            filter_chain.addFilter(date_filter)

            # 4. 压缩包文件名高亮 (天蓝色)
            # 匹配 .zip, .tar.gz, .rar 等
            # archive_filter = HighlightFilter(
            #     r'\b[\w\-\.]+\.(?:zip|tar\.gz|tgz|rar|7z|gz|bz2|xz)\b',
            #     QColor("#8be9fd"), None
            # )
            # filter_chain.addFilter(archive_filter)

            # 命令行关键字高亮
            cmd_filter = HighlightFilter(
                r'(?<![\w\-])(?:sudo\s+)?(?:ls|cd|vi|vim|cat|grep|tail|head|tar|zip|unzip|ssh|scp|find|chmod|chown|ps'
                r'|kill|ss|systemctl|docker|service|journalctl|top|htop|netstat|ip|ifconfig)\b',
                QColor("#00A1FF"), None
            )
            filter_chain.addFilter(cmd_filter)

            opt_filter = HighlightFilter(r'(?<!\w)(--?[a-zA-Z0-9][\w\-]*)', QColor("#f1c40f"), None)
            filter_chain.addFilter(opt_filter)

            path_filter = HighlightFilter(r'(?:^|[\s;])((?:/[^ \t\n]+|~[^ \t\n]+))', QColor("#8be9fd"), None)
            filter_chain.addFilter(path_filter)

            ip_filter = HighlightFilter(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', QColor("#e67e22"), None)
            filter_chain.addFilter(ip_filter)

            url_filter = HighlightFilter(r'\bhttps?://[^\s]+\b', QColor("#3498db"), None)
            filter_chain.addFilter(url_filter)

            err_filter = HighlightFilter(
                r'(command not found|No such file or directory|Permission denied|not recognized)', QColor("#e74c3c"),
                None)
            filter_chain.addFilter(err_filter)

        except Exception as e:
            util.logger.error(f"Failed to setup custom filters: {e}")

    def setup_code_font(self):
        """设置适合代码显示的字体"""
        # 优先使用用户配置的字体
        saved_font = util.THEME.get('font', '')
        current_size = util.THEME.get('font_size', 14)

        available_families = set(QFontDatabase.families())

        # 如果用户配置了字体且可用，直接使用
        if saved_font and saved_font in available_families:
            font = QFont(saved_font, current_size)
            if hasattr(self, 'setTerminalFont'):
                self.setTerminalFont(font)
                print(f"使用用户配置字体: {saved_font}, 大小: {current_size}")
                return

        # 否则使用默认字体优先级列表
        fonts_to_try = [
            "JetBrains Mono",
            "Fira Code",
            "Source Code Pro",
            "Consolas",
            "Monaco",
            "Menlo",
            "DejaVu Sans Mono",
            "Liberation Mono",
            "Courier New"
        ]

        for font_name in fonts_to_try:
            if font_name in available_families:
                font = QFont(font_name, current_size)
                if font.exactMatch():
                    if hasattr(self, 'setTerminalFont'):
                        self.setTerminalFont(font)
                        print(f"使用代码字体: {font_name}")
                        return

        # 使用系统默认等宽字体
        font = QFont("monospace", current_size)
        font.setStyleHint(QFont.Monospace)
        if hasattr(self, 'setTerminalFont'):
            self.setTerminalFont(font)
            print("使用系统默认等宽字体")

    def _compute_suggestions(self, text: str) -> list[str]:
        """基于静态命令/选项索引进行前缀匹配，返回候选列表。"""
        s = (text or "").lstrip()
        if not s:
            return list(self._prompt_commands_sorted or self._prompt_commands)
        parts = s.split()
        if not parts:
            return list(self._prompt_commands_sorted or self._prompt_commands)
        if len(parts) == 1:
            prefix = parts[0]
            if not prefix:
                return list(self._prompt_commands_sorted or self._prompt_commands)
            lst = self._prompt_commands_sorted or self._prompt_commands
            lo = bisect_left(lst, prefix)
            hi = bisect_left(lst, prefix + "\uffff")
            return lst[lo:min(hi, lo + 80)]
        cmd = parts[0]
        last = parts[-1]
        if last.startswith("-"):
            opts = self._prompt_options_sorted.get(cmd) or self._prompt_options.get(cmd) or []
            if not isinstance(opts, list):
                try:
                    opts = list(opts)
                except Exception:
                    opts = []
            lo = bisect_left(opts, last)
            hi = bisect_left(opts, last + "\uffff")
            return opts[lo:min(hi, lo + 80)]
        return []

    def _hide_suggestions_menu(self):
        """隐藏提示弹窗并重置本次输入的提示状态。"""
        popup = getattr(self, "_suggest_popup", None)
        if popup:
            try:
                popup.hide()
            except Exception:
                pass
        self._suggest_last_input = ""

    def _schedule_suggestions(self):
        """启动防抖定时器，延迟触发候选计算与弹窗显示。"""
        try:
            if self._should_disable_command_suggestions():
                return
            if hasattr(self, "_suggest_timer") and self._suggest_timer:
                self._suggest_timer.start(300)
        except Exception:
            pass

    def _get_suggestion_items(self, text: str) -> list[dict]:
        """
        生成候选列表（结构化数据）。

        候选来源顺序：
        1) 历史命令（整行）优先
        2) 静态索引候选（token 级）
        """
        s = (text or "").lstrip()
        items: list[dict] = []
        seen = set()

        for h in self._history_suggestions(s):
            if h in seen:
                continue
            seen.add(h)
            items.append({"kind": "history", "text": h})
            if len(items) >= 20:
                return items

        sugg = self._compute_suggestions(s)
        last_token = ""
        if s and not s.endswith((" ", "\t")):
            m = re.search(r"(\S+)$", s)
            last_token = m.group(1) if m else ""

        candidates = sugg
        if last_token:
            candidates = [x for x in sugg if x.startswith(last_token)]
        if not candidates:
            candidates = sugg

        for x in candidates:
            if x in seen:
                continue
            seen.add(x)
            items.append({"kind": "token", "text": x})
            if len(items) >= 20:
                break

        return items

    def _auto_show_suggestions(self):
        """定时器回调：根据当前输入决定是否显示/更新提示弹窗。"""
        try:
            popup = getattr(self, "_suggest_popup", None)
            if popup and popup.isVisible() and popup.isInteracting():
                return
            if self._should_disable_command_suggestions():
                self._hide_suggestions_menu()
                return

            display_has_focus = False
            try:
                display_has_focus = bool(self.m_impl.m_terminalDisplay.hasFocus())
            except Exception:
                display_has_focus = False

            if not (self.hasFocus() or display_has_focus):
                self._hide_suggestions_menu()
                return

            text = (self._input_buffer or "").lstrip()
            if not text:
                self._hide_suggestions_menu()
                return

            items = self._get_suggestion_items(text)
            if not items:
                self._hide_suggestions_menu()
                return

            if text == getattr(self, "_suggest_last_input", "") and popup and popup.isVisible():
                return
            self._suggest_last_input = text
            self._show_suggestions_menu()
        except Exception:
            pass

    def _show_suggestions_menu(self):
        """计算候选并在光标附近弹出提示窗口。"""
        text = (self._input_buffer or "").lstrip()
        items = self._get_suggestion_items(text)
        if not items:
            self._hide_suggestions_menu()
            return

        popup = getattr(self, "_suggest_popup", None)
        if not popup:
            return
        try:
            popup.updateSuggestions(items)
        except Exception:
            return

        try:
            display = self.m_impl.m_terminalDisplay
            rect = display.inputMethodQuery(Qt.InputMethodQuery.ImCursorRectangle)
            p = display.mapToGlobal(rect.bottomLeft())
            popup.popupAt(p)
        except Exception:
            popup.popupAt(QCursor.pos())

    def contextMenuEvent(self, event):
        """优化的右键菜单实现"""
        try:
            # 创建右键菜单，不依赖filterActions
            menu = QMenu(self)

            # 添加自定义功能
            self._add_custom_actions(menu)

            # 显示菜单
            menu.exec(event.globalPos())

        except Exception as e:
            util.logger.error(f"右键菜单创建失败: {e}")

    def _add_custom_actions(self, menu):
        """添加自定义动作到菜单"""

        # 复制操作 - 使用QTermWidget内置方法
        copy_action = QAction(self._action_icons['copy'], self.tr("复制"), self)
        copy_action.setIconVisibleInMenu(True)
        # copy_action.setShortcut("Ctrl+C")
        copy_action.triggered.connect(self.copyClipboard)
        menu.addAction(copy_action)

        # 粘贴操作 - 使用QTermWidget内置方法
        paste_action = QAction(self._action_icons['paste'], self.tr("粘贴"), self)
        paste_action.setIconVisibleInMenu(True)
        # paste_action.setShortcut("Ctrl+V")
        paste_action.triggered.connect(self.pasteClipboard)
        paste_action.setEnabled(bool(self._clipboard.text()))
        menu.addAction(paste_action)

        menu.addSeparator()

        # 清屏操作 - 使用QTermWidget内置方法
        clear_action = QAction(self._action_icons['clear'], self.tr("清屏"), self)
        clear_action.setIconVisibleInMenu(True)
        clear_action.triggered.connect(self.clear)
        menu.addAction(clear_action)

        # 添加主题相关选项
        menu.addSeparator()

        # 终端主题切换
        theme_action = QAction(self.tr("🎨 切换终端主题"), self)
        theme_action.triggered.connect(self.show_theme_selector)
        menu.addAction(theme_action)

        menu.addSeparator()
        ai_menu = menu.addMenu(self.tr("🤖 AI"))
        explain_action = QAction(self.tr("解释文本"), self)
        explain_action.triggered.connect(lambda: open_ai_dialog(self, "explain"))
        ai_menu.addAction(explain_action)

        script_action = QAction(self.tr("编写脚本"), self)
        script_action.triggered.connect(lambda: open_ai_dialog(self, "script"))
        ai_menu.addAction(script_action)

        install_action = QAction(self.tr("软件环境"), self)
        install_action.triggered.connect(lambda: open_ai_dialog(self, "install"))
        ai_menu.addAction(install_action)

        log_action = QAction(self.tr("日志分析"), self)
        log_action.triggered.connect(lambda: open_ai_dialog(self, "log"))
        ai_menu.addAction(log_action)

    def show_theme_selector(self):
        """显示增强的主题选择器"""
        try:
            dialog = TerminalThemeSelector(self)
            dialog.theme_selected.connect(self.apply_theme)
            dialog.exec()
        except Exception as e:
            util.logger.error(f"显示主题选择器失败: {e}")

    def get_theme_descriptions(self):
        """获取主题描述"""
        return {
            "Breeze": "现代简洁风格 (推荐)",
            "DarkPastels": "暗色柔和风格 (推荐)",
            "Solarized Dark": "专业暗色主题 (推荐)",
            "Solarized Light": "专业亮色主题 (推荐)",
            "Linux": "Linux经典风格",
            "WhiteOnBlack": "经典黑底白字",
            "BlackOnWhite": "传统白底黑字",
            "GreenOnBlack": "经典绿色终端",
            "BlackOnLightYellow": "淡黄底黑字",
            "DarkPicture": "暗色图片风格",
            "LightPicture": "亮色图片风格",
            "Tango": "Tango配色方案",
            "Vintage": "复古风格",
            "Monokai": "Monokai经典",
            "Ubuntu": "Ubuntu默认风格",
        }

    def apply_theme(self, theme_name):
        """应用终端主题并持久化保存"""
        try:
            # 应用主题
            self.setColorScheme(theme_name)

            # 持久化保存主题到配置文件
            try:
                theme_file = abspath("theme.json")
                data = util.read_json(theme_file)
                data["terminal_theme"] = theme_name
                util.write_json(theme_file, data)
                util.THEME = data
            except Exception as save_err:
                util.logger.error(f"保存终端主题配置失败: {save_err}")

            # 同步主题到所有其他打开的终端
            try:
                main_window = self.window()
                if main_window and hasattr(main_window, 'sync_terminal_theme'):
                    main_window.sync_terminal_theme(theme_name, exclude_terminal=self)
            except Exception as sync_err:
                util.logger.error(f"同步终端主题失败: {sync_err}")

        except Exception as e:
            QMessageBox.warning(
                self,
                "错误",
                f"切换主题失败: {e}"
            )

    def get_recommended_themes(self):
        """获取推荐的主题列表"""
        # 推荐的主题，按优先级排序
        recommended = [
            "Breeze",  # KDE现代主题
            "DarkPastels",  # 暗色柔和主题
            "Solarized Dark",  # 专业暗色主题
            "Solarized Light",  # 专业亮色主题
            "Linux",  # Linux经典主题
            "WhiteOnBlack",  # 经典黑白主题
            "BlackOnWhite",  # 白底黑字主题
            "GreenOnBlack",  # 绿色经典主题
        ]

        # 获取可用主题
        try:
            available = self.availableColorSchemes()

            # 返回推荐主题中可用的
            recommended_available = []
            for theme in recommended:
                if theme in available:
                    recommended_available.append(theme)

            # 添加其他可用主题
            for theme in available:
                if theme not in recommended_available:
                    recommended_available.append(theme)

            return recommended_available

        except Exception as e:
            util.logger.error(f"获取推荐主题失败: {e}")
            return []


class LanguageSettingsDialog(QDialog):
    """语言设置对话框 - 支持多国语言选择"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._selected_language = ""
        self.setup_ui()
        self.load_languages()

    def setup_ui(self):
        """设置 UI"""
        self.setWindowTitle(self.tr("语言设置"))
        self.setMinimumSize(400, 500)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)

        # 标题
        title_label = QLabel(self.tr("选择应用程序语言"))
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(title_label)

        # 说明
        desc_label = QLabel(self.tr("更改语言后需要重启应用程序才能生效"))
        desc_label.setStyleSheet("color: gray; margin-bottom: 10px;")
        layout.addWidget(desc_label)

        # 搜索框
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(self.tr("搜索语言..."))
        self.search_edit.textChanged.connect(self.filter_languages)
        layout.addWidget(self.search_edit)

        # 语言列表
        self.language_list = QListWidget()
        self.language_list.setAlternatingRowColors(True)
        self.language_list.itemDoubleClicked.connect(self.on_item_double_clicked)
        layout.addWidget(self.language_list, 1)

        # 当前语言显示
        current_lang = (util.THEME or {}).get("language", "zh_CN")
        current_lang_name = self._get_language_name(current_lang)
        self.current_label = QLabel(self.tr("当前语言: ") + current_lang_name)
        self.current_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        layout.addWidget(self.current_label)

        # 按钮
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        cancel_btn = QPushButton(self.tr("取消"))
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        ok_btn = QPushButton(self.tr("确定"))
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self.on_accept)
        button_layout.addWidget(ok_btn)

        layout.addLayout(button_layout)

    def load_languages(self):
        """加载语言列表"""
        current_lang = (util.THEME or {}).get("language", "zh_CN")

        for lang_code, english_name, native_name in SUPPORTED_LANGUAGES:
            # 显示格式: 原生名称 (English Name)
            display_text = f"{native_name}  ({english_name})"

            item = QListWidgetItem(display_text)
            item.setData(Qt.UserRole, lang_code)

            # 标记当前语言
            if lang_code == current_lang:
                item.setText(f"✓ {display_text}")
                font = item.font()
                font.setBold(True)
                item.setFont(font)

            self.language_list.addItem(item)

        # 选中当前语言
        for i in range(self.language_list.count()):
            item = self.language_list.item(i)
            if item.data(Qt.UserRole) == current_lang:
                self.language_list.setCurrentItem(item)
                break

    def filter_languages(self, text):
        """过滤语言列表"""
        text = text.lower()
        for i in range(self.language_list.count()):
            item = self.language_list.item(i)
            item_text = item.text().lower()
            lang_code = item.data(Qt.UserRole).lower()

            # 搜索匹配显示文本或语言代码
            visible = text in item_text or text in lang_code
            item.setHidden(not visible)

    def _get_language_name(self, lang_code):
        """获取语言名称"""
        for code, english_name, native_name in SUPPORTED_LANGUAGES:
            if code == lang_code:
                return native_name
        return lang_code

    def on_item_double_clicked(self, item):
        """双击选择语言"""
        self._selected_language = item.data(Qt.UserRole)
        self.accept()

    def on_accept(self):
        """确认选择"""
        current_item = self.language_list.currentItem()
        if current_item:
            self._selected_language = current_item.data(Qt.UserRole)
            self.accept()
        else:
            QMessageBox.warning(self, self.tr("警告"), self.tr("请选择一种语言"))

    def get_selected_language(self):
        """获取选择的语言代码"""
        return self._selected_language


class TerminalThemeSelector(QDialog):
    """增强的终端主题选择器对话框"""

    theme_selected = Signal(str)  # 主题选择信号

    def __init__(self, terminal_widget, parent=None):
        super().__init__(parent)
        self.terminal_widget = terminal_widget
        self.current_theme = ""
        self.setup_ui()
        self.load_themes()

    def setup_ui(self):
        """设置用户界面"""
        self.setWindowTitle("🎨 终端主题选择器")
        self.setFixedSize(600, 500)
        self.setModal(True)

        # 主布局
        layout = QVBoxLayout(self)

        # 标题
        title_label = QLabel("🌈 选择您喜欢的终端主题")
        title_label.setStyleSheet("""
            QLabel {
                font-size: 18px;
                font-weight: bold;
                padding: 10px;
                color: #2c3e50;
                background-color: #ecf0f1;
                border-radius: 5px;
                margin-bottom: 10px;
            }
        """)
        layout.addWidget(title_label)

        # 主题网格布局
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        scroll_widget = QWidget()
        self.grid_layout = QGridLayout(scroll_widget)
        self.grid_layout.setSpacing(10)

        scroll_area.setWidget(scroll_widget)
        layout.addWidget(scroll_area)

        # 按钮布局
        button_layout = QHBoxLayout()

        self.preview_btn = QPushButton("🔍 预览")
        self.preview_btn.setEnabled(False)
        self.preview_btn.clicked.connect(self.preview_theme)

        self.apply_btn = QPushButton("✅ 应用")
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self.apply_theme)

        cancel_btn = QPushButton("❌ 取消")
        cancel_btn.clicked.connect(self.reject)

        button_layout.addWidget(self.preview_btn)
        button_layout.addWidget(self.apply_btn)
        button_layout.addStretch()
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)

        # 设置对话框样式
        self.setStyleSheet("""
            QDialog {
                background-color: #f8f9fa;
            }
            QPushButton {
                padding: 8px 16px;
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:enabled {
                background-color: #3498db;
                color: white;
            }
            QPushButton:disabled {
                background-color: #bdc3c7;
                color: #7f8c8d;
            }
            QPushButton:hover:enabled {
                background-color: #2980b9;
            }
        """)

    def load_themes(self):
        """加载可用主题"""
        try:
            # 获取当前主题
            try:
                self.current_theme = self.terminal_widget.colorScheme()
            except:
                self.current_theme = "未知"

            # 获取推荐主题
            themes = self.terminal_widget.get_recommended_themes()
            descriptions = self.terminal_widget.get_theme_descriptions()

            # 创建主题按钮
            row, col = 0, 0
            max_cols = 3

            self.theme_buttons = {}

            for theme in themes:
                btn = self.create_theme_button(theme, descriptions.get(theme, ""))
                self.grid_layout.addWidget(btn, row, col)
                self.theme_buttons[theme] = btn

                col += 1
                if col >= max_cols:
                    col = 0
                    row += 1

            # 高亮当前主题
            if self.current_theme in self.theme_buttons:
                self.highlight_current_theme()

        except Exception as e:
            util.logger.error(f"加载主题失败: {e}")

    def create_theme_button(self, theme_name, description):
        """创建主题按钮"""
        btn = QPushButton()
        btn.setFixedSize(180, 80)
        btn.setCheckable(True)

        # 设置按钮文本
        text = f"{theme_name}"
        if description:
            text += f"\n{description}"
        btn.setText(text)

        # 设置样式
        btn.setStyleSheet("""
            QPushButton {
                text-align: center;
                border: 2px solid #bdc3c7;
                border-radius: 8px;
                background-color: white;
                color: #2c3e50;
                font-size: 11px;
                padding: 5px;
            }
            QPushButton:hover {
                border-color: #3498db;
                background-color: #ecf0f1;
            }
            QPushButton:checked {
                border-color: #e74c3c;
                background-color: #fdf2f2;
                color: #c0392b;
                font-weight: bold;
            }
        """)

        # 连接信号
        btn.clicked.connect(lambda checked, name=theme_name: self.select_theme(name))

        return btn

    def highlight_current_theme(self):
        """高亮显示当前主题"""
        if self.current_theme in self.theme_buttons:
            btn = self.theme_buttons[self.current_theme]
            btn.setStyleSheet(btn.styleSheet() + """
                QPushButton {
                    border-color: #27ae60;
                    background-color: #d5f4e6;
                    color: #27ae60;
                }
            """)

    def select_theme(self, theme_name):
        """选择主题"""
        # 取消其他按钮的选中状态
        for btn in self.theme_buttons.values():
            btn.setChecked(False)

        # 选中当前按钮
        if theme_name in self.theme_buttons:
            self.theme_buttons[theme_name].setChecked(True)

        self.selected_theme = theme_name
        self.preview_btn.setEnabled(True)
        self.apply_btn.setEnabled(True)

    def preview_theme(self):
        """预览主题"""
        if hasattr(self, 'selected_theme'):
            # 临时应用主题
            original_theme = self.current_theme
            self.terminal_widget.setColorScheme(self.selected_theme)

            # 显示预览信息
            QMessageBox.information(
                self,
                "🔍 主题预览",
                f"正在预览主题: {self.selected_theme}\n\n"
                f"如果满意，请点击'应用'按钮确认。\n"
                f"否则主题将恢复为: {original_theme}"
            )

    def apply_theme(self):
        """应用选中的主题"""
        if hasattr(self, 'selected_theme'):
            self.theme_selected.emit(self.selected_theme)
            self.accept()


if __name__ == '__main__':
    print("PySide6 version:", PySide6.__version__)

    app = QApplication(sys.argv)

    # 初始化语言管理器并加载语言设置
    try:
        # 读取配置中的语言设置
        theme_config = util.read_json(abspath('theme.json'))
        saved_language = theme_config.get('language', 'zh_CN')

        # 初始化语言管理器
        lang_manager = get_language_manager()
        i18n_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'i18n')
        lang_manager.initialize(app, i18n_dir)
        lang_manager.load_from_config(saved_language)

        print(f"Language loaded: {saved_language}")
    except Exception as e:
        print(f"Failed to load language settings: {e}")

    window = MainDialog(app)

    window.show()
    window.refreshConf()
    sys.exit(app.exec())
