"""
Claude Code 设置管理 Widget
提供模型、权限、提示词等配置的可视化管理界面。
"""

import json
import logging
import os
from typing import Optional

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QFormLayout, QComboBox,
                               QLineEdit, QTextEdit, QPushButton, QGroupBox,
                               QLabel, QMessageBox, QHBoxLayout)

logger = logging.getLogger(__name__)


class SettingsWorker(QThread):
    """后台加载/保存设置"""
    loaded = Signal(dict)  # settings dict
    saved = Signal(bool, str)  # (success, message)
    error = Signal(str)

    def __init__(self, backend, mode: str = "load", settings: Optional[dict] = None):
        super().__init__()
        self._backend = backend
        self._mode = mode
        self._settings = settings

    def run(self):
        try:
            if self._mode == "load":
                data = self._backend.read_settings()
                self.loaded.emit(data)
            elif self._mode == "save":
                success, msg = self._backend.write_settings(self._settings or {})
                self.saved.emit(success, msg)
        except Exception as e:
            logger.error(f"SettingsWorker 执行失败 (mode={self._mode}): {e}")
            self.error.emit(str(e))


# 提供商预设配置
def _load_provider_presets():
    """从配置文件加载 LLM 提供商预设"""
    _conf_path = os.path.join(
        os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')),
        "conf", "llm_providers.json"
    )
    try:
        with open(_conf_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return [{"key": "anthropic", "name": "Anthropic (默认)", "base_url": "", "models": ["sonnet", "opus", "haiku"], "supports_thinking": True},
                {"key": "custom", "name": "自定义", "base_url": "", "models": [], "supports_thinking": False}]


_PROVIDER_PRESETS = _load_provider_presets()


class SettingsWidget(QWidget):
    """Claude Code 设置管理"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._backend = None
        self._worker: Optional[SettingsWorker] = None
        self._settings_data: dict = {}
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        # --- 模型配置 ---
        model_group = QGroupBox(self.tr("模型配置"))
        model_layout = QFormLayout(model_group)

        self._model_combo = QComboBox()
        self._model_combo.setEditable(True)
        self._model_combo.addItems(["sonnet", "opus", "haiku"])
        self._model_combo.setMinimumWidth(250)
        model_layout.addRow(self.tr("模型选择:"), self._model_combo)

        self._effort_combo = QComboBox()
        self._effort_combo.addItems(["low", "medium", "high", "max"])
        self._effort_combo.setCurrentText("high")
        model_layout.addRow(self.tr("Effort 级别:"), self._effort_combo)

        layout.addWidget(model_group)

        # --- 模型提供商 ---
        provider_group = QGroupBox(self.tr("模型提供商"))
        provider_layout = QFormLayout(provider_group)

        self._provider_combo = QComboBox()
        for preset in _PROVIDER_PRESETS:
            self._provider_combo.addItem(preset["name"])
        self._provider_combo.setMinimumWidth(250)
        self._provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        provider_layout.addRow(self.tr("提供商预设:"), self._provider_combo)

        self._base_url_edit = QLineEdit()
        self._base_url_edit.setPlaceholderText(self.tr("API 地址"))
        self._base_url_edit.setMinimumWidth(400)
        self._base_url_edit.setEnabled(False)
        provider_layout.addRow(self.tr("API 地址:"), self._base_url_edit)

        self._api_key_edit = QLineEdit()
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_edit.setPlaceholderText(self.tr("输入 API Key"))
        self._api_key_edit.setMinimumWidth(400)
        self._api_key_edit.setEnabled(False)
        provider_layout.addRow(self.tr("API 密钥:"), self._api_key_edit)

        self._provider_model_combo = QComboBox()
        self._provider_model_combo.setEditable(True)
        self._provider_model_combo.setMinimumWidth(250)
        self._provider_model_combo.setEnabled(False)
        provider_layout.addRow(self.tr("模型名称:"), self._provider_model_combo)

        layout.addWidget(provider_group)

        # --- 权限配置 ---
        perm_group = QGroupBox(self.tr("权限配置"))
        perm_layout = QFormLayout(perm_group)

        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["default", "acceptEdits", "plan", "auto"])
        perm_layout.addRow(self.tr("权限模式:"), self._mode_combo)

        self._allowed_tools_edit = QLineEdit()
        self._allowed_tools_edit.setPlaceholderText("Read,Edit,Bash")
        perm_layout.addRow(self.tr("Allowed Tools:"), self._allowed_tools_edit)

        layout.addWidget(perm_group)

        # --- 提示词配置 ---
        prompt_group = QGroupBox(self.tr("提示词配置"))
        prompt_layout = QVBoxLayout(prompt_group)

        prompt_label = QLabel(self.tr("自定义系统提示词:"))
        prompt_layout.addWidget(prompt_label)

        self._prompt_edit = QTextEdit()
        self._prompt_edit.setPlaceholderText(
            self.tr("在此输入追加到系统提示词末尾的自定义内容...")
        )
        self._prompt_edit.setMinimumHeight(100)
        prompt_layout.addWidget(self._prompt_edit)

        layout.addWidget(prompt_group)

        # --- 操作按钮 ---
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._refresh_btn = QPushButton(self.tr("加载设置"))
        self._refresh_btn.clicked.connect(self._on_load)
        btn_layout.addWidget(self._refresh_btn)

        self._save_btn = QPushButton(self.tr("保存设置"))
        self._save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(self._save_btn)

        layout.addLayout(btn_layout)
        layout.addStretch()

    def set_backend(self, backend) -> None:
        """设置 Backend"""
        self._backend = backend

    def refresh(self) -> None:
        """加载设置（Tab 被选中时调用）"""
        self._load_settings()

    def _load_settings(self) -> None:
        """使用 QThread 后台加载设置"""
        if not self._backend:
            return
        if self._worker and self._worker.isRunning():
            return
        self._refresh_btn.setEnabled(False)
        self._worker = SettingsWorker(self._backend, mode="load")
        self._worker.loaded.connect(self._on_settings_loaded)
        self._worker.error.connect(self._on_worker_error)
        self._worker.finished.connect(lambda: self._refresh_btn.setEnabled(True))
        self._worker.start()

    def _on_settings_loaded(self, settings: dict) -> None:
        """设置加载完成回调"""
        try:
            self._settings_data = settings
            self._populate_ui(settings)
        except Exception as e:
            logger.error(f"填充设置 UI 失败: {e}")

    def _populate_ui(self, settings: dict) -> None:
        """将 settings dict 填充到 UI 控件"""
        # 模型
        model = settings.get("model", "")
        if model:
            idx = self._model_combo.findText(str(model))
            if idx >= 0:
                self._model_combo.setCurrentIndex(idx)
            else:
                self._model_combo.setCurrentText(str(model))

        # Effort 级别
        effort = settings.get("effortLevel", "high")
        idx = self._effort_combo.findText(str(effort))
        if idx >= 0:
            self._effort_combo.setCurrentIndex(idx)

        # 模型提供商 (从 env 加载)
        env = settings.get("env", {})
        base_url = env.get("ANTHROPIC_BASE_URL", "")
        api_key = env.get("ANTHROPIC_API_KEY", "")
        env_model = env.get("ANTHROPIC_MODEL", "")

        if base_url:
            # 反向匹配预设提供商（优先匹配 anthropic_base_url，其次 base_url）
            matched = False
            for i, preset in enumerate(_PROVIDER_PRESETS):
                anthropic_url = preset.get("anthropic_base_url", "")
                if anthropic_url and anthropic_url == base_url:
                    self._provider_combo.setCurrentIndex(i)
                    matched = True
                    break
                if preset["base_url"] and preset["base_url"] == base_url:
                    self._provider_combo.setCurrentIndex(i)
                    matched = True
                    break
            if not matched:
                # 选择"自定义"
                self._provider_combo.setCurrentIndex(len(_PROVIDER_PRESETS) - 1)
                self._base_url_edit.setText(base_url)
        else:
            self._provider_combo.setCurrentIndex(0)

        if api_key:
            self._api_key_edit.setText(api_key)
        if env_model:
            idx = self._provider_model_combo.findText(env_model)
            if idx >= 0:
                self._provider_model_combo.setCurrentIndex(idx)
            else:
                self._provider_model_combo.setCurrentText(env_model)

        # 权限模式
        default_mode = settings.get("defaultMode", "default")
        idx = self._mode_combo.findText(str(default_mode))
        if idx >= 0:
            self._mode_combo.setCurrentIndex(idx)

        # Allowed Tools
        permissions = settings.get("permissions", {})
        allow_list = permissions.get("allow", [])
        if isinstance(allow_list, list):
            self._allowed_tools_edit.setText(", ".join(allow_list))
        elif isinstance(allow_list, str):
            self._allowed_tools_edit.setText(allow_list)

        # 系统提示词
        prompt = settings.get("appendSystemPrompt", "")
        self._prompt_edit.setPlainText(str(prompt) if prompt else "")

    def _on_provider_changed(self, index: int) -> None:
        """提供商预设切换联动"""
        preset = _PROVIDER_PRESETS[index]
        is_anthropic = (index == 0)
        is_custom = (index == len(_PROVIDER_PRESETS) - 1)

        # 启用/禁用控件
        self._base_url_edit.setEnabled(not is_anthropic)
        self._api_key_edit.setEnabled(not is_anthropic)
        self._provider_model_combo.setEnabled(not is_anthropic)

        # 填充 API 地址（优先使用 anthropic_base_url）
        if is_anthropic:
            self._base_url_edit.clear()
            self._api_key_edit.clear()
        elif not is_custom:
            anthropic_url = preset.get("anthropic_base_url", "")
            self._base_url_edit.setText(anthropic_url if anthropic_url else preset["base_url"])
        # 自定义时保持用户已输入的内容

        # 更新模型列表
        self._provider_model_combo.clear()
        if preset["models"]:
            self._provider_model_combo.addItems(preset["models"])

    def _on_worker_error(self, error_msg: str) -> None:
        """Worker 错误回调"""
        logger.error(f"Settings worker 错误: {error_msg}")
        QMessageBox.warning(
            self, self.tr("错误"),
            self.tr("操作失败: {}").format(error_msg)
        )

    def _on_load(self) -> None:
        """加载设置按钮点击"""
        self._load_settings()

    def _on_save(self) -> None:
        """保存设置按钮点击"""
        if not self._backend:
            QMessageBox.warning(self, self.tr("警告"), self.tr("未连接后端"))
            return

        settings = self._build_settings_dict()
        if self._worker and self._worker.isRunning():
            return

        self._save_btn.setEnabled(False)
        self._worker = SettingsWorker(self._backend, mode="save", settings=settings)
        self._worker.saved.connect(self._on_settings_saved)
        self._worker.error.connect(self._on_worker_error)
        self._worker.finished.connect(lambda: self._save_btn.setEnabled(True))
        self._worker.start()

    def _build_settings_dict(self) -> dict:
        """从 UI 控件构建 settings dict"""
        # 以现有 settings 为基础，避免丢失未展示的字段
        settings = dict(self._settings_data)

        # 模型
        model_text = self._model_combo.currentText().strip()
        if model_text:
            settings["model"] = model_text

        # Effort 级别
        settings["effortLevel"] = self._effort_combo.currentText()

        # 模型提供商 env 配置
        provider_index = self._provider_combo.currentIndex()
        is_anthropic = (provider_index == 0)
        env = dict(settings.get("env", {}))

        if is_anthropic:
            # 移除提供商相关环境变量
            env.pop("ANTHROPIC_BASE_URL", None)
            env.pop("ANTHROPIC_API_KEY", None)
            env.pop("ANTHROPIC_MODEL", None)
            if env:
                settings["env"] = env
            else:
                settings.pop("env", None)
        else:
            base_url = self._base_url_edit.text().strip()
            api_key = self._api_key_edit.text().strip()
            provider_model = self._provider_model_combo.currentText().strip()
            if base_url:
                env["ANTHROPIC_BASE_URL"] = base_url
            if api_key:
                env["ANTHROPIC_API_KEY"] = api_key
            if provider_model:
                env["ANTHROPIC_MODEL"] = provider_model
            settings["env"] = env

        # 权限模式
        settings["defaultMode"] = self._mode_combo.currentText()

        # Allowed Tools
        tools_text = self._allowed_tools_edit.text().strip()
        if tools_text:
            allow_list = [t.strip() for t in tools_text.split(",") if t.strip()]
            settings.setdefault("permissions", {})["allow"] = allow_list
        else:
            # 清空
            if "permissions" in settings:
                settings["permissions"]["allow"] = []

        # 系统提示词
        prompt_text = self._prompt_edit.toPlainText().strip()
        if prompt_text:
            settings["appendSystemPrompt"] = prompt_text
        else:
            settings.pop("appendSystemPrompt", None)

        return settings

    def _on_settings_saved(self, success: bool, message: str) -> None:
        """设置保存完成回调"""
        if success:
            QMessageBox.information(self, self.tr("成功"), self.tr("设置已保存"))
        else:
            QMessageBox.critical(
                self, self.tr("错误"),
                self.tr("保存设置失败: {}").format(message)
            )
