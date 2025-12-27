import json
from typing import Dict, Any

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QColor, QTextCursor, QFont
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QProgressBar, QTextEdit, QGroupBox, QMessageBox, QDialog
)

from core.docker.docker_installer_core import DockerInstallerCore


# 将父目录添加到路径中，以便能够导入docker_ssh_sdk
# BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# if BASE_DIR not in sys.path:
#     sys.path.insert(0, BASE_DIR)


class LogWidget(QTextEdit):
    """显示安装过程的日志控件"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QTextEdit.WidgetWidth)
        self.setStyleSheet("font-family: 'Courier New', monospace; font-size: 10pt;")

    def append_log(self, text: str, level: str = "info"):
        """添加日志"""
        current_format = self.currentCharFormat()
        text_cursor = QTextCursor(self.document())
        text_cursor.movePosition(QTextCursor.End)

        # 根据日志级别设置颜色
        color = QColor()
        if level == "error":
            color = QColor("#FF5252")  # 红色
        elif level == "warning":
            color = QColor("#FFB300")  # 黄色
        elif level == "success":
            color = QColor("#4CAF50")  # 绿色
        elif level == "cmd":
            color = QColor("#2196F3")  # 蓝色
        else:
            color = QColor("#fcb69f")  # 灰色

        # 设置颜色
        current_format.setForeground(color)
        text_cursor.setCharFormat(current_format)

        # 添加文本
        text_cursor.insertText(text + "\n")

        # 滚动到底部
        self.setTextCursor(text_cursor)
        self.ensureCursorVisible()

    def clear_log(self):
        """清空日志"""
        self.clear()


class DockerInstallerWidget(QWidget):
    """Docker安装器主界面"""

    # 定义信号
    install_started = Signal()
    install_completed = Signal(bool, str)  # 成功/失败, 消息
    install_progress = Signal(str, int)  # 状态, 进度百分比

    def __init__(self, ssh_client):
        """
        初始化Docker安装器小部件

        Args:
            ssh_client: SSH客户端对象
        """
        super().__init__()

        self.ssh_client = ssh_client
        # 直接传递ssh_client对象给DockerInstallerCore
        self.installer = DockerInstallerCore(ssh_client)

        self.distro_info = None
        self.docker_info = None
        self.docker_compose_info = None

        self.is_installing = False

        self.init_ui()
        self.connect_signals()

    def init_ui(self):
        """初始化UI"""
        # 创建主布局
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)

        # 系统信息区域
        self.system_info_group = QGroupBox("系统信息")
        system_info_layout = QGridLayout(self.system_info_group)

        self.os_label = QLabel("操作系统: 未检测")
        self.kernel_label = QLabel("内核版本: 未检测")
        self.docker_status_label = QLabel("Docker状态: 未检测")
        self.docker_version_label = QLabel("Docker版本: 未检测")
        self.compose_status_label = QLabel("Docker Compose状态: 未检测")

        system_info_layout.addWidget(self.os_label, 0, 0)
        system_info_layout.addWidget(self.kernel_label, 0, 1)
        system_info_layout.addWidget(self.docker_status_label, 1, 0)
        system_info_layout.addWidget(self.docker_version_label, 1, 1)
        system_info_layout.addWidget(self.compose_status_label, 2, 0, 1, 2)

        # 添加检测按钮
        self.detect_button = QPushButton("检测系统")
        system_info_layout.addWidget(self.detect_button, 3, 0, 1, 2)

        main_layout.addWidget(self.system_info_group)

        # 安装选项区域
        self.install_options_group = QGroupBox("安装选项")
        install_options_layout = QVBoxLayout(self.install_options_group)

        # 添加Docker和Docker Compose安装按钮
        buttons_layout = QHBoxLayout()

        self.install_docker_button = QPushButton("安装Docker")
        self.install_docker_button.setEnabled(False)
        buttons_layout.addWidget(self.install_docker_button)

        self.install_compose_button = QPushButton("安装Docker Compose")
        self.install_compose_button.setEnabled(False)
        buttons_layout.addWidget(self.install_compose_button)

        self.config_docker_button = QPushButton("配置Docker")
        self.config_docker_button.setEnabled(False)
        buttons_layout.addWidget(self.config_docker_button)

        self.test_docker_button = QPushButton("测试Docker安装")
        self.test_docker_button.setEnabled(False)
        buttons_layout.addWidget(self.test_docker_button)

        install_options_layout.addLayout(buttons_layout)
        main_layout.addWidget(self.install_options_group)

        # 进度区域
        self.progress_group = QGroupBox("安装进度")
        progress_layout = QVBoxLayout(self.progress_group)

        # 状态标签和进度条
        self.status_label = QLabel("就绪")
        progress_layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)

        main_layout.addWidget(self.progress_group)

        # 日志区域
        self.log_group = QGroupBox("安装日志")
        log_layout = QVBoxLayout(self.log_group)

        self.log_widget = LogWidget()
        log_layout.addWidget(self.log_widget)

        # 日志操作按钮
        log_buttons_layout = QHBoxLayout()
        self.clear_log_button = QPushButton("清空日志")
        log_buttons_layout.addWidget(self.clear_log_button)
        log_buttons_layout.addStretch()

        log_layout.addLayout(log_buttons_layout)

        main_layout.addWidget(self.log_group)

        # 设置伸缩因子
        main_layout.setStretchFactor(self.system_info_group, 1)
        main_layout.setStretchFactor(self.install_options_group, 1)
        main_layout.setStretchFactor(self.progress_group, 1)
        main_layout.setStretchFactor(self.log_group, 5)

    def connect_signals(self):
        """连接信号和槽"""
        # 按钮点击事件
        self.detect_button.clicked.connect(self.on_detect_clicked)
        self.install_docker_button.clicked.connect(self.on_install_docker_clicked)
        self.install_compose_button.clicked.connect(self.on_install_compose_clicked)
        self.config_docker_button.clicked.connect(self.on_config_docker_clicked)
        self.test_docker_button.clicked.connect(self.on_test_docker_clicked)
        self.clear_log_button.clicked.connect(self.log_widget.clear_log)

        # 安装进度信号
        self.install_progress.connect(self.on_install_progress)
        self.install_completed.connect(self.on_install_completed)

    @Slot()
    def on_detect_clicked(self):
        """检测系统"""
        self.log_widget.append_log("开始检测系统...")

        # 检测操作系统
        self.distro_info = self.installer.detect_os()

        # 更新UI
        self.os_label.setText(f"操作系统: {self.distro_info.get('pretty_name', '未知')}")
        self.kernel_label.setText(f"内核版本: {self.distro_info.get('kernel', '未知')}")

        # 检查Docker
        self.docker_info = self.installer.check_docker()
        if self.docker_info['installed']:
            self.docker_status_label.setText("Docker状态: 已安装")
            self.docker_version_label.setText(f"Docker版本: {self.docker_info['version']}")
            docker_status = "运行中" if self.docker_info['running'] else "未运行"
            self.log_widget.append_log(f"检测到Docker已安装: {self.docker_info['version']}", "success")
            self.log_widget.append_log(f"Docker服务状态: {docker_status}")
        else:
            self.docker_status_label.setText("Docker状态: 未安装")
            self.docker_version_label.setText("Docker版本: 无")
            self.log_widget.append_log("未检测到Docker安装", "warning")

        # 检查Docker Compose
        self.docker_compose_info = self.installer.check_docker_compose()
        if self.docker_compose_info['installed']:
            self.compose_status_label.setText(f"Docker Compose状态: 已安装 ({self.docker_compose_info['version']})")
            self.log_widget.append_log(f"检测到Docker Compose已安装: {self.docker_compose_info['version']}", "success")
        else:
            self.compose_status_label.setText("Docker Compose状态: 未安装")
            self.log_widget.append_log("未检测到Docker Compose安装", "warning")

        # 检查发行版是否支持
        if not self.installer.is_supported_distro():
            self.log_widget.append_log(f"警告: 您的Linux发行版 ({self.distro_info.get('id', '未知')}) 可能不被完全支持",
                                       "warning")

        # 启用安装按钮
        self.install_docker_button.setEnabled(True)
        self.install_compose_button.setEnabled(True)
        self.config_docker_button.setEnabled(self.docker_info['installed'])
        self.test_docker_button.setEnabled(self.docker_info['installed'])

    @Slot()
    def on_install_docker_clicked(self):
        """安装Docker"""
        if self.is_installing:
            return

        if self.docker_info and self.docker_info['installed']:
            reply = QMessageBox.question(
                self,
                "Docker已安装",
                "Docker已经安装在系统上，是否重新安装？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )

            if reply == QMessageBox.No:
                return

        self.is_installing = True
        self.install_started.emit()

        # 禁用按钮
        self.detect_button.setEnabled(False)
        self.install_docker_button.setEnabled(False)
        self.install_compose_button.setEnabled(False)
        self.config_docker_button.setEnabled(False)
        self.test_docker_button.setEnabled(False)

        # 更新状态
        self.status_label.setText("正在安装Docker...")
        self.progress_bar.setValue(0)
        self.log_widget.append_log("开始安装Docker...", "info")

        # 在新线程中安装Docker
        import threading
        thread = threading.Thread(target=self._install_docker_thread)
        thread.daemon = True
        thread.start()

    def _install_docker_thread(self):
        """在单独的线程中安装Docker"""
        try:

            result = self.installer.install_docker(self._on_progress_update, self.ssh_client.password)

            # 在安装完成后记录结果
            if result['success']:
                self.install_completed.emit(True, result['message'])

                # 记录详细步骤
                for step in result.get('steps', []):
                    cmd = step.get('cmd', '')
                    success = step.get('success', False)
                    output = step.get('output', '')
                    error = step.get('error', '')

                    self.log_widget.append_log(f"执行: {cmd}", "cmd")
                    if success:
                        if output:
                            self.log_widget.append_log(output, "info")
                    else:
                        if error:
                            self.log_widget.append_log(f"错误: {error}", "error")

            else:
                self.install_completed.emit(False, result['message'])
        except Exception as e:
            self.install_completed.emit(False, f"安装过程中出现错误: {str(e)}")

    def _on_progress_update(self, status: str, percent: int):
        """安装进度更新回调"""
        self.install_progress.emit(status, percent)

    @Slot()
    def on_install_compose_clicked(self):
        """安装Docker Compose"""
        if self.is_installing:
            return

        if not self.docker_info or not self.docker_info['installed']:
            QMessageBox.warning(
                self,
                "Docker未安装",
                "请先安装Docker后再安装Docker Compose。",
                QMessageBox.Ok
            )
            return

        if self.docker_compose_info and self.docker_compose_info['installed']:
            reply = QMessageBox.question(
                self,
                "Docker Compose已安装",
                "Docker Compose已经安装在系统上，是否重新安装？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )

            if reply == QMessageBox.No:
                return

        self.is_installing = True
        self.install_started.emit()

        # 禁用按钮
        self.detect_button.setEnabled(False)
        self.install_docker_button.setEnabled(False)
        self.install_compose_button.setEnabled(False)
        self.test_docker_button.setEnabled(False)

        # 更新状态
        self.status_label.setText("正在安装Docker Compose...")
        self.progress_bar.setValue(0)
        self.log_widget.append_log("开始安装Docker Compose...", "info")

        # 在新线程中安装Docker Compose
        import threading
        thread = threading.Thread(target=self._install_compose_thread)
        thread.daemon = True
        thread.start()

    def _install_compose_thread(self):
        """在单独的线程中安装Docker Compose"""
        try:
            result = self.installer.install_docker_compose(self._on_progress_update)

            # 在安装完成后记录结果
            if result['success']:
                self.install_completed.emit(True, result['message'])

                # 记录详细步骤
                for step in result.get('steps', []):
                    cmd = step.get('cmd', '')
                    success = step.get('success', False)
                    output = step.get('output', '')
                    error = step.get('error', '')

                    self.log_widget.append_log(f"执行: {cmd}", "cmd")
                    if success:
                        if output:
                            self.log_widget.append_log(output, "info")
                    else:
                        if error:
                            self.log_widget.append_log(f"错误: {error}", "error")

            else:
                self.install_completed.emit(False, result['message'])
        except Exception as e:
            self.install_completed.emit(False, f"安装过程中出现错误: {str(e)}")

    @Slot()
    def on_test_docker_clicked(self):
        """测试Docker安装"""
        if self.is_installing:
            return

        self.log_widget.append_log("开始测试Docker安装...", "info")

        # 在新线程中测试Docker
        import threading
        thread = threading.Thread(target=self._test_docker_thread)
        thread.daemon = True
        thread.start()

    def _test_docker_thread(self):
        """在单独的线程中测试Docker"""
        try:
            result = self.installer.test_docker_installation()

            if result['success']:
                self.log_widget.append_log("Docker测试成功: " + result['message'], "success")
            else:
                self.log_widget.append_log("Docker测试失败: " + result['message'], "error")

            # 记录详细测试结果
            for test in result.get('tests', []):
                name = test.get('name', '')
                success = test.get('success', False)
                output = test.get('output', '')
                error = test.get('error', '')

                if success:
                    self.log_widget.append_log(f"测试 [{name}]: 通过", "success")
                    if output:
                        self.log_widget.append_log(output, "info")
                else:
                    self.log_widget.append_log(f"测试 [{name}]: 失败", "error")
                    if error:
                        self.log_widget.append_log(error, "error")

        except Exception as e:
            self.log_widget.append_log(f"测试过程中出现错误: {str(e)}", "error")

    @Slot(str, int)
    def on_install_progress(self, status: str, percent: int):
        """安装进度更新"""
        self.status_label.setText(status)
        self.progress_bar.setValue(percent)
        self.log_widget.append_log(f"进度 ({percent}%): {status}")

    @Slot()
    def on_config_docker_clicked(self):
        """配置Docker"""
        if not self.docker_info or not self.docker_info['installed']:
            QMessageBox.warning(
                self,
                "Docker未安装",
                "请先安装Docker后再进行配置。",
                QMessageBox.Ok
            )
            return

        dialog = DockerDaemonConfigDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            config = dialog.get_config()
            if not config:
                QMessageBox.warning(self, "错误", "配置无效")
                return

            self.is_installing = True
            self.install_started.emit()

            # 禁用按钮
            self.detect_button.setEnabled(False)
            self.install_docker_button.setEnabled(False)
            self.install_compose_button.setEnabled(False)
            self.test_docker_button.setEnabled(False)
            self.config_docker_button.setEnabled(False)

            # 更新状态
            self.status_label.setText("正在配置Docker...")
            self.progress_bar.setValue(0)
            self.log_widget.append_log("开始配置Docker...", "info")

            # 在新线程中配置Docker
            import threading
            thread = threading.Thread(target=self._configure_docker_thread, args=(config,))
            thread.daemon = True
            thread.start()

    def _configure_docker_thread(self, config: Dict[str, Any]):
        """在单独的线程中配置Docker"""
        try:
            result = self.installer.configure_docker_daemon(config, self._on_progress_update)

            if result['success']:
                self.install_completed.emit(True, result['message'])

                # 记录详细步骤
                for step in result.get('steps', []):
                    cmd = step.get('cmd', '')
                    success = step.get('success', False)
                    output = step.get('output', '')
                    error = step.get('error', '')

                    self.log_widget.append_log(f"执行: {cmd}", "cmd")
                    if success:
                        if output:
                            self.log_widget.append_log(output, "info")
                    else:
                        if error:
                            self.log_widget.append_log(f"错误: {error}", "error")

            else:
                self.install_completed.emit(False, result['message'])
        except Exception as e:
            self.install_completed.emit(False, f"配置过程中出现错误: {str(e)}")

    @Slot(bool, str)
    def on_install_completed(self, success: bool, message: str):
        """安装完成"""
        self.is_installing = False

        # 启用按钮
        self.detect_button.setEnabled(True)
        self.install_docker_button.setEnabled(True)
        self.install_compose_button.setEnabled(True)
        self.config_docker_button.setEnabled(True)

        # 更新状态
        if success:
            self.status_label.setText(f"操作成功: {message}")
            self.log_widget.append_log(f"操作成功: {message}", "success")

            # 更新Docker和Docker Compose状态
            self.docker_info = self.installer.check_docker()
            self.docker_compose_info = self.installer.check_docker_compose()

            if self.docker_info['installed']:
                self.docker_status_label.setText("Docker状态: 已安装")
                self.docker_version_label.setText(f"Docker版本: {self.docker_info['version']}")
                self.test_docker_button.setEnabled(True)

            if self.docker_compose_info['installed']:
                self.compose_status_label.setText(f"Docker Compose状态: 已安装 ({self.docker_compose_info['version']})")
        else:
            self.status_label.setText(f"操作失败: {message}")
            self.log_widget.append_log(f"操作失败: {message}", "error")

            # 更新测试按钮状态
            self.test_docker_button.setEnabled(self.docker_info and self.docker_info['installed'])


class DockerInstallerMainWindow(QMainWindow):
    """Docker安装器主窗口"""

    def __init__(self, ssh_client=None):
        """
        初始化Docker安装器主窗口

        Args:
            ssh_client: SSH客户端对象，可选
        """
        super().__init__()

        self.ssh_client = ssh_client

        self.setWindowTitle("Docker 安装器")
        self.resize(800, 600)

        self.init_ui()

    def init_ui(self):
        """初始化UI"""
        # 如果已经传入SSH客户端，直接创建安装界面
        if self.ssh_client:
            self.init_installer_ui()
        else:
            self.init_connect_ui()

    def init_connect_ui(self):
        """初始化连接界面"""
        # 创建一个小工具来显示"请先建立SSH连接"的消息
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout(central_widget)

        message_label = QLabel("请先建立SSH连接后再使用Docker安装器")
        message_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(message_label)

    def init_installer_ui(self):
        """初始化安装器界面"""
        # 创建安装器小部件作为中央部件
        self.installer_widget = DockerInstallerWidget(self.ssh_client)
        self.setCentralWidget(self.installer_widget)

    def set_ssh_client(self, ssh_client):
        """
        设置SSH客户端并初始化安装器界面

        Args:
            ssh_client: SSH客户端对象
        """
        self.ssh_client = ssh_client
        self.init_installer_ui()


class DockerDaemonConfigDialog(QDialog):
    """Docker守护进程配置对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Docker守护进程配置")
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)

        # 创建主布局
        layout = QVBoxLayout(self)

        # 创建配置编辑器
        self.editor = QTextEdit()
        self.editor.setFont(QFont("Courier New", 10))
        self.editor.setPlaceholderText("请输入daemon.json的配置内容...")

        # 添加默认配置
        default_config = {
            # "log-driver": "json-file",
            # "log-opts": {
            #     "max-size": "100m",
            #     "max-file": "3"
            # },
            "registry-mirrors": [
                "https://mirror.ccs.tencentyun.com"
            ]
            # ,
            # "data-root": "/var/lib/docker",
            # "exec-opts": ["native.cgroupdriver=systemd"]
        }
        self.editor.setText(json.dumps(default_config, indent=2))

        # 创建按钮
        button_layout = QHBoxLayout()

        self.validate_button = QPushButton("验证配置")
        self.validate_button.clicked.connect(self.validate_config)

        self.apply_button = QPushButton("应用配置")
        self.apply_button.clicked.connect(self.accept)

        self.cancel_button = QPushButton("取消")
        self.cancel_button.clicked.connect(self.reject)

        button_layout.addWidget(self.validate_button)
        button_layout.addWidget(self.apply_button)
        button_layout.addWidget(self.cancel_button)

        # 添加组件到主布局
        layout.addWidget(QLabel("Docker守护进程配置 (daemon.json):"))
        layout.addWidget(self.editor)
        layout.addLayout(button_layout)

    def validate_config(self):
        """验证配置是否有效"""
        try:
            config = json.loads(self.editor.toPlainText())
            QMessageBox.information(self, "验证成功", "配置格式正确！")
        except json.JSONDecodeError as e:
            QMessageBox.warning(self, "验证失败", f"配置格式错误：{str(e)}")

    def get_config(self) -> Dict[str, Any]:
        """获取配置内容"""
        try:
            return json.loads(self.editor.toPlainText())
        except json.JSONDecodeError:
            return {}
