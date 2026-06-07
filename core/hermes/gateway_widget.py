"""
Hermes Agent 消息网关管理模块
支持多平台消息通道配置、启停与测试。
"""

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
                                QLabel, QPushButton, QLineEdit, QGroupBox,
                                QFrame, QFormLayout, QComboBox, QCheckBox,
                                QMessageBox, QTextEdit, QScrollArea)
from PySide6.QtCore import Qt, QThread, Signal
import json

from function.util import logger

# 支持的平台列表 —— fields 对应 .env 中 {PLATFORM_UPPER}_{FIELD_UPPER} 变量名
PLATFORMS = [
    {"id": "telegram", "name": "Telegram", "fields": ["bot_token", "home_channel", "allowed_users"]},
    {"id": "discord", "name": "Discord", "fields": ["bot_token", "home_channel", "allowed_users"]},
    {"id": "slack", "name": "Slack", "fields": ["bot_token", "app_token", "home_channel"]},
    {"id": "feishu", "name": "飞书", "fields": ["app_id", "app_secret", "domain", "connection_mode", "group_policy"]},
    {"id": "wecom", "name": "企业微信", "fields": ["corp_id", "agent_id", "secret"]},
    {"id": "dingtalk", "name": "钉钉", "fields": ["app_key", "app_secret", "robot_code"]},
    {"id": "matrix", "name": "Matrix", "fields": ["homeserver", "user_id", "access_token"]},
    {"id": "whatsapp", "name": "WhatsApp", "fields": ["phone_number_id", "access_token", "verify_token"]},
]

# Token/Secret 类字段关键字，匹配到时使用密码模式
_SECRET_KEYWORDS = ("token", "secret", "key", "password")


class GatewayWorker(QThread):
    """后台执行网关操作的工作线程"""
    config_loaded = Signal(dict)       # gateway config
    status_checked = Signal(bool)      # is_running
    command_done = Signal(str, str)    # (description, output)
    error = Signal(str)

    def __init__(self, backend, action, **kwargs):
        super().__init__()
        self._backend = backend
        self._action = action
        self._kwargs = kwargs

    def run(self):
        try:
            if self._action == "load_config":
                self._do_load_config()
            elif self._action == "check_status":
                self._do_check_status()
            elif self._action == "start":
                self._do_start()
            elif self._action == "stop":
                self._do_stop()
            elif self._action == "test":
                self._do_test()
            elif self._action == "save_config":
                self._do_save_config()
        except Exception as e:
            self.error.emit(str(e))

    def _do_load_config(self):
        """从 .env 文件和 gateway_state.json 读取平台配置"""
        hermes_home = self._backend.get_hermes_home()

        # 读取 .env 文件解析平台配置
        env_content = self._backend.read_file(f"{hermes_home}/.env")
        env_vars = {}
        if env_content:
            for line in env_content.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    env_vars[key.strip()] = value.strip()

        # 读取 gateway_state.json 获取平台连接状态
        state_content = self._backend.read_file(f"{hermes_home}/gateway_state.json")
        platform_states = {}
        if state_content:
            try:
                state_data = json.loads(state_content)
                platform_states = state_data.get("platforms", {})
            except (json.JSONDecodeError, ValueError):
                pass

        # 将 .env 变量按平台分组
        gateway_cfg = {}
        for platform_info in PLATFORMS:
            pid = platform_info["id"]
            prefix = pid.upper() + "_"
            pcfg = {}
            for field in platform_info["fields"]:
                env_key = prefix + field.upper()
                if env_key in env_vars:
                    pcfg[field] = env_vars[env_key]
            # 检查 enabled 状态（.env 中没有被注释掉 + gateway_state 中有状态）
            if pcfg:
                # 有配置值就认为已配置
                pstate = platform_states.get(pid, {})
                pcfg["_connected"] = pstate.get("state") == "connected" if pstate else False
                gateway_cfg[pid] = pcfg

        self.config_loaded.emit(gateway_cfg)

    def _do_check_status(self):
        output = self._backend.exec_cli(["gateway", "status"])
        if output:
            lower = output.lower()
            # hermes gateway status 输出中包含 PID 或 "is loaded" 表示正在运行
            is_running = ("pid" in lower and "=" in output) or "is loaded" in lower
        else:
            is_running = False
        self.status_checked.emit(is_running)
        self.command_done.emit("检查网关状态", output or "(无输出)")

    def _do_start(self):
        output = self._backend.exec_cli(["gateway", "start"])
        self.command_done.emit("启动网关", output or "(无输出)")
        # 启动后重新检查状态
        self._do_check_status()

    def _do_stop(self):
        output = self._backend.exec_cli(["gateway", "stop"])
        self.command_done.emit("停止网关", output or "(无输出)")
        self.status_checked.emit(False)

    def _do_test(self):
        platform_id = self._kwargs.get("platform_id", "")
        output = self._backend.exec_cli(["send", "--to", platform_id, "Test from CubeShell"])
        self.command_done.emit(f"测试 {platform_id}", output or "(无输出)")

    def _do_save_config(self):
        """将平台配置写入 .env 文件"""
        platform_id = self._kwargs.get("platform_id", "")
        fields = self._kwargs.get("fields", {})

        hermes_home = self._backend.get_hermes_home()
        env_path = f"{hermes_home}/.env"
        env_content = self._backend.read_file(env_path) or ""

        prefix = platform_id.upper() + "_"
        lines = env_content.splitlines()
        new_lines = []
        updated_keys = set()

        for line in lines:
            stripped = line.strip()
            # 跳过空注释不处理，保留原样
            if stripped.startswith("#"):
                # 检查是否是被注释的同名变量，如果我们要设置它就取消注释
                comment_body = stripped.lstrip("# ").strip()
                if "=" in comment_body:
                    ck = comment_body.partition("=")[0].strip()
                    field_name = ck[len(prefix):].lower() if ck.startswith(prefix) else None
                    if field_name and field_name in fields and fields[field_name]:
                        # 取消注释，用新值替换
                        new_lines.append(f"{ck}={fields[field_name]}")
                        updated_keys.add(field_name)
                        continue
                new_lines.append(line)
                continue

            if "=" in stripped:
                key = stripped.partition("=")[0].strip()
                if key.startswith(prefix):
                    field_name = key[len(prefix):].lower()
                    if field_name in fields:
                        new_lines.append(f"{key}={fields[field_name]}")
                        updated_keys.add(field_name)
                        continue
            new_lines.append(line)

        # 追加未更新的新字段
        for field_name, value in fields.items():
            if field_name not in updated_keys and value:
                env_key = prefix + field_name.upper()
                new_lines.append(f"{env_key}={value}")

        content = "\n".join(new_lines) + "\n"
        self._backend.write_file(env_path, content)
        self.command_done.emit(f"保存 {platform_id} 配置", "配置已保存到 .env")


class GatewayWidget(QWidget):
    """Hermes Agent 消息网关管理模块"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._backend = None
        self._gateway_config = {}
        self._worker = None
        self._platform_cards = {}    # platform_id -> card widgets dict
        self._expanded = {}          # platform_id -> bool
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        # --- 顶部：网关状态栏 ---
        status_layout = QHBoxLayout()
        self._status_label = QLabel(self.tr("网关状态：未知"))
        self._status_label.setStyleSheet("font-weight: bold;")
        status_layout.addWidget(self._status_label)
        status_layout.addStretch()

        self._start_btn = QPushButton(self.tr("启动网关"))
        self._start_btn.clicked.connect(self._start_gateway)
        status_layout.addWidget(self._start_btn)

        self._stop_btn = QPushButton(self.tr("停止网关"))
        self._stop_btn.clicked.connect(self._stop_gateway)
        status_layout.addWidget(self._stop_btn)

        self._refresh_btn = QPushButton(self.tr("刷新状态"))
        self._refresh_btn.clicked.connect(self._check_gateway_status)
        status_layout.addWidget(self._refresh_btn)

        layout.addLayout(status_layout)

        # --- 主体：平台卡片 ---
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        scroll_content = QWidget()
        self._grid_layout = QGridLayout(scroll_content)
        self._grid_layout.setSpacing(10)
        self._grid_layout.setContentsMargins(0, 0, 0, 0)

        self._build_platform_cards()

        scroll_area.setWidget(scroll_content)
        layout.addWidget(scroll_area, 1)

        # --- 底部：日志区域 ---
        log_group = QGroupBox(self.tr("操作日志"))
        log_layout = QVBoxLayout(log_group)
        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setMaximumHeight(150)
        log_layout.addWidget(self._log_text)
        layout.addWidget(log_group)

    def _build_platform_cards(self):
        """构建所有平台的卡片"""
        for idx, platform_info in enumerate(PLATFORMS):
            card = self._create_platform_card(platform_info)
            row = idx // 3
            col = idx % 3
            self._grid_layout.addWidget(card, row, col)

    def _create_platform_card(self, platform_info):
        """创建单个平台的 UI 卡片"""
        platform_id = platform_info["id"]
        platform_name = platform_info["name"]
        fields = platform_info["fields"]

        card = QFrame()
        card.setFrameShape(QFrame.Shape.StyledPanel)
        # card.setStyleSheet(
        #     "QFrame { border: 1px solid #ccc; border-radius: 8px; "
        #     "padding: 10px; background-color: #fafafa; }"
        # )

        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(6)

        # 平台名称
        name_label = QLabel(platform_name)
        name_label.setStyleSheet("font-weight: bold; font-size: 14px; border: none;")
        card_layout.addWidget(name_label)

        # 启用/禁用
        enable_cb = QCheckBox(self.tr("启用"))
        enable_cb.stateChanged.connect(
            lambda state, pid=platform_id: self._toggle_platform(pid, state == Qt.CheckState.Checked.value)
        )
        card_layout.addWidget(enable_cb)

        # Token 状态
        token_label = QLabel(self.tr("Token: 未配置"))
        token_label.setStyleSheet("color: #999; border: none;")
        card_layout.addWidget(token_label)

        # 按钮行
        btn_layout = QHBoxLayout()
        config_btn = QPushButton(self.tr("配置"))
        config_btn.clicked.connect(lambda _, pid=platform_id: self._toggle_config_form(pid))
        btn_layout.addWidget(config_btn)

        test_btn = QPushButton(self.tr("测试"))
        test_btn.clicked.connect(lambda _, pid=platform_id: self._test_platform(pid))
        btn_layout.addWidget(test_btn)
        card_layout.addLayout(btn_layout)

        # 配置表单（默认隐藏）
        form_widget = QWidget()
        form_layout = QFormLayout(form_widget)
        form_layout.setContentsMargins(0, 6, 0, 0)
        field_inputs = {}
        for field in fields:
            line_edit = QLineEdit()
            # Token/Secret 类字段使用密码模式
            if any(kw in field.lower() for kw in _SECRET_KEYWORDS):
                line_edit.setEchoMode(QLineEdit.EchoMode.Password)
            line_edit.setPlaceholderText(field)
            form_layout.addRow(QLabel(field + ":"), line_edit)
            field_inputs[field] = line_edit

        save_btn = QPushButton(self.tr("保存配置"))
        save_btn.clicked.connect(lambda _, pid=platform_id: self._save_platform_config(pid))
        form_layout.addRow("", save_btn)

        form_widget.setVisible(False)
        card_layout.addWidget(form_widget)

        # 记录卡片组件引用
        self._platform_cards[platform_id] = {
            "card": card,
            "enable_cb": enable_cb,
            "token_label": token_label,
            "form_widget": form_widget,
            "field_inputs": field_inputs,
        }
        self._expanded[platform_id] = False

        return card

    # ─── 公开方法 ───

    def set_backend(self, backend):
        """设置后端引用（不触发加载）"""
        self._backend = backend

    def refresh(self):
        """当 Tab 被选中时调用，触发数据加载"""
        self._load_gateway_config()

    # ─── 内部方法 ───

    def _load_gateway_config(self):
        """读取 config.yaml 的 gateway 段"""
        if not self._backend:
            return
        self._run_worker("load_config")

    def _check_gateway_status(self):
        """检查网关进程状态"""
        if not self._backend:
            return
        self._run_worker("check_status")

    def _start_gateway(self):
        """执行 hermes gateway start"""
        if not self._backend:
            return
        self._append_log(self.tr("正在启动网关..."))
        self._run_worker("start")

    def _stop_gateway(self):
        """执行 hermes gateway stop"""
        if not self._backend:
            return
        self._append_log(self.tr("正在停止网关..."))
        self._run_worker("stop")

    def _toggle_platform(self, platform_id, enabled):
        """启用/禁用平台"""
        cfg = self._gateway_config.setdefault(platform_id, {})
        cfg["enabled"] = enabled
        self._append_log(self.tr("平台 {} {}").format(
            platform_id, self.tr("已启用") if enabled else self.tr("已禁用")))

    def _toggle_config_form(self, platform_id):
        """展开/折叠配置表单"""
        card_info = self._platform_cards.get(platform_id)
        if not card_info:
            return
        expanded = not self._expanded.get(platform_id, False)
        self._expanded[platform_id] = expanded
        card_info["form_widget"].setVisible(expanded)

    def _save_platform_config(self, platform_id):
        """保存平台配置"""
        if not self._backend:
            QMessageBox.warning(self, self.tr("警告"), self.tr("未连接后端"))
            return

        card_info = self._platform_cards.get(platform_id)
        if not card_info:
            return

        fields = {}
        for field_name, line_edit in card_info["field_inputs"].items():
            value = line_edit.text().strip()
            if value:
                fields[field_name] = value

        enabled = card_info["enable_cb"].isChecked()
        self._append_log(self.tr("正在保存 {} 配置...").format(platform_id))
        self._run_worker("save_config", platform_id=platform_id, fields=fields, enabled=enabled)

    def _test_platform(self, platform_id):
        """执行 hermes send --to PLATFORM "Test from CubeShell" """
        if not self._backend:
            QMessageBox.warning(self, self.tr("警告"), self.tr("未连接后端"))
            return
        self._append_log(self.tr("正在测试 {} ...").format(platform_id))
        self._run_worker("test", platform_id=platform_id)

    # ─── Worker 管理 ───

    def _run_worker(self, action, **kwargs):
        """创建并启动后台 Worker"""
        if self._worker and self._worker.isRunning():
            self._worker.quit()
            self._worker.wait(3000)
        self._worker = GatewayWorker(self._backend, action, **kwargs)
        self._worker.config_loaded.connect(self._on_config_loaded)
        self._worker.status_checked.connect(self._on_status_checked)
        self._worker.command_done.connect(self._on_command_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    # ─── 回调 ───

    def _on_config_loaded(self, gateway_cfg):
        """配置加载完成"""
        self._gateway_config = gateway_cfg
        self._update_cards_from_config()
        self._append_log(self.tr("网关配置已加载"))
        # 加载完配置后自动检查状态
        self._check_gateway_status()

    def _on_status_checked(self, is_running):
        """网关状态检查结果"""
        if is_running:
            self._status_label.setText(self.tr("网关状态：运行中"))
            self._status_label.setStyleSheet("font-weight: bold; color: green;")
        else:
            self._status_label.setText(self.tr("网关状态：已停止"))
            self._status_label.setStyleSheet("font-weight: bold; color: red;")

    def _on_command_done(self, description, output):
        """命令执行完成"""
        self._append_log(f"[{description}] {output.strip()}")

    def _on_error(self, error_msg):
        """Worker 出错"""
        self._append_log(f"[错误] {error_msg}")
        logger.error(f"GatewayWorker 错误: {error_msg}")

    # ─── 辅助方法 ───

    def _update_cards_from_config(self):
        """根据加载的配置更新所有平台卡片状态"""
        for platform_id, card_info in self._platform_cards.items():
            pcfg = self._gateway_config.get(platform_id, {})
            if not isinstance(pcfg, dict):
                pcfg = {}

            # 更新启用状态（有配置且已连接 → 启用）
            connected = pcfg.get("_connected", False)
            has_any_value = any(
                pcfg.get(f) for f in card_info["field_inputs"].keys()
            )
            card_info["enable_cb"].blockSignals(True)
            card_info["enable_cb"].setChecked(connected)
            card_info["enable_cb"].blockSignals(False)

            # 更新 Token 状态显示
            if connected:
                card_info["token_label"].setText(self.tr("状态: 已连接"))
                card_info["token_label"].setStyleSheet("color: green; border: none;")
            elif has_any_value:
                card_info["token_label"].setText(self.tr("Token: 已配置"))
                card_info["token_label"].setStyleSheet("color: orange; border: none;")
            else:
                card_info["token_label"].setText(self.tr("Token: 未配置"))
                card_info["token_label"].setStyleSheet("color: #999; border: none;")

            # 填充字段值
            for field_name, line_edit in card_info["field_inputs"].items():
                value = pcfg.get(field_name, "")
                if isinstance(value, list):
                    value = ", ".join(str(v) for v in value)
                line_edit.setText(str(value) if value else "")

    def _append_log(self, text):
        """追加日志到底部文本区域"""
        self._log_text.append(text)
