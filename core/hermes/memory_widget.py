# -*- coding: utf-8 -*-
"""Hermes Agent Memory 浏览器模块 - 浏览会话历史、搜索消息、管理 Memory 文件"""

import json
import os

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
                                QLabel, QPushButton, QLineEdit, QTableWidget,
                                QTableWidgetItem, QHeaderView, QTextBrowser,
                                QTabWidget, QPlainTextEdit, QMessageBox,
                                QComboBox, QGroupBox)
from PySide6.QtCore import Qt, QThread, Signal

from function.util import logger


class MemoryQueryWorker(QThread):
    """后台线程执行数据库查询或文件操作，避免阻塞 UI"""
    sessions_loaded = Signal(list)    # 会话列表
    messages_loaded = Signal(list)    # 消息列表
    files_loaded = Signal(dict)       # {filename: content}
    error = Signal(str)

    def __init__(self, backend, query_type, **kwargs):
        super().__init__()
        self._backend = backend
        self._query_type = query_type
        self._kwargs = kwargs

    def run(self):
        try:
            if self._query_type == "load_sessions":
                self._load_sessions()
            elif self._query_type == "load_messages":
                self._load_messages()
            elif self._query_type == "search":
                self._search_messages()
            elif self._query_type == "load_files":
                self._load_memory_files()
            elif self._query_type == "delete_session":
                self._delete_session()
        except Exception as e:
            logger.error(f"MemoryQueryWorker 异常: {e}")
            self.error.emit(str(e))

    def _load_sessions(self):
        hermes_home = self._backend.get_hermes_home()
        db_path = os.path.join(hermes_home, "state.db")
        if not self._backend.file_exists(db_path):
            self.error.emit("数据库未找到: state.db 不存在")
            return
        sql = ("SELECT s.id, "
               "COALESCE(NULLIF(s.title, ''), "
               "(SELECT substr(m.content, 1, 60) FROM messages m "
               "WHERE m.session_id = s.id AND m.role = 'user' AND m.content IS NOT NULL "
               "ORDER BY m.timestamp ASC LIMIT 1), s.id) as title, "
               "s.started_at, s.source, s.model, "
               "(COALESCE(s.input_tokens,0) + COALESCE(s.output_tokens,0)) as token_count "
               "FROM sessions s ORDER BY s.started_at DESC LIMIT 100")
        rows = self._backend.read_sqlite(db_path, sql)
        self.sessions_loaded.emit(rows)

    def _load_messages(self):
        session_id = self._kwargs.get("session_id", "")
        hermes_home = self._backend.get_hermes_home()
        db_path = os.path.join(hermes_home, "state.db")
        if not self._backend.file_exists(db_path):
            self.error.emit("数据库未找到: state.db 不存在")
            return
        sql = (f"SELECT timestamp as created_at, role, content FROM messages "
               f"WHERE session_id = '{session_id}' ORDER BY timestamp ASC")
        rows = self._backend.read_sqlite(db_path, sql)
        self.messages_loaded.emit(rows)

    def _search_messages(self):
        query = self._kwargs.get("query", "")
        hermes_home = self._backend.get_hermes_home()
        db_path = os.path.join(hermes_home, "state.db")
        if not self._backend.file_exists(db_path):
            self.error.emit("数据库未找到: state.db 不存在")
            return
        # 先尝试 FTS 搜索，若表不存在则回退到 LIKE 搜索
        sql_fts = (
            f"SELECT m.timestamp as created_at, m.role, m.content, s.title, s.id as session_id "
            f"FROM messages m JOIN sessions s ON m.session_id = s.id "
            f"WHERE m.id IN (SELECT rowid FROM messages_fts WHERE content MATCH '{query}') "
            f"ORDER BY m.timestamp DESC LIMIT 50"
        )
        rows = self._backend.read_sqlite(db_path, sql_fts)
        if not rows:
            # FTS 可能不可用，回退到 LIKE
            safe_query = query.replace("'", "''")
            sql_like = (
                f"SELECT m.timestamp as created_at, m.role, m.content, s.title, s.id as session_id "
                f"FROM messages m JOIN sessions s ON m.session_id = s.id "
                f"WHERE m.content LIKE '%{safe_query}%' "
                f"ORDER BY m.timestamp DESC LIMIT 50"
            )
            rows = self._backend.read_sqlite(db_path, sql_like)
        self.messages_loaded.emit(rows)

    def _load_memory_files(self):
        hermes_home = self._backend.get_hermes_home()
        files = {}
        for filename in ("MEMORY.md", "USER.md", "SOUL.md"):
            filepath = os.path.join(hermes_home, filename)
            if self._backend.file_exists(filepath):
                files[filename] = self._backend.read_file(filepath)
            else:
                files[filename] = ""
        self.files_loaded.emit(files)

    def _delete_session(self):
        session_id = self._kwargs.get("session_id", "")
        hermes_home = self._backend.get_hermes_home()
        db_path = os.path.join(hermes_home, "state.db")
        if not self._backend.file_exists(db_path):
            self.error.emit("数据库未找到: state.db 不存在")
            return
        # 删除消息和会话
        sql_del_msg = f"DELETE FROM messages WHERE session_id = '{session_id}'"
        sql_del_ses = f"DELETE FROM sessions WHERE id = '{session_id}'"
        self._backend.read_sqlite(db_path, sql_del_msg)
        self._backend.read_sqlite(db_path, sql_del_ses)
        # 重新加载会话列表
        self._load_sessions()


class MemoryWidget(QWidget):
    """Hermes Agent Memory 浏览器：浏览会话历史、搜索消息、管理 Memory 文件"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._backend = None
        self._workers = []  # 持有 worker 引用防止 GC
        self._current_sessions = []  # 当前会话列表缓存
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # 使用 QSplitter 分为左右两部分
        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter)

        # ═══════════════ 左侧面板：会话列表 + 搜索 ═══════════════
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(4, 4, 4, 4)
        left_layout.setSpacing(8)

        # ─── 搜索栏 ───
        search_layout = QHBoxLayout()
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText(self.tr("搜索对话内容..."))
        self._search_input.returnPressed.connect(self._on_search_clicked)
        search_layout.addWidget(self._search_input)

        self._search_scope_combo = QComboBox()
        self._search_scope_combo.addItem(self.tr("全部"), "all")
        self._search_scope_combo.addItem(self.tr("按会话"), "session")
        self._search_scope_combo.addItem(self.tr("按角色"), "role")
        self._search_scope_combo.setFixedWidth(80)
        search_layout.addWidget(self._search_scope_combo)

        self._btn_search = QPushButton(self.tr("搜索"))
        self._btn_search.clicked.connect(self._on_search_clicked)
        search_layout.addWidget(self._btn_search)

        left_layout.addLayout(search_layout)

        # ─── 会话列表表格 ───
        self._session_table = QTableWidget()
        self._session_table.setColumnCount(6)
        self._session_table.setHorizontalHeaderLabels([
            "ID", self.tr("标题"), self.tr("时间"), self.tr("来源"),
            self.tr("模型"), self.tr("Token数")
        ])
        self._session_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._session_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._session_table.setSelectionMode(QTableWidget.SingleSelection)
        self._session_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._session_table.setAlternatingRowColors(True)
        self._session_table.verticalHeader().setVisible(False)
        self._session_table.itemSelectionChanged.connect(self._on_session_selected)
        # 隐藏 ID 列（用于内部引用）
        self._session_table.setColumnHidden(0, True)
        left_layout.addWidget(self._session_table)

        # ─── 操作按钮 ───
        btn_layout = QHBoxLayout()
        self._btn_refresh = QPushButton(self.tr("刷新"))
        self._btn_refresh.clicked.connect(self._on_refresh_clicked)
        btn_layout.addWidget(self._btn_refresh)

        self._btn_export = QPushButton(self.tr("导出"))
        self._btn_export.clicked.connect(self._on_export_clicked)
        btn_layout.addWidget(self._btn_export)

        self._btn_delete = QPushButton(self.tr("删除"))
        self._btn_delete.clicked.connect(self._on_delete_clicked)
        btn_layout.addWidget(self._btn_delete)

        btn_layout.addStretch()
        left_layout.addLayout(btn_layout)

        splitter.addWidget(left_panel)

        # ═══════════════ 右侧面板：QTabWidget ═══════════════
        self._right_tab = QTabWidget()

        # ─── "对话详情" Tab ───
        self._detail_browser = QTextBrowser()
        self._detail_browser.setOpenExternalLinks(False)
        self._detail_browser.setPlaceholderText(self.tr("选择左侧会话查看详情..."))
        self._right_tab.addTab(self._detail_browser, self.tr("对话详情"))

        # ─── "Memory 文件" Tab ───
        self._memory_tab = QTabWidget()
        self._memory_editors = {}
        for filename in ("MEMORY.md", "USER.md", "SOUL.md"):
            editor_widget = QWidget()
            editor_layout = QVBoxLayout(editor_widget)
            editor_layout.setContentsMargins(4, 4, 4, 4)

            editor = QPlainTextEdit()
            editor.setPlaceholderText(self.tr(f"文件内容: {filename}"))
            editor_layout.addWidget(editor)

            save_btn = QPushButton(self.tr("保存"))
            save_btn.clicked.connect(lambda checked=False, fn=filename, ed=editor:
                                     self._save_memory_file(fn, ed.toPlainText()))
            save_layout = QHBoxLayout()
            save_layout.addStretch()
            save_layout.addWidget(save_btn)
            editor_layout.addLayout(save_layout)

            self._memory_editors[filename] = editor
            self._memory_tab.addTab(editor_widget, filename)

        self._right_tab.addTab(self._memory_tab, self.tr("Memory 文件"))

        splitter.addWidget(self._right_tab)

        # 设置 splitter 初始比例 (左 40%, 右 60%)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 6)

    # ═══════════════ 公共方法 ═══════════════

    def set_backend(self, backend):
        """设置后端引用（不触发加载）"""
        self._backend = backend

    def refresh(self):
        """当 Tab 被选中时调用，触发数据加载"""
        self._load_sessions()
        self._load_memory_files()

    # ═══════════════ 数据加载 ═══════════════

    def _load_sessions(self):
        """加载会话列表"""
        if not self._backend:
            return
        worker = MemoryQueryWorker(self._backend, "load_sessions")
        worker.sessions_loaded.connect(self._on_sessions_loaded)
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.finished.connect(lambda: self._cleanup_worker(worker))
        worker.start()

    def _load_memory_files(self):
        """加载 MEMORY.md / USER.md / SOUL.md"""
        if not self._backend:
            return
        worker = MemoryQueryWorker(self._backend, "load_files")
        worker.files_loaded.connect(self._on_files_loaded)
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.finished.connect(lambda: self._cleanup_worker(worker))
        worker.start()

    def _show_session_detail(self, session_id):
        """加载并显示会话详情"""
        if not self._backend or not session_id:
            return
        worker = MemoryQueryWorker(self._backend, "load_messages", session_id=session_id)
        worker.messages_loaded.connect(self._on_messages_loaded)
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.finished.connect(lambda: self._cleanup_worker(worker))
        worker.start()

    def _search_messages(self, query):
        """全文搜索消息"""
        if not self._backend or not query:
            return
        worker = MemoryQueryWorker(self._backend, "search", query=query)
        worker.messages_loaded.connect(self._on_search_results)
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.finished.connect(lambda: self._cleanup_worker(worker))
        worker.start()

    def _export_session(self, session_id):
        """导出选中会话为 JSON"""
        if not self._backend or not session_id:
            return
        hermes_home = self._backend.get_hermes_home()
        db_path = os.path.join(hermes_home, "state.db")

        # 获取会话信息
        sql_session = f"SELECT * FROM sessions WHERE id = '{session_id}'"
        session_info = self._backend.read_sqlite(db_path, sql_session)

        # 获取消息
        sql_messages = (f"SELECT timestamp as created_at, role, content FROM messages "
                        f"WHERE session_id = '{session_id}' ORDER BY timestamp ASC")
        messages = self._backend.read_sqlite(db_path, sql_messages)

        export_data = {
            "session": session_info[0] if session_info else {},
            "messages": messages
        }

        # 保存到 hermes_home/exports/ 目录
        export_dir = os.path.join(hermes_home, "exports")
        export_path = os.path.join(export_dir, f"session_{session_id}.json")
        content = json.dumps(export_data, ensure_ascii=False, indent=2)
        self._backend.write_file(export_path, content)

        QMessageBox.information(
            self, self.tr("导出成功"),
            self.tr(f"会话已导出到:\n{export_path}")
        )

    def _delete_session(self, session_id):
        """删除选中会话"""
        if not self._backend or not session_id:
            return
        reply = QMessageBox.question(
            self, self.tr("确认删除"),
            self.tr("确定要删除选中的会话吗？此操作不可恢复。"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        worker = MemoryQueryWorker(self._backend, "delete_session", session_id=session_id)
        worker.sessions_loaded.connect(self._on_sessions_loaded)
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.finished.connect(lambda: self._cleanup_worker(worker))
        worker.start()

    def _save_memory_file(self, filename, content):
        """保存 memory 文件"""
        if not self._backend:
            return
        hermes_home = self._backend.get_hermes_home()
        filepath = os.path.join(hermes_home, filename)
        try:
            self._backend.write_file(filepath, content)
            QMessageBox.information(
                self, self.tr("保存成功"),
                self.tr(f"{filename} 已保存")
            )
        except Exception as e:
            QMessageBox.warning(
                self, self.tr("保存失败"),
                self.tr(f"保存 {filename} 失败: {e}")
            )

    # ═══════════════ 信号回调 ═══════════════

    def _on_sessions_loaded(self, sessions):
        """会话列表加载完成"""
        self._current_sessions = sessions
        self._session_table.setRowCount(0)
        for row_data in sessions:
            row_idx = self._session_table.rowCount()
            self._session_table.insertRow(row_idx)
            self._session_table.setItem(row_idx, 0, QTableWidgetItem(
                str(row_data.get("id", ""))))
            self._session_table.setItem(row_idx, 1, QTableWidgetItem(
                str(row_data.get("title", "") or "")))
            # started_at 是 Unix 时间戳，转为可读格式
            started_at = row_data.get("started_at", "")
            if isinstance(started_at, (int, float)) and started_at:
                from datetime import datetime
                try:
                    time_str = datetime.fromtimestamp(started_at).strftime("%Y-%m-%d %H:%M")
                except (OSError, ValueError):
                    time_str = str(started_at)
            else:
                time_str = str(started_at)
            self._session_table.setItem(row_idx, 2, QTableWidgetItem(time_str))
            self._session_table.setItem(row_idx, 3, QTableWidgetItem(
                str(row_data.get("source", ""))))
            self._session_table.setItem(row_idx, 4, QTableWidgetItem(
                str(row_data.get("model", "") or "")))
            self._session_table.setItem(row_idx, 5, QTableWidgetItem(
                str(row_data.get("token_count", 0))))

    def _on_messages_loaded(self, messages):
        """会话消息加载完成，渲染到 QTextBrowser"""
        html_parts = [
            '<style>'
            '.msg-block { margin-bottom: 14px; padding: 10px 12px; border-radius: 6px; }'
            '.msg-user { background: #1a3a5c; border-left: 4px solid #3498db; }'
            '.msg-assistant { background: #1a3c2a; border-left: 4px solid #2ecc71; }'
            '.msg-tool { background: #2a2a2a; border-left: 4px solid #7f8c8d; '
            '  font-family: "SF Mono", "Menlo", "Monaco", monospace; font-size: 11px; '
            '  max-height: 120px; overflow: hidden; color: #999; }'
            '.msg-system { background: #2a1a3a; border-left: 4px solid #9b59b6; }'
            '.msg-header { font-weight: bold; margin-bottom: 6px; font-size: 12px; }'
            '.msg-content { white-space: pre-wrap; word-break: break-word; line-height: 1.5; }'
            '.tool-label { display: inline-block; background: #444; color: #aaa; '
            '  padding: 1px 6px; border-radius: 3px; font-size: 10px; margin-left: 8px; }'
            '.tool-hint { color: #666; font-style: italic; font-size: 11px; margin-top: 4px; }'
            '</style>'
        ]

        for msg in messages:
            time_str = msg.get("created_at", "")
            # 格式化时间戳
            if isinstance(time_str, (int, float)) and time_str:
                from datetime import datetime
                try:
                    time_str = datetime.fromtimestamp(time_str).strftime("%H:%M:%S")
                except (OSError, ValueError):
                    time_str = str(time_str)

            role = msg.get("role", "")
            content = msg.get("content") or ""

            # 转义 HTML 特殊字符
            content_escaped = (content.replace("&", "&amp;")
                               .replace("<", "&lt;")
                               .replace(">", "&gt;"))

            if role == "user":
                css_class = "msg-user"
                role_label = "👤 User"
                header_color = "#3498db"
                # 用户消息完整显示
                display_content = content_escaped.replace("\n", "<br>")
                html_parts.append(
                    f'<div class="msg-block {css_class}">'
                    f'<div class="msg-header" style="color: {header_color};">'
                    f'{role_label} <span style="font-weight:normal;color:#888;font-size:11px;">{time_str}</span></div>'
                    f'<div class="msg-content">{display_content}</div>'
                    f'</div>'
                )
            elif role == "assistant":
                css_class = "msg-assistant"
                role_label = "🤖 Assistant"
                header_color = "#2ecc71"
                display_content = content_escaped.replace("\n", "<br>")
                html_parts.append(
                    f'<div class="msg-block {css_class}">'
                    f'<div class="msg-header" style="color: {header_color};">'
                    f'{role_label} <span style="font-weight:normal;color:#888;font-size:11px;">{time_str}</span></div>'
                    f'<div class="msg-content">{display_content}</div>'
                    f'</div>'
                )
            elif role == "tool":
                # 工具调用结果：折叠显示，限制高度，使用等宽字体
                css_class = "msg-tool"
                # 截断过长的工具输出
                if len(content) > 500:
                    truncated = content_escaped[:500] + "..."
                    hint = f'<div class="tool-hint">（共 {len(content)} 字符，已截断显示）</div>'
                else:
                    truncated = content_escaped
                    hint = ""
                display_content = truncated.replace("\n", "<br>")
                html_parts.append(
                    f'<div class="msg-block {css_class}">'
                    f'<div class="msg-header" style="color: #7f8c8d;">'
                    f'🔧 Tool <span style="font-weight:normal;font-size:11px;">{time_str}</span></div>'
                    f'<div class="msg-content">{display_content}</div>'
                    f'{hint}'
                    f'</div>'
                )
            elif role == "system":
                css_class = "msg-system"
                role_label = "⚙️ System"
                header_color = "#9b59b6"
                # 系统消息也做截断
                if len(content) > 300:
                    display_content = content_escaped[:300].replace("\n", "<br>") + "..."
                else:
                    display_content = content_escaped.replace("\n", "<br>")
                html_parts.append(
                    f'<div class="msg-block {css_class}">'
                    f'<div class="msg-header" style="color: {header_color};">'
                    f'{role_label} <span style="font-weight:normal;color:#888;font-size:11px;">{time_str}</span></div>'
                    f'<div class="msg-content" style="font-size:12px;color:#bbb;">{display_content}</div>'
                    f'</div>'
                )
            else:
                # 其他角色（如 function）
                display_content = content_escaped[:300].replace("\n", "<br>")
                html_parts.append(
                    f'<div class="msg-block" style="background:#2a2a2a;border-left:4px solid #95a5a6;">'
                    f'<div class="msg-header" style="color: #95a5a6;">'
                    f'{role} <span style="font-weight:normal;color:#888;font-size:11px;">{time_str}</span></div>'
                    f'<div class="msg-content" style="font-size:12px;color:#aaa;">{display_content}</div>'
                    f'</div>'
                )

        if html_parts and len(html_parts) > 1:
            self._detail_browser.setHtml("".join(html_parts))
        else:
            self._detail_browser.setHtml(
                f'<p style="color: #7f8c8d;">{self.tr("该会话暂无消息记录")}</p>')
        # 切换到对话详情 Tab
        self._right_tab.setCurrentIndex(0)

    def _on_search_results(self, messages):
        """搜索结果加载完成"""
        html_parts = [f'<h3>{self.tr("搜索结果")} ({len(messages)} {self.tr("条")})</h3>']
        for msg in messages:
            time_str = msg.get("created_at", "")
            role = msg.get("role", "")
            content = msg.get("content") or ""
            session_title = msg.get("title", "")
            session_id = msg.get("session_id", "")
            content_escaped = (content.replace("&", "&amp;")
                               .replace("<", "&lt;")
                               .replace(">", "&gt;")
                               .replace("\n", "<br>"))
            if role == "user":
                color = "#2980b9"
            elif role == "assistant":
                color = "#27ae60"
            else:
                color = "#7f8c8d"

            html_parts.append(
                f'<div style="margin-bottom: 10px; padding: 8px; '
                f'border-left: 3px solid {color}; background: rgba(0,0,0,0.02);">'
                f'<div style="color: #555; font-size: 11px; margin-bottom: 2px;">'
                f'会话: {session_title} (ID: {session_id})</div>'
                f'<div style="color: {color}; font-weight: bold;">'
                f'[{time_str}] {role}</div>'
                f'<div style="white-space: pre-wrap;">{content_escaped}</div>'
                f'</div>'
            )

        self._detail_browser.setHtml("".join(html_parts))
        self._right_tab.setCurrentIndex(0)

    def _on_files_loaded(self, files):
        """Memory 文件加载完成"""
        for filename, content in files.items():
            if filename in self._memory_editors:
                self._memory_editors[filename].setPlainText(content)

    def _on_error(self, error_msg):
        """错误处理"""
        logger.warning(f"MemoryWidget 错误: {error_msg}")
        self._detail_browser.setHtml(
            f'<p style="color: #e74c3c; font-weight: bold;">{error_msg}</p>')

    # ═══════════════ UI 事件 ═══════════════

    def _on_session_selected(self):
        """会话列表行选中变更"""
        selected_rows = self._session_table.selectionModel().selectedRows()
        if not selected_rows:
            return
        row_idx = selected_rows[0].row()
        session_id_item = self._session_table.item(row_idx, 0)
        if session_id_item:
            self._show_session_detail(session_id_item.text())

    def _on_search_clicked(self):
        """搜索按钮点击"""
        query = self._search_input.text().strip()
        if query:
            self._search_messages(query)

    def _on_refresh_clicked(self):
        """刷新按钮点击"""
        self._load_sessions()
        self._load_memory_files()

    def _on_export_clicked(self):
        """导出按钮点击"""
        selected_rows = self._session_table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.information(self, self.tr("提示"), self.tr("请先选择一个会话"))
            return
        row_idx = selected_rows[0].row()
        session_id_item = self._session_table.item(row_idx, 0)
        if session_id_item:
            self._export_session(session_id_item.text())

    def _on_delete_clicked(self):
        """删除按钮点击"""
        selected_rows = self._session_table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.information(self, self.tr("提示"), self.tr("请先选择一个会话"))
            return
        row_idx = selected_rows[0].row()
        session_id_item = self._session_table.item(row_idx, 0)
        if session_id_item:
            self._delete_session(session_id_item.text())

    # ═══════════════ 辅助方法 ═══════════════

    def _cleanup_worker(self, worker):
        """清理已完成的 worker 引用"""
        if worker in self._workers:
            self._workers.remove(worker)
