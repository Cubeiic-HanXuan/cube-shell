"""
AI SSH 运维助手对话面板。

提供对话式交互 + 命令卡片混合模式的聊天界面，
作为 QWidget 可被嵌入 QDockWidget 作为侧边面板使用。
"""

from __future__ import annotations

import re
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextBrowser, QLineEdit, QPlainTextEdit,
    QPushButton, QLabel, QScrollArea, QFrame, QApplication, QSizePolicy
)
from PySide6.QtCore import Signal, Qt, Slot, QTimer, QSize, QEvent
from PySide6.QtGui import QFont, QTextCursor, QColor, QIcon

from .safety import RiskLevel
from .voice_input import VoiceInputManager


# ──────────────────────────── 风险等级颜色映射 ────────────────────────────

_RISK_COLORS = {
    RiskLevel.SAFE: "#4caf50",      # 绿色
    RiskLevel.LOW: "#2196f3",       # 蓝色
    RiskLevel.MEDIUM: "#ff9800",    # 橙色
    RiskLevel.HIGH: "#f44336",      # 红色
    RiskLevel.CRITICAL: "#b71c1c",  # 深红色
}

_RISK_LABELS = {
    RiskLevel.SAFE: "安全",
    RiskLevel.LOW: "低",
    RiskLevel.MEDIUM: "中",
    RiskLevel.HIGH: "高",
    RiskLevel.CRITICAL: "危险",
}


# ──────────────────────────── 命令卡片组件 ────────────────────────────────


class CommandCard(QFrame):
    """单条命令卡片，显示命令、风险等级、描述及操作按钮。"""

    execute_clicked = Signal(str)  # 点击"在终端执行"

    def __init__(self, cmd: str, description: str, risk_level: RiskLevel, parent=None):
        super().__init__(parent)
        self._cmd = cmd
        self._build_ui(cmd, description, risk_level)

    def _build_ui(self, cmd: str, description: str, risk_level: RiskLevel):
        self.setObjectName("CommandCard")
        color = _RISK_COLORS.get(risk_level, "#9e9e9e")
        label_text = _RISK_LABELS.get(risk_level, "未知")

        self.setStyleSheet(f"""
            #CommandCard {{
                border: 1px solid palette(mid);
                border-left: 3px solid {color};
                border-radius: 6px;
                padding: 8px;
                margin: 4px 8px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        # 第一行: 命令 + 风险等级标签
        top_row = QHBoxLayout()
        cmd_label = QLabel(cmd)
        cmd_label.setFont(QFont("Courier New", 12))
        cmd_label.setStyleSheet("font-weight: bold;")
        cmd_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        top_row.addWidget(cmd_label, 1)

        risk_tag = QLabel(f" {label_text} ")
        risk_tag.setStyleSheet(f"""
            background: {color};
            color: white;
            border-radius: 3px;
            padding: 1px 6px;
            font-size: 11px;
        """)
        risk_tag.setFixedHeight(20)
        top_row.addWidget(risk_tag)
        layout.addLayout(top_row)

        # 第二行: 描述
        if description:
            desc_label = QLabel(description)
            desc_label.setStyleSheet("font-size: 11px; color: palette(placeholderText);")
            desc_label.setWordWrap(True)
            layout.addWidget(desc_label)

        # 第三行: 操作按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        copy_btn = QPushButton("复制")
        copy_btn.setFixedHeight(24)
        copy_btn.setStyleSheet("""
            QPushButton {
                background: palette(button); border: none; border-radius: 4px;
                padding: 2px 10px; font-size: 11px;
            }
            QPushButton:hover { background: palette(mid); }
        """)
        copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_btn.clicked.connect(self._copy_cmd)
        btn_row.addWidget(copy_btn)

        exec_btn = QPushButton("在终端执行")
        exec_btn.setFixedHeight(24)
        exec_btn.setStyleSheet(f"""
            QPushButton {{
                background: {color}; color: white; border: none;
                border-radius: 4px; padding: 2px 10px; font-size: 11px;
            }}
            QPushButton:hover {{ opacity: 0.8; }}
        """)
        exec_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        exec_btn.clicked.connect(lambda: self.execute_clicked.emit(self._cmd))
        btn_row.addWidget(exec_btn)

        layout.addLayout(btn_row)

    def _copy_cmd(self):
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(self._cmd)


# ──────────────────────────── 深度思考可折叠面板 ────────────────────────────────


class _ThinkingWidget(QFrame):
    """AI 深度思考可折叠面板，显示思考过程和耗时。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ThinkingWidget")
        self._is_expanded = False  # 默认折叠
        self._elapsed = 0
        self._thinking_text = ""
        self._is_active = True  # 是否正在思考中

        self._build_ui()

        # 计时器
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 4, 8, 4)
        main_layout.setSpacing(0)

        # ─ 头部（可点击） ─
        self._header = QFrame()
        self._header.setCursor(Qt.PointingHandCursor)
        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(4, 4, 4, 4)
        header_layout.setSpacing(6)

        self._icon_label = QLabel("💭")
        self._icon_label.setStyleSheet("font-size: 14px;")
        header_layout.addWidget(self._icon_label)

        self._title_label = QLabel("深度思考 · 0s")
        self._title_label.setStyleSheet("font-size: 13px; font-weight: bold; color: palette(placeholderText);")
        header_layout.addWidget(self._title_label)

        header_layout.addStretch()

        self._arrow_label = QLabel("\u203a")  # 折叠状态用 ›，展开用 ˅
        self._arrow_label.setStyleSheet("font-size: 14px; color: palette(placeholderText);")
        header_layout.addWidget(self._arrow_label)

        main_layout.addWidget(self._header)

        # ─ 思考内容区（可折叠） ─
        self._content_frame = QFrame()
        self._content_frame.setVisible(False)  # 默认折叠
        content_layout = QVBoxLayout(self._content_frame)
        content_layout.setContentsMargins(24, 4, 8, 4)
        content_layout.setSpacing(0)

        self._content_label = QLabel("")
        self._content_label.setWordWrap(True)
        self._content_label.setStyleSheet("font-size: 12px; color: rgba(180, 180, 180, 0.85); line-height: 1.4;")
        self._content_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        content_layout.addWidget(self._content_label)

        main_layout.addWidget(self._content_frame)

        # 整体样式
        self.setStyleSheet("""
            #ThinkingWidget {
                border-radius: 8px;
                margin: 2px 8px;
            }
        """)

    def mousePressEvent(self, event):
        """点击头部区域切换展开/折叠。"""
        if self._header.geometry().contains(event.pos()):
            self._toggle_expanded()
        super().mousePressEvent(event)

    def _toggle_expanded(self):
        self._is_expanded = not self._is_expanded
        self._content_frame.setVisible(self._is_expanded)
        self._arrow_label.setText("\u02c5" if self._is_expanded else "\u203a")

    def _tick(self):
        self._elapsed += 1
        self._update_title()

    def _update_title(self):
        suffix = "..." if self._is_active else ""
        self._title_label.setText(f"深度思考 · {self._elapsed}s{suffix}")

    def append_thinking(self, text: str):
        """追加思考内容文本。"""
        if not text:
            return
        self._thinking_text += text
        # 显示思考内容（保留换行）
        display = self._thinking_text.replace("\n", "<br>")
        self._content_label.setText(display)

    def stop(self):
        """停止计时，标记思考结束。"""
        self._timer.stop()
        self._is_active = False
        self._update_title()
        # 如果没有思考内容，隐藏展开箭头
        if not self._thinking_text.strip():
            self._arrow_label.setVisible(False)
            self._header.setCursor(Qt.ArrowCursor)


# ──────────────────────────── 主面板 ────────────────────────────────────


class AIChatPanel(QWidget):
    """AI SSH 运维助手对话面板"""

    # 信号
    user_message_sent = Signal(str)         # 用户发送消息
    command_execute_requested = Signal(str)  # 请求执行单条命令
    stop_requested = Signal()               # 停止当前操作
    clear_requested = Signal()              # 清空对话

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(320)
        self.resize(380, 600)

        self._current_ai_bubble: Optional[QTextBrowser] = None
        self._current_ai_text: str = ""
        self._thinking_widget: Optional[_ThinkingWidget] = None

        # ─ 流式渲染节流 ─
        # 流式增量到达很快（每秒数十个 token），若每个增量都做
        # "全文 Markdown 重解析 + setHtml 全量重绘 + setFixedHeight + 滚动"
        # 会造成肉眼可见的闪烁与卡顿。用一个定时器把多次增量合并成
        # 一次渲染（约 60ms / 最多 ~16fps），流结束时再强制 flush 一次。
        self._render_dirty: bool = False
        self._last_bubble_height: int = 0
        self._render_timer = QTimer(self)
        self._render_timer.setInterval(60)
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._flush_ai_render)

        self._build_ui()

        # 语音输入管理器
        self._voice_manager = VoiceInputManager(parent=self)
        self._voice_manager.recording_started.connect(self._on_voice_recording_started)
        self._voice_manager.recording_stopped.connect(self._on_voice_recording_stopped)
        self._voice_manager.recognition_started.connect(self._on_voice_recognition_started)
        self._voice_manager.partial_text_recognized.connect(self._on_voice_partial_text)
        self._voice_manager.text_recognized.connect(self._on_voice_text_recognized)
        self._voice_manager.error_occurred.connect(self._on_voice_error)

    # ──── UI 构建 ────

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ─ 顶部状态栏 ─
        self._status_bar = QFrame()
        self._status_bar.setObjectName("StatusBar")
        status_layout = QVBoxLayout(self._status_bar)
        status_layout.setContentsMargins(12, 8, 12, 8)
        status_layout.setSpacing(2)

        self._status_label = QLabel("⚪ 未连接")
        self._status_label.setStyleSheet("font-size: 13px; font-weight: bold;")
        status_layout.addWidget(self._status_label)

        self._model_label = QLabel(self._build_model_label_text())
        self._model_label.setStyleSheet("font-size: 11px;")
        status_layout.addWidget(self._model_label)

        main_layout.addWidget(self._status_bar)

        # ─ 对话区域 ─
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll_area.setObjectName("ChatScrollArea")

        self._chat_container = QWidget()
        self._chat_layout = QVBoxLayout(self._chat_container)
        self._chat_layout.setContentsMargins(4, 8, 4, 8)
        self._chat_layout.setSpacing(8)
        self._chat_layout.addStretch()  # 使消息靠底

        self._scroll_area.setWidget(self._chat_container)
        main_layout.addWidget(self._scroll_area, 1)

        # ─ 输入区域 ─
        input_frame = QFrame()
        input_frame.setObjectName("inputFrame")
        input_vbox = QVBoxLayout(input_frame)
        input_vbox.setContentsMargins(8, 8, 8, 8)
        input_vbox.setSpacing(6)

        # 上层：多行输入框
        self._input_edit = QPlainTextEdit()
        self._input_edit.setPlaceholderText("输入运维需求，输入 '/' 获取更多能力")
        self._input_edit.setFixedHeight(80)
        self._input_edit.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self._input_edit.installEventFilter(self)
        input_vbox.addWidget(self._input_edit)

        # 下层：工具栏
        toolbar_layout = QHBoxLayout()
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(4)

        toolbar_layout.addStretch()

        # ✦ 提示词优化按钮
        self._optimize_btn = QPushButton()
        self._optimize_btn.setIcon(QIcon(":icons8-optimize-48.png"))
        self._optimize_btn.setIconSize(QSize(20, 20))
        self._optimize_btn.setFixedSize(32, 32)
        self._optimize_btn.setToolTip("优化提示词")
        self._optimize_btn.setStyleSheet("""
            QPushButton {
                border: none;
                border-radius: 8px;
            }
            QPushButton:hover { background: palette(midlight); }
        """)
        self._optimize_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._optimize_btn.clicked.connect(self._on_optimize_prompt)

        # 麦克风按钮
        self._mic_btn = QPushButton()
        self._mic_btn.setIcon(QIcon(":icons8-audio-48.png"))
        self._mic_btn.setIconSize(QSize(20, 20))
        self._mic_btn.setFixedSize(32, 32)
        self._mic_btn.setCheckable(True)
        self._mic_btn.setToolTip("语音输入（点击开始/停止录音）")
        self._mic_btn.setStyleSheet("""
            QPushButton {
                border: none;
                border-radius: 16px;
            }
            QPushButton:hover {
                background: palette(midlight);
            }
            QPushButton:checked {
                background: #F44336;
                border-color: #F44336;
            }
        """)
        self._mic_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mic_btn.clicked.connect(self._on_mic_clicked)

        # 发送按钮（绿色 ↑ 样式）
        self._send_btn = QPushButton("↑")
        self._send_btn.setFixedSize(32, 32)
        self._send_btn.setToolTip("发送 (Enter)")
        self._send_btn.setStyleSheet("""
            QPushButton {
                background: #4CAF50;
                color: white;
                border-radius: 8px;
                font-size: 18px;
                font-weight: bold;
            }
            QPushButton:hover { background: #43A047; }
            QPushButton:pressed { background: #388E3C; }
            QPushButton:disabled { background: palette(mid); color: palette(mid-light); }
        """)
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_btn.clicked.connect(self._on_send)

        # 停止按钮
        self._stop_btn = QPushButton("停止")
        self._stop_btn.setFixedSize(50, 32)
        self._stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._stop_btn.setVisible(False)
        self._stop_btn.clicked.connect(self._on_stop)

        toolbar_layout.addWidget(self._optimize_btn)
        toolbar_layout.addWidget(self._mic_btn)
        toolbar_layout.addWidget(self._send_btn)
        toolbar_layout.addWidget(self._stop_btn)

        input_vbox.addLayout(toolbar_layout)

        main_layout.addWidget(input_frame)

    # ──── 公共接口 ────

    def append_user_message(self, text: str):
        """显示用户消息气泡"""
        bubble = self._create_bubble(text, is_user=True)
        self._insert_widget(bubble)
        self._scroll_to_bottom()

    def append_ai_message(self, text: str):
        """显示 AI 回复消息（支持 Markdown 渲染）"""
        # 先结束上一轮可能仍在等待渲染的流式气泡，避免 pending flush 落到新气泡上
        self._finalize_ai_render()
        bubble = self._create_bubble(text, is_user=False)
        self._current_ai_bubble = bubble
        self._current_ai_text = text
        self._last_bubble_height = 0
        self._insert_widget(bubble)
        self._scroll_to_bottom()

    def append_ai_delta(self, reasoning: str, content: str):
        """流式追加 AI 回复增量（用于 streaming 模式）"""
        # reasoning 内容路由到思考面板
        if reasoning and self._thinking_widget is not None:
            self._thinking_widget.append_thinking(reasoning)

        # content 追加到 AI 气泡
        if not content:
            return

        if self._current_ai_bubble is None:
            # 创建新的 AI 气泡
            self._current_ai_text = ""
            self._last_bubble_height = 0
            bubble = self._create_bubble("", is_user=False)
            self._current_ai_bubble = bubble
            self._insert_widget(bubble)

        # 只累积文本，真正的渲染交给节流定时器合并处理，避免逐 token 全量重绘导致闪烁
        self._current_ai_text += content
        self._render_dirty = True
        if not self._render_timer.isActive():
            self._render_timer.start()

    def _flush_ai_render(self):
        """把累积的流式文本一次性渲染到当前 AI 气泡（节流后调用）。"""
        if not self._render_dirty or self._current_ai_bubble is None:
            return
        self._render_dirty = False

        html = self._render_markdown(self._current_ai_text)
        # 内联主题文字颜色
        text_color = self.palette().color(self.palette().ColorRole.Text).name()
        self._current_ai_bubble.setHtml(f'<div style="color:{text_color};">{html}</div>')
        # 更新文档宽度以适配当前面板尺寸
        available_width = self._get_bubble_available_width(is_user=False)
        self._current_ai_bubble.document().setTextWidth(available_width)
        # 仅在高度真正变化时才调整固定高度，避免每次都触发父布局 reflow 抖动
        new_height = max(36, self._current_ai_bubble.document().size().toSize().height() + 16)
        if new_height != self._last_bubble_height:
            self._last_bubble_height = new_height
            self._current_ai_bubble.setFixedHeight(new_height)
        self._scroll_to_bottom()

    def _finalize_ai_render(self):
        """结束当前 AI 气泡前调用：停止节流定时器并强制渲染最后一段内容，防止尾部丢失。"""
        self._render_timer.stop()
        if self._render_dirty:
            self._flush_ai_render()

    def append_command_card(self, cmd: str, description: str, risk_level: RiskLevel):
        """添加命令卡片组件"""
        card = CommandCard(cmd, description, risk_level, parent=self._chat_container)
        card.execute_clicked.connect(self.command_execute_requested.emit)
        self._finalize_ai_render()
        self._insert_widget(card)
        self._current_ai_bubble = None
        self._scroll_to_bottom()

    def append_execution_result(self, cmd: str, exit_code: int, output: str, description: str = ""):
        """添加命令执行结果"""
        frame = QFrame()
        frame.setObjectName("ExecResult")
        success = exit_code == 0
        border_color = "#4caf50" if success else "#f44336"
        frame.setStyleSheet(f"""
            #ExecResult {{
                border: 1px solid {border_color};
                border-radius: 6px;
                margin: 4px 8px;
                padding: 8px;
            }}
        """)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        # 状态行
        icon = "✅" if success else "❌"
        status_text = f"{icon} 执行{'成功' if success else '失败'} (exit_code: {exit_code})"
        status_label = QLabel(status_text)
        status_label.setStyleSheet(f"font-size: 12px; color: {border_color}; font-weight: bold;")
        layout.addWidget(status_label)

        # 命令说明（如果有）
        if description:
            desc_label = QLabel(f"# {description}")
            desc_label.setStyleSheet("font-size: 11px; color: #888; font-style: italic;")
            desc_label.setWordWrap(True)
            layout.addWidget(desc_label)

        # 命令（支持换行、可选中复制）
        cmd_label = QLabel(f"$ {cmd}")
        cmd_label.setFont(QFont("Courier New", 11))
        cmd_label.setWordWrap(True)
        cmd_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        cmd_label.setCursor(Qt.IBeamCursor)
        cmd_label.setStyleSheet("")
        layout.addWidget(cmd_label)

        # 输出（最多显示 20 行，可点击展开）
        if output:
            output_browser = QTextBrowser()
            output_browser.setFont(QFont("Courier New", 11))
            output_browser.setStyleSheet("""
                QTextBrowser {
                    background: #263238; color: #e0e0e0;
                    border-radius: 4px; padding: 6px;
                    border: none;
                }
            """)
            lines = output.splitlines()
            display_text = "\n".join(lines[:20])
            if len(lines) > 20:
                display_text += f"\n... (共 {len(lines)} 行)"
            output_browser.setPlainText(display_text)
            # 动态高度
            doc_height = min(200, max(40, len(lines[:20]) * 16 + 20))
            output_browser.setFixedHeight(doc_height)
            layout.addWidget(output_browser)

        self._finalize_ai_render()
        self._insert_widget(frame)
        self._current_ai_bubble = None
        self._scroll_to_bottom()

    def set_status(self, connected: bool, host: str = "", os_info: str = ""):
        """更新顶部状态栏"""
        if connected:
            self._status_label.setText(f"🟢 已连接 {host}")
        else:
            self._status_label.setText("⚪ 未连接")
        if os_info:
            self._model_label.setText(self._build_model_label_text(os_info))

    def set_thinking(self, is_thinking: bool):
        """设置 AI 思考中动画"""
        if is_thinking:
            if self._thinking_widget is None:
                self._thinking_widget = _ThinkingWidget(self._chat_container)
                self._insert_widget(self._thinking_widget)
                self._scroll_to_bottom()
            self._stop_btn.setVisible(True)
        else:
            if self._thinking_widget is not None:
                self._thinking_widget.stop()
                # 不再删除组件，保留为可折叠的已完成状态
            self._stop_btn.setVisible(False)
            self._finalize_ai_render()
            self._current_ai_bubble = None
            self._thinking_widget = None  # 释放引用，但组件保留在布局中

    def set_executing(self, is_executing: bool, progress_text: str = "",
                      current: int = 0, total: int = 0):
        """设置执行中状态，支持进度显示"""
        self._stop_btn.setVisible(is_executing)
        if is_executing:
            if current > 0 and total > 0:
                self._model_label.setText(f"执行中 [{current}/{total}] $ {progress_text}")
            elif progress_text:
                self._model_label.setText(f"执行中 $ {progress_text}")
            else:
                self._model_label.setText("命令执行中...")
        else:
            self._model_label.setText(self._build_model_label_text())

    def _build_model_label_text(self, os_info: str = "") -> str:
        """动态构造模型标签文本：从 prefs 读取当前配置的模型名。"""
        model_name = "GLM-4"
        try:
            from .prefs import load_ai_prefs
            prefs = load_ai_prefs()
            if prefs and getattr(prefs, "model", None):
                model_name = prefs.model
        except Exception:
            pass
        base = f"{model_name} | SSH 模式"
        if os_info:
            return f"{base} | {os_info}"
        return base

    def refresh_model_label(self):
        """外部在配置变更后调用，刷新顶部状态栏中的模型名称显示。"""
        if hasattr(self, "_model_label") and self._model_label is not None:
            self._model_label.setText(self._build_model_label_text())

    def update_command_output(self, output_line: str):
        """更新命令实时输出（显示在状态栏，用于下载进度等）"""
        if not output_line:
            return
        # 截取显示（状态栏空间有限）
        display = output_line[-80:] if len(output_line) > 80 else output_line
        self._model_label.setText(f"⬇ {display}")

    def append_task_summary(self, summary: str):
        """在聊天流中追加任务执行总结卡片"""
        frame = QFrame()
        frame.setObjectName("TaskSummary")

        # 根据内容判断颜色：包含"失败"用橙色，否则绿色
        if "失败" in summary:
            bg_color = "#fff3e0"    # 浅橙色背景
            border_color = "#ff9800"  # 橙色边框
            icon = "⚠️"
        else:
            bg_color = "#e8f5e9"    # 浅绿色背景
            border_color = "#4caf50"  # 绿色边框
            icon = "✅"

        frame.setStyleSheet(f"""
            #TaskSummary {{
                background: {bg_color};
                border: 1px solid {border_color};
                border-radius: 6px;
                margin: 6px 8px;
                padding: 10px 12px;
            }}
        """)

        layout = QHBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)

        label = QLabel(f"{icon} {summary}")
        label.setStyleSheet(f"font-size: 13px; color: #333; font-weight: bold; background: transparent;")
        label.setWordWrap(True)
        layout.addWidget(label)

        self._finalize_ai_render()
        self._insert_widget(frame)
        self._current_ai_bubble = None
        self._scroll_to_bottom()

    def append_skill_output(self, skill_name: str, output: str, is_error: bool) -> None:
        """显示 Skill 调用结果卡片。

        Args:
            skill_name: Skill 名称
            output: 执行输出或错误信息
            is_error: 是否为错误
        """
        # 结束当前流式气泡
        if self._current_ai_bubble is not None:
            self._finalize_ai_render()
            self._current_ai_bubble = None
            self._current_ai_text = ""

        # 构建卡片
        if is_error:
            bg_color = "rgba(198, 40, 40, 0.15)"
            border_color = "rgba(198, 40, 40, 0.4)"
            title = f"❌ {skill_name} 执行失败"
        else:
            bg_color = "rgba(46, 125, 50, 0.15)"
            border_color = "rgba(46, 125, 50, 0.4)"
            title = f"🔧 {skill_name}"

        escaped_output = (output.replace("&", "&amp;")
                          .replace("<", "&lt;")
                          .replace(">", "&gt;"))

        frame = QFrame()
        frame.setObjectName("SkillOutputCard")
        frame.setStyleSheet(f"""
            #SkillOutputCard {{
                background: {bg_color};
                border: 1px solid {border_color};
                border-radius: 6px;
                margin: 4px 8px;
                padding: 8px 12px;
            }}
        """)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        # 标题行
        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 12px; font-weight: bold; background: transparent;")
        layout.addWidget(title_label)

        # 输出内容（等宽字体，代码块样式）
        if escaped_output.strip():
            output_browser = QTextBrowser()
            output_browser.setFont(QFont("Courier New", 11))
            output_browser.setStyleSheet("""
                QTextBrowser {
                    background: rgba(0, 0, 0, 0.2);
                    color: #e0e0e0;
                    border-radius: 4px;
                    padding: 6px;
                    border: none;
                }
            """)
            output_browser.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            output_browser.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            output_browser.setPlainText(output)
            # 动态高度（最大 200px）
            lines = output.splitlines()
            doc_height = min(200, max(40, len(lines[:20]) * 16 + 20))
            output_browser.setFixedHeight(doc_height)
            layout.addWidget(output_browser)

        self._insert_widget(frame)
        self._scroll_to_bottom()

    def append_diagnosing_hint(self):
        """插入'正在自动诊断失败原因'提示"""
        self.append_ai_message("检测到命令执行失败，正在自动分析原因并生成修复方案...")

    # ──── 内部方法 ────

    def _on_send(self):
        text = self._input_edit.toPlainText().strip()
        if not text:
            return
        self._input_edit.clear()
        self.append_user_message(text)
        self.user_message_sent.emit(text)

    def eventFilter(self, obj, event):
        if obj is self._input_edit and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
                event.modifiers() & Qt.KeyboardModifier.ShiftModifier
            ):
                self._on_send()
                return True
        return super().eventFilter(obj, event)


    def _on_optimize_prompt(self):
        """优化当前输入框中的提示词（流式输出，逐步填入）"""
        text = self._input_edit.toPlainText().strip()
        if not text:
            return

        self._optimize_btn.setEnabled(False)

        import threading

        def _restore_btn():
            from PySide6.QtCore import QMetaObject, Qt as _Qt, Q_ARG
            QMetaObject.invokeMethod(
                self._optimize_btn, "setEnabled",
                _Qt.ConnectionType.QueuedConnection,
                Q_ARG(bool, True),
            )

        def _push_partial(partial: str):
            from PySide6.QtCore import QMetaObject, Qt as _Qt, Q_ARG
            QMetaObject.invokeMethod(
                self, "_apply_optimized_text",
                _Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, partial),
            )

        def _do_optimize():
            try:
                from openai import OpenAI
                from .prefs import load_ai_prefs, get_provider_preset
                from .secrets import get_ai_api_key

                prefs = load_ai_prefs()
                api_key = get_ai_api_key(prefs.provider)
                if not api_key:
                    _restore_btn()
                    return

                preset = get_provider_preset(prefs.provider)
                base_url = prefs.base_url or preset["base_url"]
                client = OpenAI(api_key=api_key, base_url=base_url)
                response = client.chat.completions.create(
                    model=prefs.model,
                    messages=[
                        {
                            "role": "system",
                            "content": "你是一个提示词优化专家，请把下面这段运维需求改写得更清晰、更具体，直接输出优化后的文本，不要任何解释。",
                        },
                        {"role": "user", "content": text},
                    ],
                    stream=True,
                    max_tokens=200,
                )

                result = ""
                for chunk in response:
                    try:
                        if chunk.choices and chunk.choices[0].delta.content:
                            result += chunk.choices[0].delta.content
                            _push_partial(result)
                    except Exception:
                        continue
            except Exception:
                pass
            finally:
                _restore_btn()

        threading.Thread(target=_do_optimize, daemon=True).start()

    @Slot(str)
    def _apply_optimized_text(self, text: str):
        """在主线程中将优化后的文本填入输入框（流式分段更新）"""
        if not text:
            return
        self._input_edit.setPlainText(text)
        cursor = self._input_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._input_edit.setTextCursor(cursor)

    def _on_mic_clicked(self):
        """麦克风按钮点击。"""
        self._voice_manager.toggle_recording()

    def _on_voice_recording_started(self):
        """录音开始。"""
        self._mic_btn.setChecked(True)
        self._mic_btn.setToolTip("录音中... 点击停止")
        self._input_edit.clear()  # 清空输入框准备接收实时文字
        self._input_edit.setPlaceholderText("🔴 正在听...")

    def _on_voice_recording_stopped(self):
        """录音停止。"""
        self._mic_btn.setChecked(False)
        self._mic_btn.setToolTip("语音输入（点击开始/停止录音）")
        self._input_edit.setPlaceholderText("正在完成识别...")

    def _on_voice_recognition_started(self):
        """开始识别。"""
        self._input_edit.setPlaceholderText("正在识别语音...")

    def _on_voice_partial_text(self, text: str):
        """实时语音识别增量更新输入框。"""
        self._input_edit.setPlainText(text)
        cursor = self._input_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._input_edit.setTextCursor(cursor)

    def _on_voice_text_recognized(self, text: str):
        """语音识别完成，设置最终文本。"""
        self._input_edit.setPlaceholderText("输入运维需求提示词")
        if text:
            self._input_edit.setPlainText(text)
            cursor = self._input_edit.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self._input_edit.setTextCursor(cursor)
            self._input_edit.setFocus()

    def _on_voice_error(self, error_msg: str):
        """语音输入错误。"""
        self._mic_btn.setChecked(False)
        self._input_edit.setPlaceholderText("输入运维需求提示词")
        # 在面板中显示错误提示
        self.append_ai_message(f"🎤 {error_msg}")

    def _on_stop(self):
        self.stop_requested.emit()

    def _insert_widget(self, widget: QWidget):
        """在 chat_layout 的 stretch 之前插入组件。"""
        count = self._chat_layout.count()
        # 插入到 stretch 前面
        self._chat_layout.insertWidget(count - 1, widget)

    def _scroll_to_bottom(self):
        """延迟滚动到底部，确保布局更新后再滚动。"""
        QTimer.singleShot(50, self._do_scroll)

    def _do_scroll(self):
        vbar = self._scroll_area.verticalScrollBar()
        if vbar:
            vbar.setValue(vbar.maximum())

    def resizeEvent(self, event):
        """面板大小变化时重新调整所有气泡的文档宽度和高度。"""
        super().resizeEvent(event)
        QTimer.singleShot(0, self._relayout_bubbles)

    def _relayout_bubbles(self):
        """重新计算所有气泡的宽度和高度。"""
        available_width_ai = self._get_bubble_available_width(is_user=False)
        available_width_user = self._get_bubble_available_width(is_user=True)

        for i in range(self._chat_layout.count()):
            item = self._chat_layout.itemAt(i)
            if item is None:
                continue
            widget = item.widget()
            if isinstance(widget, QTextBrowser):
                # 判断是用户消息还是 AI 消息（通过 margin 样式或位置）
                style = widget.styleSheet()
                if "40px 2px 8px" in style:
                    # AI 消息 margin 格式: "2px 40px 2px 8px"
                    w = available_width_ai
                else:
                    w = available_width_user
                widget.document().setTextWidth(w)
                doc_height = widget.document().size().toSize().height() + 16
                widget.setFixedHeight(max(36, doc_height))

    def _get_bubble_available_width(self, is_user: bool = False) -> float:
        """计算气泡内文档的可用宽度。"""
        # 滚动区域 viewport 宽度
        viewport_w = self._scroll_area.viewport().width()
        if viewport_w <= 0:
            viewport_w = self.width() - 20  # fallback
        if viewport_w <= 0:
            viewport_w = 300  # 最终 fallback

        # 减去 chat_layout 的左右 margins (4+4)
        viewport_w -= 8
        # 减去气泡样式中的 margin（用户消息: 8+40, AI消息: 40+8）和 padding (12+12)
        if is_user:
            viewport_w -= (8 + 40 + 24)
        else:
            viewport_w -= (40 + 8 + 24)

        return max(200, viewport_w)

    def _create_bubble(self, text: str, is_user: bool) -> QTextBrowser:
        """创建消息气泡。"""
        bubble = QTextBrowser()
        bubble.setOpenExternalLinks(True)
        bubble.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        bubble.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        bubble.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        bubble.setFont(QFont("sans-serif", 13))

        # 使用 palette 获取主题自适应颜色
        palette = self.palette()
        if is_user:
            # 用户消息：使用 highlight 色的低透明度版本
            highlight = palette.color(palette.ColorRole.Highlight)
            bg_color = QColor(highlight)
            bg_color.setAlpha(30)
            bg_hex = f"rgba({bg_color.red()}, {bg_color.green()}, {bg_color.blue()}, 0.15)"
            margin = "2px 8px 2px 40px"
        else:
            # AI 消息：使用 Window 色的半透明版本（避免 AlternateBase 在暗色主题返回白色）
            window_color = palette.color(palette.ColorRole.Window)
            bg_hex = f"rgba({window_color.red()}, {window_color.green()}, {window_color.blue()}, 0.5)"
            margin = "2px 40px 2px 8px"

        bubble.setStyleSheet(f"""
            QTextBrowser {{
                background: {bg_hex};
                border-radius: 8px;
                padding: 8px 12px;
                border: none;
                margin: {margin};
            }}
        """)

        # 通过 palette 获取当前主题文字颜色
        theme_text_color = palette.color(palette.ColorRole.Text).name()

        html = self._render_markdown(text) if not is_user else self._escape_html(text)
        # 直接在 HTML 中内联文字颜色（QPalette 对 QTextBrowser HTML 渲染不可靠）
        bubble.setHtml(f'<div style="color:{theme_text_color};">{html}</div>')

        # 根据滚动区域实际可用宽度计算文档宽度
        available_width = self._get_bubble_available_width(is_user)
        bubble.document().setTextWidth(available_width)
        doc_height = bubble.document().size().toSize().height() + 16
        bubble.setFixedHeight(max(36, doc_height))

        return bubble

    @staticmethod
    def _escape_html(text: str) -> str:
        """转义 HTML 特殊字符。"""
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br>")
        )

    @staticmethod
    def _render_markdown(text: str) -> str:
        """简易 Markdown → HTML 渲染，支持标题、表格、列表、代码块等常用语法。"""
        if not text:
            return ""

        # 先转义基础 HTML 字符
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        # 代码块 ```...```
        def _code_block_repl(m):
            code = m.group(1).strip()
            return f'<pre style="background:#263238;color:#e0e0e0;padding:8px;border-radius:4px;font-family:Courier New;font-size:12px;overflow-x:auto;white-space:pre-wrap;margin:6px 0;">{code}</pre>'

        text = re.sub(r"```(?:\w*)\n?(.*?)```", _code_block_repl, text, flags=re.DOTALL)

        # 行内代码 `...`
        text = re.sub(
            r"`([^`]+)`",
            r'<code style="background:rgba(128,128,128,0.2);padding:1px 4px;border-radius:3px;font-family:Courier New;font-size:12px;">\1</code>',
            text,
        )

        # 粗体 **...**
        text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)

        # 斜体 *...*
        text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)

        # 按行处理：标题、表格、列表
        lines = text.split("\n")
        result_lines = []
        in_ul = False
        in_ol = False
        in_table = False
        table_rows = []

        for line in lines:
            stripped = line.strip()

            # 跳过 <pre> 块内的内容（已被处理）
            if '<pre ' in line or '</pre>' in line:
                if in_ul:
                    result_lines.append("</ul>")
                    in_ul = False
                if in_ol:
                    result_lines.append("</ol>")
                    in_ol = False
                if in_table:
                    result_lines.append(AIChatPanel._build_table_html(table_rows))
                    table_rows = []
                    in_table = False
                result_lines.append(line)
                continue

            # 表格行检测（以 | 开头和结尾）
            if stripped.startswith("|") and stripped.endswith("|"):
                if in_ul:
                    result_lines.append("</ul>")
                    in_ul = False
                if in_ol:
                    result_lines.append("</ol>")
                    in_ol = False
                # 跳过分隔行（如 |---|---|---|）
                if re.match(r'^\|[\s\-:|]+\|$', stripped):
                    in_table = True
                    continue
                table_rows.append(stripped)
                in_table = True
                continue
            else:
                if in_table:
                    result_lines.append(AIChatPanel._build_table_html(table_rows))
                    table_rows = []
                    in_table = False

            # 水平分隔线 --- *** ___
            hr_match = re.match(r'^(\-{3,}|\*{3,}|_{3,})$', stripped)
            if hr_match:
                if in_ul:
                    result_lines.append("</ul>")
                    in_ul = False
                if in_ol:
                    result_lines.append("</ol>")
                    in_ol = False
                result_lines.append('<hr style="margin:2px 0;border:none;border-top:1px solid rgba(128,128,128,0.3);">')
                continue

            # 标题 # ## ### ####
            header_match = re.match(r'^(#{1,4})\s+(.+)$', stripped)
            if header_match:
                if in_ul:
                    result_lines.append("</ul>")
                    in_ul = False
                if in_ol:
                    result_lines.append("</ol>")
                    in_ol = False
                level = len(header_match.group(1))
                header_text = header_match.group(2)
                sizes = {1: '18px', 2: '16px', 3: '14px', 4: '13px'}
                font_size = sizes.get(level, '13px')
                result_lines.append(
                    f'<p style="font-size:{font_size};font-weight:bold;margin:1px 0 1px 0;">{header_text}</p>'
                )
                continue

            # 无序列表 - ...
            if stripped.startswith("- ") or stripped.startswith("• "):
                if in_ol:
                    result_lines.append("</ol>")
                    in_ol = False
                if not in_ul:
                    result_lines.append("<ul style='margin:1px 0;padding-left:20px;'>")
                    in_ul = True
                item_text = stripped[2:]
                result_lines.append(f"<li>{item_text}</li>")
                continue

            # 有序列表 1. 2. 3.
            ol_match = re.match(r'^(\d+)\.\s+(.+)$', stripped)
            if ol_match:
                if in_ul:
                    result_lines.append("</ul>")
                    in_ul = False
                if not in_ol:
                    result_lines.append("<ol style='margin:1px 0;padding-left:20px;'>")
                    in_ol = True
                result_lines.append(f"<li>{ol_match.group(2)}</li>")
                continue

            # 普通行
            if in_ul:
                result_lines.append("</ul>")
                in_ul = False
            if in_ol:
                result_lines.append("</ol>")
                in_ol = False
            result_lines.append(line)

        # 关闭未结束的列表/表格
        if in_ul:
            result_lines.append("</ul>")
        if in_ol:
            result_lines.append("</ol>")
        if in_table:
            result_lines.append(AIChatPanel._build_table_html(table_rows))

        text = "\n".join(result_lines)

        # 换行：不在 <pre>/<table>/<ul>/<ol> 块内的换行转为 <br>
        parts = re.split(r"(<pre.*?</pre>|<table.*?</table>|<ul.*?</ul>|<ol.*?</ol>)", text, flags=re.DOTALL)
        for i, part in enumerate(parts):
            if not (part.startswith("<pre") or part.startswith("<table") or
                    part.startswith("<ul") or part.startswith("<ol")):
                parts[i] = part.replace("\n", "<br>")
        text = "".join(parts)

        return text

    @staticmethod
    def _build_table_html(rows: list[str]) -> str:
        """将 Markdown 表格行转换为 HTML 表格。"""
        if not rows:
            return ""

        html = '<table style="border-collapse:collapse;margin:6px 0;width:100%;font-size:12px;">'

        for i, row in enumerate(rows):
            cells = [c.strip() for c in row.strip("|").split("|")]
            tag = "th" if i == 0 else "td"
            cell_style = (
                'style="border:1px solid rgba(128,128,128,0.3);padding:4px 8px;'
                + ('font-weight:bold;background:rgba(128,128,128,0.1);"' if i == 0 else '"')
            )
            html += "<tr>"
            for cell in cells:
                html += f"<{tag} {cell_style}>{cell}</{tag}>"
            html += "</tr>"

        html += "</table>"
        return html
