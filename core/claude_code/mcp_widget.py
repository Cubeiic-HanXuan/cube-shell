"""
Claude Code MCP Server 管理 Widget
提供 MCP Server 的可视化增删改查管理界面。
"""

import logging
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                               QTableWidget, QTableWidgetItem, QHeaderView,
                               QDialog, QFormLayout, QLineEdit, QTextEdit,
                               QLabel, QMessageBox, QDialogButtonBox)

logger = logging.getLogger(__name__)


class McpWorker(QThread):
    """后台加载/保存 MCP 配置"""
    loaded = Signal(dict)  # MCP config dict
    saved = Signal(bool, str)  # (success, message)
    error = Signal(str)

    def __init__(self, backend, mode: str = "load", config: Optional[dict] = None):
        super().__init__()
        self._backend = backend
        self._mode = mode
        self._config = config

    def run(self):
        try:
            if self._mode == "load":
                data = self._backend.read_mcp_config()
                self.loaded.emit(data)
            elif self._mode == "save":
                success, msg = self._backend.write_mcp_config(self._config or {})
                self.saved.emit(success, msg)
        except Exception as e:
            logger.error(f"McpWorker 执行失败 (mode={self._mode}): {e}")
            self.error.emit(str(e))


class McpEditDialog(QDialog):
    """MCP Server 编辑对话框"""

    def __init__(self, parent=None, server_name: str = "",
                 server_config: Optional[dict] = None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("编辑 MCP Server"))
        self.setMinimumWidth(450)
        self._init_ui(server_name, server_config or {})

    def _init_ui(self, server_name: str, config: dict) -> None:
        layout = QVBoxLayout(self)

        form_layout = QFormLayout()

        # Server 名称
        self._name_edit = QLineEdit()
        self._name_edit.setText(server_name)
        self._name_edit.setPlaceholderText("server-name")
        form_layout.addRow(self.tr("Server 名称:"), self._name_edit)

        # Command
        self._command_edit = QLineEdit()
        self._command_edit.setText(config.get("command", ""))
        self._command_edit.setPlaceholderText("npx")
        form_layout.addRow(self.tr("Command:"), self._command_edit)

        # Args
        self._args_edit = QLineEdit()
        args_list = config.get("args", [])
        if isinstance(args_list, list):
            self._args_edit.setText(", ".join(str(a) for a in args_list))
        self._args_edit.setPlaceholderText("@some/mcp-server, --port, 3000")
        form_layout.addRow(self.tr("Args (逗号分隔):"), self._args_edit)

        # Env
        env_label = QLabel(self.tr("Env (KEY=VALUE，每行一个):"))
        form_layout.addRow(env_label)

        self._env_edit = QTextEdit()
        self._env_edit.setMinimumHeight(80)
        self._env_edit.setMaximumHeight(150)
        env_dict = config.get("env", {})
        if isinstance(env_dict, dict):
            env_lines = [f"{k}={v}" for k, v in env_dict.items()]
            self._env_edit.setPlainText("\n".join(env_lines))
        self._env_edit.setPlaceholderText("API_KEY=xxx\nDEBUG=true")
        form_layout.addRow(self._env_edit)

        layout.addLayout(form_layout)

        # 按钮
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def get_server_name(self) -> str:
        """获取 Server 名称"""
        return self._name_edit.text().strip()

    def get_server_config(self) -> dict:
        """获取 Server 配置 dict"""
        config: dict = {}

        command = self._command_edit.text().strip()
        if command:
            config["command"] = command

        # 解析 args
        args_text = self._args_edit.text().strip()
        if args_text:
            config["args"] = [a.strip() for a in args_text.split(",") if a.strip()]

        # 解析 env
        env_text = self._env_edit.toPlainText().strip()
        if env_text:
            env_dict: dict = {}
            for line in env_text.split("\n"):
                line = line.strip()
                if line and "=" in line:
                    key, _, value = line.partition("=")
                    env_dict[key.strip()] = value.strip()
            if env_dict:
                config["env"] = env_dict

        return config

    def set_name_readonly(self, readonly: bool) -> None:
        """编辑模式下锁定名称"""
        self._name_edit.setReadOnly(readonly)


class McpWidget(QWidget):
    """Claude Code MCP Server 管理"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._backend = None
        self._worker: Optional[McpWorker] = None
        self._mcp_data: dict = {}
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # --- 顶部工具栏 ---
        toolbar = QHBoxLayout()

        self._refresh_btn = QPushButton(self.tr("刷新"))
        self._refresh_btn.clicked.connect(self._on_refresh)
        toolbar.addWidget(self._refresh_btn)

        self._add_btn = QPushButton(self.tr("添加"))
        self._add_btn.clicked.connect(self._on_add)
        toolbar.addWidget(self._add_btn)

        self._edit_btn = QPushButton(self.tr("编辑"))
        self._edit_btn.clicked.connect(self._on_edit)
        toolbar.addWidget(self._edit_btn)

        self._delete_btn = QPushButton(self.tr("删除"))
        self._delete_btn.clicked.connect(self._on_delete)
        toolbar.addWidget(self._delete_btn)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        # --- MCP Server 表格 ---
        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels([
            self.tr("名称"), self.tr("Command"),
            self.tr("Args"), self.tr("状态")
        ])
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self._table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table)

        # --- 底部说明 ---
        hint_label = QLabel(self.tr(
            "MCP 配置文件路径: ~/.claude/mcp.json  |  "
            "选中行后可编辑或删除"
        ))
        hint_label.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(hint_label)

    def set_backend(self, backend) -> None:
        """设置 Backend"""
        self._backend = backend

    def refresh(self) -> None:
        """加载 MCP 配置（Tab 被选中时调用）"""
        self._load_mcp_config()

    def _load_mcp_config(self) -> None:
        """使用 QThread 后台加载 MCP 配置"""
        if not self._backend:
            return
        if self._worker and self._worker.isRunning():
            return
        self._refresh_btn.setEnabled(False)
        self._worker = McpWorker(self._backend, mode="load")
        self._worker.loaded.connect(self._on_mcp_loaded)
        self._worker.error.connect(self._on_worker_error)
        self._worker.finished.connect(lambda: self._refresh_btn.setEnabled(True))
        self._worker.start()

    def _on_mcp_loaded(self, config: dict) -> None:
        """MCP 配置加载完成回调"""
        try:
            self._mcp_data = config
            self._populate_table()
        except Exception as e:
            logger.error(f"填充 MCP 表格失败: {e}")

    def _populate_table(self) -> None:
        """将 MCP 配置填充到表格"""
        self._table.setRowCount(0)
        servers = self._mcp_data.get("mcpServers", {})
        if not isinstance(servers, dict):
            return

        self._table.setRowCount(len(servers))
        for row, (name, cfg) in enumerate(servers.items()):
            # 名称
            name_item = QTableWidgetItem(name)
            self._table.setItem(row, 0, name_item)

            # Command
            command = cfg.get("command", "") if isinstance(cfg, dict) else ""
            self._table.setItem(row, 1, QTableWidgetItem(str(command)))

            # Args
            args = cfg.get("args", []) if isinstance(cfg, dict) else []
            args_str = ", ".join(str(a) for a in args) if isinstance(args, list) else str(args)
            self._table.setItem(row, 2, QTableWidgetItem(args_str))

            # 状态
            status = self.tr("已配置") if command else self.tr("未知")
            status_item = QTableWidgetItem(status)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 3, status_item)

    def _on_worker_error(self, error_msg: str) -> None:
        """Worker 错误回调"""
        logger.error(f"MCP worker 错误: {error_msg}")
        QMessageBox.warning(
            self, self.tr("错误"),
            self.tr("操作失败: {}").format(error_msg)
        )

    def _on_refresh(self) -> None:
        """刷新按钮点击"""
        self._load_mcp_config()

    def _on_add(self) -> None:
        """添加 MCP Server"""
        dialog = McpEditDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            name = dialog.get_server_name()
            if not name:
                QMessageBox.warning(self, self.tr("警告"), self.tr("Server 名称不能为空"))
                return
            config = dialog.get_server_config()
            # 更新数据
            self._mcp_data.setdefault("mcpServers", {})[name] = config
            self._save_mcp_config()

    def _on_edit(self) -> None:
        """编辑选中的 MCP Server"""
        row = self._table.currentRow()
        if row < 0:
            QMessageBox.information(self, self.tr("提示"), self.tr("请先选中一行"))
            return

        name_item = self._table.item(row, 0)
        if not name_item:
            return
        server_name = name_item.text()
        servers = self._mcp_data.get("mcpServers", {})
        server_config = servers.get(server_name, {})

        dialog = McpEditDialog(self, server_name=server_name, server_config=server_config)
        dialog.set_name_readonly(True)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_config = dialog.get_server_config()
            self._mcp_data.setdefault("mcpServers", {})[server_name] = new_config
            self._save_mcp_config()

    def _on_delete(self) -> None:
        """删除选中的 MCP Server"""
        row = self._table.currentRow()
        if row < 0:
            QMessageBox.information(self, self.tr("提示"), self.tr("请先选中一行"))
            return

        name_item = self._table.item(row, 0)
        if not name_item:
            return
        server_name = name_item.text()

        reply = QMessageBox.question(
            self, self.tr("确认删除"),
            self.tr("确定要删除 MCP Server \"{}\" 吗？").format(server_name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            servers = self._mcp_data.get("mcpServers", {})
            servers.pop(server_name, None)
            self._save_mcp_config()

    def _save_mcp_config(self) -> None:
        """保存 MCP 配置到文件"""
        if not self._backend:
            QMessageBox.warning(self, self.tr("警告"), self.tr("未连接后端"))
            return
        if self._worker and self._worker.isRunning():
            return

        self._worker = McpWorker(self._backend, mode="save", config=self._mcp_data)
        self._worker.saved.connect(self._on_mcp_saved)
        self._worker.error.connect(self._on_worker_error)
        self._worker.start()

    def _on_mcp_saved(self, success: bool, message: str) -> None:
        """MCP 配置保存完成回调"""
        if success:
            # 刷新表格显示
            self._populate_table()
        else:
            QMessageBox.critical(
                self, self.tr("错误"),
                self.tr("保存 MCP 配置失败: {}").format(message)
            )
