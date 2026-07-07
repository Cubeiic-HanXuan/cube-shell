# -*- coding: utf-8 -*-
"""Hermes Agent Profile 管理模块 - 支持 Profile 列表/创建/删除/重命名，一键从 Profile 打开终端"""

import yaml
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
                                QListWidget, QListWidgetItem, QLabel, QPushButton,
                                QLineEdit, QFrame, QMessageBox, QInputDialog,
                                QToolBar, QGridLayout, QStyledItemDelegate,
                                QStyleOptionViewItem, QStyle, QDialog, QTabWidget,
                                QPlainTextEdit, QDialogButtonBox)
from PySide6.QtCore import Qt, QThread, Signal, QSize, QRect
from PySide6.QtGui import QFont, QIcon, QPen, QBrush, QColor, QPainter

from function.util import logger
from core.hermes.config_highlighter import YamlHighlighter, DotenvHighlighter


class ProfileItemDelegate(QStyledItemDelegate):
    """自定义绘制 Profile 列表项，多行卡片式效果"""

    ITEM_HEIGHT = 56
    PADDING_LEFT = 12
    PADDING_RIGHT = 12
    PADDING_TOP = 8
    ACTIVE_BAR_WIDTH = 3
    STATUS_DOT_RADIUS = 4

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), self.ITEM_HEIGHT)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = option.rect
        profile = index.data(Qt.UserRole + 1)
        if not profile:
            super().paint(painter, option, index)
            painter.restore()
            return

        is_active = profile.get("active", False)
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
        is_hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        # ─── 背景绘制 ───
        if is_selected:
            bg_color = QColor("#2a4a6b")
        elif is_hovered:
            bg_color = QColor("#2a2a2a")
        else:
            bg_color = QColor("#1e1e1e")
        painter.fillRect(rect, bg_color)

        # ─── 活跃标识：左侧蓝色竖条 ───
        if is_active:
            bar_rect = QRect(rect.left(), rect.top() + 4,
                             self.ACTIVE_BAR_WIDTH, rect.height() - 8)
            painter.fillRect(bar_rect, QColor("#1e90ff"))

        # ─── 文字区域起始 X ───
        text_x = rect.left() + self.PADDING_LEFT + (self.ACTIVE_BAR_WIDTH + 4 if is_active else 0)

        # ─── 第一行：Profile 名称 ───
        name_font = QFont()
        name_font.setPixelSize(14)
        name_font.setBold(True)
        painter.setFont(name_font)
        painter.setPen(QColor("#ffffff"))

        name_y = rect.top() + self.PADDING_TOP + 14
        painter.drawText(text_x, name_y, profile.get("name", ""))

        # ─── 第一行右侧：运行状态 ───
        gateway = profile.get("gateway", "stopped")
        is_running = gateway.lower() == "running"
        status_text = "running" if is_running else "stopped"
        dot_color = QColor("#4caf50") if is_running else QColor("#888888")

        status_font = QFont()
        status_font.setPixelSize(11)
        painter.setFont(status_font)
        fm = painter.fontMetrics()
        status_text_width = fm.horizontalAdvance(status_text)
        dot_diameter = self.STATUS_DOT_RADIUS * 2
        status_total_width = dot_diameter + 4 + status_text_width

        status_x = rect.right() - self.PADDING_RIGHT - status_total_width
        status_y = rect.top() + self.PADDING_TOP + 14

        # 绘制小圆点
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(dot_color))
        dot_center_y = status_y - fm.ascent() // 2
        painter.drawEllipse(status_x, dot_center_y - self.STATUS_DOT_RADIUS,
                            dot_diameter, dot_diameter)

        # 绘制状态文字
        painter.setPen(QColor("#4caf50") if is_running else QColor("#888888"))
        painter.drawText(status_x + dot_diameter + 4, status_y, status_text)

        # ─── 第二行：模型名称 ───
        model_font = QFont()
        model_font.setPixelSize(12)
        painter.setFont(model_font)
        painter.setPen(QColor("#888888"))

        model_y = rect.top() + self.PADDING_TOP + 14 + 18
        painter.drawText(text_x, model_y, profile.get("model", ""))

        # ─── 底部分隔线 ───
        painter.setPen(QPen(QColor("#333333"), 0.5))
        painter.drawLine(rect.left() + 8, rect.bottom(),
                         rect.right() - 8, rect.bottom())

        painter.restore()


class ProfileWorker(QThread):
    """后台线程执行 hermes CLI 命令"""
    profiles_loaded = Signal(list)
    command_done = Signal(str, str)  # description, output
    error = Signal(str)

    def __init__(self, backend, args, parse_profiles=False):
        super().__init__()
        self._backend = backend
        self._args = args
        self._parse_profiles = parse_profiles

    def run(self):
        try:
            result = self._backend.exec_cli(self._args)
            if self._parse_profiles:
                profiles = self._parse_profile_list(result)
                self.profiles_loaded.emit(profiles)
            else:
                self.command_done.emit(' '.join(self._args), result)
        except Exception as e:
            self.error.emit(str(e))

    def _parse_profile_list(self, output: str) -> list:
        """解析 hermes profile list 的输出"""
        profiles = []
        if not output:
            return profiles
        for line in output.strip().split('\n'):
            line = line.strip()
            if not line or '─' in line or line.startswith('Profile'):
                continue
            active = line.startswith('◆')
            if active:
                line = line[1:]
            parts = line.split()
            if len(parts) >= 3:
                profiles.append({
                    "name": parts[0],
                    "active": active,
                    "model": parts[1] if len(parts) > 1 else "",
                    "gateway": parts[2] if len(parts) > 2 else "",
                    "alias": parts[3] if len(parts) > 3 else "—",
                    "distribution": parts[4] if len(parts) > 4 else "—",
                })
        return profiles


class ProfileConfigLoader(QThread):
    """后台加载 Profile 的 config.yaml 与 .env 文本"""
    loaded = Signal(str, str)   # (config_yaml, dotenv)
    error = Signal(str)

    def __init__(self, backend, config_path, env_path):
        super().__init__()
        self._backend = backend
        self._config_path = config_path
        self._env_path = env_path

    def run(self):
        try:
            config_text = self._backend.read_file(self._config_path) or ""
            env_text = ""
            # .env 可能不存在，读取失败不应中断整体加载
            if self._backend.file_exists(self._env_path):
                env_text = self._backend.read_file(self._env_path) or ""
            self.loaded.emit(config_text, env_text)
        except Exception as e:
            self.error.emit(str(e))


class ProfileConfigSaver(QThread):
    """后台写入 Profile 的 config.yaml / .env（只写有改动的文件）"""
    finished = Signal(list)  # 已保存文件名列表
    error = Signal(str)

    def __init__(self, backend, writes):
        super().__init__()
        self._backend = backend
        self._writes = writes  # [(path, content, label)]

    def run(self):
        try:
            saved = []
            for path, content, label in self._writes:
                self._backend.write_file(path, content)
                saved.append(label)
            self.finished.emit(saved)
        except Exception as e:
            logger.error(f"保存 Profile 配置失败: {e}")
            self.error.emit(str(e))


class ProfileConfigDialog(QDialog):
    """Profile 配置编辑对话框：编辑 config.yaml 与 .env（带语法高亮、YAML 校验）"""

    def __init__(self, backend, profile_name, config_path, env_path, parent=None):
        super().__init__(parent)
        self._backend = backend
        self._profile_name = profile_name
        self._config_path = config_path
        self._env_path = env_path
        self._loaded_config = ""
        self._loaded_env = ""
        self._env_existed = False
        self._loader = None
        self._saver = None
        self._init_ui()
        self._load()

    def _init_ui(self):
        self.setWindowTitle(self.tr("编辑配置 - {}").format(self._profile_name))
        self.resize(720, 620)
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(8)

        path_lbl = QLabel(self._config_path)
        path_lbl.setStyleSheet("color: #888888;")
        path_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(path_lbl)

        mono = self._mono_font()

        self._tabs = QTabWidget()

        # config.yaml
        self._yaml_edit = QPlainTextEdit()
        self._yaml_edit.setFont(mono)
        self._yaml_edit.setTabStopDistance(
            self._yaml_edit.fontMetrics().horizontalAdvance(' ') * 2)
        # 高亮器需持有引用，否则被 GC
        self._yaml_hl = YamlHighlighter(self._yaml_edit.document())
        self._tabs.addTab(self._yaml_edit, "config.yaml")

        # .env
        self._env_edit = QPlainTextEdit()
        self._env_edit.setFont(mono)
        self._env_hl = DotenvHighlighter(self._env_edit.document())
        self._tabs.addTab(self._env_edit, ".env")

        v.addWidget(self._tabs)

        self._status_lbl = QLabel(self.tr("加载中..."))
        self._status_lbl.setStyleSheet("color: #888888;")
        v.addWidget(self._status_lbl)

        # 按钮：保存 / 重新加载 / 关闭
        btn_box = QDialogButtonBox()
        self._save_btn = btn_box.addButton(
            self.tr("保存"), QDialogButtonBox.AcceptRole)
        self._reload_btn = btn_box.addButton(
            self.tr("重新加载"), QDialogButtonBox.ResetRole)
        self._close_btn = btn_box.addButton(
            self.tr("关闭"), QDialogButtonBox.RejectRole)
        self._save_btn.clicked.connect(self._on_save)
        self._reload_btn.clicked.connect(self._load)
        self._close_btn.clicked.connect(self.reject)
        v.addWidget(btn_box)

    def _set_editing_enabled(self, enabled):
        self._yaml_edit.setReadOnly(not enabled)
        self._env_edit.setReadOnly(not enabled)
        self._save_btn.setEnabled(enabled)
        self._reload_btn.setEnabled(enabled)

    # ── 加载 ──

    def _load(self):
        if not self._backend:
            self._status_lbl.setText(self.tr("未连接后端"))
            return
        if self._loader and self._loader.isRunning():
            return
        self._set_editing_enabled(False)
        self._status_lbl.setText(self.tr("加载中..."))
        self._loader = ProfileConfigLoader(
            self._backend, self._config_path, self._env_path)
        self._loader.loaded.connect(self._on_loaded)
        self._loader.error.connect(self._on_load_error)
        self._loader.start()

    def _on_loaded(self, config_text, env_text):
        self._loaded_config = config_text
        self._loaded_env = env_text
        self._env_existed = bool(env_text)
        self._yaml_edit.setPlainText(config_text)
        self._env_edit.setPlainText(env_text)
        self._set_editing_enabled(True)
        if not config_text:
            self._status_lbl.setText(
                self.tr("未找到 config.yaml，保存后将新建"))
        else:
            self._status_lbl.setText(self.tr("就绪"))

    def _on_load_error(self, msg):
        self._set_editing_enabled(True)
        self._status_lbl.setText(self.tr("加载失败: {}").format(msg))

    # ── 保存 ──

    def _on_save(self):
        if not self._backend:
            QMessageBox.warning(self, self.tr("警告"), self.tr("未连接后端"))
            return
        if self._saver and self._saver.isRunning():
            return

        config_text = self._yaml_edit.toPlainText()
        env_text = self._env_edit.toPlainText()

        # 收集有改动的文件
        writes = []
        if config_text != self._loaded_config:
            # YAML 语法校验：解析失败拒绝写入，避免写坏配置
            try:
                yaml.safe_load(config_text)
            except yaml.YAMLError as e:
                self._tabs.setCurrentIndex(0)
                QMessageBox.critical(
                    self, self.tr("YAML 语法错误"),
                    self.tr("config.yaml 无法保存，请修正后重试：\n{}").format(str(e)))
                return
            writes.append((self._config_path, config_text, "config.yaml"))
        # .env：原本存在或用户填了内容才写，避免为一个空文件平白创建 .env
        if env_text != self._loaded_env and (env_text.strip() or self._env_existed):
            writes.append((self._env_path, env_text, ".env"))

        if not writes:
            QMessageBox.information(
                self, self.tr("提示"), self.tr("没有需要保存的改动"))
            return

        self._set_editing_enabled(False)
        self._status_lbl.setText(self.tr("保存中..."))
        self._saver = ProfileConfigSaver(self._backend, writes)
        self._saver.finished.connect(self._on_saved)
        self._saver.error.connect(self._on_save_error)
        self._saver.start()

    def _on_saved(self, saved_labels):
        # 更新基准值，避免重复写入
        self._loaded_config = self._yaml_edit.toPlainText()
        self._loaded_env = self._env_edit.toPlainText()
        if self._loaded_env.strip():
            self._env_existed = True
        self._set_editing_enabled(True)
        self._status_lbl.setText(
            self.tr("已保存: {}").format("、".join(saved_labels)))
        QMessageBox.information(
            self, self.tr("成功"),
            self.tr("已保存: {}").format("、".join(saved_labels)))

    def _on_save_error(self, msg):
        self._set_editing_enabled(True)
        self._status_lbl.setText(self.tr("保存失败: {}").format(msg))
        QMessageBox.critical(
            self, self.tr("错误"), self.tr("保存失败: {}").format(msg))

    @staticmethod
    def _mono_font():
        font = QFont()
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setFamilies(["Consolas", "Menlo", "DejaVu Sans Mono",
                          "Courier New", "monospace"])
        font.setFixedPitch(True)
        font.setPointSize(15)
        return font


class AgentWidget(QWidget):
    """Hermes Agent Profile 管理面板"""

    # 信号：请求主窗口打开终端
    open_terminal_requested = Signal(str)  # profile_name

    def __init__(self, parent=None):
        super().__init__(parent)
        self._backend = None
        self._workers = []  # 持有 worker 引用，防止 GC
        self._profiles = []
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        # ─── 工具栏 ───
        toolbar_layout = QHBoxLayout()
        toolbar_layout.setSpacing(6)

        self._btn_refresh = QPushButton(self.tr("刷新"))
        self._btn_refresh.clicked.connect(self.refresh)
        toolbar_layout.addWidget(self._btn_refresh)

        self._btn_create = QPushButton(self.tr("新建 Profile"))
        self._btn_create.clicked.connect(self._create_profile)
        toolbar_layout.addWidget(self._btn_create)

        self._btn_rename = QPushButton(self.tr("重命名"))
        self._btn_rename.clicked.connect(self._rename_profile)
        toolbar_layout.addWidget(self._btn_rename)

        self._btn_delete = QPushButton(self.tr("删除"))
        self._btn_delete.clicked.connect(self._delete_profile)
        toolbar_layout.addWidget(self._btn_delete)

        toolbar_layout.addStretch()
        main_layout.addLayout(toolbar_layout)

        # ─── 左右分割面板 ───
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)

        # 左侧：搜索框 + Profile 列表
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText(self.tr("搜索 Profile..."))
        self._search_input.textChanged.connect(self._filter_profiles)
        left_layout.addWidget(self._search_input)

        self._profile_list = QListWidget()
        self._profile_list.setMouseTracking(True)
        self._profile_list.setItemDelegate(ProfileItemDelegate(self._profile_list))
        self._profile_list.setStyleSheet("""
            QListWidget {
                background-color: #1e1e1e;
                border: 1px solid #333333;
                outline: none;
            }
            QListWidget::item {
                border: none;
                padding: 0px;
            }
        """)
        self._profile_list.currentItemChanged.connect(self._show_profile_detail)
        left_layout.addWidget(self._profile_list)

        splitter.addWidget(left_widget)

        # 右侧：Profile 详情 + 操作按钮
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.setSpacing(10)

        # 信息卡片
        info_frame = QFrame()
        info_frame.setFrameShape(QFrame.StyledPanel)
        info_layout = QGridLayout(info_frame)
        info_layout.setContentsMargins(12, 12, 12, 12)
        info_layout.setSpacing(8)

        info_layout.addWidget(QLabel(self.tr("名称：")), 0, 0)
        self._lbl_name = QLabel("—")
        self._lbl_name.setFont(QFont("", -1, QFont.Bold))
        info_layout.addWidget(self._lbl_name, 0, 1)

        info_layout.addWidget(QLabel(self.tr("模型：")), 1, 0)
        self._lbl_model = QLabel("—")
        info_layout.addWidget(self._lbl_model, 1, 1)

        info_layout.addWidget(QLabel(self.tr("网关状态：")), 2, 0)
        self._lbl_gateway = QLabel("—")
        info_layout.addWidget(self._lbl_gateway, 2, 1)

        info_layout.addWidget(QLabel(self.tr("Alias：")), 3, 0)
        self._lbl_alias = QLabel("—")
        info_layout.addWidget(self._lbl_alias, 3, 1)

        info_layout.addWidget(QLabel(self.tr("Distribution：")), 4, 0)
        self._lbl_distribution = QLabel("—")
        info_layout.addWidget(self._lbl_distribution, 4, 1)

        info_layout.addWidget(QLabel(self.tr("状态：")), 5, 0)
        self._lbl_active = QLabel("—")
        info_layout.addWidget(self._lbl_active, 5, 1)

        right_layout.addWidget(info_frame)

        # 操作按钮区域
        actions_layout = QVBoxLayout()
        actions_layout.setSpacing(8)

        self._btn_open_terminal = QPushButton(self.tr("在终端中打开"))
        self._btn_open_terminal.setMinimumHeight(36)
        font = self._btn_open_terminal.font()
        font.setBold(True)
        self._btn_open_terminal.setFont(font)
        self._btn_open_terminal.clicked.connect(self._open_in_terminal)
        actions_layout.addWidget(self._btn_open_terminal)

        btn_row1 = QHBoxLayout()
        self._btn_set_default = QPushButton(self.tr("设为默认"))
        self._btn_set_default.clicked.connect(self._set_as_default)
        btn_row1.addWidget(self._btn_set_default)

        self._btn_edit_config = QPushButton(self.tr("编辑配置"))
        self._btn_edit_config.clicked.connect(self._edit_config)
        btn_row1.addWidget(self._btn_edit_config)
        actions_layout.addLayout(btn_row1)

        btn_row2 = QHBoxLayout()
        self._btn_start_gateway = QPushButton(self.tr("启动网关"))
        self._btn_start_gateway.clicked.connect(self._start_gateway)
        btn_row2.addWidget(self._btn_start_gateway)

        self._btn_stop_gateway = QPushButton(self.tr("停止网关"))
        self._btn_stop_gateway.clicked.connect(self._stop_gateway)
        btn_row2.addWidget(self._btn_stop_gateway)
        actions_layout.addLayout(btn_row2)

        right_layout.addLayout(actions_layout)
        right_layout.addStretch()

        # 初始无选中：右侧操作按钮全部禁用，待选中 Profile 后按状态启用
        self._update_action_buttons(None)

        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

    def set_backend(self, backend):
        """设置数据访问后端"""
        self._backend = backend

    def refresh(self):
        """刷新 Profile 列表"""
        if not self._backend:
            return
        worker = ProfileWorker(self._backend, ["profile", "list"], parse_profiles=True)
        worker.profiles_loaded.connect(self._on_profiles_loaded)
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        worker.start()

    def _on_profiles_loaded(self, profiles):
        """加载 Profile 列表完成"""
        self._profiles = profiles
        self._render_profile_list()

    def _render_profile_list(self):
        """渲染 Profile 列表到 QListWidget"""
        # 记住当前选中项，刷新后尽量保持选中，避免跳回第一项
        current = self._profile_list.currentItem()
        selected_name = current.data(Qt.UserRole) if current else None

        self._profile_list.clear()
        filter_text = self._search_input.text().strip().lower()
        target_row = -1
        for p in self._profiles:
            if filter_text and filter_text not in p["name"].lower():
                continue
            item = QListWidgetItem(p["name"])
            item.setData(Qt.UserRole, p["name"])
            item.setData(Qt.UserRole + 1, p)
            self._profile_list.addItem(item)
            if p["name"] == selected_name:
                target_row = self._profile_list.count() - 1
        # 恢复之前的选中项；找不到（首次加载/被过滤/已删除）则回退到第一项
        if target_row >= 0:
            self._profile_list.setCurrentRow(target_row)
        elif self._profile_list.count() > 0:
            self._profile_list.setCurrentRow(0)

    def _filter_profiles(self, text):
        """搜索框过滤"""
        self._render_profile_list()

    def _show_profile_detail(self, current, previous=None):
        """显示选中 Profile 的详情"""
        if not current:
            self._clear_detail()
            return
        profile = current.data(Qt.UserRole + 1)
        if not profile:
            self._clear_detail()
            return
        self._lbl_name.setText(profile["name"])
        self._lbl_model.setText(profile["model"])
        self._lbl_gateway.setText(profile["gateway"])
        self._lbl_alias.setText(profile.get("alias", "—"))
        self._lbl_distribution.setText(profile.get("distribution", "—"))
        self._lbl_active.setText(self.tr("当前活跃") if profile["active"] else self.tr("非活跃"))
        self._update_action_buttons(profile)

    def _clear_detail(self):
        """清空详情面板"""
        self._lbl_name.setText("—")
        self._lbl_model.setText("—")
        self._lbl_gateway.setText("—")
        self._lbl_alias.setText("—")
        self._lbl_distribution.setText("—")
        self._lbl_active.setText("—")
        self._update_action_buttons(None)

    def _update_action_buttons(self, profile):
        """根据选中 Profile 的状态切换各操作按钮可用性。

        - 在终端中打开 / 停止网关：仅网关 running 时可用
        - 启动网关：仅网关 stopped 时可用
        - 编辑配置：任意状态均可用（有选中即可）
        - 设为默认 / 删除：仅当 Profile 非默认（非活跃）时可用
        """
        if not profile:
            # 无选中：除刷新/新建等工具栏按钮外，右侧操作按钮全部禁用
            self._btn_open_terminal.setEnabled(False)
            self._btn_stop_gateway.setEnabled(False)
            self._btn_start_gateway.setEnabled(False)
            self._btn_edit_config.setEnabled(False)
            self._btn_set_default.setEnabled(False)
            self._btn_delete.setEnabled(False)
            return

        is_running = str(profile.get("gateway", "")).lower() == "running"
        is_stopped = str(profile.get("gateway", "")).lower() == "stopped"
        is_default = bool(profile.get("active", False))

        self._btn_open_terminal.setEnabled(is_running)
        self._btn_stop_gateway.setEnabled(is_running)
        self._btn_start_gateway.setEnabled(is_stopped)
        self._btn_edit_config.setEnabled(True)
        self._btn_set_default.setEnabled(not is_default)
        # 默认 Profile 不允许删除
        self._btn_delete.setEnabled(not is_default)

    def _open_in_terminal(self):
        """在新 Terminal Tab 中打开选中的 Profile"""
        current = self._profile_list.currentItem()
        if not current:
            return
        profile_name = current.data(Qt.UserRole)
        if profile_name:
            self.open_terminal_requested.emit(profile_name)

    def _set_as_default(self):
        """设为默认 Profile"""
        current = self._profile_list.currentItem()
        if not current:
            return
        profile_name = current.data(Qt.UserRole)
        if not profile_name:
            return
        self._run_command(["profile", "use", profile_name],
                         self.tr("已切换默认 Profile 为: ") + profile_name)

    def _create_profile(self):
        """新建 Profile（克隆当前）"""
        name, ok = QInputDialog.getText(self, self.tr("新建 Profile"),
                                        self.tr("输入 Profile 名称:"))
        if ok and name.strip():
            self._run_command(["profile", "create", name.strip(), "--clone"],
                             self.tr("创建 Profile: ") + name.strip())

    def _delete_profile(self):
        """删除选中的 Profile"""
        current = self._profile_list.currentItem()
        if not current:
            return
        profile_name = current.data(Qt.UserRole)
        if not profile_name:
            return
        profile = current.data(Qt.UserRole + 1) or {}
        # 默认（活跃）Profile 不允许删除，避免删掉当前正在使用的配置
        if profile.get("active", False):
            QMessageBox.warning(
                self, self.tr("无法删除"),
                self.tr("「{}」是当前默认 Profile，请先切换到其他 Profile 再删除。")
                .format(profile_name))
            return
        # 网关运行中先停止再删，避免残留进程
        if str(profile.get("gateway", "")).lower() == "running":
            QMessageBox.warning(
                self, self.tr("无法删除"),
                self.tr("「{}」的网关正在运行，请先停止网关再删除。")
                .format(profile_name))
            return
        reply = QMessageBox.question(
            self, self.tr("确认删除"),
            self.tr("确定要删除 Profile「{}」吗？此操作不可撤销。").format(profile_name),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self._run_command(["profile", "delete", profile_name, "-y"],
                             self.tr("删除 Profile: ") + profile_name)

    def _rename_profile(self):
        """重命名选中的 Profile"""
        current = self._profile_list.currentItem()
        if not current:
            return
        old_name = current.data(Qt.UserRole)
        if not old_name:
            return
        new_name, ok = QInputDialog.getText(self, self.tr("重命名 Profile"),
                                            self.tr("新名称:"), text=old_name)
        if ok and new_name.strip() and new_name.strip() != old_name:
            self._run_command(["profile", "rename", old_name, new_name.strip()],
                             self.tr("重命名 Profile: {} → {}").format(old_name, new_name.strip()))

    def _edit_config(self):
        """编辑选中 Profile 的 config.yaml / .env"""
        current = self._profile_list.currentItem()
        if not current:
            return
        profile_name = current.data(Qt.UserRole)
        if not profile_name or not self._backend:
            return
        hermes_home = self._backend.get_hermes_home()
        profile_dir = f"{hermes_home}/profiles/{profile_name}"
        config_path = f"{profile_dir}/config.yaml"
        env_path = f"{profile_dir}/.env"
        dlg = ProfileConfigDialog(
            self._backend, profile_name, config_path, env_path, self)
        dlg.exec()
        # 配置可能影响列表展示（如模型），关闭后刷新
        self.refresh()

    def _start_gateway(self):
        """启动网关"""
        current = self._profile_list.currentItem()
        if not current:
            return
        profile_name = current.data(Qt.UserRole)
        if not profile_name:
            return
        self._run_command(["-p", profile_name, "gateway", "start"],
                         self.tr("启动网关: ") + profile_name)

    def _stop_gateway(self):
        """停止网关"""
        current = self._profile_list.currentItem()
        if not current:
            return
        profile_name = current.data(Qt.UserRole)
        if not profile_name:
            return
        self._run_command(["-p", profile_name, "gateway", "stop"],
                         self.tr("停止网关: ") + profile_name)

    def _run_command(self, args, success_msg):
        """执行 CLI 命令并在完成后刷新"""
        if not self._backend:
            return
        worker = ProfileWorker(self._backend, args, parse_profiles=False)
        worker.command_done.connect(lambda desc, output: self._on_command_done(success_msg, output))
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        worker.start()

    def _on_command_done(self, msg, output):
        """命令执行完成回调"""
        # 刷新列表
        self.refresh()

    def _on_error(self, err_msg):
        """错误回调"""
        QMessageBox.warning(self, self.tr("错误"), err_msg)

    def _parse_profile_list(self, output: str) -> list:
        """
        解析 hermes profile list 的输出
        返回: [{"name": "dev", "active": False, "model": "kimi-for-coding",
                 "gateway": "running", "alias": "dev", "distribution": "—"}, ...]
        """
        profiles = []
        if not output:
            return profiles
        for line in output.strip().split('\n'):
            line = line.strip()
            if not line or '─' in line or line.startswith('Profile'):
                continue
            active = line.startswith('◆')
            if active:
                line = line[1:]
            parts = line.split()
            if len(parts) >= 3:
                profiles.append({
                    "name": parts[0],
                    "active": active,
                    "model": parts[1] if len(parts) > 1 else "",
                    "gateway": parts[2] if len(parts) > 2 else "",
                    "alias": parts[3] if len(parts) > 3 else "—",
                    "distribution": parts[4] if len(parts) > 4 else "—",
                })
        return profiles
