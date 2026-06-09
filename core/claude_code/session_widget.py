# -*- coding: utf-8 -*-
"""Claude Code 会话管理模块 - 支持会话列表/新建后台任务/停止/删除/恢复"""

import logging
from typing import Optional

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                               QTableWidget, QTableWidgetItem, QHeaderView,
                               QLabel, QMessageBox, QInputDialog, QAbstractItemView)

logger = logging.getLogger(__name__)


class SessionWorker(QThread):
    """后台线程执行 Claude Code Backend I/O 操作"""

    sessions_loaded = Signal(list)       # 会话列表加载完成
    command_done = Signal(str, str)      # (description, output)
    error = Signal(str)                  # 错误信息

    def __init__(self, backend, action: str, payload: Optional[str] = None):
        """
        Args:
            backend: ClaudeCodeBackend 实例
            action: 操作类型 - "list" | "stop" | "remove" | "background"
            payload: 操作参数（session_id 或 prompt）
        """
        super().__init__()
        self._backend = backend
        self._action = action
        self._payload = payload

    def run(self):
        try:
            if self._action == "list":
                sessions = self._backend.list_sessions()
                self.sessions_loaded.emit(sessions)
            elif self._action == "stop":
                success, msg = self._backend.stop_session(self._payload)
                if success:
                    self.command_done.emit("停止会话", msg or "会话已停止")
                else:
                    self.error.emit(f"停止会话失败: {msg}")
            elif self._action == "remove":
                success, msg = self._backend.remove_session(self._payload)
                if success:
                    self.command_done.emit("删除会话", msg or "会话已删除")
                else:
                    self.error.emit(f"删除会话失败: {msg}")
            elif self._action == "background":
                success, msg = self._backend.start_background_task(self._payload)
                if success:
                    self.command_done.emit("新建后台任务", msg or "后台任务已启动")
                else:
                    self.error.emit(f"启动后台任务失败: {msg}")
            else:
                self.error.emit(f"未知操作: {self._action}")
        except Exception as e:
            logger.exception(f"SessionWorker 执行异常: {self._action}")
            self.error.emit(str(e))


class SessionWidget(QWidget):
    """Claude Code 会话管理面板"""

    # 信号：请求在终端中恢复会话
    open_terminal_requested = Signal(str)  # 参数为 "claude --resume {session_id}"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._backend = None
        self._workers: list[SessionWorker] = []  # 持有 worker 引用，防止 GC
        self._sessions: list[dict] = []
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        # ─── 顶部工具栏 ───
        toolbar_layout = QHBoxLayout()
        toolbar_layout.setSpacing(6)

        self._btn_refresh = QPushButton(self.tr("刷新"))
        self._btn_refresh.clicked.connect(self.refresh)
        toolbar_layout.addWidget(self._btn_refresh)

        self._btn_new_task = QPushButton(self.tr("新建后台任务"))
        self._btn_new_task.clicked.connect(self._new_background_task)
        toolbar_layout.addWidget(self._btn_new_task)

        self._btn_stop = QPushButton(self.tr("停止"))
        self._btn_stop.clicked.connect(self._stop_session)
        toolbar_layout.addWidget(self._btn_stop)

        self._btn_delete = QPushButton(self.tr("删除"))
        self._btn_delete.clicked.connect(self._remove_session)
        toolbar_layout.addWidget(self._btn_delete)

        toolbar_layout.addStretch()
        main_layout.addLayout(toolbar_layout)

        # ─── 会话表格 ───
        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels([
            self.tr("ID"), self.tr("名称"), self.tr("状态"), self.tr("创建时间")
        ])
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)

        # 列宽策略
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)

        # 双击恢复会话
        self._table.doubleClicked.connect(self._resume_session)

        self._table.setStyleSheet("""
            QTableWidget {
                background-color: #1e1e1e;
                border: 1px solid #333333;
                gridline-color: #333333;
            }
            QTableWidget::item {
                padding: 4px 8px;
            }
            QTableWidget::item:selected {
                background-color: #2a4a6b;
            }
            QHeaderView::section {
                background-color: #2a2a2a;
                border: 1px solid #333333;
                padding: 4px 8px;
                color: #cccccc;
            }
        """)

        main_layout.addWidget(self._table)

        # ─── 底部状态区 ───
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #888888; padding: 4px;")
        main_layout.addWidget(self._status_label)

    def set_backend(self, backend) -> None:
        """设置 Backend 实例"""
        self._backend = backend

    def refresh(self) -> None:
        """刷新会话列表"""
        if not self._backend:
            self._set_status(self.tr("未连接 Backend"))
            return
        self._set_status(self.tr("正在加载会话列表..."))
        self._btn_refresh.setEnabled(False)
        worker = SessionWorker(self._backend, "list")
        worker.sessions_loaded.connect(self._on_sessions_loaded)
        worker.error.connect(self._on_error)
        worker.finished.connect(lambda: self._cleanup_worker(worker))
        self._workers.append(worker)
        worker.start()

    def _new_background_task(self) -> None:
        """新建后台任务"""
        if not self._backend:
            return
        prompt, ok = QInputDialog.getText(
            self, self.tr("新建后台任务"),
            self.tr("输入任务 Prompt:")
        )
        if not ok or not prompt.strip():
            return
        self._set_status(self.tr("正在启动后台任务..."))
        worker = SessionWorker(self._backend, "background", prompt.strip())
        worker.command_done.connect(self._on_command_done)
        worker.error.connect(self._on_error)
        worker.finished.connect(lambda: self._cleanup_worker(worker))
        self._workers.append(worker)
        worker.start()

    def _stop_session(self) -> None:
        """停止选中的会话"""
        session_id = self._get_selected_session_id()
        if not session_id:
            return
        self._set_status(self.tr("正在停止会话..."))
        worker = SessionWorker(self._backend, "stop", session_id)
        worker.command_done.connect(self._on_command_done)
        worker.error.connect(self._on_error)
        worker.finished.connect(lambda: self._cleanup_worker(worker))
        self._workers.append(worker)
        worker.start()

    def _remove_session(self) -> None:
        """删除选中的会话"""
        session_id = self._get_selected_session_id()
        if not session_id:
            return
        reply = QMessageBox.question(
            self, self.tr("确认删除"),
            self.tr("确定要删除会话「{}」吗？此操作不可撤销。").format(session_id[:8]),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        self._set_status(self.tr("正在删除会话..."))
        worker = SessionWorker(self._backend, "remove", session_id)
        worker.command_done.connect(self._on_command_done)
        worker.error.connect(self._on_error)
        worker.finished.connect(lambda: self._cleanup_worker(worker))
        self._workers.append(worker)
        worker.start()

    def _resume_session(self, index) -> None:
        """双击恢复会话 - emit 信号"""
        row = index.row()
        if row < 0 or row >= len(self._sessions):
            return
        session = self._sessions[row]
        full_id = session.get("id", "")
        if full_id:
            cmd = f"claude --resume {full_id}"
            self.open_terminal_requested.emit(cmd)
            logger.info(f"请求恢复会话: {cmd}")

    # ─── 内部方法 ───

    def _get_selected_session_id(self) -> Optional[str]:
        """获取当前选中行的完整 session_id"""
        row = self._table.currentRow()
        if row < 0 or row >= len(self._sessions):
            QMessageBox.information(
                self, self.tr("提示"), self.tr("请先选择一个会话")
            )
            return None
        return self._sessions[row].get("id", "")

    def _on_sessions_loaded(self, sessions: list) -> None:
        """会话列表加载完成回调"""
        self._sessions = sessions
        self._render_table()
        self._btn_refresh.setEnabled(True)
        count = len(sessions)
        self._set_status(self.tr("共 {} 个会话").format(count))

    def _on_command_done(self, desc: str, output: str) -> None:
        """命令执行完成回调 - 显示状态并自动刷新"""
        self._set_status(f"{desc}: {output}")
        self.refresh()

    def _on_error(self, err_msg: str) -> None:
        """错误回调"""
        self._btn_refresh.setEnabled(True)
        self._set_status(f"❌ {err_msg}")
        logger.error(f"SessionWidget 错误: {err_msg}")

    def _cleanup_worker(self, worker: SessionWorker) -> None:
        """清理已完成的 worker 引用"""
        if worker in self._workers:
            self._workers.remove(worker)

    def _render_table(self) -> None:
        """将会话列表渲染到表格"""
        self._table.setRowCount(0)
        self._table.setRowCount(len(self._sessions))

        for row, session in enumerate(self._sessions):
            # ID（短 ID，前 8 位）
            full_id = session.get("id", "")
            short_id = full_id[:8] if len(full_id) > 8 else full_id
            id_item = QTableWidgetItem(short_id)
            id_item.setToolTip(full_id)
            self._table.setItem(row, 0, id_item)

            # 名称
            name = session.get("name", "") or session.get("prompt", "")
            name_item = QTableWidgetItem(name)
            name_item.setToolTip(name)
            self._table.setItem(row, 1, name_item)

            # 状态（带颜色圆点指示）
            status = session.get("status", "unknown")
            status_item = QTableWidgetItem(f"  {status}")
            if status.lower() == "running":
                status_item.setForeground(QBrush(QColor("#4caf50")))
            else:
                status_item.setForeground(QBrush(QColor("#888888")))
            self._table.setItem(row, 2, status_item)

            # 创建时间
            created = session.get("created_at", "") or session.get("createdAt", "")
            time_item = QTableWidgetItem(created)
            self._table.setItem(row, 3, time_item)

    def _set_status(self, text: str) -> None:
        """更新底部状态文字"""
        self._status_label.setText(text)
