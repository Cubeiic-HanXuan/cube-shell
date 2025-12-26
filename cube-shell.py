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
from PySide6.QtGui import QIcon, QAction, QCursor, QCloseEvent, QInputMethodEvent, QPixmap, \
    QDragEnterEvent, QDropEvent, QFont, QFontDatabase, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QApplication, QMainWindow, QMenu, QDialog, QMessageBox, QTreeWidgetItem, \
    QInputDialog, QFileDialog, QTreeWidget, QWidget, QVBoxLayout, QLabel, QHBoxLayout, QPushButton, QTableWidgetItem, \
    QHeaderView, QStyle, QTabBar, QTextBrowser, QLineEdit, QScrollArea, QGridLayout, QProgressBar, QProgressDialog, \
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
from ui.tunnel_config import Ui_TunnelConfig
from ui.code_editor import CodeEditor, Highlighter
from function.ssh_prompt_client import load_linux_commands
from core.ai import AISettingsDialog, open_ai_dialog

# 配置日志输出到文件
logging.basicConfig(
    filename=os.path.join(log_dir, "cube-shell.log"),
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)
logger = logging.getLogger("cube-shell")

# 将 stdout/stderr 重定向到文件，便于排查问题
sys.stdout = open(os.path.join(log_dir, 'stdout.log'), 'a', buffering=1, encoding='utf-8')
sys.stderr = open(os.path.join(log_dir, 'stderr.log'), 'a', buffering=1, encoding='utf-8')

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

    def __init__(self, ssh_conn):
        super().__init__()
        self.ssh_conn = ssh_conn

    def run(self):
        if not self.ssh_conn or not self.ssh_conn.active:
            self.data_ready.emit({}, [])
            return

        groups = defaultdict(list)
        container_list = []
        try:
            # 获取 compose 项目和配置文件列表
            ls = self.ssh_conn.sudo_exec("docker compose ls -a")
            if ls:
                lines = ls.strip().splitlines()
                for compose_ls in lines[1:]:
                    parts = compose_ls.rsplit(None, 1)
                    if len(parts) >= 2:
                        config = parts[-1]
                        ps_cmd = f"docker compose --file {config} ps -a --format '{{{{json .}}}}'"
                        conn_exec = self.ssh_conn.sudo_exec(ps_cmd)

                        current_containers = []
                        for ps in conn_exec.strip().splitlines():
                            if ps.strip():
                                try:
                                    data = json.loads(ps)
                                    current_containers.append(data)
                                except:
                                    pass

                        for item in current_containers:
                            project_name = item.get('Project', '未知')
                            groups[project_name].append(item)

            # 如果没有 compose 组，或者作为 fallback，获取普通 docker 容器
            if not groups:
                conn_exec = self.ssh_conn.exec("docker ps -a --format '{{json .}}'")
                for ps in conn_exec.strip().splitlines():
                    if ps.strip():
                        try:
                            data = json.loads(ps)
                            container_list.append(data)
                        except:
                            pass

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

            conn_exec = self.ssh_conn.sudo_exec("docker ps -a --format '{{json .}}'")
            container_list = []
            for ps in conn_exec.strip().splitlines():
                if ps.strip():
                    try:
                        data = json.loads(ps)
                        container_list.append(data)
                    except:
                        pass

            services = util.get_compose_service(self.config_path)
            services_config = util.update_has_attribute(services, container_list)

            self.data_ready.emit(services_config, True)

        except Exception as e:
            util.logger.error(f"Common containers fetch error: {e}")
            self.data_ready.emit({}, False)


# 主界面逻辑
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
        # 存储 SSH 客户端实例，用于管理后台连接
        self.ssh_clients = {}
        icon = QIcon(":index.png")
        self.ui.ShellTab.tabBar().setTabIcon(0, icon)

        # 确保配置目录存在并迁移现有配置文件（仅首次运行时）
        migrate_existing_configs(util.APP_NAME)

        # 保存所有 QLineEdit 的列表
        self.line_edits = []

        init_config()

        self.setDarkTheme()  # 默认设置为暗主题
        self.index_pwd()

        # 读取 JSON 文件内容
        util.THEME = util.read_json(abspath('theme.json'))

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
        self.ui.theme.clicked.connect(self.toggleTheme)
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
        #  操作docker 成功,发射信号
        self.finished.connect(self.on_ssh_docker_finished)

        self.NAT = False
        self.NAT_lod()
        self.ui.pushButton.clicked.connect(self.on_NAT_traversal)

        # 记录当前文件树显示的连接ID
        self.current_displayed_connection_id = None

        # 连接状态防抖
        self.is_connecting_lock = False
        self._last_connect_attempt_ts = 0
        self.is_closing = False

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

        # 检查服务器是否可以连接
        if not util.check_server_accessibility(host.split(':')[0], int(host.split(':')[1])):
            # 删除当前的 tab 并显示警告消息
            self._delete_tab()
            QMessageBox.warning(self, self.tr("连接超时"), self.tr("服务器无法连接，请检查网络或服务器状态。"))
            return

        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            ssh_conn = SshClient(host.split(':')[0], int(host.split(':')[1]), username, password, key_type, key_file,
                                 )
            ssh_conn.connect()
            # 上传文件
            sftp = ssh_conn.open_sftp()
            if not self.NAT:
                # 如果路径不存在，则创建目录
                if not util.check_remote_directory_exists(sftp, '/opt/frp'):
                    # 目前大部分服务器是x86_64 (amd64) 架构
                    # 以后可能需要按需选择，使用以下检测命令来检测架构类型
                    # conn_exec = ssh_conn.exec(cmd='arch', pty=False)
                    # if conn_exec == 'x86_64':
                    join = os.path.join(current_dir, 'frp', 'frps.tar.gz')
                    sftp.put(join, '/opt/' + os.path.basename(join))
                    frps = traversal.frps(token)
                    # 解压，并替换配置文件
                    cmd = f"tar -xzvf /opt/frps.tar.gz -C /opt/ && cat <<EOF > /opt/frp/frps.toml {frps}"
                    ssh_conn.exec(cmd=cmd, pty=False)
                # 启动服务
                cmd1 = f"cd /opt/frp && nohup ./frps -c frps.toml &> frps.log &"
                ssh_conn.conn.exec_command(timeout=1, command=cmd1, get_pty=False)

                # 覆盖本地配置文件
                frpc = traversal.frpc(host.split(':')[0], token, ant_type, local_port, server_prot)
                with open(abspath('frpc.toml'), 'w') as file:
                    file.write(frpc)

                # 获取配置文件绝对路径
                local_dir = os.path.join(current_dir, 'frp')
                # 启动客户端
                cmd_u = f"cd {local_dir} && nohup ./frpc -c {abspath('frpc.toml')} &> frpc.log &"
                if platform.system() == 'Darwin' or platform.system() == 'Linux':
                    os.system(cmd_u)
                elif platform.system() == 'Windows':
                    subprocess.Popen(
                        [f"{local_dir}\\frpc.exe", "-c", abspath('frpc.toml')],
                        stdout=open("frpc.log", "a"),
                        stderr=subprocess.STDOUT,
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )

                icon1 = QIcon()
                icon1.addFile(u":off.png", QSize(), QIcon.Mode.Normal, QIcon.State.Off)
                self.ui.pushButton.setIcon(icon1)
                self.NAT = True
            else:
                # 关闭服务和客户端
                ssh_conn.conn.exec_command(timeout=1, command="pkill -9 frps", get_pty=False)
                if platform.system() == 'Darwin' or platform.system() == 'Linux':
                    os.system("pkill -9 frpc")
                elif platform.system() == 'Windows':
                    subprocess.run(['taskkill', '/f', '/im', 'frpc.exe'], capture_output=True, text=True)

                icon1 = QIcon()
                icon1.addFile(u":open.png", QSize(), QIcon.Mode.Normal, QIcon.State.Off)
                self.ui.pushButton.setIcon(icon1)
                self.NAT = False
            self.NAT_lod()
            ssh_conn.close()
        except Exception as e:
            util.logger.error(str(e))

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
        try:
            self.Shell._ssh_config_name = name
        except Exception:
            pass
        try:
            self.Shell.finished.connect(lambda term=self.Shell: self.on_terminal_session_finished(term))
        except Exception:
            pass

        # 🔧 修复：使用addWidget并设置拉伸因子确保完全填充
        self.verticalLayout_shell.addWidget(self.Shell, 0)  # 拉伸因子1
        self.verticalLayout_index.addLayout(self.verticalLayout_shell, 0)  # 拉伸因子1

        tab_name = self.generate_unique_tab_name(name)
        tab_index = self.ui.ShellTab.addTab(self.tab, tab_name)
        self.ui.ShellTab.setCurrentIndex(tab_index)

        if tab_index > 0:
            close_button = QPushButton(self)
            close_button.setCursor(QCursor(Qt.PointingHandCursor))
            close_button.setIcon(self.style().standardIcon(QStyle.SP_TitleBarCloseButton))
            close_button.setMaximumSize(QSize(16, 16))
            close_button.setFlat(True)
            close_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)

            close_button.clicked.connect(lambda: self.off(tab_index, tab_name))
            self.ui.ShellTab.tabBar().setTabButton(tab_index, QTabBar.LeftSide, close_button)
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
        refresh_action = QAction("刷新进程列表", self)
        refresh_action.triggered.connect(self.update_process_list)
        context_menu.addAction(refresh_action)

        # 如果已选择进程，添加终止进程选项
        if len(self.ui.result.selectedItems()) > 0:
            kill_action = QAction("终止进程", self)
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
            self.update_process_list_signal.emit(ssh_conn.id, processes)
        except Exception as e:
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
        headers = ["PID", "用户", "内存", "CPU", "端口", "命令行"]
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
        #
        # 创建"重做"动作
        # docker_action = QAction(QIcon(":redo.png"), "&容器编排", self)
        # docker_action.setShortcut("Shift+Ctrl+D")
        # docker_action.setStatusTip(self.tr("容器编排"))
        # setting_menu.addAction(docker_action)
        # docker_action.triggered.connect(self.container_orchestration)

        # 创建"关于"动作
        about_action = QAction(QIcon(":about.png"), self.tr("&关于"), self)
        about_action.setShortcut("Shift+Ctrl+B")
        about_action.setStatusTip(self.tr("cubeShell 有关信息"))
        help_menu.addAction(about_action)
        about_action.triggered.connect(self.about)

        linux_action = QAction(QIcon(":about.png"), self.tr("&Linux常用命令"), self)
        linux_action.setShortcut("Shift+Ctrl+P")
        linux_action.setStatusTip(self.tr("最常用的Linux命令查找"))
        help_menu.addAction(linux_action)
        linux_action.triggered.connect(self.linux)

        help_action = QAction(QIcon(":about.png"), self.tr("&帮助"), self)
        help_action.setShortcut("Shift+Ctrl+H")
        help_action.setStatusTip(self.tr("cubeShell使用说明"))
        help_menu.addAction(help_action)
        help_action.triggered.connect(self.help)

    # 关于
    def about(self):
        self.about_dialog = about.AboutDialog()
        self.about_dialog.show()

    def theme(self):
        self.theme_dialog = theme.MainWindow()
        self.theme_dialog.show()

    def show_ai_settings(self):
        dialog = AISettingsDialog(self)
        dialog.exec()

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

    def _find_tab_index_by_terminal(self, terminal):
        try:
            for i in range(self.ui.ShellTab.count()):
                t = self.get_text_browser_from_tab(i)
                if t is terminal:
                    return i
        except Exception:
            return None
        return None

    def on_terminal_session_finished(self, terminal):
        tab_index = self._find_tab_index_by_terminal(terminal)
        if tab_index is None:
            return

        try:
            terminal._ssh_needs_reconnect = True
        except Exception:
            pass

        try:
            title = self.ui.ShellTab.tabText(tab_index)
            if "断开" not in title:
                self.ui.ShellTab.setTabText(tab_index, f"{title} (断开)")
        except Exception:
            pass

        try:
            conn_id = self.ui.ShellTab.tabWhatsThis(tab_index)
            if conn_id and conn_id in self.ssh_clients:
                try:
                    self.ssh_clients[conn_id].close()
                except Exception:
                    pass
                try:
                    del self.ssh_clients[conn_id]
                except Exception:
                    pass
        except Exception:
            pass

        if self.ui.ShellTab.currentIndex() == tab_index:
            self.isConnected = False
            self.current_displayed_connection_id = None
            try:
                self.ui.discButton.setEnabled(False)
                self.ui.result.setEnabled(False)
                self.ui.theme.setEnabled(False)
            except Exception:
                pass

    def reconnect_terminal(self, terminal):
        tab_index = self._find_tab_index_by_terminal(terminal)
        if tab_index is None:
            return False

        try:
            self.ui.ShellTab.setCurrentIndex(tab_index)
        except Exception:
            pass

        name = getattr(terminal, "_ssh_config_name", None)
        if not name:
            try:
                title = self.ui.ShellTab.tabText(tab_index)
                name = title.replace(" (断开)", "").split(" (")[0]
            except Exception:
                name = None
        if not name:
            return False

        try:
            title = self.ui.ShellTab.tabText(tab_index)
            if " (断开)" in title:
                self.ui.ShellTab.setTabText(tab_index, title.replace(" (断开)", ""))
        except Exception:
            pass

        try:
            terminal._ssh_needs_reconnect = False
        except Exception:
            pass

        try:
            conn_id = self.ui.ShellTab.tabWhatsThis(tab_index)
            if conn_id and conn_id in self.ssh_clients:
                try:
                    self.ssh_clients[conn_id].close()
                except Exception:
                    pass
                try:
                    del self.ssh_clients[conn_id]
                except Exception:
                    pass
        except Exception:
            pass

        try:
            terminal.clear()
        except Exception:
            pass

        ok = self.run(name=name, terminal=terminal)
        return bool(ok)

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

            if username:
                ssh_args.extend(["-o", "StrictHostKeyChecking=no",  # 跳过主机密钥检查
                                 "-o", "UserKnownHostsFile=/dev/null"  # 不保存主机密钥文件
                                 ])
                ssh_args.append(f"{username}@{host}")
            else:
                ssh_args.append(host)

            terminal.setShellProgram(ssh_command)
            terminal.setArgs(ssh_args)
            terminal.startShellProgram()

            # 🔧 修复：在启动 Shell 后重新应用主题，防止被重置
            if hasattr(terminal, 'current_theme_name'):
                terminal.setColorScheme(terminal.current_theme_name)
            else:
                terminal.setColorScheme("Ubuntu")

            if not key_type and not key_file:
                def auto_input_password():
                    terminal.sendText(password + "\n")

                # 等待1.5秒让SSH显示密码提示，然后自动输入
                QTimer.singleShot(1200, auto_input_password)

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
        self.is_connecting_lock = False

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

        self.isConnected = True
        self.ui.discButton.setEnabled(True)
        self.ui.result.setEnabled(True)
        self.ui.theme.setEnabled(True)

        self.refreshDirs()
        # 进程管理
        self.processInitUI()

        if not hasattr(ssh_conn, 'flush_sys_info_thread') or not ssh_conn.flush_sys_info_thread.is_alive():
            ssh_conn.flush_sys_info_thread = threading.Thread(target=ssh_conn.get_datas, args=(ssh_conn,), daemon=True)
            ssh_conn.flush_sys_info_thread.start()
            self.flushSysInfo()

        # threading.Thread(target=ssh_conn.get_datas, daemon=True).start()

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

    # 选择文件夹
    def cd(self):
        if self.isConnected:
            ssh_conn = self.ssh()

            # 关键安全检查：
            # 如果当前显示的连接ID与实际操作的连接ID不一致（说明UI显示的是旧数据），则阻止操作
            if self.current_displayed_connection_id != ssh_conn.id:
                return

            focus = self.ui.treeWidget.currentIndex().row()
            if focus != -1 and self.dir_tree_now[focus][0].startswith('d'):
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

                # 创建新 Tab 并立即启动连接
                try:
                    # 传递 name 参数，避免依赖 UI 焦点
                    tab_index, terminal = self.add_new_tab(name)
                    if tab_index != -1:
                        self.run(name, terminal)
                finally:
                    # 释放锁
                    self.is_connecting_lock = False

            else:
                self.add_new_tab()
                self.run()

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
                if hasattr(ssh_conn, 'timer1') and ssh_conn.timer1:
                    ssh_conn.timer1.stop()
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
                            if hasattr(ssh_conn, 'timer1') and ssh_conn.timer1:
                                ssh_conn.timer1.stop()
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
            if selected_items:
                self.ui.action.setVisible(False)
                self.ui.action1.setVisible(True)
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
            self.ui.action7.triggered.connect(self.remove)
            self.ui.action8.triggered.connect(self.rename)
            self.ui.action9.triggered.connect(self.unzip)
            self.ui.action10.triggered.connect(self.zip)

            # 声明当鼠标在groupBox控件上右击时，在鼠标位置显示右键菜单   ,exec_,popup两个都可以，
            self.ui.tree_menu.popup(QCursor.pos())

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
            # self.ui.action4 = QAction('日志', self)

            self.ui.tree_menu.addAction(self.ui.action1)
            self.ui.tree_menu.addAction(self.ui.action2)
            self.ui.tree_menu.addAction(self.ui.action3)
            # self.ui.tree_menu.addAction(self.ui.action4)

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
            # self.ui.action4.triggered.connect(self.rmDockerContainer)
            else:  # 子级
                container_id = item.text(1)  # 容器ID在第二列
                self.ui.action1.triggered.connect(lambda: self.stopDockerContainer([container_id]))
                self.ui.action2.triggered.connect(lambda: self.restartDockerContainer([container_id]))
                self.ui.action3.triggered.connect(lambda: self.rmDockerContainer([container_id]))

            # 声明当鼠标在groupBox控件上右击时，在鼠标位置显示右键菜单,exec_,popup两个都可以，
            self.ui.tree_menu.popup(QCursor.pos())

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
        # 创建一个新的 QLineEdit
        line_edit = QLineEdit()
        line_edit.setFocusPolicy(Qt.ClickFocus)
        line_edit.setText(q_str)
        # 保存新创建的 QLineEdit
        self.line_edits.append(line_edit)
        # 将 QLineEdit 添加到布局中
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
                    item.setIcon(0, util.get_default_file_icon(n[8]))

                items.append(item)

            # 批量添加项目
            self.ui.treeWidget.addTopLevelItems(items)

            # 恢复UI更新
            self.ui.treeWidget.setUpdatesEnabled(True)

        except Exception as e:
            util.logger.error(f"Error refreshing directories UI: {e}")

    # 旧的同步方法已废弃，保留 getDirNow

    # 获取当前目录列表
    def getDirNow(self, ssh_conn=None):
        if ssh_conn is None:
            ssh_conn = self.ssh()
            if not ssh_conn:
                return "", []
            # 使用 getData2 (带信号发射)
            pwd = self.getData2('cd ' + ssh_conn.pwd.replace("//", "/") + ' && pwd')
            dir_info = self.getData2(cmd='cd ' + ssh_conn.pwd.replace("//", "/") + ' && ls -al').split('\n')
        else:
            # 直接使用 exec (后台线程使用，不通过 getData2 避免跨线程 UI 访问)
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
            sftp = self.ssh().open_sftp()
            with sftp.file(path, 'w') as f:
                f.write(content.encode('utf-8'))
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
            # 使用单个定时器更新多个信息
            if not hasattr(self, 'update_timer'):
                ssh_conn.timer1 = QTimer()
                ssh_conn.timer1.timeout.connect(self.refreshSysInfo)
                ssh_conn.timer1.start(1000)
        except Exception as e:
            util.logger.error(f"Error setting up system info update: {e}")

    # 刷新设备状态信息功能
    def refreshSysInfo(self):
        if self.isConnected:
            current_index = self.ui.ShellTab.currentIndex()
            this = self.ui.ShellTab.tabWhatsThis(current_index)
            if this and this in self.ssh_clients:
                ssh_conn = self.ssh_clients[this]
                system_info_dict = ssh_conn.system_info_dict
                cpu_use = ssh_conn.cpu_use
                mem_use = ssh_conn.mem_use
                dissk_use = ssh_conn.disk_use
                # 上行
                transmit_speed = ssh_conn.transmit_speed
                # 下行
                receive_speed = ssh_conn.receive_speed

                self.ui.cpuRate.setValue(cpu_use)
                self.ui.cpuRate.setStyleSheet(updateColor(cpu_use))
                self.ui.memRate.setValue(mem_use)
                self.ui.memRate.setStyleSheet(updateColor(mem_use))
                self.ui.diskRate.setValue(dissk_use)
                self.ui.diskRate.setStyleSheet(updateColor(dissk_use))
                # 自定义显示格式
                self.ui.networkUpload.setText(util.format_speed(transmit_speed))
                self.ui.networkDownload.setText(util.format_speed(receive_speed))
                self.ui.operatingSystem.setText(system_info_dict['Operating System'])
                self.ui.kernelVersion.setText(system_info_dict['Kernel'])
                if 'Firmware Version' in system_info_dict:
                    self.ui.kernel.setText(system_info_dict['Firmware Version'])
                else:
                    self.ui.kernel.setText(self.tr("无"))

        else:
            self.ui.cpuRate.setValue(0)
            self.ui.memRate.setValue(0)
            self.ui.diskRate.setValue(0)

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
                     self.tr("启动命令"), self.tr("创建时间"), self.tr("端口")
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
        container_item.setText(5, c.get('Command', ""))
        container_item.setText(6, c.get('CreatedAt', ""))
        container_item.setText(7, c.get('Ports', ""))
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
            for container_id in container_ids:
                self.start_async_task('docker stop ' + container_id)
            self.refreshDokerInfo()

    # 重启docker容器
    def restartDockerContainer(self, container_ids):
        if container_ids:
            for container_id in container_ids:
                self.start_async_task('docker restart ' + container_id)
            self.refreshDokerInfo()

    # 删除docker容器
    def rmDockerContainer(self, container_ids):
        if container_ids:
            for container_id in container_ids:
                self.start_async_task('docker rm ' + container_id)
            self.refreshDokerInfo()

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

    # def inputMethodQuery(self, a0):
    #     pass

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

    def toggleTheme(self):
        sheet = self.app.styleSheet()
        stylesheet = qdarktheme.load_stylesheet(custom_colors={"[dark]": {"primary": "#00A1FF", }}, )
        if self.app.styleSheet() == stylesheet:
            self.setLightTheme()
        else:
            self.setDarkTheme()
        # 🔧 发射主题切换信号
        self.themeChanged.emit(True)

    def on_system_theme_changed(self, is_dark_theme):
        """系统主题切换时，重新应用终端主题"""
        try:
            # 遍历所有终端标签页
            for index in range(self.ui.ShellTab.count()):
                terminal = self.get_text_browser_from_tab(index)
                # 检查是否为 SSHQTermWidget 实例（或具有 setColorScheme 方法）
                if terminal and hasattr(terminal, 'setColorScheme'):
                    # 重新应用当前主题，以覆盖系统样式表的影响
                    if hasattr(terminal, 'current_theme_name'):
                        terminal.setColorScheme(terminal.current_theme_name)
                    else:
                        terminal.setColorScheme("Ubuntu")
        except Exception as e:
            util.logger.error(f"Failed to changed system theme: {e}")

    def on_ssh_failed(self, error_msg):
        """SSH连接失败回调"""
        # 确保 UI 操作在主线程
        if QThread.currentThread() != QCoreApplication.instance().thread():
            QMetaObject.invokeMethod(self, "on_ssh_failed", Qt.QueuedConnection, Q_ARG(str, error_msg))
            return

        self._delete_tab()
        QMessageBox.warning(self, self.tr("拒绝连接"), self.tr("请检查服务器用户名、密码或密钥是否正确"))

    # 获取当前标签页的backend
    def ssh(self):
        current_index = self.ui.ShellTab.currentIndex()
        this = self.ui.ShellTab.tabWhatsThis(current_index)
        if this and this in self.ssh_clients:
            return self.ssh_clients[this]
        return None


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


# 移除不再需要的类
# class ConnectSignals(QObject):
#     """用于 Runnable 的信号发射器"""
#     connected = Signal(object)
#     failed = Signal(str)


# class ConnectRunnable(PySide6.QtCore.QRunnable):
#     """SSH 连接任务 - 独立于 UI 线程运行"""
#
#     def __init__(self, host, port, username, password, key_type, key_file):
#         super().__init__()
#         self.host = host
#         self.port = port
#         self.username = username
#         self.password = password
#         self.key_type = key_type
#         self.key_file = key_file
#         self.signals = ConnectSignals()
#         self.setAutoDelete(True)  # 任务完成后自动删除
#
#     def run(self):
#         try:
#             # 执行耗时的连接操作
#             ssh_conn = SshClient(self.host, self.port, self.username, self.password, self.key_type, self.key_file)
#             ssh_conn.connect()
#             self.signals.connected.emit(ssh_conn)
#         except Exception as e:
#             self.signals.failed.emit(str(e))


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
            # 合并命令
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
            QMessageBox.information(self, "查找", "未找到匹配项")

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
        QMessageBox.information(self, "替换", f"已替换 {count} 处匹配项")

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
    提供复制SSH命令和
    """

    def __init__(self, parent, data):
        super(TunnelConfig, self).__init__(parent)

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
        else:
            try:
                self.start_tunnel()
            except Exception as e:
                util.logger.error(f"Error starting tunnel: {e}")
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

        # 本地服务器地址
        local_bind_address = self.tunnelconfig.ui.local_bind_address_edit.text()
        local_host, local_port = local_bind_address.split(':')[0], int(local_bind_address.split(':')[1])

        # 获取SSH信息
        ssh_user, ssh_password, host, key_type, key_file = open_data(ssh)
        ssh_host, ssh_port = host.split(':')[0], int(host.split(':')[1])

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
    username, password, host, key_type, key_file = '', '', '', '', ''
    if len(conf) == 3:
        return username, password, host, '', ''
    else:
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

        # 记录当前主题
        self.current_theme_name = "Ubuntu"
        self._ssh_needs_reconnect = False

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
                        super().setColorScheme(self.current_theme_name)
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

                    if getattr(self, "_ssh_needs_reconnect", False):
                        parent = self.window()
                        if hasattr(parent, "reconnect_terminal"):
                            parent.reconnect_terminal(self)
                        return True
                except Exception:
                    pass
        return super().eventFilter(obj, event)

    def _on_term_key_pressed(self, event):
        """
        终端按键事件（来自 QTermWidget.termKeyPressed）。

        只做与智能提示相关的“轻量输入跟踪”：
        - 维护 _input_buffer（尽力而为，不保证覆盖远端 shell 的所有编辑行为）
        - 控制提示弹窗显示/隐藏
        - 记录历史命令（优先从屏幕提取真实命令行）
        """
        try:
            if getattr(self, "_ssh_needs_reconnect", False):
                return
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

    def resizeEvent(self, event):
        """重写 resizeEvent，在调整大小后恢复主题"""
        # 延迟恢复主题，确保底层重绘完成后应用
        if hasattr(self, 'current_theme_name'):
            super().setColorScheme(self.current_theme_name)

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
        # 优选等宽字体，支持更好的代码显示
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

        current_size = util.THEME.get('font_size', 14)

        # 提前获取可用字体列表，避免直接创建不存在的 QFont 导致系统开销和警告
        available_families = set(QFontDatabase.families())

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
            if getattr(self, "_ssh_needs_reconnect", False):
                return
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

    def _validate_command(self, cmdline: str) -> str:
        s = (cmdline or "").strip()
        if not s:
            return ""
        cmd = s.split()[0]
        if cmd in set(self._prompt_commands):
            return ""
        return "unknown_command"

    def _get_completion(self) -> str:
        s = (self._input_buffer or "").lstrip()
        if not s:
            return ""
        sugg = self._compute_suggestions(s)
        if not sugg:
            return ""
        return sugg[0]

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
            self._apply_dark_menu_style(menu)

            # 添加自定义功能
            self._add_custom_actions(menu)

            # 显示菜单
            menu.exec(event.globalPos())
            print("显示了自定义右键菜单")

        except Exception as e:
            util.logger.error(f"右键菜单创建失败: {e}")

    def _apply_dark_menu_style(self, menu):
        """应用暗色主题菜单样式"""
        menu.setStyleSheet("""
            QMenu {
                background-color: #2d2d30;
                color: #d4d4d4;
                border: 1px solid #3c3c3c;
                border-radius: 3px;
                padding: 2px;
            }
            QMenu::item {
                padding: 8px 16px;
                border-radius: 2px;
                margin: 1px;
            }
            QMenu::item:selected {
                background-color: #094771;
                color: white;
            }
            QMenu::separator {
                height: 1px;
                background-color: #3c3c3c;
                margin: 4px 0px;
            }
            QMenu::icon {
                margin-right: 8px;
            }
        """)

    def _add_custom_actions(self, menu):
        """添加自定义动作到菜单"""

        # 复制操作 - 使用QTermWidget内置方法
        copy_action = QAction(self._action_icons['copy'], "复制", self)
        copy_action.setIconVisibleInMenu(True)
        copy_action.setShortcut("Ctrl+Shift+C")
        copy_action.triggered.connect(self.copyClipboard)
        menu.addAction(copy_action)

        # 粘贴操作 - 使用QTermWidget内置方法
        paste_action = QAction(self._action_icons['paste'], "粘贴", self)
        paste_action.setIconVisibleInMenu(True)
        paste_action.setShortcut("Ctrl+Shift+V")
        paste_action.triggered.connect(self.pasteClipboard)
        paste_action.setEnabled(bool(self._clipboard.text()))
        menu.addAction(paste_action)

        menu.addSeparator()

        # 清屏操作 - 使用QTermWidget内置方法
        clear_action = QAction(self._action_icons['clear'], "清屏", self)
        clear_action.setIconVisibleInMenu(True)
        clear_action.triggered.connect(self.clear)
        menu.addAction(clear_action)

        # 添加主题相关选项
        menu.addSeparator()

        # 终端主题切换
        theme_action = QAction("🎨 切换终端主题", self)
        theme_action.triggered.connect(self.show_theme_selector)
        menu.addAction(theme_action)

        menu.addSeparator()
        ai_menu = menu.addMenu("🤖 AI")
        explain_action = QAction("解释文本", self)
        explain_action.triggered.connect(lambda: open_ai_dialog(self, "explain"))
        ai_menu.addAction(explain_action)

        script_action = QAction("编写脚本", self)
        script_action.triggered.connect(lambda: open_ai_dialog(self, "script"))
        ai_menu.addAction(script_action)

        install_action = QAction("软件环境", self)
        install_action.triggered.connect(lambda: open_ai_dialog(self, "install"))
        ai_menu.addAction(install_action)

        log_action = QAction("日志分析", self)
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
        """应用终端主题"""
        try:
            # 应用主题
            self.setColorScheme(theme_name)
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

        # 当前主题显示
        self.current_label = QLabel()
        self.current_label.setStyleSheet("""
            QLabel {
                padding: 8px;
                background-color: #3498db;
                color: white;
                border-radius: 3px;
                font-weight: bold;
            }
        """)
        layout.addWidget(self.current_label)

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

            self.current_label.setText(f"📌 当前主题: {self.current_theme}")

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

    # translator = QTranslator()
    # # 加载编译后的 .qm 文件
    # translator.load("app_zh_CN.qm")
    #
    # # 安装翻译
    # app.installTranslator(translator)

    window = MainDialog(app)

    window.show()
    window.refreshConf()
    sys.exit(app.exec())
