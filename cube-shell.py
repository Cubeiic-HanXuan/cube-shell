import asyncio
import glob
import json
import os
import pickle
import platform
import re
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import PySide6
import qdarktheme
from PySide6 import QtWidgets, QtGui
from PySide6.QtCore import QTimer, Signal, Qt, QPoint, QRect, QEvent, QObject, Slot, QUrl, QCoreApplication, \
    QTranslator, QSize
from PySide6.QtGui import QIcon, QAction, QTextCursor, QCursor, QCloseEvent, QKeyEvent, QInputMethodEvent, QPixmap, \
    QDragEnterEvent, QDropEvent, QFont, QContextMenuEvent, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QApplication, QMainWindow, QMenu, QDialog, QMessageBox, QTreeWidgetItem, \
    QInputDialog, QFileDialog, QTreeWidget, QWidget, QVBoxLayout, QLabel, QHBoxLayout, QPushButton, QTableWidgetItem, \
    QHeaderView, QStyle, QTabBar, QTextBrowser
from deepdiff import DeepDiff
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import PythonLexer

from core.forwarder import ForwarderManager
from core.frequently_used_commands import TreeSearchApp
from core.mux import mux
from core.vars import ICONS, CONF_FILE, CMDS, KEYS
from function import util, about, theme
from function.ssh_func import SshClient
from function.util import format_file_size, has_valid_suffix
from style.style import updateColor
from ui import add_config, text_editor, confirm, main, docker_install
from ui.add_tunnel_config import Ui_AddTunnelConfig
from ui.tunnel import Ui_Tunnel
from ui.tunnel_config import Ui_TunnelConfig
import icons.icons

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


# 主界面逻辑
class MainDialog(QMainWindow):
    initSftpSignal = Signal()

    def __init__(self, qt_app):
        super().__init__()
        self.app = qt_app  # 将 app 传递并设置为类属性
        self.ui = main.Ui_MainWindow()
        self.ui.setupUi(self)
        self.setWindowIcon(QIcon(":logo.ico"))
        self.setAttribute(Qt.WA_InputMethodEnabled, True)
        self.setAttribute(Qt.WA_KeyCompression, True)
        self.setFocusPolicy(Qt.WheelFocus)
        icon = QIcon(":index.png")
        self.ui.ShellTab.tabBar().setTabIcon(0, icon)

        self.setDarkTheme()  # 默认设置为暗主题

        file_path = 'conf/theme.json'
        # 读取 JSON 文件内容
        util.THEME = util.read_json(file_path)

        # 隧道管理
        self.data = None
        self.tunnels = []
        self.tunnel_refresh()

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

        self.buffer = ""
        self.prompt_pos = 0
        self.prompt = ""

        self.ssh_username, self.ssh_password, self.ssh_ip, self.key_type, self.key_file = None, None, None, None, None

        self.ui.discButton.clicked.connect(self.disc_off)
        self.ui.theme.clicked.connect(self.toggleTheme)
        self.ui.treeWidget.customContextMenuRequested.connect(self.treeRight)
        self.ui.treeWidget.doubleClicked.connect(self.cd)
        self.ui.ShellTab.currentChanged.connect(self.shell_tab_current_changed)
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
        self.startTimer(50)
        # 连接信号和槽
        self.initSftpSignal.connect(self.on_initSftpSignal)

    # 删除标签页
    def _delete_tab(self):  # 删除标签页
        current_index = self.ui.ShellTab.currentIndex()
        current_index1 = self.ui.ShellTab.tabText(current_index)
        if current_index1 != "首页":
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

            self.Shell = QTextBrowser(self.tab)
            self.Shell.setObjectName(u"Shell")
            self.verticalLayout_shell.addWidget(self.Shell)
            self.verticalLayout_index.addLayout(self.verticalLayout_shell)
            tab_name = self.generate_unique_tab_name(name)
            tab_index = self.ui.ShellTab.addTab(self.tab, tab_name)
            self.ui.ShellTab.setCurrentIndex(tab_index)
            self.Shell.setAttribute(Qt.WA_InputMethodEnabled, True)
            self.Shell.setAttribute(Qt.WA_KeyCompression, True)
            # 重写 contextMenuEvent 方法
            self.Shell.contextMenuEvent = self.showCustomContextMenu

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
            return tab.findChild(QTextBrowser, "Shell")
        return None

    # 监听标签页切换
    def shell_tab_current_changed(self, index):
        current_index = self.ui.ShellTab.currentIndex()

        if mux.backend_index:
            current_text = self.ui.ShellTab.tabText(index)
            this = self.ui.ShellTab.tabWhatsThis(current_index)
            if this:
                ssh_conn = mux.backend_index[this]
                if current_text == "首页":
                    if ssh_conn:
                        ssh_conn.close_sig = 0
                    self.isConnected = False
                    self.ui.treeWidget.setColumnCount(1)
                    self.ui.treeWidget.setHeaderLabels(["设备列表"])
                    self.ui.remove_last_line_edit()
                    self.ui.treeWidget.clear()
                    self.refreshConf()
                else:
                    if mux.backend_index:
                        ssh_conn.close_sig = 1
                        self.isConnected = True
                        self.refreshDirs()
                        self.processInitUI()
            else:
                if current_text == "首页":
                    self.isConnected = False
                    self.ui.treeWidget.setColumnCount(1)
                    self.ui.treeWidget.setHeaderLabels(["设备列表"])
                    self.ui.remove_last_line_edit()
                    self.ui.treeWidget.clear()
                    self.refreshConf()

    def index_pwd(self):
        if platform.system() == 'Darwin':
            pass
        else:
            self.ui.label_7.setText("添加配置 Shift+Ctrl+A")
            self.ui.label_9.setText("添加隧道 Shift+Ctrl+S")
            self.ui.label_11.setText("帮助 Shift+Ctrl+H")
            self.ui.label_12.setText("关于 Shift+Ctrl+B")
            self.ui.label_13.setText("查找命令行 Shift+Ctrl+C")

    # 进程列表初始化
    def processInitUI(self):
        # 创建表格部件
        self.ui.result.setColumnCount(6)
        # 展示表头标签
        self.ui.result.horizontalHeader().setVisible(True)
        self.ui.result.setHorizontalHeaderLabels(["PID", "用户", "内存", "CPU", "地址", "命令行"])
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
        kill_action = QAction(QIcon(':kill.png'), 'Kill 进程', self)
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
            current_index = self.ui.ShellTab.currentIndex()
            this = self.ui.ShellTab.tabWhatsThis(current_index)
            ssh_conn = mux.backend_index[this]
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
            QMessageBox.critical(self, "Error", f"连接或检索进程列表失败: {e}")
            return []

    # kill 选中的进程数据
    def kill_process(self, selected_rows):
        pips = ""
        for value in selected_rows:
            pips += str(value) + " "
        # 优雅结束进程，避免数据丢失
        command = "echo " + pips + "| xargs -n 1 kill -15"

        try:
            current_index = self.ui.ShellTab.currentIndex()
            this = self.ui.ShellTab.tabWhatsThis(current_index)
            ssh_conn = mux.backend_index[this]

            # 在远程服务器上执行命令结束进程
            stdin, stdout, stderr = ssh_conn.conn.exec_command(timeout=10, command=command, get_pty=False)
            error = stderr.read().decode('utf-8').strip()
            if error:
                QMessageBox.warning(self, "Warning", f"服务器结束以下进程出错 {pips}: {error}")
            else:
                QMessageBox.information(self, "Success", f"以下进程 {pips} 被成功 kill.")
                self.update_process_list()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"kill 以下进程失败 {pips}: {e}")

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
                self.send(text.encode("utf-8"))
            else:
                s = keymap.get(key)
                if s:
                    self.send(s)

        event.accept()

    def keyReleaseEvent(self, event: QKeyEvent):
        if mux.backend_index:
            text = str(event.text())
            key = event.key()
            current_index = self.ui.ShellTab.currentIndex()
            this = self.ui.ShellTab.tabWhatsThis(current_index)
            ssh_conn = mux.backend_index[this]

            if text and key == Qt.Key_Space:
                self.send(text.encode("utf-8"))
            elif text and key == Qt.Key_Tab:
                self.send(text.encode("utf-8"))
            elif key == Qt.Key_Up:
                # 点击上键查询历史命令
                self.send(b'\x1b[A')
            elif key == Qt.Key_Down:
                # 点击下键查询历史命令
                self.send(b'\x1b[B')
            elif key == Qt.Key_Left:
                ssh_conn.buffer_write = b'\x1b[D'
                self.send(b'\x1b[D')
            elif key == Qt.Key_Right:
                ssh_conn.buffer_write = b'\x1b[C'
                self.send(b'\x1b[C')

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
        self.data = util.read_json(CONF_FILE)
        self.tunnels = []

        # 展示ssh隧道列表
        if self.data:
            i = 0
            for i, name in enumerate(sorted(self.data.keys())):
                tunnel = Tunnel(name, self.data[name], self)
                self.tunnels.append(tunnel)
                self.ui.gridLayout_tunnel_tabs.addWidget(tunnel, i, 0)
            self.kill_button = QPushButton('关闭所有隧道')
            self.kill_button.setIcon(QIcon(ICONS.KILL_SSH))
            self.kill_button.setFocusPolicy(Qt.NoFocus)
            self.kill_button.clicked.connect(self.do_killall_ssh)
            self.ui.gridLayout_kill_all.addWidget(self.kill_button, i + 1, 0)

    def menuBarController(self):
        # 创建菜单栏
        menubar = self.menuBar()

        file_menu = menubar.addMenu("文件")
        # 创建“设置”菜单
        setting_menu = menubar.addMenu("设置")
        # 创建“帮助”菜单
        help_menu = menubar.addMenu("帮助")

        # 创建“新建”动作
        new_action = QAction(QIcon(":icons8-ssh-48.png"), "&新增配置", self)
        new_action.setShortcut("Shift+Ctrl+A")
        new_action.setStatusTip("添加配置")
        file_menu.addAction(new_action)
        new_action.triggered.connect(self.showAddConfig)

        new_ssh_tunnel_action = QAction(QIcon(ICONS.TUNNEL), "&新增SSH隧道", self)
        new_ssh_tunnel_action.setShortcut("Shift+Ctrl+S")
        new_ssh_tunnel_action.setStatusTip("新增SSH隧道")
        file_menu.addAction(new_ssh_tunnel_action)
        new_ssh_tunnel_action.triggered.connect(self.showAddSshTunnel)

        # 创建“主题设置”动作
        theme_action = QAction(QIcon(":undo.png"), "&主题设置", self)
        theme_action.setShortcut("Shift+Ctrl+T")
        theme_action.setStatusTip("设置主题")
        setting_menu.addAction(theme_action)
        theme_action.triggered.connect(self.theme)
        #
        # # 创建“重做”动作
        # redo_action = QAction(QIcon(":redo.png"), "&Redo", self)
        # redo_action.setShortcut("Ctrl+Y")
        # redo_action.setStatusTip("Redo last undone action")
        # setting_menu.addAction(redo_action)

        # 创建“关于”动作
        about_action = QAction(QIcon(":about.png"), "&关于", self)
        about_action.setShortcut("Shift+Ctrl+B")
        about_action.setStatusTip("cubeShell 有关信息")
        help_menu.addAction(about_action)
        about_action.triggered.connect(self.about)

        linux_action = QAction(QIcon(":about.png"), "&Linux常用命令", self)
        linux_action.setShortcut("Shift+Ctrl+P")
        linux_action.setStatusTip("最常用的Linux命令查找")
        help_menu.addAction(linux_action)
        linux_action.triggered.connect(self.linux)

        help_action = QAction(QIcon(":about.png"), "&帮助", self)
        help_action.setShortcut("Shift+Ctrl+H")
        help_action.setStatusTip("cubeShell使用说明")
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
                if self.ui.ShellTab.tabText(self.originalIndex) == "首页":
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

    # 自定义右键菜单
    def showCustomContextMenu(self, event: QContextMenuEvent):
        # 创建一个 QMenu 对象
        menu = QMenu(self.Shell)
        menu.setStyleSheet("""
                QMenu::item {
                    padding-left: 5px;  /* 调整图标和文字之间的间距 */
                }
                QMenu::icon {
                    padding-right: 0px; /* 设置图标右侧的间距 */
                }
            """)

        # 创建复制和粘贴的 QAction 对象
        copy_action = QAction(QIcon(":copy.png"), '复制', self)
        paste_action = QAction(QIcon(":paste.png"), '粘贴', self)
        clear_action = QAction(QIcon(":clear.png"), '清屏', self)

        # 绑定槽函数到 QAction 对象
        copy_action.triggered.connect(self.copy)
        paste_action.triggered.connect(self.paste)
        clear_action.triggered.connect(self.clear)

        # 将 QAction 对象添加到菜单中
        menu.addAction(copy_action)
        menu.addAction(paste_action)
        menu.addAction(clear_action)

        # 显示菜单
        menu.exec(event.globalPos())

    # 复制文本
    def copy(self):
        # 获取当前选中的文本，并复制到剪贴板
        selected_text = self.Shell.textCursor().selectedText()
        clipboard = QApplication.clipboard()
        clipboard.setText(selected_text)

    # 粘贴文本
    def paste(self):
        # 从剪贴板获取文本，并粘贴到 QTextBrowser
        clipboard = QApplication.clipboard()
        clipboard_text = clipboard.text()
        self.send(clipboard_text.encode('utf8'))

    def clear(self):
        self.send('clear'.encode('utf8') + b'\n')

    # 连接服务器
    def run(self):
        focus = self.ui.treeWidget.currentIndex().row()
        if focus != -1:
            name = self.ui.treeWidget.topLevelItem(focus).text(0)
            with open('conf/config.dat', 'rb') as c:
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
                QMessageBox.warning(self, "连接超时", "服务器无法连接，请检查网络或服务器状态。")
                return

            try:
                ssh_conn = SshClient(host.split(':')[0], int(host.split(':')[1]), username, password,
                                     key_type, key_file)

                # 启动一个线程来异步执行 SSH 连接
                threading.Thread(target=self.connect_ssh_thread, args=(ssh_conn,), daemon=True).start()
                self.ssh_username, self.ssh_password, self.ssh_ip, self.key_type, self.key_file = username, password, \
                    host, key_type, key_file
            except Exception as e:
                print(str(e))
                self.Shell.setPlaceholderText(str(e))
        else:
            self.alarm('请选择一台设备！')

    def connect_ssh_thread(self, ssh_conn):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            loop.run_until_complete(self.async_connect_ssh(ssh_conn))
        finally:
            loop.close()

    async def async_connect_ssh(self, ssh_conn):
        # 创建一个线程池执行器
        executor = ThreadPoolExecutor(max_workers=1)

        # 在线程池中执行同步的 connect 方法
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(executor, ssh_conn.connect)

        current_index = self.ui.ShellTab.currentIndex()
        self.ui.ShellTab.setTabWhatsThis(current_index, ssh_conn.id)

        # 异步初始化 SFTP
        self.initSftpSignal.emit()

    # 初始化sftp和控制面板
    def initSftp(self):
        current_index = self.ui.ShellTab.currentIndex()
        this = self.ui.ShellTab.tabWhatsThis(current_index)
        ssh_conn = mux.backend_index[this]

        self.isConnected = True
        self.ui.discButton.setEnabled(True)
        self.ui.result.setEnabled(True)
        self.ui.theme.setEnabled(True)
        threading.Thread(target=ssh_conn.get_datas, daemon=True).start()
        self.flushSysInfo()
        self.refreshDokerInfo()
        self.flushDokerInfo()
        self.refreshDirs()

        # 读取json文件
        items = util.read_json_file("conf/docker.json")
        # 每行最多四个小块
        max_columns = 6
        # 遍历列表，创建小块并添加到网格布局中
        for index, item in enumerate(items):
            row = index // max_columns
            col = index % max_columns

            # 创建外部容器
            container_widget = QWidget()
            container_layout = QVBoxLayout()
            container_widget.setLayout(container_layout)
            container_layout.setContentsMargins(0, 0, 0, 0)  # 去掉布局的内边距
            container_widget.setStyleSheet("background-color: rgb(187, 232, 221);")

            # 创建自定义小块并添加到外部容器
            widget = CustomWidget(item, ssh_conn)
            container_layout.addWidget(widget)

            self.ui.gridLayout_7.addWidget(container_widget, row, col)

        # 进程管理
        self.processInitUI()

    def on_initSftpSignal(self):
        self.initSftp()

    # 后台获取信息，不打印至程序界面
    def getData2(self, cmd='', pty=False):
        try:
            current_index = self.ui.ShellTab.currentIndex()
            this = self.ui.ShellTab.tabWhatsThis(current_index)
            ssh_conn = mux.backend_index[this]
            ack = ssh_conn.exec(cmd=cmd, pty=pty)
            return ack
        except Exception as e:
            self.ui.result.append(e)
            return 'error'

    # 选择文件夹
    def cd(self):
        if self.isConnected:
            focus = self.ui.treeWidget.currentIndex().row()
            if focus != -1 and self.dir_tree_now[focus][0].startswith('d'):
                current_index = self.ui.ShellTab.currentIndex()
                this = self.ui.ShellTab.tabWhatsThis(current_index)
                ssh_conn = mux.backend_index[this]
                ssh_conn.pwd = self.getData2(
                    'cd ' + ssh_conn.pwd + '/' + self.ui.treeWidget.topLevelItem(focus).text(0) +
                    ' && pwd')[:-1]
                self.refreshDirs()
            else:
                self.alarm('文件无法前往，右键编辑文件！')
        elif not self.isConnected:
            self.add_new_tab()
            self.run()

    # 断开服务器
    def _off(self, name):
        this = self.get_tab_whats_this_by_name(name)
        ssh_conn = mux.backend_index[this]

        ssh_conn.timer1.stop()
        ssh_conn.timer2.stop()
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
        self.ui.treeWidget.setHeaderLabels(["设备列表"])
        self.ui.remove_last_line_edit()
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

        ssh_conn.close()
        self.refreshConf()

    # 断开服务器并删除tab
    def off(self, index, name):
        self._off(name)
        self._remove_tab_by_name(name)

    # 关闭当前连接
    def disc_off(self):
        current_index = self.ui.ShellTab.currentIndex()
        name = self.ui.ShellTab.tabText(current_index)
        if name != "首页":
            self._off(name)
            self._remove_tab_by_name(name)

    def timerEvent(self, event):
        try:
            current_index = self.ui.ShellTab.currentIndex()
            this = self.ui.ShellTab.tabWhatsThis(current_index)
            ssh_conn = mux.backend_index[this]
            if not ssh_conn.screen.dirty:
                if ssh_conn.buffer_write:
                    self.updateTerminal(ssh_conn)
                    ssh_conn.buffer_write = b''
                return

            self.updateTerminal(ssh_conn)
            self.update()
        except:
            pass

    # 更新终端输出
    def updateTerminal(self, ssh_conn):
        current_index = self.ui.ShellTab.currentIndex()
        shell = self.get_text_browser_from_tab(current_index)

        font_ = util.THEME['font']
        theme_ = util.THEME['theme']
        color_ = util.THEME['theme_color']

        font = QFont(font_, 14)
        shell.setFont(font)

        shell.moveCursor(QTextCursor.End)
        screen = ssh_conn.screen
        # 使用 filter() 函数过滤空行
        # 添加光标表示
        cursor_x = screen.cursor.x
        cursor_y = screen.cursor.y
        lines = screen.display
        if cursor_y < len(lines):
            line = lines[cursor_y]
            lines[cursor_y] = line[:cursor_x] + '▉' + line[cursor_x:]
        filtered_lines = list(filter(lambda x: x.strip(), lines))

        terminal_str = '\n'.join(filtered_lines)

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
            highlighted2 = highlight(util.BANNER + replace, PythonLexer(), formatter)
        else:
            # 高亮代码
            highlighted2 = highlight(replace, PythonLexer(), formatter)

        # 将HTML插入QTextBrowser
        shell.setHtml(highlighted2)

        shell.moveCursor(QTextCursor.End)

        # 如果没有这串代码，执行器就会疯狂执行代码
        ssh_conn.screen.dirty.clear()

    def send(self, data):
        if mux.backend_index:
            current_index = self.ui.ShellTab.currentIndex()
            this = self.ui.ShellTab.tabWhatsThis(current_index)
            ssh_conn = mux.backend_index[this]
            ssh_conn.write(data)

    def do_killall_ssh(self):
        for tunnel in self.tunnels:
            tunnel.stop_tunnel()
        if os.name == 'nt':
            os.system(CMDS.SSH_KILL_WIN)
        else:
            os.system(CMDS.SSH_KILL_NIX)

    def closeEvent(self, event):
        """
         窗口关闭事件 当存在通道的时候关闭通道
         不存在时结束多路复用器的监听
        :param event: 关闭事件
        :return: None
        """
        # current_index = self.ui.ShellTab.currentIndex()
        # this = self.ui.ShellTab.tabWhatsThis(current_index)
        # ssh_conn = mux.backend_index[this]
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
            shutil.copy(CONF_FILE, F"{CONF_FILE}-{timestamp}")
            with open(CONF_FILE, "w") as fp:
                json.dump(data, fp)
            backup_configs = glob.glob(F"{CONF_FILE}-*")
            if len(backup_configs) > 10:
                for config in sorted(backup_configs, reverse=True)[10:]:
                    os.remove(config)
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
            self.ui.action = QAction(QIcon(':addConfig.png'), '添加配置', self)
            self.ui.action1 = QAction(QIcon(':addConfig.png'), '编辑配置', self)
            self.ui.action2 = QAction(QIcon(':delConf.png'), '删除配置', self)
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

            self.ui.action1 = QAction(QIcon(':Download.png'), '下载文件', self)
            self.ui.action2 = QAction(QIcon(':Upload.png'), '上传文件', self)
            self.ui.action3 = QAction(QIcon(':Edit.png'), '编辑文本', self)
            self.ui.action4 = QAction(QIcon(':createdirector.png'), '创建文件夹', self)
            self.ui.action5 = QAction(QIcon(':createfile.png'), '创建文件', self)
            self.ui.action6 = QAction(QIcon(':refresh.png'), '刷新', self)

            self.ui.action7 = QAction(QIcon(':remove.png'), '删除', self)
            self.ui.tree_menu.addAction(self.ui.action1)
            self.ui.tree_menu.addAction(self.ui.action2)
            self.ui.tree_menu.addAction(self.ui.action3)
            self.ui.tree_menu.addAction(self.ui.action4)
            self.ui.tree_menu.addAction(self.ui.action5)
            self.ui.tree_menu.addAction(self.ui.action6)

            # 添加分割线,做标记区分
            bottom_separator = QAction(self)
            bottom_separator.setSeparator(True)
            self.ui.tree_menu.addAction(bottom_separator)

            self.ui.tree_menu.addAction(self.ui.action7)
            self.ui.action1.triggered.connect(self.downloadFile)
            self.ui.action2.triggered.connect(self.uploadFile)
            self.ui.action3.triggered.connect(self.editFile)
            self.ui.action4.triggered.connect(self.createDir)
            self.ui.action5.triggered.connect(self.createFile)
            self.ui.action6.triggered.connect(self.refresh)
            self.ui.action7.triggered.connect(self.remove)
            # 声明当鼠标在groupBox控件上右击时，在鼠标位置显示右键菜单   ,exec_,popup两个都可以，
            self.ui.tree_menu.popup(QCursor.pos())

    # 创建docker列表树右键菜单函数
    def treeDocker(self):
        if self.isConnected:
            self.ui.tree_menu = QMenu(self)
            self.ui.tree_menu.setStyleSheet("""
                QMenu::item {
                    padding-left: 5px;  /* 调整图标和文字之间的间距 */
                }
                QMenu::icon {
                    padding-right: 0px; /* 设置图标右侧的间距 */
                }
            """)
            self.ui.action1 = QAction(QIcon(':stop.png'), '停止', self)
            self.ui.action2 = QAction(QIcon(':restart.png'), '重启', self)
            self.ui.action3 = QAction(QIcon(':remove.png'), '删除', self)
            # self.ui.action4 = QAction('日志', self)

            self.ui.tree_menu.addAction(self.ui.action1)
            self.ui.tree_menu.addAction(self.ui.action2)
            self.ui.tree_menu.addAction(self.ui.action3)
            # self.ui.tree_menu.addAction(self.ui.action4)

            self.ui.action1.triggered.connect(self.stopDockerContainer)
            self.ui.action2.triggered.connect(self.restartDockerContainer)
            self.ui.action3.triggered.connect(self.rmDockerContainer)
            # self.ui.action4.triggered.connect(self.rmDockerContainer)

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
                QMessageBox.warning(self, '警告', '只能编辑一个设备')
                return
            # 遍历选中的项
            for item in selected_items:
                # 获取项的内容
                name = item.text(0)
                with open('conf/config.dat', 'rb') as c:
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

    # 刷新设备列表
    def refreshConf(self):
        if not os.path.exists('conf/config.dat'):
            with open('conf/config.dat', 'wb') as c:
                start_dic = {}
                c.write(pickle.dumps(start_dic))
                c.close()
        with open('conf/config.dat', 'rb') as c:
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

    # 当前目录列表刷新
    def refreshDirs(self):
        current_index = self.ui.ShellTab.currentIndex()
        this = self.ui.ShellTab.tabWhatsThis(current_index)
        ssh_conn = mux.backend_index[this]
        ssh_conn.pwd, files = self.getDirNow()
        self.dir_tree_now = files[1:]
        self.ui.treeWidget.setHeaderLabels(["文件名", "文件大小", "修改日期", "权限", "所有者/组"])
        self.ui.add_line_edit('当前目录：' + ssh_conn.pwd)  # 添加一个初始的 QLineEdit
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

    # 获取当前目录列表
    def getDirNow(self):
        current_index = self.ui.ShellTab.currentIndex()
        this = self.ui.ShellTab.tabWhatsThis(current_index)
        ssh_conn = mux.backend_index[this]
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
            self.alarm('只能编辑一个文件！')
            return
        focus = self.ui.treeWidget.currentIndex().row()
        if focus != -1 and self.dir_tree_now[focus][0].startswith('-'):
            self.file_name = self.ui.treeWidget.currentItem().text(0)
            if has_valid_suffix(self.file_name):
                self.alarm('不支持编辑此文件！')
                return
            current_index = self.ui.ShellTab.currentIndex()
            this = self.ui.ShellTab.tabWhatsThis(current_index)
            ssh_conn = mux.backend_index[this]
            text = self.getData2('cat ' + ssh_conn.pwd + '/' + self.file_name)
            if text != 'error' and text != '\n':
                self.ui.addTextEditWin = TextEditor(title=self.file_name, old_text=text)
                self.ui.addTextEditWin.show()
                self.ui.addTextEditWin.save_tex.connect(self.getNewText)
            elif text == 'error' or text == '\n':
                self.alarm('无法编辑文件，请确认！')
        else:
            self.alarm('文件夹不能被编辑！')

    def createDir(self):
        current_index = self.ui.ShellTab.currentIndex()
        this = self.ui.ShellTab.tabWhatsThis(current_index)
        ssh_conn = mux.backend_index[this]
        dialog = QInputDialog(self)
        dialog.setWindowTitle('创建文件夹')
        dialog.setLabelText('文件夹名字:')
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
                    print(f"An error occurred: {create_error}")
                    self.alarm('创建文件夹失败，请联系开发作者')
            else:
                self.alarm('文件夹已存在')

    # 创建文件
    def createFile(self):
        current_index = self.ui.ShellTab.currentIndex()
        this = self.ui.ShellTab.tabWhatsThis(current_index)
        ssh_conn = mux.backend_index[this]
        dialog = QInputDialog(self)
        dialog.setWindowTitle('创建文件')
        dialog.setLabelText('文件名字:')
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
                print(f"创建文件出现异常: {e}")
                self.alarm('创建文件失败，请联系开发作者')

    # 获取返回信息，并保存文件
    def getNewText(self, new_list):
        current_index = self.ui.ShellTab.currentIndex()
        this = self.ui.ShellTab.tabWhatsThis(current_index)
        ssh_conn = mux.backend_index[this]
        nt, sig = new_list[0], new_list[1]
        # 将双引号转义为转义字符
        escaped_string = nt.replace("\"", '\\"')
        if sig == 0:
            self.getData2('echo -e "' + escaped_string + '" > ' + ssh_conn.pwd + '/' + self.file_name)
            self.ui.addTextEditWin.new_text = self.ui.addTextEditWin.old_text
            self.ui.addTextEditWin.te.chk.close()
            self.ui.addTextEditWin.close()
        elif sig == 1:
            self.getData2('echo -e "' + escaped_string + '" > ' + ssh_conn.pwd + '/' + self.file_name)
            self.ui.addTextEditWin.old_text = nt

    # 删除设备配置文件
    def delConf(self):
        # 创建消息框
        reply = QMessageBox()
        reply.setWindowTitle('确认删除')
        reply.setText(f'您确定要删除选中设备吗？这将无法恢复！')
        reply.setStandardButtons(QMessageBox.Yes | QMessageBox.No)

        # 设置按钮文本为中文
        yes_button = reply.button(QMessageBox.Yes)
        no_button = reply.button(QMessageBox.No)
        yes_button.setText("确定")
        no_button.setText("取消")
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
                    with open('conf/config.dat', 'rb') as c:
                        conf = pickle.loads(c.read())
                    with open('conf/config.dat', 'wb') as c:
                        del conf[name]
                        c.write(pickle.dumps(conf))
                self.refreshConf()

    # 定时刷新设备状态信息
    def flushSysInfo(self):
        current_index = self.ui.ShellTab.currentIndex()
        this = self.ui.ShellTab.tabWhatsThis(current_index)
        ssh_conn = mux.backend_index[this]

        timer1 = QTimer()
        timer1.start(1000)
        ssh_conn.timer1 = timer1
        ssh_conn.timer1.timeout.connect(self.refreshSysInfo)

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
                    self.ui.kernel.setText("无")

        else:
            self.ui.cpuRate.setValue(0)
            self.ui.memRate.setValue(0)
            self.ui.diskRate.setValue(0)

    def flushDokerInfo(self):
        current_index = self.ui.ShellTab.currentIndex()
        this = self.ui.ShellTab.tabWhatsThis(current_index)
        ssh_conn = mux.backend_index[this]

        timer2 = QTimer()
        timer2.start(5000)
        ssh_conn.timer2 = timer2
        ssh_conn.timer2.timeout.connect(self.refreshDokerInfo)

    def refreshDokerInfo(self):
        if self.isConnected:
            current_index = self.ui.ShellTab.currentIndex()
            this = self.ui.ShellTab.tabWhatsThis(current_index)
            if this:
                ssh_conn = mux.backend_index[this]

                info = ssh_conn.docker_info
                self.ui.treeWidgetDocker.clear()
                self.ui.treeWidgetDocker.headerItem().setText(0, 'docker容器管理：')
                if len(info) != 0:
                    i = 0
                    for n in info:
                        self.ui.treeWidgetDocker.addTopLevelItem(QTreeWidgetItem(0))
                        self.ui.treeWidgetDocker.topLevelItem(i).setText(0, n)
                        if i != 0:
                            self.ui.treeWidgetDocker.topLevelItem(i).setIcon(0, QIcon(":icons8-docker-48.png"))
                        # 设置字体为加粗
                        if i == 0:
                            bold_font = QFont()
                            bold_font.setBold(True)  # 设置字体为加粗
                            self.ui.treeWidgetDocker.topLevelItem(i).setFont(0, bold_font)

                        i += 1

                    # 设置列宽为自适应内容
                    for i in range(self.ui.treeWidgetDocker.columnCount()):
                        self.ui.treeWidgetDocker.resizeColumnToContents(i)
                else:
                    self.ui.treeWidgetDocker.addTopLevelItem(QTreeWidgetItem(0))
                    self.ui.treeWidgetDocker.topLevelItem(0).setText(0, '没有可用的docker容器')
        else:
            self.ui.treeWidgetDocker.clear()
            self.ui.treeWidgetDocker.addTopLevelItem(QTreeWidgetItem(0))
            self.ui.treeWidgetDocker.topLevelItem(0).setText(0, '没有可用的docker容器')

    # 下载文件
    def downloadFile(self):
        try:
            # 选择保存文件夹
            directory = QFileDialog.getExistingDirectory(
                None,  # 父窗口，这里为None表示没有父窗口
                '选择保存文件夹',  # 对话框标题
                '',  # 默认打开目录
                QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks  # 显示选项
            )
            if directory:
                current_index = self.ui.ShellTab.currentIndex()
                this = self.ui.ShellTab.tabWhatsThis(current_index)
                ssh_conn = mux.backend_index[this]
                items = self.ui.treeWidget.selectedItems()
                sftp = ssh_conn.open_sftp()
                for item in items:
                    item_text = item.text(0)
                    sftp.get(ssh_conn.pwd + '/' + item_text, f'{directory}/{item_text}')

            self.success("下载文件")
        except Exception as e:
            print(e)
            self.alarm('无法下载文件，请确认！')

    # 上传文件
    def uploadFile(self):
        # 打开文件对话框让用户选择文件
        files, _ = QFileDialog.getOpenFileNames(self, "选择文件", "", "所有文件 (*)")
        if files:
            for file_path in files:
                if os.path.isfile(file_path):
                    current_index = self.ui.ShellTab.currentIndex()
                    this = self.ui.ShellTab.tabWhatsThis(current_index)
                    ssh_conn = mux.backend_index[this]
                    sftp = ssh_conn.open_sftp()
                    try:
                        sftp.put(file_path, ssh_conn.pwd + '/' + os.path.basename(file_path))
                    except IOError as e:
                        print(f"Failed to upload file: {e}")
            self.refreshDirs()

    # 刷新
    def refresh(self):
        self.refreshDirs()

    # 删除
    def remove(self):
        current_index = self.ui.ShellTab.currentIndex()
        this = self.ui.ShellTab.tabWhatsThis(current_index)
        ssh_conn = mux.backend_index[this]
        # 创建消息框
        reply = QMessageBox()
        reply.setWindowTitle('确认删除')
        reply.setText(f'确定删除选中项目吗？这将无法恢复！')
        reply.setStandardButtons(QMessageBox.Yes | QMessageBox.No)

        # 设置按钮文本为中文
        yes_button = reply.button(QMessageBox.Yes)
        no_button = reply.button(QMessageBox.No)
        yes_button.setText("是")
        no_button.setText("否")
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
                    self.refreshDirs()
                except IOError as e:
                    print(f"Failed to remove file: {e}")
            rm_dict.clear()
            self.success("删除")

    # 停止docker容器
    def stopDockerContainer(self):
        focus = self.ui.treeWidgetDocker.currentIndex().row()
        if focus != -1:
            text = self.ui.treeWidgetDocker.topLevelItem(focus).text(0)
            # 取出前12位字符串
            container_id = text[:12]
            data_ = self.getData2('docker stop ' + container_id)
            print('stop----', data_)
            time.sleep(1)  # 延迟一秒
            self.refreshDokerInfo()

    # 重启docker容器
    def restartDockerContainer(self):
        focus = self.ui.treeWidgetDocker.currentIndex().row()
        if focus != -1:
            text = self.ui.treeWidgetDocker.topLevelItem(focus).text(0)
            # 取出前12位字符串
            container_id = text[:12]
            data_ = self.getData2('docker restart ' + container_id)
            print('restart----', data_)
            time.sleep(1)  # 延迟一秒
            self.refreshDokerInfo()

    # 删除docker容器
    def rmDockerContainer(self):
        focus = self.ui.treeWidgetDocker.currentIndex().row()
        if focus != -1:
            text = self.ui.treeWidgetDocker.topLevelItem(focus).text(0)
            # 取出前12位字符串
            container_id = text[:12]
            data_ = self.getData2('docker rm ' + container_id)
            print('rm----', data_)
            time.sleep(1)  # 延迟一秒
            self.refreshDokerInfo()

    # 删除文件夹
    def removeDir(self):
        current_index = self.ui.ShellTab.currentIndex()
        this = self.ui.ShellTab.tabWhatsThis(current_index)
        ssh_conn = mux.backend_index[this]
        focus = self.ui.treeWidget.currentIndex().row()
        if focus != -1:
            text = self.ui.treeWidget.topLevelItem(focus).text(0)
            sftp = ssh_conn.open_sftp()
            try:
                sftp.rmdir(ssh_conn.pwd + '/' + text)
                self.refreshDirs()
            except IOError as e:
                print(f"Failed to remove directory: {e}")
        pass

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    # 拖拉拽上传文件
    def dropEvent(self, event: QDropEvent):
        current_index = self.ui.ShellTab.currentIndex()
        this = self.ui.ShellTab.tabWhatsThis(current_index)
        ssh_conn = mux.backend_index[this]
        mime_data = event.mimeData()
        if mime_data.hasUrls():
            for url in mime_data.urls():
                file_path = url.toLocalFile()
                if os.path.isfile(file_path):
                    self.fileEvent = file_path
                    sftp = ssh_conn.open_sftp()
                    try:
                        sftp.put(file_path, ssh_conn.pwd + '/' + os.path.basename(file_path))
                    except IOError as e:
                        print(f"Failed to upload file: {e}")
            self.refreshDirs()

    # 信息提示窗口
    def alarm(self, alart):
        """
        创建一个错误消息框，并设置自定义图标
        """
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle('操作失败')
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
        msg_box.setWindowTitle('操作成功')
        msg_box.setText(f'{alart}成功')

        # 加载自定义图标
        custom_icon = QIcon(':icons8-success-48.png')  # 替换为你的图标路径
        pixmap = QPixmap(custom_icon.pixmap(32, 32))

        # 设置消息框图标
        msg_box.setIconPixmap(pixmap)

        # 显示消息框
        msg_box.exec()

    def inputMethodQuery(self, a0):
        pass
        # print(a0)

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
            self.alarm('配置名称不能为空！')
        elif username == '':
            self.alarm('用户名不能为空！')
        elif password == '' and private_key_type == '':
            self.alarm('密码或者密钥必须提供一个！')
        elif private_key_type != '' and private_key_file == '':
            self.alarm('请上传私钥文件！')
        elif ip == '':
            self.alarm('ip地址不能为空！')
        else:
            with open('conf/config.dat', 'rb') as c:
                conf = pickle.loads(c.read())
                c.close()
            with open('conf/config.dat', 'wb') as c:
                conf[name] = [username, password, f"{ip}:{prot}", private_key_type, private_key_file]
                c.write(pickle.dumps(conf))
                c.close()
            self.close()

    def addKeyFile(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "选择文件",
            "",
            "所有文件 (*);;Python 文件 (*.py);;文本文件 (*.txt)",
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
        self.dial.alarmbox.setWindowTitle('错误提示')
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


class CustomWidget(QWidget):
    def __init__(self, item, ssh_conn, parent=None):
        super().__init__(parent)

        self.docker = None

        self.layout = QVBoxLayout()

        # 创建图标标签
        icon_label = QLabel(self)
        pixmap = QPixmap(item['icon'])
        icon_label.setPixmap(pixmap)
        icon_label.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(icon_label)

        # 创建按钮布局
        self.button_layout = QHBoxLayout()

        cmd = "docker ps -a | grep " + item['containerName']
        ack = ssh_conn.exec(cmd=cmd, pty=False)
        if not ack:
            # 安装按钮
            self.install_button = QPushButton("安装", self)
            self.install_button.setCursor(QCursor(Qt.PointingHandCursor))
            self.install_button.clicked.connect(lambda: self.installAction(item, ssh_conn))
            self.button_layout.addWidget(self.install_button)
        else:
            # 安装按钮
            self.install_button = QPushButton("已安装", self)
            self.install_button.setCursor(QCursor(Qt.PointingHandCursor))
            self.install_button.setStyleSheet("background-color: rgb(102, 221, 121);")
            self.install_button.setDisabled(True)
            self.button_layout.addWidget(self.install_button)

        self.layout.addLayout(self.button_layout)
        self.setLayout(self.layout)

        # 设置样式表为小块添加边框
        self.setStyleSheet("""
            QWidget {
                border-radius: 5px;
                padding: 5px;
            }
            QPushButton {
                background-color: rgb(50,115,245);
                border-radius: 5px;
                padding: 10px;
            }
            QPushButton:pressed {
                background-color: darkgray;
            }
        """)

    def installAction(self, item, ssh_conn):
        """
        点击安装按钮，安装docker容器
        :param item: 数据对象
        :param ssh_conn: ssh 连接对象
        :return:
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

    def refresh(self, item, ssh_conn):
        # 安装按钮
        self.install_button.setText("已安装")
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
            print(f"安装失败：{e}")
            return 'error'
        print("安装成功")


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
            QMessageBox.warning(self, "连接超时", "服务器无法连接，请检查网络或服务器状态。")
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
        self.tunnel.add_tunnel.accepted.connect(self.addTunnel)
        self.tunnel.add_tunnel.rejected.connect(TunnelConfig.reject)
        self.tunnel.comboBox_tunnel_type.currentIndexChanged.connect(self.readonly_remote_bind_address_edit)

    def addTunnel(self):

        remote = self.tunnel.remote_bind_address_edit.text()
        tunnel_type = self.tunnel.comboBox_tunnel_type.currentText()
        if remote == '' and tunnel_type != '动态':
            QMessageBox.critical(self, "警告", "请填写远程绑定地址")
            return
        split = remote.split(':')
        if len(split) != 2 and tunnel_type != '动态':
            QMessageBox.critical(self, "警告", "远程绑定地址格式不正确，请检查")
            return

        local = self.tunnel.local_bind_address_edit.text()
        if local == '':
            QMessageBox.critical(self, "警告", "请填写本地绑定地址")
            return
        local_split = local.split(':')
        if len(local_split) != 2:
            QMessageBox.critical(self, "警告", "本地绑定地址格式不正确，请检查")
            return
        if self.tunnel.ssh_tunnel_name.text() == '':
            QMessageBox.critical(self, "警告", "请填写隧道名称")
            return

        dic = {
            KEYS.TUNNEL_TYPE: self.tunnel.comboBox_tunnel_type.currentText(),
            KEYS.BROWSER_OPEN: self.tunnel.browser_open.text(),
            KEYS.DEVICE_NAME: self.tunnel.comboBox_ssh.currentText(),
            KEYS.REMOTE_BIND_ADDRESS: self.tunnel.remote_bind_address_edit.text(),
            KEYS.LOCAL_BIND_ADDRESS: self.tunnel.local_bind_address_edit.text(),
        }

        file_path = 'conf/tunnel.json'
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
                print(f"Error stopping tunnel: {e}")
        else:
            try:
                self.start_tunnel()
            except Exception as e:
                print(f"Error starting tunnel: {e}")
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
            print(f"Error stopping process: {e}")
        self.ui.action_tunnel.setIcon(QIcon(ICONS.START))

    # 删除隧道
    def delete_tunnel(self, parent):

        # 创建消息框
        reply = QMessageBox()
        reply.setWindowTitle('确认删除')
        reply.setText(f'您确定要删除此隧道吗？这将无法恢复！')
        reply.setStandardButtons(QMessageBox.Yes | QMessageBox.No)

        # 设置按钮文本为中文
        yes_button = reply.button(QMessageBox.Yes)
        no_button = reply.button(QMessageBox.No)
        yes_button.setText("确定")
        no_button.setText("取消")
        # 显示对话框并等待用户响应
        reply.exec()

        if reply.clickedButton() == yes_button:
            name_text = self.ui.name.text()
            file_path = 'conf/tunnel.json'
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
    with open('conf/config.dat', 'rb') as c:
        conf = pickle.loads(c.read())[ssh]
    username, password, host, key_type, key_file = '', '', '', '', ''
    if len(conf) == 3:
        return username, password, host, '', ''
    else:
        return conf[0], conf[1], conf[2], conf[3], conf[4]


if __name__ == '__main__':
    print("PySide6 version:", PySide6.__version__)
    qdarktheme.enable_hi_dpi()
    app = QApplication(sys.argv)
    translator = QTranslator()
    # 加载编译后的 .qm 文件
    translator.load("translations.qm")

    # 安装翻译
    app.installTranslator(translator)

    window = MainDialog(app)

    window.show()
    window.refreshConf()
    sys.exit(app.exec())
