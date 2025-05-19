import asyncio
import glob
import json
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
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from socket import socket

import PySide6
import appdirs
import pyte
import qdarktheme
import toml
from PySide6.QtCore import QTimer, Signal, Qt, QPoint, QRect, QEvent, QObject, Slot, QUrl, QCoreApplication, \
    QTranslator, QSize, QTimerEvent, QThread, QMetaObject, Q_ARG
from PySide6.QtGui import QIcon, QAction, QTextCursor, QCursor, QCloseEvent, QKeyEvent, QInputMethodEvent, QPixmap, \
    QDragEnterEvent, QDropEvent, QFont, QContextMenuEvent, QDesktopServices, QGuiApplication, QPalette, QColor, \
    QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import QApplication, QMainWindow, QMenu, QDialog, QMessageBox, QTreeWidgetItem, \
    QInputDialog, QFileDialog, QTreeWidget, QWidget, QVBoxLayout, QLabel, QHBoxLayout, QPushButton, QTableWidgetItem, \
    QHeaderView, QStyle, QTabBar, QTextBrowser, QLineEdit, QScrollArea, QGridLayout, QProgressBar, QPlainTextEdit, \
    QTextEdit
from deepdiff import DeepDiff
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import PythonLexer

from core.docker.docker_compose_editor import DockerComposeEditor
from core.docker.docker_installer_ui import DockerInstallerWidget
from core.frequently_used_commands import TreeSearchApp
from core.pty.forwarder import ForwarderManager
from core.pty.mux import mux
from core.uploader.progress_adapter import ProgressAdapter
from core.uploader.sftp_uploader_core import SFTPUploaderCore
from core.vars import ICONS, CONF_FILE, CMDS, KEYS
from function import util, about, theme, traversal, parse_data
from function.ssh_func import SshClient
from function.util import format_file_size, has_valid_suffix
from style.style import updateColor, InstalledButtonStyle, InstallButtonStyle
from ui import add_config, text_editor, confirm, main, docker_install, auth
from ui.add_tunnel_config import Ui_AddTunnelConfig
from ui.tunnel import Ui_Tunnel
from ui.tunnel_config import Ui_TunnelConfig

keymap = {
    Qt.Key_Backspace: chr(127).encode(),
    Qt.Key_Escape: chr(27).encode(),
    Qt.Key_AsciiTilde: chr(126).encode(),
    Qt.Key_Up: b'\x1b[A',
    Qt.Key_Down: b'\x1b[B',
    Qt.Key_Left: b'\x1b[D',
    Qt.Key_Right: b'\x1b[C',
    Qt.Key_PageUp: "~1".encode(),
    Qt.Key_PageDown: "~2".encode(),
    Qt.Key_Home: "~H".encode(),
    Qt.Key_End: "~F".encode(),
    Qt.Key_Insert: "~3".encode(),
    Qt.Key_Delete: "~4".encode(),
    Qt.Key_F1: "~a".encode(),
    Qt.Key_F2: "~b".encode(),
    Qt.Key_F3: "~c".encode(),
    Qt.Key_F4: "~d".encode(),
    Qt.Key_F5: "~e".encode(),
    Qt.Key_F6: "~f".encode(),
    Qt.Key_F7: "~g".encode(),
    Qt.Key_F8: "~h".encode(),
    Qt.Key_F9: "~i".encode(),
    Qt.Key_F10: "~j".encode(),
    Qt.Key_F11: "~k".encode(),
    Qt.Key_F12: "~l".encode(),
}


def abspath(path):
    """
    获取当前脚本的绝对路径
    :param path:
    :return:
    """
    current_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(current_dir, 'conf', path)


# 主界面逻辑
class MainDialog(QMainWindow):
    initSftpSignal = Signal()
    finished = Signal(str, str)  # 信号：成功结果 (命令, 输出)
    error = Signal(str, str)  # 信号：错误 (命令, 错误信息)

    def __init__(self, qt_app):
        super().__init__()
        self.app = qt_app  # 将 app 传递并设置为类属性
        self.ui = main.Ui_MainWindow()
        self.ui.setupUi(self)
        self.setWindowIcon(QIcon(":logo.ico"))
        self.setAttribute(Qt.WA_InputMethodEnabled, True)
        self.setAttribute(Qt.WA_KeyCompression, True)
        self.setFocusPolicy(Qt.WheelFocus)
        self.Shell = None
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

        self.ui.discButton.clicked.connect(self.disc_off)
        self.ui.theme.clicked.connect(self.toggleTheme)
        self.ui.treeWidget.customContextMenuRequested.connect(self.treeRight)
        self.ui.treeWidget.doubleClicked.connect(self.cd)
        self.ui.ShellTab.currentChanged.connect(self.shell_tab_current_changed)
        # 连接信号
        self.ui.tabWidget.currentChanged.connect(self.on_tab_changed)
        # 设置选择模式为多选模式
        self.ui.treeWidget.setSelectionMode(QTreeWidget.ExtendedSelection)
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

        self.isConnected = False
        self.timer_id = self.startTimer(16)
        # 连接信号和槽
        self.initSftpSignal.connect(self.on_initSftpSignal)
        #  操作docker 成功,发射信号
        self.finished.connect(self.on_ssh_docker_finished)

        self.NAT = False
        self.NAT_lod()
        self.ui.pushButton.clicked.connect(self.on_NAT_traversal)

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
            self.ui.ShellTab.removeTab(current_index)

    # 根据标签页名字删除标签页
    def _remove_tab_by_name(self, name):
        for i in range(self.ui.ShellTab.count()):
            if self.ui.ShellTab.tabText(i) == name:
                self.ui.ShellTab.removeTab(i)
                break

    # 增加标签页
    def add_new_tab(self):
        focus = self.ui.treeWidget.currentIndex().row()
        if focus != -1:
            name = self.ui.treeWidget.topLevelItem(focus).text(0)
            self.tab = QWidget()
            self.tab.setObjectName("tab")

            self.verticalLayout_index = QVBoxLayout(self.tab)
            self.verticalLayout_index.setSpacing(0)
            self.verticalLayout_index.setObjectName(u"verticalLayout_index")
            self.verticalLayout_index.setContentsMargins(0, 0, 0, 0)

            self.verticalLayout_shell = QVBoxLayout()
            self.verticalLayout_shell.setObjectName(u"verticalLayout_shell")

            # self.Shell = QTextBrowser(self.tab)
            self.Shell = TerminalWidget(self.tab)
            self.Shell.setReadOnly(True)
            self.Shell.setObjectName(u"Shell")
            self.verticalLayout_shell.addWidget(self.Shell)
            self.verticalLayout_index.addLayout(self.verticalLayout_shell)
            tab_name = self.generate_unique_tab_name(name)
            tab_index = self.ui.ShellTab.addTab(self.tab, tab_name)
            self.ui.ShellTab.setCurrentIndex(tab_index)
            self.Shell.setAttribute(Qt.WA_InputMethodEnabled, True)
            self.Shell.setAttribute(Qt.WA_KeyCompression, True)

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
            return tab.findChild(TerminalWidget, "Shell")
        return None

    # 监听标签页切换
    def shell_tab_current_changed(self, index):
        current_index = self.ui.ShellTab.currentIndex()

        if mux.backend_index:
            current_text = self.ui.ShellTab.tabText(index)
            this = self.ui.ShellTab.tabWhatsThis(current_index)
            if this:
                ssh_conn = mux.backend_index[this]
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
                    if mux.backend_index:
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
        """增大字体"""
        current_index = self.ui.ShellTab.currentIndex()
        shell = self.get_text_browser_from_tab(current_index)
        if shell:
            font = shell.font()
            size = font.pointSize()
            if size < 28:  # 设置最大字体大小限制
                font.setPointSize(size + 1)
                shell.setFont(font)
                # 保存字体大小设置，供下次使用
                util.THEME['font_size'] = size + 1

    def zoom_out(self):
        """减小字体"""
        current_index = self.ui.ShellTab.currentIndex()
        shell = self.get_text_browser_from_tab(current_index)
        if shell:
            font = shell.font()
            size = font.pointSize()
            if size > 14:  # 设置最小字体大小限制
                font.setPointSize(size - 1)
                shell.setFont(font)
                # 保存字体大小设置，供下次使用
                util.THEME['font_size'] = size - 1

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
    def showContextMenu(self, pos):
        # 获取所有选中的索引
        selected_indexes = self.ui.result.selectedIndexes()
        if not selected_indexes:
            return

        # 获取所有选中行的第一列值
        first_column_values = set()
        for index in selected_indexes:
            if index.column() == 0:
                first_column_values.add(index.data(Qt.DisplayRole))

        # 创建菜单
        menu = QMenu()
        kill_action = QAction(QIcon(':kill.png'), self.tr('Kill 进程'), self)
        menu.setCursor(QCursor(Qt.PointingHandCursor))
        kill_action.triggered.connect(lambda: self.kill_process(list(first_column_values)))
        menu.addAction(kill_action)
        menu.exec(self.ui.result.viewport().mapToGlobal(pos))

    def update_process_list(self):
        self.all_processes = self.get_filtered_process_list()
        self.filtered_processes = self.all_processes[:]
        self.display_processes()

    def display_processes(self):
        self.ui.result.setRowCount(0)
        for row_num, process in enumerate(self.filtered_processes):
            self.ui.result.insertRow(row_num)
            self.ui.result.setItem(row_num, 0, QTableWidgetItem(str(process['pid'])))
            self.ui.result.setItem(row_num, 1, QTableWidgetItem(process['user']))
            self.ui.result.setItem(row_num, 2, QTableWidgetItem(str(process['memory'])))
            self.ui.result.setItem(row_num, 3, QTableWidgetItem(str(process['cpu'])))
            self.ui.result.setItem(row_num, 4, QTableWidgetItem(process['name']))
            self.ui.result.setItem(row_num, 5, QTableWidgetItem(process['command']))
            self.ui.result.item(row_num, 0).setData(Qt.UserRole, str(process['pid']))

    @Slot(str)
    def apply_filter(self, text):
        self.search_text = text.lower()
        self.filtered_processes = [p for p in self.all_processes if any(text.lower() in v.lower() for v in p.values())]
        self.display_processes()

    def get_filtered_process_list(self):
        try:
            ssh_conn = self.ssh()
            # 在远程服务器上执行命令获取进程信息
            stdin, stdout, stderr = ssh_conn.conn.exec_command(timeout=10, command="ps aux --no-headers",
                                                               get_pty=False)
            output = stdout.readlines()

            # 解析输出结果
            process_list = []
            system_users = []  # 添加系统用户列表
            for line in output:
                fields = line.strip().split()
                user = fields[0]
                if user not in system_users:
                    pid = fields[1]
                    memory = fields[3]
                    cpu = fields[2]
                    name = fields[-1] if len(fields[-1]) <= 15 else fields[-1][:12] + "..."
                    command = " ".join(fields[10:])
                    process_list.append({
                        'pid': pid,
                        'user': user,
                        'memory': memory,
                        'cpu': cpu,
                        'name': name,
                        'command': command
                    })

            return process_list

        except Exception as e:
            QMessageBox.critical(self, "Error", self.tr("连接或检索进程列表失败") + f": {e}")
            return []

    # kill 选中的进程数据
    def kill_process(self, selected_rows):
        pips = ""
        for value in selected_rows:
            pips += str(value) + " "
        # 优雅结束进程，避免数据丢失
        command = "echo " + pips + "| xargs -n 1 kill -15"

        try:
            ssh_conn = self.ssh()

            # 在远程服务器上执行命令结束进程
            stdin, stdout, stderr = ssh_conn.conn.exec_command(timeout=10, command=command, get_pty=False)
            error = stderr.read().decode('utf-8').strip()
            if error:
                QMessageBox.warning(self, "Warning", self.tr("服务器结束以下进程出错") + f" {pips}: {error}")
            else:
                QMessageBox.information(self, "Success", self.tr(f"以下进程 {pips} 被成功 kill."))
                self.update_process_list()
        except Exception as e:
            QMessageBox.critical(self, "Error", self.tr(f"kill 以下进程失败 {pips}: {e}"))

    # 进程管理结束

    def keyPressEvent(self, event):
        text = str(event.text())
        key = event.key()

        modifiers = event.modifiers()
        ctrl = modifiers == Qt.ControlModifier
        if ctrl and key == Qt.Key_Plus:
            self.zoom_in()
        elif ctrl and key == Qt.Key_Minus:
            self.zoom_out()
        else:
            if text and key != Qt.Key_Backspace:
                focus_widget = QApplication.focusWidget()
                # QLineEdit回车之后不发送命令
                if not isinstance(focus_widget, QLineEdit):
                    self.send(text.encode("utf-8"))
            else:
                s = keymap.get(key)
                if s:
                    self.send(s)

        # self.on_text_changed(text)
        # event.accept()
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent):
        if mux.backend_index:
            text = str(event.text())
            key = event.key()
            # ssh_conn = self.ssh()

            if text and key == Qt.Key_Tab:
                self.send(text.encode("utf-8"))

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
        # 创建“设置”菜单
        setting_menu = menubar.addMenu(self.tr("设置"))
        # 创建“帮助”菜单
        help_menu = menubar.addMenu(self.tr("帮助"))

        # 创建“新建”动作
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

        # 创建“主题设置”动作
        theme_action = QAction(QIcon(":undo.png"), self.tr("&主题设置"), self)
        theme_action.setShortcut("Shift+Ctrl+T")
        theme_action.setStatusTip(self.tr("设置主题"))
        setting_menu.addAction(theme_action)
        theme_action.triggered.connect(self.theme)
        #
        # 创建“重做”动作
        # docker_action = QAction(QIcon(":redo.png"), "&容器编排", self)
        # docker_action.setShortcut("Shift+Ctrl+D")
        # docker_action.setStatusTip(self.tr("容器编排"))
        # setting_menu.addAction(docker_action)
        # docker_action.triggered.connect(self.container_orchestration)

        # 创建“关于”动作
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
    def run(self):
        focus = self.ui.treeWidget.currentIndex().row()
        if focus != -1:
            name = self.ui.treeWidget.topLevelItem(focus).text(0)

            with open(get_config_path('config.dat'), 'rb') as c:
                conf = pickle.loads(c.read())[name]
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
                QMessageBox.warning(self, self.tr("连接超时"), self.tr("服务器无法连接，请检查网络或服务器状态"))
                return

            try:
                ssh_conn = SshClient(host.split(':')[0], int(host.split(':')[1]), username, password,
                                     key_type, key_file)

                # 启动一个线程来异步执行 SSH 连接
                threading.Thread(target=self.connect_ssh_thread, args=(ssh_conn,), daemon=True).start()
            except Exception as e:
                util.logger.error(str(e))
                self.Shell.setPlaceholderText(str(e))
        else:
            self.alarm(self.tr('请选择一台设备！'))

    # 获取当前标签页的backend
    def ssh(self):
        current_index = self.ui.ShellTab.currentIndex()
        this = self.ui.ShellTab.tabWhatsThis(current_index)
        return mux.backend_index[this]

    def connect_ssh_thread(self, ssh_conn):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            loop.run_until_complete(self.async_connect_ssh(ssh_conn))
        finally:
            loop.close()

    async def async_connect_ssh(self, ssh_conn):
        try:
            # 使用上下文管理器创建线程池执行器，动态调整线程池大小
            max_workers = min(32, (os.cpu_count() or 1) * 5)
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # 在线程池中执行同步的 connect 方法
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(executor, ssh_conn.connect)
        except Exception as e:
            # 处理连接失败的情况
            util.logger.error(f"SSH connection failed: {e}")
            # 删除当前的 tab 并显示警告消息
            self._delete_tab()
            # 在主线程中显示消息框
            QMetaObject.invokeMethod(self, "warning", Qt.QueuedConnection, Q_ARG(str, self.tr("拒绝连接")),
                                     Q_ARG(str, self.tr("请检查服务器用户名、密码或密钥是否正确"))
                                     )
            return

        current_index = self.ui.ShellTab.currentIndex()
        ssh_conn.Shell = self.Shell
        self.ui.ShellTab.setTabWhatsThis(current_index, ssh_conn.id)

        # 异步初始化 SFTP
        self.initSftpSignal.emit()

    @Slot(str, str)  # 将其标记为槽
    def warning(self, title, message):
        QMessageBox.warning(self, self.tr(title), self.tr(message))

    # 初始化sftp和控制面板
    def initSftp(self):
        ssh_conn = self.ssh()

        self.isConnected = True
        self.ui.discButton.setEnabled(True)
        self.ui.result.setEnabled(True)
        self.ui.theme.setEnabled(True)
        threading.Thread(target=ssh_conn.get_datas, daemon=True).start()
        self.flushSysInfo()
        self.refreshDirs()

        # 进程管理
        self.processInitUI()

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
            # self.ui.result.append(e)
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
            focus = self.ui.treeWidget.currentIndex().row()
            if focus != -1 and self.dir_tree_now[focus][0].startswith('d'):
                ssh_conn = self.ssh()
                ssh_conn.pwd = self.getData2(
                    'cd ' + ssh_conn.pwd + '/' + self.ui.treeWidget.topLevelItem(focus).text(0) +
                    ' && pwd')[:-1]
                self.refreshDirs()
            else:
                self.editFile()
                # self.alarm('文件无法前往，右键编辑文件！')
        elif not self.isConnected:
            self.add_new_tab()
            self.run()

            current_index = self.ui.ShellTab.currentIndex()
            shell = self.get_text_browser_from_tab(current_index)

            try:
                shell.termKeyPressed.connect(lambda data: self.send(data))
            except Exception as e:
                util.logger.error(str(e))

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
        this = self.get_tab_whats_this_by_name(name)
        ssh_conn = mux.backend_index[this]

        ssh_conn.timer1.stop()
        ssh_conn.term_data = b''
        ssh_conn.close()
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
        ssh_conn.pwd = ''
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
        mux.remove_and_close(ssh_conn)

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

    def timerEvent(self, event: QTimerEvent):
        if event.timerId() == self.timer_id:
            try:
                ssh_conn = self.ssh()
                if ssh_conn.screen.dirty or ssh_conn.need_refresh_flags:
                    self.updateTerminal(ssh_conn)
                    ssh_conn.need_refresh_flags = False
                # self.updateTerminal(ssh_conn)
                # self.update()
            except Exception as e:
                pass
        else:
            # 确保处理其他定时器事件
            super().timerEvent(event)

    def updateTerminal(self, ssh_conn):
        current_index = self.ui.ShellTab.currentIndex()
        shell = self.get_text_browser_from_tab(current_index)

        font_ = util.THEME['font']
        theme_ = util.THEME['theme']
        color_ = util.THEME['theme_color']

        font_size = util.THEME.get('font_size', 14)

        font = QFont(font_, font_size)
        shell.setFont(font)

        # shell.moveCursor(QTextCursor.End)
        # 获取屏幕内容，保持原始行结构
        screen = ssh_conn.screen
        lines = screen.display.copy()
        # 使用 filter() 函数过滤空行
        # 添加光标表示
        cursor_x = screen.cursor.x
        cursor_y = screen.cursor.y

        if cursor_y < len(lines):
            line = lines[cursor_y]
            lines[cursor_y] = line[:cursor_x] + '[[CURSOR]]' + line[cursor_x:]
        # filtered_lines = list(filter(lambda x: x.strip(), lines))

        terminal_str = '\n'.join(lines)

        shell.clear()
        # 使用Pygments进行语法高亮
        formatter = HtmlFormatter(style=theme_, noclasses=True, bg_color='#ffffff')
        shell.setStyleSheet("background-color: " + color_ + ";")
        filtered_data = terminal_str.rstrip().replace("\0", " ")

        pattern = r'\s+(?=\n)'
        result = re.sub(pattern, '', filtered_data)
        special_lines = util.remove_special_lines(result)
        replace = special_lines.replace("                        ", "")

        # 第一次打开渲染banner
        if "Last login:" in terminal_str:
            # 高亮代码
            highlighted2 = highlight(util.BANNER + special_lines, PythonLexer(), formatter)
        else:
            # 高亮代码
            highlighted2 = highlight(special_lines, PythonLexer(), formatter)

        shell.setHtml(highlighted2)

        # 将光标移动到 pyte 的真实位置
        shell.moveCursor(QTextCursor.Start)
        if shell.find('[[CURSOR]]'):
            cursor = shell.textCursor()
            # 删除标记（选中后直接删除）
            cursor.removeSelectedText()
            cursor.insertText('▉')
            shell.setTextCursor(cursor)
            shell.ensureCursorVisible()

        # 如果没有这串代码，执行器就会疯狂执行代码
        ssh_conn.screen.dirty.clear()

    def send(self, data):
        if mux.backend_index:
            ssh_conn = self.ssh()
            ssh_conn.write(data)
            # 如果是方向键，设置刷新标志
            if data in ['\x1b[D', '\x1b[C', '\x1b[A', '\x1b[B']:
                ssh_conn.need_refresh_flags = True

    def do_killall_ssh(self):
        for tunnel in self.tunnels:
            tunnel.stop_tunnel()
        if os.name == 'nt':
            os.system(CMDS.SSH_KILL_WIN)
        else:
            os.system(CMDS.SSH_KILL_NIX)

    def closeEvent(self, event):
        try:
            # 关闭定时起动器
            if self.timer_id is not None:
                self.killTimer(self.timer_id)
                self.timer_id = None
            """
             窗口关闭事件 当存在通道的时候关闭通道
             不存在时结束多路复用器的监听
            :param event: 关闭事件
            :return: None
            """
            # ssh_conn = self.ssh()
            # if mux.backend_index:
            #     for key, ssh_conn in mux.backend_index.items():
            #         if ssh_conn:
            #             ssh_conn.close()
            mux.stop()

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
        try:
            # 先删除旧项目释放内存
            while self.ui.treeWidget.topLevelItemCount() > 0:
                self.ui.treeWidget.takeTopLevelItem(0)
            ssh_conn = self.ssh()
            ssh_conn.pwd, files = self.getDirNow()
            self.dir_tree_now = files[1:]
            self.ui.treeWidget.setHeaderLabels(
                [self.tr("文件名"), self.tr("文件大小"), self.tr("修改日期"), self.tr("权限"), self.tr("所有者/组")])
            self.add_line_edit(ssh_conn.pwd)  # 添加一个初始的 QLineEdit
            self.ui.treeWidget.clear()
            i = 0
            for n in files[1:]:
                self.ui.treeWidget.addTopLevelItem(QTreeWidgetItem(0))
                self.ui.treeWidget.topLevelItem(i).setText(0, n[8])
                size_in_bytes = int(n[4].replace(",", ""))
                self.ui.treeWidget.topLevelItem(i).setText(1, format_file_size(size_in_bytes))
                self.ui.treeWidget.topLevelItem(i).setText(2, n[5] + ' ' + n[6] + ' ' + n[7])
                self.ui.treeWidget.topLevelItem(i).setText(3, n[0])
                self.ui.treeWidget.topLevelItem(i).setText(4, n[3])
                # 设置图标
                if n[0].startswith('d'):
                    # 获取默认的文件夹图标
                    folder_icon = util.get_default_folder_icon()
                    self.ui.treeWidget.topLevelItem(i).setIcon(0, folder_icon)
                elif n[0][0] in ['l', '-', 's']:
                    file_icon = util.get_default_file_icon(n[8])
                    self.ui.treeWidget.topLevelItem(i).setIcon(0, file_icon)
                i += 1
        except Exception as e:
            util.logger.error(f"Error refreshing directories: {e}")

    # 获取当前目录列表
    def getDirNow(self):
        ssh_conn = self.ssh()
        pwd = self.getData2('cd ' + ssh_conn.pwd.replace("//", "/") + ' && pwd')
        dir_info = self.getData2(cmd='cd ' + ssh_conn.pwd.replace("//", "/") + ' && ls -al').split('\n')
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
                ssh_conn.timer1.timeout.connect(self.refreshAllInfo)
                ssh_conn.timer1.start(1000)
        except Exception as e:
            util.logger.error(f"Error setting up system info update: {e}")

    def refreshAllInfo(self):
        # 批量更新所有信息
        self.refreshSysInfo()

    # 刷新设备状态信息功能
    def refreshSysInfo(self):
        if self.isConnected:
            current_index = self.ui.ShellTab.currentIndex()
            this = self.ui.ShellTab.tabWhatsThis(current_index)
            if this:
                ssh_conn = mux.backend_index[this]
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

                # self.ui.networkUpload.setValue(util.format_speed(transmit_speed))
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
        ls = ssh_conn.exec("docker compose ls -a")
        lines = ls.strip().splitlines()

        # 获取compose 项目下的所有容器
        for compose_ls in lines[1:]:
            # 从右边开始分割，比如 rsplit，只分割最后一次空格
            # 这样最后一列可以拿出来
            parts = compose_ls.rsplit(None, 1)  # 从右边切一次空白字符
            config = parts[-1]
            ps_cmd = f"docker compose --file {config} ps -a --format '{{{{json .}}}}'"
            # 执行docker compose ps
            conn_exec = ssh_conn.exec(ps_cmd)
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

                groups = self.compose_container_list()
                if len(groups) != 0:
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
                                container_item = QTreeWidgetItem()
                                container_item.setText(1, c.get('ID', ""))
                                container_item.setText(2, c.get('Name', ""))
                                container_item.setText(3, c.get('Image', ""))
                                container_item.setText(4, c.get('State', ""))
                                container_item.setText(5, c.get('Command', ""))
                                container_item.setText(6, c.get('CreatedAt', ""))
                                container_item.setText(7, c.get('Ports', ""))
                                container_item.setIcon(0, QIcon(":icons8-docker-48.png"))
                                # 设置容器信息居中
                                # container_item.setTextAlignment(4, Qt.AlignCenter)
                                # 设置项目名称居中
                                for i in range(self.ui.treeWidgetDocker.columnCount()):
                                    container_item.setTextAlignment(i, Qt.AlignCenter)
                                project_item.addChild(container_item)
                elif len(groups) == 0:
                    container_list = self.docker_container_list()
                    # 只有容器的情况
                    for c in container_list:
                        container_item = QTreeWidgetItem()
                        container_item.setText(1, c.get('ID', ""))
                        container_item.setText(2, c.get('Names', ""))
                        container_item.setText(3, c.get('Image', ""))
                        container_item.setText(4, c.get('State', ""))
                        container_item.setText(5, c.get('Command', ""))
                        container_item.setText(6, c.get('CreatedAt', ""))
                        container_item.setText(7, c.get('Ports', ""))
                        container_item.setIcon(0, QIcon(":icons8-docker-48.png"))
                        # 设置容器信息居中
                        for i in range(self.ui.treeWidgetDocker.columnCount()):
                            container_item.setTextAlignment(i, Qt.AlignCenter)
                        self.ui.treeWidgetDocker.addTopLevelItem(container_item)
                else:
                    self.ui.treeWidgetDocker.addTopLevelItem(QTreeWidgetItem(0))
                    self.ui.treeWidgetDocker.topLevelItem(0).setText(0, self.tr('服务器还没有安装docker容器'))

                # 展开所有节点
                self.ui.treeWidgetDocker.expandAll()

        else:
            self.ui.treeWidgetDocker.clear()
            self.ui.treeWidgetDocker.addTopLevelItem(QTreeWidgetItem(0))
            self.ui.treeWidgetDocker.topLevelItem(0).setText(0, self.tr('没有可用的docker容器'))

    # 刷新docker常用容器信息
    def refresh_docker_common_containers(self):
        if self.isConnected:
            ssh_conn = self.ssh()
            util.clear_grid_layout(self.ui.gridLayout_7)
            # 检测服务器是否安装了docker，如果没有安装就不展示常用容器
            data_ = ssh_conn.exec('docker --version')
            if data_:
                services = util.get_compose_service(abspath('docker-compose-full.yml'))
                # 每行最多四个小块
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

                conn_exec = ssh_conn.exec("docker ps -a --format '{{json .}}'")
                container_list = []
                for ps in conn_exec.strip().splitlines():
                    if ps.strip():
                        data = json.loads(ps)
                        container_list.append(data)

                services_config = util.update_has_attribute(services, container_list)

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

    # 上传文件
    def uploadFile(self):
        ssh_conn = self.ssh()
        # 保存进度条字典，用于在上传完成后隐藏
        self.progress_bars = {}  # file_id -> progress_bar

        # 跟踪正在上传的文件数量和状态
        self.active_uploads = set()  # 跟踪正在上传的文件ID
        self.completed_uploads = set()  # 跟踪已完成的文件ID
        self.failed_uploads = set()  # 跟踪失败的文件ID

        # 打开文件对话框让用户选择文件
        files, _ = QFileDialog.getOpenFileNames(self, self.tr("选择文件"), "", self.tr("所有文件 (*)"))
        if files:
            # 创建上传器核心
            self.uploader = SFTPUploaderCore(ssh_conn.open_sftp())

            # 创建进度适配器
            self.progress_adapter = ProgressAdapter()
            self.progress_adapter.connect_signals(self.uploader)

            # 监听完成和失败信号，用于关闭进度条
            self.uploader.upload_completed.connect(self.on_upload_completed)
            self.uploader.upload_failed.connect(self.on_upload_failed)

            # 上传每个文件
            for local_path in files:
                file_id = str(uuid.uuid4())
                filename = os.path.basename(local_path)
                remote_path = f"{ssh_conn.pwd}/{filename}"  # 根据实际需要修改远程路径

                # 添加到正在上传的集合
                self.active_uploads.add(file_id)

                # 创建进度条控件
                progress_group = QWidget()
                progress_layout = QHBoxLayout(progress_group)

                # 文件信息标签
                label = QLabel(f"{filename}")
                progress_layout.addWidget(label, 1)

                # 进度条
                progress_bar = QProgressBar()
                progress_bar.setRange(0, 100)
                progress_bar.setValue(0)
                progress_layout.addWidget(progress_bar, 2)

                # 添加到主布局
                self.ui.download_with_resume.addWidget(progress_group)

                # 保存到字典中
                self.progress_bars[file_id] = progress_bar

                # 注册进度条到适配器
                self.progress_adapter.register_pyside_progress_bar(file_id, progress_bar, label)

                # 开始上传
                self.uploader.upload_file(file_id, local_path, remote_path)
            self.refreshDirs()

    def on_upload_completed(self, file_id, filename):
        """上传完成时隐藏进度条"""
        if file_id in self.progress_bars:
            # 获取进度条对象
            progress_bar = self.progress_bars[file_id]

            # 设置完成状态
            progress_bar.setValue(100)
            progress_bar.setFormat("完成")

            # 更新文件状态
            if file_id in self.active_uploads:
                self.active_uploads.remove(file_id)
                self.completed_uploads.add(file_id)

            # 检查是否所有文件都完成了
            self.check_all_uploads_completed()
            self.refreshDirs()

    def on_upload_failed(self, file_id, filename, error):
        """上传失败时标记进度条为失败状态"""
        if file_id in self.progress_bars:
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
            if file_id in self.active_uploads:
                self.active_uploads.remove(file_id)
                self.failed_uploads.add(file_id)

            # 检查是否所有文件都完成了
            self.check_all_uploads_completed()

    def check_all_uploads_completed(self):
        """检查是否所有上传都已完成，如果是则清理界面"""
        if not self.active_uploads and (self.completed_uploads or self.failed_uploads):
            # 所有上传都已完成或失败，延迟一段时间后清理界面
            from PySide6.QtCore import QTimer
            QTimer.singleShot(1500, self.clear_all_progress)  # 1.5秒后清理

    def clear_all_progress(self):
        """清除所有进度条和相关组件"""
        util.clear_grid_layout(self.ui.download_with_resume)
        # 重置状态
        self.active_uploads.clear()
        self.completed_uploads.clear()
        self.failed_uploads.clear()

    # 上传更新进度条
    def upload_update_progress(self, value):
        self.ui.download_with_resume.setValue(value)
        # 设置进度条为完成
        if value >= 100:
            self.ui.download_with_resume.setVisible(False)
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

    # 压缩 tar
    def zip(self):
        ssh_conn = self.ssh()
        selected_items = self.ui.treeWidget.selectedItems()
        # 要压缩的远程文件列表
        remote_files = []
        # 压缩文件名
        output_file = ""
        # 先取出所有选中项目
        for item in selected_items:
            item_text = item.text(0)
            remote_files.append(ssh_conn.pwd + '/' + item_text)
            s = str(item_text).lstrip('.')
            base_name, ext = os.path.splitext(s)
            output_file = f'{ssh_conn.pwd}/{base_name}.tar.gz'

        # 构建压缩命令
        files_str = ' '.join(remote_files)
        compress_command = f"tar -czf {output_file} {files_str}"
        ssh_conn.exec(compress_command)
        self.refreshDirs()

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

    # 解压 tar
    def unzip(self):
        ssh_conn = self.ssh()
        selected_items = self.ui.treeWidget.selectedItems()
        # 构建解压命令
        decompress_commands = []
        for item in selected_items:
            item_text = item.text(0)
            tar_file = ssh_conn.pwd + '/' + item_text
            decompress_commands.append(f"tar -xzvf {tar_file} -C {ssh_conn.pwd}")

        # 合并解压命令
        combined_command = " && ".join(decompress_commands)
        ssh_conn.exec(combined_command)
        self.refreshDirs()

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
        ssh_conn = self.ssh()
        mime_data = event.mimeData()
        if mime_data.hasUrls():
            for url in mime_data.urls():
                file_path = url.toLocalFile()
                if os.path.isfile(file_path):
                    self.fileEvent = file_path
                    sftp = ssh_conn.open_sftp()
                    try:
                        self.ui.download_with_resume.setVisible(True)

                        # 转换为 KB
                        self.upload_thread = UploadThread(sftp, file_path,
                                                          ssh_conn.pwd + '/' + os.path.basename(file_path))
                        self.upload_thread.start()
                        self.upload_thread.progress.connect(self.upload_update_progress)
                        # sftp.put(file_path, ssh_conn.pwd + '/' + os.path.basename(file_path))
                        # sftp.put(file_path, os.path.join(ssh_conn.pwd, os.path.basename(file_path)))
                    except (IOError, OSError) as e:
                        util.logger.error(f"Failed to upload file: {e}")
                        QMessageBox.critical(self, self.tr("上传失败"), self.tr(f"文件上传失败: {e}"))
            self.refreshDirs()

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
    def success(self, alart):
        """
        创建一个成功消息框，并设置自定义图标
        """
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
        self.dial.alarmbox = QMessageBox()
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

        # 使用Pygments进行语法高亮
        formatter = HtmlFormatter(style='fruity', noclasses=True)
        # 高亮代码
        highlighted = highlight(old_text, PythonLexer(), formatter)

        self.te.textEdit.setHtml(highlighted)
        self.te.textEdit.setStyleSheet('background-color: rgb(17, 17, 17);')
        self.new_text = self.te.textEdit.toPlainText()

        self.timer1 = None
        self.flushNewText()

        self.te.action.triggered.connect(lambda: self.saq(1))
        self.te.action_2.triggered.connect(lambda: self.daq(1))

    def flushNewText(self):
        self.timer1 = QTimer()
        self.timer1.start(100)
        self.timer1.timeout.connect(self.autosave)

    def autosave(self):
        text = self.te.textEdit.toPlainText()
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


# 上传文件
class UploadThread(QThread):
    progress = Signal(int)

    def __init__(self, sftp, local_path, remote_path):
        super().__init__()
        self.sftp = sftp
        self.local_path = local_path
        self.remote_path = remote_path

    def run(self):
        util.resume_upload(self.sftp, self.local_path, self.remote_path, self.progress.emit)


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
            # self.install_button.clicked.connect(lambda: self.show_install_docker_window(item, ssh_conn))
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
            highlighted = highlight(ack, PythonLexer(), formatter)
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
                highlighted = highlight(ack, PythonLexer(), formatter)
                self.dial.textBrowserDockerInout.append(highlighted)
                if ack:
                    for bind in item['volumes']:
                        source = bind.get('source')
                        cp = bind.get('cp')
                        cmd3 = f"docker cp {container_name}:{source}/ {cp}" + " "
                        ack = ssh_conn.exec(cmd=cmd3, pty=False)
                        highlighted = highlight(ack, PythonLexer(), formatter)
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
            highlighted = highlight(ack, PythonLexer(), formatter)
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
        # Ensure UI is updated after the tunnel operation completes
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


class TerminalHighlighter(QSyntaxHighlighter):
    def __init__(self, parent=None):
        super().__init__(parent)
        # 你可以在这里定义高亮规则，比如关键字、颜色等

    def highlightBlock(self, text):
        # 这里可以自定义高亮规则，比如高亮命令、路径、错误等
        # 示例：高亮以 $ 开头的行
        if text.strip().startswith("$"):
            fmt = QTextCharFormat()
            fmt.setForeground(QColor("#00FF00"))
            self.setFormat(0, len(text), fmt)


class TerminalWidget(QTextEdit):
    """
    自定义终端
    """
    termKeyPressed = Signal(str)  # 输入信号

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFont(QFont("Monospace", 13))
        # self.setStyleSheet("background-color: #000; color: #fff;")
        self.setUndoRedoEnabled(False)
        self.setLineWrapMode(QTextEdit.NoWrap)
        self.setCursorWidth(2)
        self.setTabStopDistance(4 * self.fontMetrics().horizontalAdvance(' '))

        self.highlighter = TerminalHighlighter(self.document())
        self.setReadOnly(False)
        self.setFocusPolicy(Qt.StrongFocus)

        # pyte 终端仿真
        self.screen = pyte.Screen(80, 24)
        self.stream = pyte.Stream(self.screen)

        # 禁止鼠标选中时弹出菜单
        # self.setContextMenuPolicy(Qt.NoContextMenu)

    def keyPressEvent(self, event):
        # 处理所有按键，转发给 SSH
        text = event.text()
        key = event.key()
        if key == Qt.Key_Return or key == Qt.Key_Enter:
            self.termKeyPressed.emit('\r')
        elif key == Qt.Key_Backspace:
            self.termKeyPressed.emit('\x7f')
        elif key == Qt.Key_Left:
            self.termKeyPressed.emit('\x1b[D')
        elif key == Qt.Key_Right:
            self.termKeyPressed.emit('\x1b[C')
        elif key == Qt.Key_Up:
            self.termKeyPressed.emit('\x1b[A')
        elif key == Qt.Key_Down:
            self.termKeyPressed.emit('\x1b[B')
        elif text:
            self.termKeyPressed.emit(text)
        # 不让 QPlainTextEdit 处理按键，全部交给 pyte+SSH
        # 不调用 super().keyPressEvent(event)

    # 重写 contextMenuEvent 方法
    # 自定义右键菜单
    def contextMenuEvent(self, event: QContextMenuEvent):
        # 创建一个 QMenu 对象
        menu = QMenu(self)
        menu.setStyleSheet("""
                QMenu::item {
                    padding-left: 5px;  /* 调整图标和文字之间的间距 */
                }
                QMenu::icon {
                    padding-right: 0px; /* 设置图标右侧的间距 */
                }
            """)

        # 创建复制和粘贴的 QAction 对象
        copy_action = QAction(QIcon(":copy.png"), self.tr('复制'), self)
        copy_action.setIconVisibleInMenu(True)
        paste_action = QAction(QIcon(":paste.png"), self.tr('粘贴'), self)
        paste_action.setIconVisibleInMenu(True)
        clear_action = QAction(QIcon(":clear.png"), self.tr('清屏'), self)
        clear_action.setIconVisibleInMenu(True)

        # 绑定槽函数到 QAction 对象
        copy_action.triggered.connect(self.copy)
        paste_action.triggered.connect(self.paste)
        clear_action.triggered.connect(self.clear_term)

        # 将 QAction 对象添加到菜单中
        menu.addAction(copy_action)
        menu.addAction(paste_action)
        menu.addAction(clear_action)

        # 显示菜单
        menu.exec(event.globalPos())

    # 复制文本
    def copy(self):
        # 获取当前选中的文本，并复制到剪贴板
        selected_text = self.textCursor().selectedText()
        clipboard = QApplication.clipboard()
        clipboard.setText(selected_text)

    # 粘贴文本
    def paste(self):
        # 从剪贴板获取文本，并粘贴到终端
        clipboard = QApplication.clipboard()
        clipboard_text = clipboard.text()
        if clipboard_text:
            self.termKeyPressed.emit(clipboard_text)

    def clear_term(self):
        self.termKeyPressed.emit('clear' + '\n')

    def wheelEvent(self, event):
        """处理鼠标滚轮事件"""
        if event.modifiers() & Qt.ControlModifier:
            # 转发到MainDialog处理
            parent = self.window()
            if hasattr(parent, 'zoom_in') and hasattr(parent, 'zoom_out'):
                if event.angleDelta().y() > 0:
                    parent.zoom_in()
                else:
                    parent.zoom_out()
                event.accept()
                return
        # 默认处理
        super().wheelEvent(event)


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


if __name__ == '__main__':
    print("PySide6 version:", PySide6.__version__)
    app = QApplication(sys.argv)

    translator = QTranslator()
    # 加载编译后的 .qm 文件
    translator.load("app_zh_CN.qm")

    # 安装翻译
    app.installTranslator(translator)

    window = MainDialog(app)

    window.show()
    window.refreshConf()
    sys.exit(app.exec())
