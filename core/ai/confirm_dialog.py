"""
命令确认对话框模块。

在 AI 建议执行命令前，弹出对话框让用户确认。
支持显示命令列表、风险标签颜色标注、三种操作模式（全部执行/逐条确认/取消）。
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QLineEdit, QWidget, QMessageBox,
)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QColor, QFont

from .safety import RiskLevel, SafetyCheckResult


# ──────────────────────────── 风险颜色映射 ────────────────────────────

_RISK_COLORS: dict[RiskLevel, str] = {
    RiskLevel.SAFE: "#4CAF50",
    RiskLevel.LOW: "#2196F3",
    RiskLevel.MEDIUM: "#FF9800",
    RiskLevel.HIGH: "#F44336",
    RiskLevel.CRITICAL: "#B71C1C",
}

_RISK_LABELS: dict[RiskLevel, str] = {
    RiskLevel.SAFE: "安全",
    RiskLevel.LOW: "低",
    RiskLevel.MEDIUM: "中",
    RiskLevel.HIGH: "高",
    RiskLevel.CRITICAL: "危险",
}

# 风险等级排序权重（用于取最大值）
_RISK_ORDER: dict[RiskLevel, int] = {
    RiskLevel.SAFE: 0,
    RiskLevel.LOW: 1,
    RiskLevel.MEDIUM: 2,
    RiskLevel.HIGH: 3,
    RiskLevel.CRITICAL: 4,
}


# ──────────────────────────── 命令列表项组件 ────────────────────────────


class _CommandItemWidget(QWidget):
    """单条命令的自定义列表项 Widget。"""

    def __init__(self, index: int, cmd_info: dict, parent=None):
        super().__init__(parent)
        self._setup_ui(index, cmd_info)

    def _setup_ui(self, index: int, cmd_info: dict):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        # 序号
        index_label = QLabel(f"{index}.")
        index_label.setFixedWidth(24)
        layout.addWidget(index_label)

        # 命令文本（等宽字体）
        cmd_text = cmd_info.get("cmd", "")
        cmd_label = QLabel(cmd_text)
        mono_font = QFont("Courier New", 11)
        mono_font.setStyleHint(QFont.StyleHint.Monospace)
        cmd_label.setFont(mono_font)
        cmd_label.setWordWrap(True)
        layout.addWidget(cmd_label, 1)

        # 风险等级标签
        risk_level: RiskLevel = cmd_info.get("risk_level", RiskLevel.LOW)
        color = _RISK_COLORS.get(risk_level, "#2196F3")
        label_text = _RISK_LABELS.get(risk_level, "低")
        risk_label = QLabel(f"[{label_text}]")
        risk_label.setStyleSheet(
            f"color: {color}; font-weight: bold; padding: 0 4px;"
        )
        layout.addWidget(risk_label)

    def sizeHint(self):
        """提供合理的尺寸提示。"""
        hint = super().sizeHint()
        hint.setHeight(max(hint.height(), 36))
        return hint


# ──────────────────────────── 主对话框 ────────────────────────────────


class CommandConfirmDialog(QDialog):
    """命令确认对话框 - 用户确认 AI 建议的命令。"""

    # 信号
    commands_approved = Signal(list)   # 全部批准执行
    command_step = Signal(list)        # 逐条确认模式
    commands_cancelled = Signal()      # 取消全部

    def __init__(self, commands: list[dict], parent=None):
        """
        Args:
            commands: 命令列表，每项为 dict:
                {
                    "cmd": "sudo systemctl restart nginx",
                    "description": "重启 Nginx 服务",
                    "risk_level": RiskLevel.MEDIUM,
                    "safety_result": SafetyCheckResult(...),
                }
        """
        super().__init__(parent)
        self._commands = commands
        self._max_risk = self._compute_max_risk()
        self._setup_ui()

    # ──────────── UI 构建 ──────────────

    def _setup_ui(self):
        self.setWindowTitle("AI 命令确认")
        self.setMinimumWidth(500)
        self.setModal(True)

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(16, 16, 16, 16)

        # 顶部提示
        header = QLabel("⚠️  AI 建议执行以下命令:")
        header_font = QFont()
        header_font.setPointSize(13)
        header_font.setBold(True)
        header.setFont(header_font)
        main_layout.addWidget(header)

        # 命令列表
        self._list_widget = QListWidget()
        self._list_widget.setAlternatingRowColors(True)
        self._populate_commands()
        main_layout.addWidget(self._list_widget)

        # 整体风险等级
        risk_color = _RISK_COLORS.get(self._max_risk, "#2196F3")
        risk_text = _RISK_LABELS.get(self._max_risk, "低")
        risk_reason = self._get_risk_reason()
        risk_info = QLabel(
            f'风险等级: <span style="color:{risk_color}; font-weight:bold;">'
            f'●{risk_text}</span>  ({risk_reason})'
        )
        risk_info.setTextFormat(Qt.TextFormat.RichText)
        main_layout.addWidget(risk_info)

        # 描述信息（如有）
        descriptions = [
            cmd.get("description", "") for cmd in self._commands if cmd.get("description")
        ]
        if descriptions:
            desc_text = "; ".join(descriptions[:3])
            desc_label = QLabel(f"说明: {desc_text}")
            desc_label.setStyleSheet("color: gray;")
            desc_label.setWordWrap(True)
            main_layout.addWidget(desc_label)

        # 二次确认区域（初始隐藏）
        self._confirm_widget = QWidget()
        confirm_layout = QHBoxLayout(self._confirm_widget)
        confirm_layout.setContentsMargins(0, 8, 0, 0)
        confirm_hint = QLabel('⚠️ 高风险操作！请输入 "CONFIRM" 以确认执行:')
        confirm_hint.setStyleSheet("color: #F44336; font-weight: bold;")
        confirm_layout.addWidget(confirm_hint)
        self._confirm_input = QLineEdit()
        self._confirm_input.setPlaceholderText("输入 CONFIRM")
        self._confirm_input.setMaximumWidth(140)
        self._confirm_input.returnPressed.connect(self._on_confirm_input)
        confirm_layout.addWidget(self._confirm_input)
        self._confirm_btn = QPushButton("确认")
        self._confirm_btn.clicked.connect(self._on_confirm_input)
        confirm_layout.addWidget(self._confirm_btn)
        self._confirm_widget.setVisible(False)
        main_layout.addWidget(self._confirm_widget)

        # 底部按钮
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        self._btn_execute = QPushButton("全部执行")
        self._btn_execute.setMinimumHeight(32)
        self._btn_execute.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; "
            "border-radius: 4px; padding: 4px 16px; }"
            "QPushButton:hover { background-color: #388E3C; }"
        )
        self._btn_execute.clicked.connect(self._on_execute_all)
        btn_layout.addWidget(self._btn_execute)

        self._btn_step = QPushButton("逐条确认")
        self._btn_step.setMinimumHeight(32)
        self._btn_step.setStyleSheet(
            "QPushButton { background-color: #2196F3; color: white; "
            "border-radius: 4px; padding: 4px 16px; }"
            "QPushButton:hover { background-color: #1976D2; }"
        )
        self._btn_step.clicked.connect(self._on_step_mode)
        btn_layout.addWidget(self._btn_step)

        self._btn_cancel = QPushButton("取消")
        self._btn_cancel.setMinimumHeight(32)
        self._btn_cancel.setStyleSheet(
            "QPushButton { border: 1px solid #999; border-radius: 4px; "
            "padding: 4px 16px; }"
            "QPushButton:hover { background-color: #eee; }"
        )
        self._btn_cancel.clicked.connect(self._on_cancel)
        btn_layout.addWidget(self._btn_cancel)

        main_layout.addLayout(btn_layout)

    def _populate_commands(self):
        """填充命令列表。"""
        for i, cmd_info in enumerate(self._commands, start=1):
            item = QListWidgetItem(self._list_widget)
            widget = _CommandItemWidget(i, cmd_info)
            item.setSizeHint(widget.sizeHint())
            self._list_widget.addItem(item)
            self._list_widget.setItemWidget(item, widget)

    # ──────────── 按钮响应 ──────────────

    def _on_execute_all(self):
        """全部执行按钮点击。"""
        if self._max_risk == RiskLevel.HIGH:
            self._show_high_risk_confirm()
        else:
            self.commands_approved.emit(self._commands)
            self.accept()

    def _on_step_mode(self):
        """逐条确认模式。"""
        self.command_step.emit(self._commands)
        self.accept()

    def _on_cancel(self):
        """取消按钮。"""
        self.commands_cancelled.emit()
        self.reject()

    # ──────────── 高风险二次确认 ──────────────

    def _show_high_risk_confirm(self):
        """显示高风险二次确认输入框。"""
        self._confirm_widget.setVisible(True)
        self._confirm_input.setFocus()
        self._btn_execute.setEnabled(False)

    def _on_confirm_input(self):
        """用户在二次确认输入框中按回车或点击确认。"""
        if self._confirm_input.text().strip() == "CONFIRM":
            self.commands_approved.emit(self._commands)
            self.accept()
        else:
            self._confirm_input.setStyleSheet("border: 1px solid #F44336;")
            self._confirm_input.setPlaceholderText("请输入 CONFIRM")
            self._confirm_input.clear()

    # ──────────── 辅助方法 ──────────────

    def _compute_max_risk(self) -> RiskLevel:
        """计算所有命令中的最高风险等级。"""
        if not self._commands:
            return RiskLevel.SAFE
        return max(
            (cmd.get("risk_level", RiskLevel.LOW) for cmd in self._commands),
            key=lambda r: _RISK_ORDER.get(r, 0),
        )

    def _get_risk_reason(self) -> str:
        """获取最高风险等级的原因描述。"""
        max_risk = self._max_risk
        for cmd_info in self._commands:
            if cmd_info.get("risk_level") == max_risk:
                safety_result: SafetyCheckResult | None = cmd_info.get("safety_result")
                if safety_result and safety_result.reason:
                    return safety_result.reason
                desc = cmd_info.get("description", "")
                if desc:
                    return desc
        return "AI 建议操作"


# ──────────────────────── 单条命令确认对话框 ────────────────────────


class SingleCommandConfirmDialog(QDialog):
    """单条命令确认对话框 - 逐条审批模式中的单步弹窗。"""

    def __init__(self, cmd_info: dict, index: int, total: int, parent=None):
        """
        Args:
            cmd_info: 命令信息 dict
            index: 当前命令序号（1-based）
            total: 命令总数
            parent: 父窗口
        """
        super().__init__(parent)
        self._cmd_info = cmd_info
        self.abort_all = False  # 是否终止全部后续命令
        self._setup_ui(index, total)

    def _setup_ui(self, index: int, total: int):
        self.setWindowTitle(f"逐条确认 ({index}/{total})")
        self.setMinimumWidth(450)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # 进度提示
        progress_label = QLabel(f"命令 {index} / {total}")
        progress_label.setStyleSheet("color: gray; font-size: 12px;")
        layout.addWidget(progress_label)

        # 命令内容
        cmd_text = self._cmd_info.get("cmd", "")
        cmd_label = QLabel(cmd_text)
        mono_font = QFont("Courier New", 12)
        mono_font.setStyleHint(QFont.StyleHint.Monospace)
        cmd_label.setFont(mono_font)
        cmd_label.setWordWrap(True)
        cmd_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        cmd_label.setStyleSheet(
            "background: palette(base); border: 1px solid palette(mid); "
            "border-radius: 4px; padding: 8px;"
        )
        layout.addWidget(cmd_label)

        # 描述
        description = self._cmd_info.get("description", "")
        if description:
            desc_label = QLabel(f"说明: {description}")
            desc_label.setStyleSheet("color: gray;")
            desc_label.setWordWrap(True)
            layout.addWidget(desc_label)

        # 风险等级
        risk_level = self._cmd_info.get("risk_level", RiskLevel.LOW)
        color = _RISK_COLORS.get(risk_level, "#2196F3")
        label_text = _RISK_LABELS.get(risk_level, "低")
        risk_label = QLabel(f'风险: <span style="color:{color}; font-weight:bold;">●{label_text}</span>')
        risk_label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(risk_label)

        # 安全检查警告
        safety = self._cmd_info.get("safety", {})
        warnings = safety.get("warnings", [])
        if warnings:
            for w in warnings[:3]:
                warn_label = QLabel(f"⚠️ {w}")
                warn_label.setStyleSheet("color: #FF9800; font-size: 11px;")
                warn_label.setWordWrap(True)
                layout.addWidget(warn_label)

        # 按钮区域
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        btn_execute = QPushButton("✓ 执行此条")
        btn_execute.setMinimumHeight(32)
        btn_execute.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; "
            "border-radius: 4px; padding: 4px 16px; }"
            "QPushButton:hover { background-color: #388E3C; }"
        )
        btn_execute.clicked.connect(self.accept)
        btn_layout.addWidget(btn_execute)

        btn_skip = QPushButton("⏭ 跳过")
        btn_skip.setMinimumHeight(32)
        btn_skip.setStyleSheet(
            "QPushButton { background-color: #FF9800; color: white; "
            "border-radius: 4px; padding: 4px 16px; }"
            "QPushButton:hover { background-color: #F57C00; }"
        )
        btn_skip.clicked.connect(self.reject)
        btn_layout.addWidget(btn_skip)

        btn_abort = QPushButton("✕ 终止全部")
        btn_abort.setMinimumHeight(32)
        btn_abort.setStyleSheet(
            "QPushButton { border: 1px solid #F44336; color: #F44336; "
            "border-radius: 4px; padding: 4px 16px; }"
            "QPushButton:hover { background-color: #FFEBEE; }"
        )
        btn_abort.clicked.connect(self._on_abort)
        btn_layout.addWidget(btn_abort)

        layout.addLayout(btn_layout)

    def _on_abort(self):
        """终止全部后续命令。"""
        self.abort_all = True
        self.reject()
