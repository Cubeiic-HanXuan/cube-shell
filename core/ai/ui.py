"""
AI 相关 UI 组件与交互入口。

该模块包含两类能力：
1) 设置界面：保存非敏感偏好到 `ai.json`，敏感 Key 通过系统钥匙串保存；
2) 输出界面：启动后台线程进行流式生成，并提供复制/插入/远程执行等动作。
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from .prefs import PROVIDER_PRESETS, AIUserPrefs, get_provider_preset, load_ai_prefs, save_ai_prefs
from .secrets import get_ai_api_key, set_ai_api_key


class AISettingsDialog(QDialog):
    """
    AI 设置弹窗（保存到 ai.json + 系统钥匙串）。

    设计要点：
    - ai.json：保存模型与参数（非敏感）
    - keyring：保存 API Key（敏感），避免落盘
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("AI 设置"))
        self.setModal(True)
        self.setFixedWidth(520)

        self._prefs = load_ai_prefs()

        layout = QVBoxLayout(self)

        form = QGridLayout()
        row = 0

        # ---- AI 服务提供商 ----
        form.addWidget(QLabel(self.tr("AI 服务提供商")), row, 0)
        self.provider_combo = QComboBox()
        for key, preset in PROVIDER_PRESETS.items():
            self.provider_combo.addItem(preset["name"], key)  # userData 存 key
        form.addWidget(self.provider_combo, row, 1)
        row += 1

        # ---- 模型（可编辑下拉框） ----
        form.addWidget(QLabel(self.tr("模型")), row, 0)
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        form.addWidget(self.model_combo, row, 1)
        row += 1

        # ---- Base URL ----
        form.addWidget(QLabel(self.tr("Base URL(可选)")), row, 0)
        self.base_url_edit = QLineEdit(self._prefs.base_url)
        form.addWidget(self.base_url_edit, row, 1)
        row += 1

        # ---- max_tokens ----
        form.addWidget(QLabel("max_tokens"), row, 0)
        self.max_tokens_edit = QLineEdit(str(self._prefs.max_tokens))
        form.addWidget(self.max_tokens_edit, row, 1)
        row += 1

        # ---- temperature ----
        form.addWidget(QLabel("temperature"), row, 0)
        self.temperature_edit = QLineEdit(str(self._prefs.temperature))
        form.addWidget(self.temperature_edit, row, 1)
        row += 1

        # ---- 深度思考 ----
        self.thinking_check = QCheckBox(self.tr("启用深度思考"))
        self.thinking_check.setChecked(self._prefs.thinking_enabled)
        form.addWidget(self.thinking_check, row, 1)
        row += 1

        # ---- 流式输出 ----
        self.stream_check = QCheckBox(self.tr("启用流式输出"))
        self.stream_check.setChecked(self._prefs.stream)
        form.addWidget(self.stream_check, row, 1)
        row += 1

        # ---- 系统提示词 ----
        form.addWidget(QLabel(self.tr("系统提示词")), row, 0)
        self.system_prompt_edit = QLineEdit(self._prefs.system_prompt)
        form.addWidget(self.system_prompt_edit, row, 1)
        row += 1

        layout.addLayout(form)

        # ---- API Key ----
        key_box = QHBoxLayout()
        key_box.addWidget(QLabel(self.tr("API Key")))
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText(self.tr("使用系统钥匙串保存，不写入配置文件"))
        key_box.addWidget(self.key_edit)
        layout.addLayout(key_box)

        # ---- 按钮 ----
        btns = QHBoxLayout()
        self.save_btn = QPushButton(self.tr("保存"))
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn = QPushButton(self.tr("取消"))
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btns.addStretch(1)
        btns.addWidget(self.save_btn)
        btns.addWidget(self.cancel_btn)
        layout.addLayout(btns)

        # ---- 信号连接 ----
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        self.save_btn.clicked.connect(self._save)
        self.cancel_btn.clicked.connect(self.reject)

        # ---- 初始化：根据已保存的 provider 设置下拉框选中项 ----
        self._init_provider_selection()

    def _init_provider_selection(self):
        """根据已保存的 prefs.provider 设置下拉框选中项，并触发联动。"""
        saved_provider = self._prefs.provider
        idx = self.provider_combo.findData(saved_provider)
        if idx < 0:
            idx = 0
        # 先断开信号防止重复触发，设置完再连接
        self.provider_combo.blockSignals(True)
        self.provider_combo.setCurrentIndex(idx)
        self.provider_combo.blockSignals(False)
        # 手动触发一次联动
        self._on_provider_changed(idx)
        # 恢复用户保存的模型名（可能不在推荐列表中）
        self.model_combo.setCurrentText(self._prefs.model)

    def _on_provider_changed(self, index: int):
        """
        选择厂商后：
        - 自动填充 base_url（custom 则清空）
        - 更新模型下拉框的选项列表
        - 启用/禁用"深度思考"复选框
        - 加载对应 provider 的 API Key
        """
        provider_key = self.provider_combo.itemData(index)
        preset = get_provider_preset(provider_key)

        # base_url
        if provider_key == "custom":
            self.base_url_edit.clear()
        else:
            self.base_url_edit.setText(preset["base_url"])

        # 模型列表
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        for model_name in preset.get("models", []):
            self.model_combo.addItem(model_name)
        if preset.get("models"):
            self.model_combo.setCurrentIndex(0)
        self.model_combo.blockSignals(False)

        # 深度思考
        supports_thinking = preset.get("supports_thinking", False)
        self.thinking_check.setEnabled(supports_thinking)
        if not supports_thinking:
            self.thinking_check.setChecked(False)

        # API Key：加载对应 provider 的已保存 key
        existing_key = get_ai_api_key(provider_key)
        if existing_key:
            self.key_edit.setPlaceholderText(self.tr("已保存（输入新值可覆盖）"))
        else:
            self.key_edit.setPlaceholderText(self.tr("使用系统钥匙串保存，不写入配置文件"))
        self.key_edit.clear()

    def _save(self):
        """
        保存按钮处理：
        1) 解析 UI 输入并写入 ai.json（save_ai_prefs）
        2) 若用户输入了 API Key，则写入系统钥匙串（set_ai_api_key）
        """
        try:
            provider = self.provider_combo.currentData()
            prefs = AIUserPrefs(
                provider=provider,
                model=self.model_combo.currentText().strip() or "glm-4-plus",
                base_url=self.base_url_edit.text().strip(),
                thinking_enabled=self.thinking_check.isChecked(),
                stream=self.stream_check.isChecked(),
                max_tokens=int(self.max_tokens_edit.text().strip() or "8192"),
                temperature=float(self.temperature_edit.text().strip() or "1.0"),
                system_prompt=(
                    self.system_prompt_edit.text().strip()
                    or "你是一个资深 Linux 运维与终端助手。输出尽量可执行、可复制。"
                ),
            )
            save_ai_prefs(prefs)

            key = self.key_edit.text().strip()
            if key:
                if not set_ai_api_key(key, provider=provider):
                    QMessageBox.warning(self, self.tr("错误"), self.tr("保存 API Key 失败"))
                    return
            self.accept()
        except Exception as e:
            QMessageBox.warning(self, self.tr("错误"), self.tr("保存失败: {}").format(e))
