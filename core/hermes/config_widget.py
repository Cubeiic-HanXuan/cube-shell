from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
                                QLabel, QPushButton, QLineEdit, QComboBox,
                                QTableWidget, QTableWidgetItem, QHeaderView,
                                QGroupBox, QCheckBox, QMessageBox, QTextEdit)
from PySide6.QtCore import Qt, QThread, Signal
import yaml
import re

from function.util import logger


class ConfigLoader(QThread):
    """后台加载 hermes 配置，避免阻塞 UI"""
    loaded = Signal(dict, dict)  # (config_data, env_data)
    error = Signal(str)

    def __init__(self, backend):
        super().__init__()
        self._backend = backend

    def run(self):
        try:
            hermes_home = self._backend.get_hermes_home()
            config_content = self._backend.read_file(f"{hermes_home}/config.yaml")
            env_content = self._backend.read_file(f"{hermes_home}/.env")
            config_data = yaml.safe_load(config_content) if config_content else {}
            env_data = self._parse_env(env_content)
            self.loaded.emit(config_data or {}, env_data)
        except Exception as e:
            self.error.emit(str(e))

    def _parse_env(self, content):
        env = {}
        if not content:
            return env
        for line in content.strip().split('\n'):
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                env[key.strip()] = value.strip()
        return env


class ConfigWidget(QWidget):
    """Hermes Agent 配置管理模块"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._backend = None
        self._config_data = {}
        self._env_data = {}
        self._loader = None
        self._tool_checkboxes = []
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        # --- 模型配置区域 ---
        model_group = QGroupBox(self.tr("模型配置"))
        model_layout = QFormLayout(model_group)
        self._model_combo = QComboBox()
        self._model_combo.setEditable(True)
        self._model_combo.setMinimumWidth(250)
        model_layout.addRow(self.tr("当前模型:"), self._model_combo)
        layout.addWidget(model_group)

        # --- Provider 配置表格 ---
        provider_group = QGroupBox(self.tr("API Provider"))
        provider_layout = QVBoxLayout(provider_group)
        self._provider_table = QTableWidget()
        self._provider_table.setColumnCount(3)
        self._provider_table.setHorizontalHeaderLabels(
            [self.tr("Provider 名称"), self.tr("API Key 状态"), self.tr("操作")]
        )
        self._provider_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._provider_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self._provider_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self._provider_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._provider_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._provider_table.verticalHeader().setVisible(False)
        provider_layout.addWidget(self._provider_table)
        layout.addWidget(provider_group)

        # --- 工具集配置 ---
        tools_group = QGroupBox(self.tr("工具集"))
        self._tools_layout = QVBoxLayout(tools_group)
        self._tools_placeholder = QLabel(self.tr("未配置"))
        self._tools_layout.addWidget(self._tools_placeholder)
        layout.addWidget(tools_group)

        # --- Terminal Backend 选择 ---
        terminal_group = QGroupBox(self.tr("Terminal Backend"))
        terminal_layout = QFormLayout(terminal_group)
        self._terminal_combo = QComboBox()
        self._terminal_combo.addItems(["local", "docker", "ssh", "modal"])
        terminal_layout.addRow(self.tr("Backend:"), self._terminal_combo)
        layout.addWidget(terminal_group)

        # --- 操作按钮区域 ---
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self._refresh_btn = QPushButton(self.tr("刷新配置"))
        self._refresh_btn.clicked.connect(self._on_refresh)
        btn_layout.addWidget(self._refresh_btn)
        self._save_btn = QPushButton(self.tr("保存配置"))
        self._save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(self._save_btn)
        layout.addLayout(btn_layout)

        layout.addStretch()

    def set_backend(self, backend):
        """设置后端引用（不触发加载）"""
        self._backend = backend

    def refresh(self):
        """当 Tab 被选中时调用，触发数据加载"""
        self._load_config()

    def _load_config(self):
        """使用 QThread 后台加载配置"""
        if not self._backend:
            return
        # 防止多次并发加载
        if self._loader and self._loader.isRunning():
            return
        self._loader = ConfigLoader(self._backend)
        self._loader.loaded.connect(self._on_config_loaded)
        self._loader.error.connect(self._on_config_error)
        self._loader.start()

    def _on_config_loaded(self, config_data, env_data):
        """配置加载完成回调"""
        try:
            self._config_data = config_data
            self._env_data = env_data
            self._populate_model()
            self._populate_providers()
            self._populate_tools()
            self._populate_terminal()
        except Exception as e:
            logger.error(f"填充配置 UI 失败: {e}")

    def _on_config_error(self, error_msg):
        """配置加载出错回调"""
        try:
            logger.error(f"加载 hermes 配置失败: {error_msg}")
            self._config_data = {}
            self._env_data = {}
            self._populate_model()
            self._populate_providers()
            self._populate_tools()
            self._populate_terminal()
        except Exception as e:
            logger.error(f"重置配置 UI 失败: {e}")

    def _populate_model(self):
        """填充模型选择下拉框"""
        self._model_combo.clear()
        model = self._config_data.get("model", "")
        # model 字段可能是 dict（含 default/provider/base_url）或简单字符串
        if isinstance(model, dict):
            model_name = model.get("default", "") or model.get("name", "")
            provider_name = model.get("provider", "")
            base_url = model.get("base_url", "")
        else:
            model_name = str(model) if model else ""
            provider_name = ""
            base_url = ""
        if model_name:
            display = model_name
            if provider_name:
                display += f"  (provider: {provider_name})"
            self._model_combo.addItem(display)
            self._model_combo.setCurrentText(display)
        else:
            self._model_combo.addItem(self.tr("未配置"))

    def _populate_providers(self):
        """填充 Provider 配置表格 - 从 config.yaml providers + .env API Keys 综合检测"""
        self._provider_table.setRowCount(0)

        # 从 config.yaml 的 providers 字段获取
        providers = self._config_data.get("providers", {})

        # 从 model 配置获取当前使用的 provider
        model_cfg = self._config_data.get("model", {})
        current_provider = model_cfg.get("provider", "") if isinstance(model_cfg, dict) else ""
        current_base_url = model_cfg.get("base_url", "") if isinstance(model_cfg, dict) else ""

        # 从 .env 检测 *_API_KEY 模式的 provider
        env_providers = {}
        for key, value in self._env_data.items():
            if key.endswith("_API_KEY") and value:
                # KIMI_API_KEY -> kimi
                provider_id = key[:-8].lower()  # remove _API_KEY
                env_providers[provider_id] = {"env_key": key, "value": value}

        # 合并所有 provider 信息
        all_providers = {}

        # 1. 从 config.yaml providers
        if isinstance(providers, dict):
            for name, cfg in providers.items():
                all_providers[name] = {"source": "config", "config": cfg}

        # 2. 从 .env 的 API Key
        for pid, info in env_providers.items():
            if pid not in all_providers:
                all_providers[pid] = {"source": "env", "env_key": info["env_key"], "value": info["value"]}
            else:
                all_providers[pid]["env_key"] = info["env_key"]
                all_providers[pid]["value"] = info["value"]

        # 3. 从 model.provider（如果以上都没覆盖到）
        if current_provider and current_provider not in all_providers:
            all_providers[current_provider] = {"source": "model", "base_url": current_base_url}

        if not all_providers:
            self._provider_table.setRowCount(1)
            item = QTableWidgetItem(self.tr("未配置"))
            self._provider_table.setItem(0, 0, item)
            self._provider_table.setItem(0, 1, QTableWidgetItem(""))
            return

        self._provider_table.setRowCount(len(all_providers))
        for row, (provider_name, provider_info) in enumerate(all_providers.items()):
            # Provider 名称（标注是否为当前使用）
            display_name = provider_name
            if current_provider and provider_name.lower().startswith(current_provider.split("-")[0].lower()):
                display_name += " ★"
            name_item = QTableWidgetItem(display_name)
            self._provider_table.setItem(row, 0, name_item)

            # API Key 状态
            env_key = provider_info.get("env_key", "")
            key_value = provider_info.get("value", "")
            if not key_value and env_key:
                key_value = self._env_data.get(env_key, "")
            if not key_value and isinstance(provider_info.get("config"), dict):
                # 从 config 中的 api_key_env 字段查找
                api_key_env = provider_info["config"].get("api_key_env", "")
                key_value = self._env_data.get(api_key_env, "")
                env_key = api_key_env

            if key_value:
                masked = self._mask_key(key_value)
            else:
                base_url = provider_info.get("base_url", "")
                masked = f"Base URL: {base_url}" if base_url else self.tr("未设置 API Key")
            key_item = QTableWidgetItem(masked)
            self._provider_table.setItem(row, 1, key_item)

            # 操作按钮
            edit_btn = QPushButton(self.tr("编辑"))
            edit_btn.clicked.connect(
                lambda checked, p=provider_name, r=row, ek=env_key: self._edit_api_key_by_env(p, r, ek))
            self._provider_table.setCellWidget(row, 2, edit_btn)

    def _populate_tools(self):
        """填充工具集复选框"""
        # 清理旧的复选框
        for cb in self._tool_checkboxes:
            self._tools_layout.removeWidget(cb)
            cb.deleteLater()
        self._tool_checkboxes.clear()

        # 兼容 toolsets 和 tools 两种字段名
        tools = self._config_data.get("toolsets") or self._config_data.get("tools") or []
        if not tools:
            self._tools_placeholder.setVisible(True)
            return

        self._tools_placeholder.setVisible(False)
        for tool_name in tools:
            cb = QCheckBox(str(tool_name))
            cb.setChecked(True)
            self._tools_layout.addWidget(cb)
            self._tool_checkboxes.append(cb)

    def _populate_terminal(self):
        """填充 Terminal Backend 下拉框"""
        terminal_cfg = self._config_data.get("terminal", {})
        backend_value = terminal_cfg.get("backend", "local") if isinstance(terminal_cfg, dict) else "local"
        index = self._terminal_combo.findText(backend_value)
        if index >= 0:
            self._terminal_combo.setCurrentIndex(index)
        else:
            self._terminal_combo.setCurrentText(backend_value)

    def _mask_key(self, key):
        """将 API Key 遮蔽为 '前4****后4' 格式"""
        if not key:
            return ""
        if len(key) <= 8:
            return key[:2] + "****" + key[-2:] if len(key) > 4 else "****"
        return key[:4] + "****" + key[-4:]

    def _edit_api_key_by_env(self, provider, row, env_key):
        """通过环境变量名编辑 API Key"""
        if not env_key:
            # 自动推导 env key
            env_key = f"{provider.upper()}_API_KEY"

        current_value = self._env_data.get(env_key, "")
        from PySide6.QtWidgets import QInputDialog
        new_key, ok = QInputDialog.getText(
            self, self.tr("编辑 API Key"),
            self.tr("请输入 {} 的 API Key ({})：").format(provider, env_key),
            QLineEdit.EchoMode.Normal,
            current_value
        )
        if ok and new_key:
            self._env_data[env_key] = new_key.strip()
            # 更新表格显示
            masked = self._mask_key(new_key.strip())
            self._provider_table.setItem(row, 1, QTableWidgetItem(masked))

    def _edit_api_key(self, provider, row):
        """弹出编辑 API Key 对话框"""
        providers = self._config_data.get("providers", {})
        provider_cfg = providers.get(provider, {})
        api_key_env = provider_cfg.get("api_key_env", "") if isinstance(provider_cfg, dict) else ""

        if not api_key_env:
            QMessageBox.warning(self, self.tr("警告"),
                                self.tr("该 Provider 未配置 api_key_env 字段"))
            return

        current_value = self._env_data.get(api_key_env, "")
        from PySide6.QtWidgets import QInputDialog
        new_key, ok = QInputDialog.getText(
            self, self.tr("编辑 API Key"),
            self.tr("请输入 {} 的 API Key:").format(provider),
            QLineEdit.EchoMode.Normal,
            current_value
        )
        if ok and new_key:
            self._env_data[api_key_env] = new_key.strip()
            # 更新表格显示
            masked = self._mask_key(new_key.strip())
            self._provider_table.setItem(row, 1, QTableWidgetItem(masked))

    def _on_refresh(self):
        """刷新配置按钮点击"""
        self._load_config()

    def _on_save(self):
        """保存配置按钮点击"""
        if not self._backend:
            QMessageBox.warning(self, self.tr("警告"), self.tr("未连接后端"))
            return
        try:
            self._save_config()
            self._save_env()
            QMessageBox.information(self, self.tr("成功"), self.tr("配置已保存"))
        except Exception as e:
            QMessageBox.critical(self, self.tr("错误"),
                                 self.tr("保存配置失败: {}").format(str(e)))

    def _save_config(self):
        """保存配置到 config.yaml"""
        # 更新 config_data
        model_text = self._model_combo.currentText().strip()
        if model_text and model_text != self.tr("未配置"):
            # 保持 model 字段原有结构（dict 或 string）
            model_field = self._config_data.get("model")
            if isinstance(model_field, dict):
                model_field["default"] = model_text
            else:
                self._config_data["model"] = model_text

        # 更新 terminal backend
        self._config_data.setdefault("terminal", {})
        self._config_data["terminal"]["backend"] = self._terminal_combo.currentText()

        # 更新 tools 列表（基于复选框状态）
        enabled_tools = []
        for cb in self._tool_checkboxes:
            if cb.isChecked():
                enabled_tools.append(cb.text())
        if enabled_tools:
            self._config_data["tools"] = enabled_tools

        # 优先尝试 CLI 保存
        cli_success = False
        if model_text and model_text != self.tr("未配置"):
            result = self._backend.exec_cli(["config", "set", "model", model_text])
            if result is not None:
                cli_success = True

        # 始终写文件确保完整性
        hermes_home = self._backend.get_hermes_home()
        config_path = f"{hermes_home}/config.yaml"
        content = yaml.dump(self._config_data, default_flow_style=False, allow_unicode=True)
        self._backend.write_file(config_path, content)

    def _save_env(self):
        """保存 .env 文件"""
        if not self._env_data:
            return
        hermes_home = self._backend.get_hermes_home()
        env_path = f"{hermes_home}/.env"

        lines = []
        for key, value in self._env_data.items():
            lines.append(f"{key}={value}")
        content = '\n'.join(lines) + '\n'
        self._backend.write_file(env_path, content)
