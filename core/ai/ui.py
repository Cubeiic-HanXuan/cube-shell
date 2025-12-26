"""
AI 相关 UI 组件与交互入口。

该模块包含两类能力：
1) 设置界面：保存非敏感偏好到 `ai.json`，敏感 Key 通过系统钥匙串保存；
2) 输出界面：启动后台线程进行流式生成，并提供复制/插入/远程执行等动作。
"""

import threading
import html
import re
from functools import lru_cache

from PySide6.QtCore import QMetaObject, Qt, Q_ARG, Slot, QTimer
from PySide6.QtGui import QPalette, QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QToolButton,
    QWidget,
    QVBoxLayout,
)

from function import util

from .prefs import AIUserPrefs, load_ai_prefs, save_ai_prefs
from .secrets import set_ai_api_key
from .worker import AIChatWorker


@lru_cache(maxsize=16)
def _code_css(style: str) -> str:
    try:
        from pygments.formatters import HtmlFormatter

        formatter = HtmlFormatter(style=style)
        return formatter.get_style_defs(".highlight")
    except Exception:
        return ""


@lru_cache(maxsize=64)
def _base_css(
    text_color: str,
    link_color: str,
    page_bg: str,
    block_bg: str,
    block_fg: str,
    inline_bg: str,
    inline_border: str,
    code_border: str,
    bar_bg: str,
    bar_fg: str,
    lineno_bg: str,
    lineno_fg: str,
    quote_bg: str,
    quote_border: str,
) -> str:
    return f"""
    html, body {{ margin: 0; padding: 0; background: {page_bg}; }}
    body {{ background: {page_bg}; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", Arial, sans-serif; }}
    a {{ color: {link_color}; }}
    pre, code {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace; }}
    pre {{ background: {block_bg}; color: {block_fg}; padding: 12px 14px; border-radius: 10px; border: 1px solid {code_border}; overflow-x: auto; }}
    .md {{ font-size: 13px; line-height: 1.55; color: {text_color}; background: {page_bg}; margin: 0; padding: 0; }}
    .md h1, .md h2, .md h3 {{ margin: 10px 0 8px; }}
    .md p {{ margin: 0; }}
    .md ul, .md ol {{ margin: 6px 0 6px 18px; }}
    .md code {{ background: {inline_bg}; border: 1px solid {inline_border}; padding: 1px 5px; border-radius: 6px; }}
    .md blockquote {{ margin: 8px 0; padding: 6px 10px; border-left: 3px solid {quote_border}; background: {quote_bg}; border-radius: 8px; }}
    .codewrap {{ margin: 10px 0; border: 1px solid {code_border}; border-radius: 10px; overflow: hidden; background: {block_bg}; }}
    .codewrap__bar {{ display: flex; align-items: center; gap: 8px; padding: 6px 10px; background: {bar_bg}; color: {bar_fg}; border-bottom: 1px solid {code_border}; }}
    .codewrap__lang {{ font-size: 12px; letter-spacing: 0.2px; opacity: 0.92; }}
    .codewrap__body {{ overflow-x: auto; }}
    .highlight {{ background: transparent !important; }}
    .highlight pre {{ background: transparent !important; }}
    .codewrap .highlight {{ margin: 0; background: transparent !important; }}
    .codewrap table.highlighttable {{ width: 100%; border-collapse: separate; border-spacing: 0; }}
    .codewrap table.highlighttable td {{ padding: 0; vertical-align: top; }}
    .codewrap table.highlighttable td.linenos {{ background: {lineno_bg}; border-right: 1px solid {code_border}; user-select: none; }}
    .codewrap table.highlighttable td.linenos pre {{ padding: 12px 10px; margin: 0; color: {lineno_fg}; background: transparent; border: 0; }}
    .codewrap table.highlighttable td.code pre {{ padding: 12px 14px; margin: 0; background: transparent; border: 0; }}
    .highlight pre {{ margin: 0; }}
    """


@lru_cache(maxsize=8)
def _pick_pygments_style(is_light: bool) -> str:
    try:
        from pygments.formatters import HtmlFormatter

        candidates = (
            ["rrt", "default"]
            if is_light
            else ["monokai"]
        )
        for name in candidates:
            try:
                HtmlFormatter(style=name)
                return name
            except Exception:
                continue
        return "default"
    except Exception:
        return "default"


def _extract_body(html_text: str) -> str:
    m = re.search(r"<body[^>]*>(.*)</body>", html_text, flags=re.IGNORECASE | re.DOTALL)
    if not m:
        return html_text
    return m.group(1)


def _split_fenced_code_blocks(markdown_text: str):
    lines = (markdown_text or "").splitlines()
    parts = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            lang = line[3:].strip()
            i += 1
            code_lines = []
            while i < len(lines) and not lines[i].startswith("```"):
                code_lines.append(lines[i])
                i += 1
            if i < len(lines) and lines[i].startswith("```"):
                i += 1
            parts.append(("code", lang, "\n".join(code_lines)))
        else:
            text_lines = [line]
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                text_lines.append(lines[i])
                i += 1
            parts.append(("text", "\n".join(text_lines)))
    return parts


def _highlight_code_to_html(code: str, lang: str, style: str) -> str:
    code = code or ""
    lang = (lang or "").strip().lower()
    try:
        from pygments import highlight
        from pygments.formatters import HtmlFormatter
        from pygments.lexers import get_lexer_by_name, guess_lexer
        from pygments.lexers.special import TextLexer

        if lang:
            try:
                lexer = get_lexer_by_name(lang)
            except Exception:
                lexer = None
        else:
            lexer = None

        if lexer is None:
            try:
                lexer = guess_lexer(code)
            except Exception:
                lexer = TextLexer()

        formatter = HtmlFormatter(style=style, cssclass="highlight")
        highlighted = highlight(code, lexer, formatter)
        label = lang or getattr(lexer, "name", "") or "text"
        return (
            "<div class='codewrap'>"
            "<div class='codewrap__bar'>"
            f"<span class='codewrap__lang'>{html.escape(label)}</span>"
            "</div>"
            f"<div class='codewrap__body'>{highlighted}</div>"
            "</div>"
        )
    except Exception:
        return (
            "<div class='codewrap'>"
            "<div class='codewrap__bar'>"
            "<span class='codewrap__lang'>text</span>"
            "</div>"
            f"<div class='codewrap__body'><pre>{html.escape(code)}</pre></div>"
            "</div>"
        )


def _markdown_to_html(markdown_text: str) -> str:
    doc = QTextDocument()
    doc.setMarkdown(markdown_text or "")
    return _extract_body(doc.toHtml())


def _render_markdown_with_highlight(markdown_text: str, style: str) -> str:
    pieces = []
    for part in _split_fenced_code_blocks(markdown_text or ""):
        if not part:
            continue
        if part[0] == "text":
            pieces.append(_markdown_to_html(part[1]))
        else:
            _, lang, code = part
            pieces.append(_highlight_code_to_html(code, lang, style))
    return f"<div class='md'>{''.join(pieces)}</div>"


def _extract_first_fenced_code(markdown_text: str) -> str:
    lines = (markdown_text or "").splitlines()
    i = 0
    while i < len(lines):
        if lines[i].startswith("```"):
            i += 1
            code_lines = []
            while i < len(lines) and not lines[i].startswith("```"):
                code_lines.append(lines[i])
                i += 1
            return "\n".join(code_lines).strip()
        i += 1
    return (markdown_text or "").strip()


def open_ai_dialog(terminal_widget, mode: str) -> None:
    """
    在终端控件上以交互方式唤起 AI。

    参数：
    - terminal_widget: QTermWidget/SSHQTermWidget 实例（需具备 sendText/selectedText 等能力）
    - mode:
      - explain: 解释选中文本/输入缓冲
      - hint: 命令提示（不提供远程执行）
      - script: 自动生成脚本（允许远程执行）
      - install: 安装软件环境（允许远程执行）
    """

    try:
        selected = ""
        try:
            if hasattr(terminal_widget, "selectedText"):
                selected = terminal_widget.selectedText(True) or ""
        except Exception:
            selected = ""

        input_buffer = ""
        try:
            input_buffer = getattr(terminal_widget, "_input_buffer", "") or ""
        except Exception:
            input_buffer = ""

        default_text = (selected or input_buffer).strip()
        title = "AI"
        enable_exec = mode in {"install", "script"}

        if mode == "explain":
            title = "AI：解释"
            text, ok = QInputDialog.getMultiLineText(terminal_widget, title, "输入需要解释的内容：", default_text)
            if not ok or not text.strip():
                return
            user_prompt = (
                "请解释以下终端内容（命令/脚本/输出/报错）。"
                "给出原因分析、风险点、以及下一步建议（含可执行命令）。\n\n"
                f"{text.strip()}"
            )
        elif mode == "script":
            title = "AI：自动编写脚本"
            text, ok = QInputDialog.getMultiLineText(terminal_widget, title, "描述要实现的脚本目标：", default_text)
            if not ok or not text.strip():
                return
            user_prompt = (
                "请输出一个可直接运行的 bash 脚本，要求：\n"
                "- 第一行写 shebang\n"
                "- 开启严格模式 set -euo pipefail\n"
                "- 关键步骤用 echo 提示\n"
                "- 尽量兼容 Debian/Ubuntu 与 CentOS/RHEL\n"
                "- 只输出脚本内容，不要使用三引号或 markdown 代码块\n\n"
                f"{text.strip()}"
            )
        elif mode == "install":
            title = "AI：安装/卸载软件环境"
            text, ok = QInputDialog.getMultiLineText(
                terminal_widget, title, "输入要安装/卸载的软件/环境（如 安装 docker / 卸载 node）：", default_text
            )
            if not ok or not text.strip():
                return
            user_prompt = (
                "作为专业的 Linux 运维自动化助手，请严格遵循以下规范生成可直接执行的命令：\n"
                "1) 输出格式要求：\n"
                "   - 必须且只能包含一个标准的 bash 代码块（以 ```bash 开头、``` 结尾）\n"
                "   - 除代码块外禁止输出任何解释性文字或段落\n"
                "   - 代码块内只允许包含可执行命令和必要的 # 注释\n\n"

                "2) 功能实现要求：\n"
                "   - 自动检测系统发行版并智能选择包管理器（支持 apt/dnf/yum/pacman/zypper/apk）\n"
                "   - 所有需要提权的操作必须显式包含 sudo\n"
                "   - 必须包含错误处理机制（建议以 `set -euo pipefail` 开头）\n"
                "   - 提供标准化辅助函数：\n"
                "     * has_cmd() - 检测命令是否存在\n"
                "     * os_release() - 获取系统发行版信息\n"
                "     * install_xxx() - 模块化安装函数\n"
                "     * uninstall_xxx() - 模块化卸载函数\n\n"

                "3) 特殊场景处理：\n"
                "   - 卸载操作必须覆盖所有常见安装来源（包管理器、源码编译、第三方仓库等）\n"
                "   - 每个操作完成后必须包含验证步骤（如版本检查或命令存在性验证）\n"
                "   - 对危险操作（如 rm -rf）必须添加明确警告注释\n\n"

                "4) 代码质量标准：\n"
                "   - 命令必须符合 POSIX 标准\n"
                "   - 变量使用必须遵循命名规范（全大写+下划线）\n"
                "   - 必须包含合理的错误处理逻辑\n"
                "   - 注释必须清晰标明关键步骤\n\n"

                f"{text.strip()}"
            )
        elif mode == "log":
            title = "AI：日志分析"
            text, ok = QInputDialog.getMultiLineText(
                terminal_widget,
                title,
                "粘贴日志内容（可包含多段），或描述你希望分析的问题：",
                default_text,
            )
            if not ok or not text.strip():
                return
            user_prompt = (
                "请作为资深 SRE/运维工程师，对以下日志进行详细分析。\n"
                "要求：\n"
                "1) 先给结论：是否异常/风险等级/影响范围\n"
                "2) 再给定位：关键报错行/触发链路/时间线（按时间顺序）\n"
                "3) 再给根因：最可能原因 + 次要可能原因（带证据）\n"
                "4) 再给解决：立即缓解(止血) / 根治方案 / 验证方法 / 回滚方案\n"
                "5) 需要命令时：用 ```bash 代码块输出可复制命令\n"
                "6) 如果日志信息不足：列出最小补充信息清单（具体要看什么、怎么采集）\n\n"
                f"{text.strip()}"
            )
            enable_exec = False
        else:
            return

        prefs = load_ai_prefs()
        messages = [
            {"role": "system", "content": prefs.system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        parent = None
        try:
            parent = terminal_widget.window()
        except Exception:
            parent = None

        ssh_conn = None
        if parent and enable_exec:
            try:
                if hasattr(parent, "ssh"):
                    ssh_conn = parent.ssh()
            except Exception:
                ssh_conn = None

        dialog = AIOutputDialog(terminal_widget, ssh_conn, title, messages, enable_exec, parent)
        dialog.exec()
    except Exception as e:
        util.logger.error(f"打开 AI 失败: {e}")


class AISettingsDialog(QDialog):
    """
    AI 设置弹窗（保存到 ai.json + 系统钥匙串）。

    设计要点：
    - ai.json：保存模型与参数（非敏感）
    - keyring：保存 API Key（敏感），避免落盘
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI 设置")
        self.setModal(True)
        self.setFixedWidth(520)

        self._prefs = load_ai_prefs()

        layout = QVBoxLayout(self)

        form = QGridLayout()
        row = 0

        form.addWidget(QLabel("模型"), row, 0)
        self.model_edit = QLineEdit(self._prefs.model)
        form.addWidget(self.model_edit, row, 1)
        row += 1

        form.addWidget(QLabel("Base URL(可选)"), row, 0)
        self.base_url_edit = QLineEdit(self._prefs.base_url)
        form.addWidget(self.base_url_edit, row, 1)
        row += 1

        form.addWidget(QLabel("max_tokens"), row, 0)
        self.max_tokens_edit = QLineEdit(str(self._prefs.max_tokens))
        form.addWidget(self.max_tokens_edit, row, 1)
        row += 1

        form.addWidget(QLabel("temperature"), row, 0)
        self.temperature_edit = QLineEdit(str(self._prefs.temperature))
        form.addWidget(self.temperature_edit, row, 1)
        row += 1

        self.thinking_check = QCheckBox("启用深度思考")
        self.thinking_check.setChecked(self._prefs.thinking_enabled)
        form.addWidget(self.thinking_check, row, 1)
        row += 1

        self.stream_check = QCheckBox("启用流式输出")
        self.stream_check.setChecked(self._prefs.stream)
        form.addWidget(self.stream_check, row, 1)
        row += 1

        form.addWidget(QLabel("系统提示词"), row, 0)
        self.system_prompt_edit = QLineEdit(self._prefs.system_prompt)
        form.addWidget(self.system_prompt_edit, row, 1)
        row += 1

        layout.addLayout(form)

        key_box = QHBoxLayout()
        key_box.addWidget(QLabel("API Key"))
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText("使用系统钥匙串保存，不写入配置文件")
        key_box.addWidget(self.key_edit)
        layout.addLayout(key_box)

        btns = QHBoxLayout()
        self.save_btn = QPushButton("保存")
        self.cancel_btn = QPushButton("取消")
        btns.addStretch(1)
        btns.addWidget(self.save_btn)
        btns.addWidget(self.cancel_btn)
        layout.addLayout(btns)

        self.save_btn.clicked.connect(self._save)
        self.cancel_btn.clicked.connect(self.reject)

    def _save(self):
        """
        保存按钮处理：
        1) 解析 UI 输入并写入 ai.json（save_ai_prefs）
        2) 若用户输入了 API Key，则写入系统钥匙串（set_ai_api_key）
        """

        try:
            prefs = AIUserPrefs(
                model=self.model_edit.text().strip() or "glm-4.7",
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
                if not set_ai_api_key(key):
                    QMessageBox.warning(self, "错误", "保存 API Key 失败")
                    return
            self.accept()
        except Exception as e:
            QMessageBox.warning(self, "错误", f"保存失败: {e}")


class AIOutputDialog(QDialog):
    """
    AI 输出窗口：展示 reasoning 与 content，并提供复制/插入/后台执行等按钮。

    交互逻辑：
    - 创建 `AIChatWorker` 在后台请求，并实时把 token 增量显示到两个 QTextBrowser；
    - 用户可把输出插入到当前终端（不一定执行）；
    - 在 SSH 已连接且允许执行的场景下，提供“执行到远程(后台)”按钮。
    """

    def __init__(self, terminal, ssh_conn: object, title: str, messages: list[dict], enable_exec: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(820, 620)

        self.terminal = terminal
        self.ssh_conn = ssh_conn
        self._enable_exec = bool(enable_exec)
        self._final_text = ""
        self._reasoning_md = ""
        self._output_md = ""
        self._exec_running = False
        self._follow_reasoning = True
        self._follow_output = True
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._render_views)

        prefs = load_ai_prefs()

        layout = QVBoxLayout(self)

        reasoning_header = QHBoxLayout()
        self.reasoning_toggle = QToolButton()
        self.reasoning_toggle.setCheckable(True)
        self.reasoning_toggle.setChecked(False)
        self.reasoning_toggle.setArrowType(Qt.RightArrow)
        self.reasoning_toggle.toggled.connect(self._toggle_reasoning)
        reasoning_header.addWidget(self.reasoning_toggle)
        reasoning_header.addWidget(QLabel("思考"))
        reasoning_header.addStretch(1)
        layout.addLayout(reasoning_header)

        self._reasoning_container = QWidget(self)
        reasoning_container_layout = QVBoxLayout(self._reasoning_container)
        reasoning_container_layout.setContentsMargins(0, 0, 0, 0)
        self.reasoning_view = QTextBrowser()
        self.reasoning_view.setOpenExternalLinks(False)
        self.reasoning_view.setPlaceholderText("思考中…")
        reasoning_container_layout.addWidget(self.reasoning_view)
        layout.addWidget(self._reasoning_container, 2)
        self._reasoning_container.setVisible(False)
        self._follow_reasoning = True

        self.output_view = QTextBrowser()
        self.output_view.setOpenExternalLinks(False)
        self.output_view.setPlaceholderText("输出中…")
        layout.addWidget(self.output_view, 5)
        self._follow_output = True

        btns = QHBoxLayout()
        self.stop_btn = QPushButton("停止")
        self.copy_btn = QPushButton("复制输出")
        # self.insert_btn = QPushButton("插入到终端")
        self.exec_btn = QPushButton("执行到远程(后台)")
        self.close_btn = QPushButton("关闭")
        btns.addWidget(self.stop_btn)
        btns.addStretch(1)
        btns.addWidget(self.copy_btn)
        # btns.addWidget(self.insert_btn)
        btns.addWidget(self.exec_btn)
        btns.addWidget(self.close_btn)
        layout.addLayout(btns)

        self.exec_btn.setEnabled(bool(self.ssh_conn) and self._enable_exec)

        self.worker = AIChatWorker(prefs, messages, self)
        self.worker.delta_ready.connect(self._on_delta)
        self.worker.finished_text.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)

        self.stop_btn.clicked.connect(self._stop)
        self.copy_btn.clicked.connect(self._copy)
        # self.insert_btn.clicked.connect(self._insert)
        self.exec_btn.clicked.connect(self._exec_remote)
        self.close_btn.clicked.connect(self.reject)

        self.reasoning_view.verticalScrollBar().valueChanged.connect(self._on_reasoning_scroll)
        self.output_view.verticalScrollBar().valueChanged.connect(self._on_output_scroll)

        self.worker.start()

    def _on_delta(self, reasoning: str, content: str):
        """
        流式增量显示：
        - reasoning_content（若 SDK 提供）写入上方窗口；
        - content 写入下方窗口。
        """

        if reasoning:
            self._reasoning_md += reasoning
        if content:
            self._output_md += content
        self._schedule_render()

    def _on_finished(self, text: str):
        """
        记录最终输出，用于后续复制/插入/执行。

        优先使用窗口里已累计的内容（因为 UI 的 token 拼接更直观），其次使用线程返回的 full_text。
        """

        self._final_text = (self._output_md or "").strip() or (text or "").strip()
        self._schedule_render()
        self.stop_btn.setEnabled(False)

    def _on_failed(self, msg: str):
        QMessageBox.warning(self, "AI 错误", msg)
        self.stop_btn.setEnabled(False)

    def _stop(self):
        self.worker.request_stop()
        self.stop_btn.setEnabled(False)

    def _copy(self):
        QApplication.clipboard().setText(self._get_output_plain_text() or "")

    # def _insert(self):
    #     """
    #     将 AI 输出插入到终端输入区（不强制执行）。
    #     """
    #
    #     text = self._get_output_plain_text() or ""
    #     if not text:
    #         return
    #     try:
    #         self.terminal.sendText(text)
    #     except Exception as e:
    #         QMessageBox.warning(self, "错误", str(e))

    def _exec_remote(self):
        """
        把输出当作命令逐行执行到远程服务器。

        安全策略：
        - 强制二次确认；
        - 跳过空行与以 # 开头的注释行；
        - 执行过程与输出追加回窗口，便于审计。
        """

        if not self.ssh_conn:
            return
        text = (self._get_output_plain_text() or "").strip()
        if not text:
            return

        reply = QMessageBox.question(self, "确认执行", "将把输出内容作为命令执行到远程服务器，确认继续？")
        if reply != QMessageBox.Yes:
            return

        if self._exec_running:
            return
        self._exec_running = True
        self.exec_btn.setEnabled(False)
        QMetaObject.invokeMethod(
            self,
            "_append_exec_log",
            Qt.QueuedConnection,
            Q_ARG(str, "\n\n## 开始执行到远程(后台)\n"),
        )
        threading.Thread(target=self._exec_remote_thread, args=(text,), daemon=True).start()

    def _schedule_render(self):
        if not self._render_timer.isActive():
            self._render_timer.start(60)

    def _compose_html(self, markdown_text: str) -> str:
        pal = self.palette()
        text_color = pal.color(QPalette.Text).name()
        link_color = pal.color(QPalette.Link).name()
        base_color = pal.color(QPalette.Base)
        is_light = base_color.lightness() >= 128
        page_bg = base_color.name()
        style = _pick_pygments_style(is_light)
        block_bg = "#f6f8fa" if is_light else "#0d1117"
        block_fg = "#24292f" if is_light else "#e6edf3"
        inline_bg = "#eef2f6" if is_light else "#161b22"
        inline_border = "#d0d7de" if is_light else "#30363d"
        code_border = "#d0d7de" if is_light else "#30363d"
        bar_bg = "#ffffff" if is_light else "#161b22"
        bar_fg = "#57606a" if is_light else "#9da7b3"
        lineno_bg = "#f0f3f6" if is_light else "#0b1320"
        lineno_fg = "#6e7781" if is_light else "#6e7681"
        quote_bg = "rgba(208, 215, 222, 0.25)" if is_light else "rgba(48, 54, 61, 0.35)"
        quote_border = "#d0d7de" if is_light else "#30363d"

        # formatter = HtmlFormatter(style='rrt', noclasses=True)
        # # 高亮代码
        # highlighted = highlight(ack, PythonLexer(), formatter)

        css = (
            _base_css(
                text_color,
                link_color,
                page_bg,
                block_bg,
                block_fg,
                inline_bg,
                inline_border,
                code_border,
                bar_bg,
                bar_fg,
                lineno_bg,
                lineno_fg,
                quote_bg,
                quote_border,
            )
            + "\n"
            + _code_css(style)
        )
        body = _render_markdown_with_highlight(markdown_text or "", style)
        return f"<html><head><meta charset='utf-8'><style>{css}</style></head><body>{body}</body></html>"

    def _set_view_html(self, view: QTextBrowser, html_text: str):
        view.setHtml(html_text)
        follow = self._follow_output if view is self.output_view else self._follow_reasoning
        if follow:
            self._scroll_view_to_bottom(view)

    def _render_views(self):
        self._set_view_html(self.reasoning_view, self._compose_html(self._reasoning_md or ""))
        self._set_view_html(self.output_view, self._compose_html(self._output_md or ""))

    def _toggle_reasoning(self, expanded: bool):
        self.reasoning_toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self._reasoning_container.setVisible(bool(expanded))
        if expanded:
            self._follow_reasoning = True
            self._scroll_view_to_bottom(self.reasoning_view)

    def _is_scroll_at_bottom(self, view: QTextBrowser) -> bool:
        sb = view.verticalScrollBar()
        return sb.value() >= sb.maximum() - 4

    @Slot(int)
    def _on_output_scroll(self, value: int):
        sb = self.output_view.verticalScrollBar()
        self._follow_output = value >= sb.maximum() - 4

    @Slot(int)
    def _on_reasoning_scroll(self, value: int):
        sb = self.reasoning_view.verticalScrollBar()
        self._follow_reasoning = value >= sb.maximum() - 4

    def _scroll_view_to_bottom(self, view: QTextBrowser):
        def _do():
            try:
                view.moveCursor(QTextCursor.End)
                view.ensureCursorVisible()
                sb = view.verticalScrollBar()
                sb.setValue(sb.maximum())
            except Exception:
                pass

        QTimer.singleShot(0, _do)
        QTimer.singleShot(30, _do)

    def _get_output_plain_text(self) -> str:
        return _extract_first_fenced_code(self._final_text or self._output_md or "")

    @Slot(str)
    def _append_exec_log(self, markdown_block: str):
        self._output_md += markdown_block
        self._final_text = (self._output_md or "").strip()
        self._schedule_render()

    @Slot(int, int, int, str)
    def _on_exec_finished(self, total: int, ok_count: int, fail_count: int, failed_preview: str):
        self._exec_running = False
        self.exec_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)

        summary_md = (
            "\n\n## 远程执行完成\n"
            f"- 总计: {total}\n"
            f"- 成功: {ok_count}\n"
            f"- 失败: {fail_count}\n"
        )
        if failed_preview:
            summary_md += "\n### 失败示例\n```text\n" + failed_preview.strip() + "\n```\n"
        self._append_exec_log(summary_md)

        if total == 0:
            QMessageBox.information(self, "执行完成", "没有检测到可执行命令。")
            return
        if fail_count == 0:
            QMessageBox.information(self, "执行成功", f"远程后台执行完成：共 {total} 条命令，全部成功。")
        else:
            QMessageBox.warning(
                self,
                "执行完成(有失败)",
                f"远程后台执行完成：共 {total} 条命令，成功 {ok_count}，失败 {fail_count}。\n"
                f"可在输出窗口查看失败命令与输出。",
            )

    def _exec_remote_thread(self, text: str):
        """
        后台执行线程：逐行 sudo_exec。

        注意：
        - 不能在子线程直接操作 Qt 控件，所以使用 QMetaObject.invokeMethod 回到主线程追加输出。
        """

        total = 0
        ok_count = 0
        fail_count = 0
        failed_cmds: list[str] = []
        try:
            for line in text.splitlines():
                cmd = line.strip()
                if not cmd or cmd.startswith("#"):
                    continue
                total += 1
                out = ""
                ok = True
                try:
                    out = self.ssh_conn.sudo_exec(cmd) or ""
                except Exception as e:
                    ok = False
                    out = str(e)

                if ok:
                    ok_count += 1
                    title = "### ✅ 成功"
                else:
                    fail_count += 1
                    title = "### ❌ 失败"
                    if len(failed_cmds) < 5:
                        failed_cmds.append(cmd)

                md = (
                        "\n\n"
                        + title
                        + "\n```bash\n"
                        + cmd
                        + "\n```\n"
                        + "```text\n"
                        + (out or "").rstrip()
                        + "\n```\n"
                )
                QMetaObject.invokeMethod(self, "_append_exec_log", Qt.QueuedConnection, Q_ARG(str, md))
        except Exception as e:
            fail_count += 1
            md = "\n\n### ❌ 失败\n```text\n" + f"[执行失败] {e}\n" + "```\n"
            QMetaObject.invokeMethod(self, "_append_exec_log", Qt.QueuedConnection, Q_ARG(str, md))
        finally:
            failed_preview = "\n".join(failed_cmds)
            QMetaObject.invokeMethod(
                self,
                "_on_exec_finished",
                Qt.QueuedConnection,
                Q_ARG(int, total),
                Q_ARG(int, ok_count),
                Q_ARG(int, fail_count),
                Q_ARG(str, failed_preview),
            )
