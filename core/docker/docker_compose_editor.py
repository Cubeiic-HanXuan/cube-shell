import os

import yaml
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (QWidget, QVBoxLayout,
                               QHBoxLayout, QPushButton, QTreeWidget,
                               QTreeWidgetItem, QLabel, QMessageBox, QLineEdit,
                               QFormLayout, QScrollArea, QSplitter, QDialog, QDialogButtonBox, QTextEdit, QComboBox)
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name

from function import util


class ServiceConfigWidget(QWidget):
    config_changed = Signal()

    def __init__(self, service_name, config=None, parent=None):
        super().__init__(parent)
        self.service_name = service_name
        self.config = config or {}
        # 保存父窗口引用
        self.parent_window = parent

        # 创建主布局
        main_layout = QVBoxLayout()
        self.setLayout(main_layout)

        # 服务名称标签
        title = QLabel(f"服务: {service_name}")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        main_layout.addWidget(title)

        # 创建滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        main_layout.addWidget(scroll)

        # 创建配置容器
        config_container = QWidget()
        scroll.setWidget(config_container)

        # 配置表单布局
        form_layout = QFormLayout()
        form_layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        form_layout.setLabelAlignment(Qt.AlignRight)
        config_container.setLayout(form_layout)

        # 基本配置
        self.image_edit = QLineEdit(self.config.get('image', ''))
        self.image_edit.setMinimumWidth(300)
        form_layout.addRow("镜像:", self.image_edit)

        # 容器名称
        self.container_name_edit = QLineEdit(self.config.get('container_name', ''))
        self.container_name_edit.setMinimumWidth(300)
        form_layout.addRow("容器名称:", self.container_name_edit)

        # 重启策略（下拉选择）
        self.restart_combo = QComboBox()
        self.restart_combo.setMinimumWidth(300)
        # 添加常用的重启策略选项
        restart_options = [
            "",
            "no",
            "always",
            "on-failure",
            "unless-stopped"
        ]
        self.restart_combo.addItems(restart_options)
        # 设置当前值
        current_restart = self.config.get('restart', '')
        index = self.restart_combo.findText(current_restart)
        if index >= 0:
            self.restart_combo.setCurrentIndex(index)
        # 添加提示
        self.restart_combo.setToolTip(
            "no: 不自动重启\n"
            "always: 总是重启\n"
            "on-failure: 非正常退出时重启\n"
            "unless-stopped: 除非手动停止，否则总是重启"
        )
        form_layout.addRow("重启策略:", self.restart_combo)

        # 命令 - 支持字符串或列表类型
        command = self.config.get('command', '')
        # 如果是列表类型，转换为字符串
        if isinstance(command, list):
            command = ' '.join(command)
        self.command_edit = QLineEdit(command)
        self.command_edit.setMinimumWidth(300)
        self.command_edit.setPlaceholderText("例如: nginx -g 'daemon off;'")
        form_layout.addRow("命令:", self.command_edit)

        # 依赖服务
        self.depends_on_container = QWidget()
        self.depends_on_container.setObjectName("depends_on_container")
        depends_on_layout = QVBoxLayout()
        self.depends_on_container.setLayout(depends_on_layout)
        self.depends_on_list = []

        # Build 配置
        build_container = QWidget()
        build_layout = QVBoxLayout()
        build_container.setLayout(build_layout)

        # Context 路径
        self.context_edit = QLineEdit(self.config.get('build', {}).get('context', ''))
        self.context_edit.setMinimumWidth(300)
        build_layout.addWidget(QLabel("Context 路径:"))
        build_layout.addWidget(self.context_edit)

        # Dockerfile 路径
        self.dockerfile_edit = QLineEdit(self.config.get('build', {}).get('dockerfile', ''))
        self.dockerfile_edit.setMinimumWidth(300)
        build_layout.addWidget(QLabel("Dockerfile 路径:"))
        build_layout.addWidget(self.dockerfile_edit)

        # Build 参数
        self.build_args_container = QWidget()
        self.build_args_layout = QVBoxLayout()
        self.build_args_container.setLayout(self.build_args_layout)
        self.build_args_list = []

        # 处理 build args
        build_args = self.config.get('build', {}).get('args', {})
        if isinstance(build_args, dict):
            # 处理字典格式
            for key, value in build_args.items():
                self.add_build_arg_item(key, str(value))
        elif isinstance(build_args, list):
            # 处理列表格式
            for arg in build_args:
                if '=' in arg:
                    key, value = arg.split('=', 1)
                    self.add_build_arg_item(key, value)

        add_build_arg_btn = QPushButton("添加构建参数")
        add_build_arg_btn.clicked.connect(self.add_build_arg)
        self.build_args_layout.addWidget(add_build_arg_btn)

        build_layout.addWidget(QLabel("构建参数:"))
        build_layout.addWidget(self.build_args_container)

        form_layout.addRow("构建配置:", build_container)

        # 端口配置
        self.ports_container = QWidget()
        self.ports_container.setObjectName("ports_container")
        ports_layout = QVBoxLayout()
        self.ports_container.setLayout(ports_layout)
        self.ports_list = []
        for port in self.config.get('ports', []):
            self.add_port_item(port)

        add_port_btn = QPushButton("添加端口")
        add_port_btn.clicked.connect(self.add_port)
        ports_layout.addWidget(add_port_btn)

        form_layout.addRow("端口:", self.ports_container)

        # 环境变量
        self.env_container = QWidget()
        self.env_container.setObjectName("env_container")
        self.env_layout = QVBoxLayout()
        self.env_container.setLayout(self.env_layout)
        self.env_list = []

        # 处理环境变量配置
        env_config = self.config.get('environment', {})
        if isinstance(env_config, dict):
            # 处理字典格式
            for key, value in env_config.items():
                self.add_env_item(key, str(value))
        elif isinstance(env_config, list):
            # 处理列表格式
            for env in env_config:
                if '=' in env:
                    key, value = env.split('=', 1)
                    self.add_env_item(key, value)

        add_env_btn = QPushButton("添加环境变量")
        add_env_btn.clicked.connect(self.add_environment)
        self.env_layout.addWidget(add_env_btn)

        form_layout.addRow("环境变量:", self.env_container)

        # 卷挂载
        self.volumes_container = QWidget()
        self.volumes_container.setObjectName("volumes_container")
        volumes_layout = QVBoxLayout()
        self.volumes_container.setLayout(volumes_layout)
        self.volumes_list = []
        for volume in self.config.get('volumes', []):
            self.add_volume_item(volume)

        add_volume_btn = QPushButton("添加卷")
        add_volume_btn.clicked.connect(self.add_volume)
        volumes_layout.addWidget(add_volume_btn)

        form_layout.addRow("卷:", self.volumes_container)

        # 处理依赖服务
        depends_on = self.config.get('depends_on', [])
        if isinstance(depends_on, list):
            for service in depends_on:
                self.add_depends_on_item(service)
        elif isinstance(depends_on, dict):
            for service in depends_on.keys():
                self.add_depends_on_item(service)

        add_depends_on_btn = QPushButton("添加依赖服务")
        add_depends_on_btn.clicked.connect(self.add_depends_on)
        depends_on_layout.addWidget(add_depends_on_btn)

        form_layout.addRow("依赖服务:", self.depends_on_container)

        # 网络配置
        self.networks_container = QWidget()
        self.networks_container.setObjectName("networks_container")
        networks_layout = QVBoxLayout()
        self.networks_container.setLayout(networks_layout)
        self.networks_list = []

        # 处理网络配置
        networks = self.config.get('networks', [])
        if isinstance(networks, list):
            for network in networks:
                self.add_network_item(network)
        elif isinstance(networks, dict):
            for network in networks.keys():
                self.add_network_item(network)

        add_network_btn = QPushButton("添加网络")
        add_network_btn.clicked.connect(self.add_network)
        networks_layout.addWidget(add_network_btn)

        form_layout.addRow("网络:", self.networks_container)

        # 保存按钮
        save_btn = QPushButton("保存配置")
        save_btn.clicked.connect(self.save_config)
        main_layout.addWidget(save_btn)

    def add_build_arg_item(self, key="", value=""):
        arg_item = QWidget()
        arg_layout = QHBoxLayout()
        key_edit = QLineEdit(key)
        key_edit.setMinimumWidth(150)
        value_edit = QLineEdit(str(value))
        value_edit.setMinimumWidth(150)
        delete_btn = QPushButton("—")
        delete_btn.setStyleSheet("color: red; font-weight: bold;")
        delete_btn.clicked.connect(lambda: self.remove_build_arg(arg_item, key_edit, value_edit))
        arg_layout.addWidget(key_edit)
        arg_layout.addWidget(value_edit)
        arg_layout.addWidget(delete_btn)
        arg_item.setLayout(arg_layout)
        self.build_args_list.append((key_edit, value_edit))
        self.build_args_layout.insertWidget(
            self.build_args_layout.count() - 1, arg_item)

    def remove_build_arg(self, arg_item, key_edit, value_edit):
        self.build_args_list.remove((key_edit, value_edit))
        arg_item.deleteLater()
        self.config_changed.emit()

    def add_build_arg(self):
        self.add_build_arg_item()

    def add_port_item(self, port_value=""):
        port_item = QWidget()
        port_layout = QHBoxLayout()
        port_edit = QLineEdit(port_value)
        port_edit.setMinimumWidth(300)
        delete_btn = QPushButton("—")
        delete_btn.setStyleSheet("color: red; font-weight: bold;")
        delete_btn.clicked.connect(lambda: self.remove_port(port_item, port_edit))
        port_layout.addWidget(port_edit)
        port_layout.addWidget(delete_btn)
        port_item.setLayout(port_layout)
        self.ports_list.append(port_edit)
        self.ports_container.layout().insertWidget(
            self.ports_container.layout().count() - 1, port_item)

    def remove_port(self, port_item, port_edit):
        self.ports_list.remove(port_edit)
        port_item.deleteLater()
        self.config_changed.emit()

    def add_env_item(self, key, value):
        env_item = QWidget()
        env_item_layout = QHBoxLayout()
        key_edit = QLineEdit(key)
        key_edit.setMinimumWidth(150)
        value_edit = QLineEdit(str(value))
        value_edit.setMinimumWidth(150)
        delete_btn = QPushButton("—")
        delete_btn.setStyleSheet("color: red; font-weight: bold;")
        delete_btn.clicked.connect(lambda: self.remove_env(env_item, key_edit, value_edit))
        env_item_layout.addWidget(key_edit)
        env_item_layout.addWidget(value_edit)
        env_item_layout.addWidget(delete_btn)
        env_item.setLayout(env_item_layout)
        self.env_list.append((key_edit, value_edit))
        self.env_layout.insertWidget(self.env_layout.count() - 1, env_item)

    def remove_env(self, env_item, key_edit, value_edit):
        self.env_list.remove((key_edit, value_edit))
        env_item.deleteLater()
        self.config_changed.emit()

    def add_port(self):
        self.add_port_item()

    def add_environment(self):
        self.add_env_item('', '')

    def add_volume_item(self, volume_value=""):
        volume_item = QWidget()
        volume_layout = QHBoxLayout()
        volume_edit = QLineEdit(volume_value)
        volume_edit.setMinimumWidth(300)
        delete_btn = QPushButton("—")
        delete_btn.setStyleSheet("color: red; font-weight: bold;")
        delete_btn.clicked.connect(lambda: self.remove_volume(volume_item, volume_edit))
        volume_layout.addWidget(volume_edit)
        volume_layout.addWidget(delete_btn)
        volume_item.setLayout(volume_layout)
        self.volumes_list.append(volume_edit)
        self.volumes_container.layout().insertWidget(
            self.volumes_container.layout().count() - 1, volume_item)

    def remove_volume(self, volume_item, volume_edit):
        self.volumes_list.remove(volume_edit)
        volume_item.deleteLater()
        self.config_changed.emit()

    def add_volume(self):
        self.add_volume_item()

    def add_depends_on_item(self, service_name=""):
        depends_on_item = QWidget()
        depends_on_layout = QHBoxLayout()
        service_edit = QLineEdit(service_name)
        service_edit.setMinimumWidth(300)
        delete_btn = QPushButton("-")
        delete_btn.setStyleSheet("color: red; font-weight: bold;")
        delete_btn.clicked.connect(lambda: self.remove_depends_on(depends_on_item, service_edit))
        depends_on_layout.addWidget(service_edit)
        depends_on_layout.addWidget(delete_btn)
        depends_on_item.setLayout(depends_on_layout)
        self.depends_on_list.append(service_edit)
        self.depends_on_container.layout().insertWidget(
            self.depends_on_container.layout().count() - 1, depends_on_item)

    def remove_depends_on(self, depends_on_item, service_edit):
        self.depends_on_list.remove(service_edit)
        depends_on_item.deleteLater()
        self.config_changed.emit()

    def add_depends_on(self):
        self.add_depends_on_item()

    def add_network_item(self, network_name=""):
        network_item = QWidget()
        network_layout = QHBoxLayout()
        network_edit = QLineEdit(network_name)
        network_edit.setMinimumWidth(300)
        delete_btn = QPushButton("-")
        delete_btn.setStyleSheet("color: red; font-weight: bold;")
        delete_btn.clicked.connect(lambda: self.remove_network(network_item, network_edit))
        network_layout.addWidget(network_edit)
        network_layout.addWidget(delete_btn)
        network_item.setLayout(network_layout)
        self.networks_list.append(network_edit)
        self.networks_container.layout().insertWidget(
            self.networks_container.layout().count() - 1, network_item)

    def remove_network(self, network_item, network_edit):
        self.networks_list.remove(network_edit)
        network_item.deleteLater()
        self.config_changed.emit()

    def add_network(self):
        self.add_network_item()

    def save_config(self):
        # 处理环境变量
        env_dict = {}
        for key_edit, value_edit in self.env_list:
            key = key_edit.text().strip()
            value = value_edit.text().strip()
            if key and value:
                env_dict[key] = value

        # 处理构建参数
        build_args = {}
        for key_edit, value_edit in self.build_args_list:
            key = key_edit.text().strip()
            value = value_edit.text().strip()
            if key and value:
                build_args[key] = value

        # 构建配置
        build_config = {}
        if self.context_edit.text().strip():
            build_config['context'] = self.context_edit.text().strip()
        if self.dockerfile_edit.text().strip():
            build_config['dockerfile'] = self.dockerfile_edit.text().strip()
        if build_args:
            build_config['args'] = build_args

        # 处理依赖服务
        depends_on = [service.text() for service in self.depends_on_list if service.text()]
        # 处理网络配置
        networks = [network.text() for network in self.networks_list if network.text()]

        # 更新当前服务的配置
        self.config = {
            'image': self.image_edit.text(),
            'container_name': self.container_name_edit.text() or None,
            'restart': self.restart_combo.currentText() or None,
            'build': build_config if build_config else None,
            'ports': [port.text() for port in self.ports_list if port.text()],
            'environment': env_dict,
            'command': self.command_edit.text() or None,
            'volumes': [volume.text() for volume in self.volumes_list if volume.text()],
            'depends_on': depends_on if depends_on else None,
            'networks': networks if networks else None
        }

        # 移除空值
        self.config = {k: v for k, v in self.config.items() if v is not None}

        # 更新主窗口的配置
        if self.parent_window:
            self.parent_window.config['services'][self.service_name] = self.config
            self.parent_window.save_config()

        self.config_changed.emit()


class ServiceSearchDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("搜索并添加服务")
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)

        layout = QVBoxLayout()
        self.setLayout(layout)

        # 搜索框
        search_layout = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("输入服务名称搜索...")
        self.search_edit.textChanged.connect(self.filter_services)
        search_layout.addWidget(self.search_edit)
        layout.addLayout(search_layout)

        # 服务列表
        self.service_list = QTreeWidget()
        self.service_list.setHeaderLabels(["服务名称", "描述"])
        self.service_list.itemDoubleClicked.connect(self.accept)
        layout.addWidget(self.service_list)

        # 按钮
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            Qt.Horizontal, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # 从本地文件加载预定义服务
        self.services = self.load_predefined_services()
        self.update_service_list()

    def load_predefined_services(self):
        # 内置配置文件
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.abspath(os.path.join(current_dir, '../../'))
        config_file = os.path.join(project_root, 'conf', 'docker-compose-full.yml')

        services = {}
        try:
            # 读取配置文件
            if os.path.exists(config_file):
                with open(config_file, 'r') as f:
                    config = yaml.safe_load(f) or {}
                    for name, service_config in config.get('services', {}).items():
                        # 从配置中提取描述信息
                        labels = service_config.get('labels', '')
                        services[name] = {
                            'description': labels['description'],
                            'config': service_config
                        }
        except Exception as e:
            QMessageBox.warning(self, "警告", f"加载预定义服务失败: {str(e)}")

        return services

    def update_service_list(self):
        self.service_list.clear()
        for name, info in self.services.items():
            item = QTreeWidgetItem([name, info['description']])
            self.service_list.addTopLevelItem(item)

    def filter_services(self):
        search_text = self.search_edit.text().lower()
        for i in range(self.service_list.topLevelItemCount()):
            item = self.service_list.topLevelItem(i)
            name = item.text(0).lower()
            description = item.text(1).lower()
            item.setHidden(not (search_text in name or search_text in description))

    def get_selected_service(self):
        selected_items = self.service_list.selectedItems()
        if selected_items:
            name = selected_items[0].text(0)
            return name, self.services[name]['config']
        return None, None


class DockerComposeEditor(QWidget):
    def __init__(self, parent=None, ssh=None):
        super().__init__(parent)
        self.setWindowTitle("Docker Compose 可视化编辑器")

        # SSH客户端
        self.ssh = ssh

        self.file_name = "docker-compose.yml"
        # 如果不是超级管理员账户，则切换到用户目录
        self.dirs = "/home/app/"
        if self.ssh.username != "root":
            self.dirs = f"/home/{self.ssh.username}/app/"

        # 添加日志查看控制变量
        self.logs_running = False
        self.logs_thread = None
        self.logs_channel = None

        # 创建主布局
        main_layout = QHBoxLayout()
        self.setLayout(main_layout)

        # 创建垂直分割器（上下分割）
        vertical_splitter = QSplitter(Qt.Vertical)
        main_layout.addWidget(vertical_splitter)

        # 创建水平分割器（左右分割）
        horizontal_splitter = QSplitter(Qt.Horizontal)
        vertical_splitter.addWidget(horizontal_splitter)

        # 左侧服务列表
        left_widget = QWidget()
        left_layout = QVBoxLayout()
        left_widget.setLayout(left_layout)

        # 添加服务列表标题
        services_title = QLabel("服务列表")
        services_title.setStyleSheet("""
            font-size: 16px; 
            font-weight: bold; 
            color: #333; 
            padding: 5px;
            background-color: #f0f0f0;
            border-bottom: 1px solid #ccc;
        """)
        services_title.setAlignment(Qt.AlignCenter)
        left_layout.addWidget(services_title)

        self.services_tree = QTreeWidget()
        self.services_tree.setHeaderHidden(True)  # 隐藏表头
        self.services_tree.setAlternatingRowColors(True)  # 交替行颜色
        self.services_tree.setAnimated(True)  # 展开/折叠动画
        self.services_tree.setStyleSheet("""
            QTreeWidget {
                # background-color: #f8f8f8;
                border: 1px solid #ccc;
                border-radius: 4px;
                padding: 5px;
            }
            QTreeWidget::item {
                padding: 10px;
                border-bottom: 1px solid #eee;
            }
            QTreeWidget::item:selected {
                background-color: #0078d7;
                color: white;
            }
            QTreeWidget::item:hover {
                background-color: #e5f1fb;
            }
        """)
        self.services_tree.setFont(QFont("Arial", 11))
        self.services_tree.setIconSize(QSize(24, 24))
        self.services_tree.itemClicked.connect(self.on_service_selected)
        left_layout.addWidget(self.services_tree)

        add_service_btn = QPushButton("添加服务")
        add_service_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                border: none;
                padding: 8px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
        """)
        add_service_btn.setCursor(Qt.PointingHandCursor)
        add_service_btn.clicked.connect(self.add_service)
        left_layout.addWidget(add_service_btn)

        # 右侧配置编辑区
        right_widget = QWidget()
        right_layout = QVBoxLayout()
        right_widget.setLayout(right_layout)

        self.config_widget = QWidget()
        right_layout.addWidget(self.config_widget)

        # 添加水平分割器部件
        horizontal_splitter.addWidget(left_widget)
        horizontal_splitter.addWidget(right_widget)
        horizontal_splitter.setSizes([300, 900])  # 设置左右区域的比例

        # 创建命令执行区域
        command_widget = QWidget()
        command_layout = QVBoxLayout()
        command_widget.setLayout(command_layout)

        # 命令按钮组
        button_layout = QHBoxLayout()
        up_btn = QPushButton("启动服务")
        up_btn.clicked.connect(lambda: self.execute_command("up -d"))
        down_btn = QPushButton("停止服务")
        down_btn.clicked.connect(lambda: self.execute_command("stop"))
        restart_btn = QPushButton("重启服务")
        restart_btn.clicked.connect(lambda: self.execute_command("restart"))
        ps_btn = QPushButton("查看状态")
        ps_btn.clicked.connect(lambda: self.execute_command("ps"))
        logs_btn = QPushButton("查看日志")
        logs_btn.clicked.connect(self.toggle_logs)
        button_layout.addWidget(up_btn)
        button_layout.addWidget(down_btn)
        button_layout.addWidget(restart_btn)
        button_layout.addWidget(ps_btn)
        button_layout.addWidget(logs_btn)
        command_layout.addLayout(button_layout)

        # 输出显示区域
        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        self.output_text.setMinimumHeight(200)
        # 设置等宽字体
        self.output_text.setFont(QFont("Courier New", 10))
        # 设置深色背景
        self.output_text.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4;")
        command_layout.addWidget(self.output_text)

        # 添加垂直分割器部件
        vertical_splitter.addWidget(command_widget)
        vertical_splitter.setSizes([600, 200])  # 设置上下区域的比例

        # 加载配置
        self.load_config()

    def highlight_text(self, text):
        try:
            # 获取日志词法分析器
            lexer = get_lexer_by_name("docker-compose-log")
            formatter = HtmlFormatter(style=util.THEME['theme'], noclasses=True, bg_color='#ffffff')
            # 高亮文本
            highlighted = highlight(text, lexer, formatter)
            return highlighted
        except:
            # 如果高亮失败，返回原始文本
            return text

    def append_text(self, text):
        # 高亮文本
        highlighted = self.highlight_text(text)
        # 追加到输出区域
        self.output_text.append(highlighted)
        # 滚动到底部
        self.output_text.verticalScrollBar().setValue(
            self.output_text.verticalScrollBar().maximum())

    def execute_command(self, command):
        if command == "logs -f":
            self.start_logs()
            return

        if not self.ssh:
            QMessageBox.warning(self, "警告", "未配置SSH管理器")
            return

        try:
            # 构建完整的docker-compose命令
            full_command = f"docker compose -f {self.dirs}{self.file_name} {command}"

            # 执行命令并获取输出
            stdin, stdout, stderr = self.ssh.conn.exec_command(full_command)

            # 清空输出区域
            self.output_text.clear()

            # 创建线程来读取输出
            def read_output():
                try:
                    # 读取标准输出
                    while True:
                        line = stdout.readline()
                        if not line:
                            break
                        if isinstance(line, bytes):
                            line = line.decode('utf-8')
                        self.append_text(line.strip())

                    # 读取错误输出
                    error = stderr.read()
                    if error:
                        if isinstance(error, bytes):
                            error = error.decode('utf-8')
                        self.append_text(f"错误:\n{error}")
                except Exception as e:
                    self.append_text(f"读取输出时出错: {str(e)}")

            # 启动线程
            import threading
            thread = threading.Thread(target=read_output)
            thread.daemon = True
            thread.start()

        except Exception as e:
            QMessageBox.critical(self, "错误", f"执行命令时出错: {str(e)}")

    def start_logs(self):
        if not self.ssh:
            QMessageBox.warning(self, "警告", "未配置SSH管理器")
            return

        try:
            # 清空输出区域
            self.output_text.clear()

            # 执行日志命令
            stdin, stdout, stderr = self.ssh.conn.exec_command(f"docker compose -f {self.dirs}{self.file_name} logs -f")

            # 创建线程来读取输出
            def read_logs():
                self.logs_running = True
                try:
                    while self.logs_running:
                        # 检查是否有新数据
                        if stdout.channel.recv_ready():
                            line = stdout.channel.recv(1024)
                            if isinstance(line, bytes):
                                line = line.decode('utf-8')
                            self.append_text(line.strip())

                        # 检查是否有错误
                        if stderr.channel.recv_ready():
                            error = stderr.channel.recv(1024)
                            if isinstance(error, bytes):
                                error = error.decode('utf-8')
                            self.append_text(f"错误:\n{error}")

                        # 短暂休眠以避免过度占用CPU
                        import time
                        time.sleep(0.1)

                except Exception as e:
                    if self.logs_running:  # 只在未主动停止时显示错误
                        self.append_text(f"读取日志时出错: {str(e)}")
                finally:
                    self.logs_running = False

            # 启动线程
            import threading
            self.logs_thread = threading.Thread(target=read_logs)
            self.logs_thread.daemon = True
            self.logs_thread.start()

        except Exception as e:
            QMessageBox.critical(self, "错误", f"启动日志查看时出错: {str(e)}")

    def stop_logs(self):
        if self.logs_running:
            self.logs_running = False
            if self.logs_thread:
                self.logs_thread.join(timeout=1.0)

    def toggle_logs(self):
        if self.logs_running:
            self.stop_logs()
        else:
            self.start_logs()

    def closeEvent(self, event):
        # 停止日志查看
        self.stop_logs()
        # 停止所有正在执行的命令
        # try:
        #     if hasattr(self, 'ssh') and self.ssh:
        #         self.ssh.close()
        # except:
        #     pass
        super().closeEvent(event)

    def load_config(self):
        if not self.ssh:
            QMessageBox.warning(self, "警告", "未配置SSH管理器")
            return

        try:

            default_config = {
                'version': '3.8',
                'services': {},
                'volumes': {},
                'networks': {}
            }

            # 检查文件是否存在
            try:
                # 使用paramiko的SFTP方法读取文件
                with self.ssh.open_sftp().open(f"{self.dirs}{self.file_name}", 'r') as f:
                    content = f.read().decode('utf-8')
            except Exception as e:

                # 如果文件不存在，检查目录是否存在
                try:
                    self.ssh.open_sftp().stat(self.dirs)
                except FileNotFoundError:
                    self.ssh.open_sftp().mkdir(self.dirs)

                # 如果文件不存在，创建新的docker-compose.yml
                content = yaml.dump(default_config, default_flow_style=False, sort_keys=False)
                # 使用paramiko的SFTP方法写入文件
                with self.ssh.open_sftp().open(f"{self.dirs}{self.file_name}", 'w') as f:
                    f.write(content.encode('utf-8'))
                # QMessageBox.information(self, "提示", "已创建新的docker-compose.yml文件")

            self.config = yaml.safe_load(content) or default_config
            self.update_services_tree()

            # 默认选择第一个服务
            if self.services_tree.topLevelItemCount() > 0:
                first_item = self.services_tree.topLevelItem(0)
                self.services_tree.setCurrentItem(first_item)
                self.on_service_selected(first_item)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载配置文件时出错: {str(e)}")

    def save_config(self):
        if not self.ssh:
            QMessageBox.warning(self, "警告", "未配置SSH管理器")
            return

        try:
            content = yaml.dump(self.config, default_flow_style=False, sort_keys=False)
            # 使用paramiko的SFTP方法写入文件
            with self.ssh.open_sftp().open(f"{self.dirs}{self.file_name}", 'w') as f:
                f.write(content.encode('utf-8'))
            # QMessageBox.information(self, "成功", "配置已保存")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存配置时出错: {str(e)}")

    def update_services_tree(self):
        self.services_tree.clear()
        for service_name in self.config.get('services', {}).keys():
            item = QTreeWidgetItem([service_name])

            # 设置图标
            item.setIcon(0, QIcon(f":{service_name}_128.png"))

            # 设置提示信息
            service_info = self.config.get('services', {}).get(service_name, {})
            tooltip = f"服务: {service_name}\n"
            if 'image' in service_info:
                tooltip += f"镜像: {service_info['image']}\n"
            if 'ports' in service_info and service_info['ports']:
                tooltip += f"端口: {', '.join(service_info['ports'])}\n"

            item.setToolTip(0, tooltip)

            self.services_tree.addTopLevelItem(item)

    def on_service_selected(self, item):
        service_name = item.text(0)
        service_config = self.config['services'].get(service_name, {})

        # 清除旧的配置部件
        old_widget = self.config_widget
        self.config_widget = ServiceConfigWidget(service_name, service_config, self)
        self.config_widget.config_changed.connect(
            lambda: self.update_service_config(service_name))

        # 获取右侧编辑区域
        vertical_splitter = self.layout().itemAt(0).widget()
        horizontal_splitter = vertical_splitter.widget(0)
        right_widget = horizontal_splitter.widget(1)
        right_layout = right_widget.layout()
        # 替换配置部件
        if old_widget:
            right_layout.replaceWidget(old_widget, self.config_widget)
            old_widget.deleteLater()
        else:
            right_layout.addWidget(self.config_widget)

    def update_service_config(self, service_name):
        # 更新服务配置
        self.config['services'][service_name] = self.config_widget.config
        # 显示保存成功消息
        QMessageBox.information(self, "成功", f"服务 {service_name} 的配置已更新")

    def add_service(self):
        dialog = ServiceSearchDialog(self)
        if dialog.exec() == QDialog.Accepted:
            service_name, service_config = dialog.get_selected_service()
            if service_name:
                self.config['services'][service_name] = service_config
                self.update_services_tree()
                # 选择新添加的服务
                for i in range(self.services_tree.topLevelItemCount()):
                    item = self.services_tree.topLevelItem(i)
                    if item.text(0) == service_name:
                        self.services_tree.setCurrentItem(item)
                        break
