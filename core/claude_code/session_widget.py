# -*- coding: utf-8 -*-
"""Claude Code 会话管理模块 - 支持会话列表/新建后台任务/停止/删除/恢复"""

import logging
import os
import shlex

from PySide6.QtCore import QThread, Signal, QDateTime, Qt
from PySide6.QtGui import QColor, QBrush, QFont
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                               QTreeWidget, QTreeWidgetItem, QHeaderView,
                               QLabel, QAbstractItemView)

logger = logging.getLogger(__name__)


class SessionWorker(QThread):
    """后台线程加载会话列表，避免阻塞 UI"""

    sessions_loaded = Signal(list)       # 会话列表加载完成
    error = Signal(str)                  # 错误信息

    def __init__(self, backend):
        super().__init__()
        self._backend = backend

    def run(self):
        try:
            sessions = self._backend.list_sessions()
            self.sessions_loaded.emit(sessions)
        except Exception as e:
            logger.exception("SessionWorker 加载会话列表异常")
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

        # 当前 claude CLI 无 agents stop/remove 与 --bg 子命令，
        # 故不提供停止/删除/新建后台任务按钮，仅支持列表查看与双击恢复。
        hint = QLabel(self.tr("双击会话可在终端中恢复，双击项目可展开/折叠"))
        hint.setStyleSheet("color: #888888;")
        toolbar_layout.addWidget(hint)

        toolbar_layout.addStretch()
        main_layout.addLayout(toolbar_layout)

        # ─── 会话树（按项目分组） ───
        self._tree = QTreeWidget()
        self._tree.setColumnCount(4)
        self._tree.setHeaderLabels([
            self.tr("名称"), self.tr("ID"), self.tr("状态"), self.tr("创建时间")
        ])
        self._tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self._tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._tree.setAlternatingRowColors(True)
        self._tree.setRootIsDecorated(True)
        self._tree.setUniformRowHeights(True)

        # 列宽策略：名称列自适应拉伸，其余列固定/紧凑
        header = self._tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Interactive)
        self._tree.setColumnWidth(3, 160)

        # 双击会话恢复；双击项目分组则展开/折叠
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)

        self._tree.setStyleSheet("""
            QTreeWidget {
                background-color: #1e1e1e;
                border: 1px solid #333333;
            }
            QTreeWidget::item {
                padding: 4px 6px;
            }
            QTreeWidget::item:selected {
                background-color: #2a4a6b;
            }
            QHeaderView::section {
                background-color: #2a2a2a;
                border: 1px solid #333333;
                padding: 4px 8px;
                color: #cccccc;
            }
        """)

        main_layout.addWidget(self._tree)

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
        worker = SessionWorker(self._backend)
        worker.sessions_loaded.connect(self._on_sessions_loaded)
        worker.error.connect(self._on_error)
        worker.finished.connect(lambda: self._cleanup_worker(worker))
        self._workers.append(worker)
        worker.start()

    def _on_item_double_clicked(self, item, column) -> None:
        """双击树节点：会话→恢复；项目分组→展开/折叠"""
        session = item.data(0, Qt.UserRole)
        if not session:
            item.setExpanded(not item.isExpanded())
            return
        self._resume_session(session)

    def _resume_session(self, session: dict) -> None:
        """在终端恢复指定会话 - emit 信号"""
        full_id = self._session_id_at_static(session)
        if not full_id:
            return
        # claude 的会话是按工作目录（project）划分的，--resume 只能在该会话
        # 所属的 cwd 下找到对应记录，否则报 "No conversation found"。
        # 因此优先 cd 到会话的 cwd 再执行 resume。
        cwd = session.get("cwd", "")
        if cwd:
            cmd = f"cd {shlex.quote(str(cwd))} && claude --resume {full_id}"
        else:
            cmd = f"claude --resume {full_id}"
        self.open_terminal_requested.emit(cmd)
        logger.info(f"请求恢复会话: {cmd}")

    # ─── 内部方法 ───

    @staticmethod
    def _session_id_at_static(session: dict) -> str:
        """从单条会话记录提取完整 session_id（兼容多种字段名）"""
        return (
            session.get("sessionId")
            or session.get("id")
            or session.get("session_id")
            or ""
        )

    def _on_sessions_loaded(self, sessions: list) -> None:
        """会话列表加载完成回调"""
        self._sessions = sessions
        self._render_tree()
        self._btn_refresh.setEnabled(True)
        count = len(sessions)
        project_count = len({s.get("cwd", "") for s in sessions})
        self._set_status(
            self.tr("共 {} 个会话，{} 个项目").format(count, project_count)
        )

    def _on_error(self, err_msg: str) -> None:
        """错误回调"""
        self._btn_refresh.setEnabled(True)
        self._set_status(f"❌ {err_msg}")
        logger.error(f"SessionWidget 错误: {err_msg}")

    def _cleanup_worker(self, worker: SessionWorker) -> None:
        """清理已完成的 worker 引用"""
        if worker in self._workers:
            self._workers.remove(worker)

    def _render_tree(self) -> None:
        """按项目（cwd）分组渲染会话树。"""
        # 记录刷新前展开的项目，刷新后保持其展开状态
        previously_expanded = self._expanded_projects()
        first_load = not previously_expanded and self._tree.topLevelItemCount() == 0

        self._tree.clear()

        # 按 cwd 分组，保持会话原有顺序（已按创建时间降序）
        groups: dict[str, list] = {}
        for session in self._sessions:
            cwd = session.get("cwd") or ""
            groups.setdefault(cwd, []).append(session)

        for cwd, items in groups.items():
            group_item = self._make_group_item(cwd, items)
            self._tree.addTopLevelItem(group_item)
            for session in items:
                group_item.addChild(self._make_session_item(session))
            # 默认全部展开；刷新后保留用户之前的展开/折叠状态
            if first_load or cwd in previously_expanded:
                group_item.setExpanded(True)

    def _make_group_item(self, cwd: str, sessions: list) -> QTreeWidgetItem:
        """创建项目分组节点。"""
        display = cwd or self.tr("（未知项目）")
        basename = os.path.basename(cwd.rstrip("/")) if cwd else display
        running = sum(1 for s in sessions
                      if str(s.get("status", "")).lower()
                      in ("running", "busy", "idle", "active"))
        label = f"📁 {basename}  ·  {len(sessions)}"
        if running:
            label += self.tr("（{} 运行中）").format(running)
        item = QTreeWidgetItem([label, "", "", ""])
        item.setToolTip(0, display)
        item.setData(0, Qt.UserRole + 1, cwd)  # 标记为分组（无会话数据）
        font = QFont()
        font.setBold(True)
        item.setFont(0, font)
        item.setForeground(0, QBrush(QColor("#dcb67a")))
        return item

    def _make_session_item(self, session: dict) -> QTreeWidgetItem:
        """创建会话子节点。"""
        full_id = self._session_id_at_static(session)
        short_id = full_id[:8] if len(full_id) > 8 else full_id
        name = session.get("name") or session.get("prompt") or self.tr("(无标题)")
        status = str(session.get("status", "unknown"))
        created = self._format_started_at(session)

        item = QTreeWidgetItem([name, short_id, status, created])
        item.setToolTip(0, name)
        item.setToolTip(1, full_id)
        if status.lower() in ("running", "busy", "idle", "active"):
            item.setForeground(2, QBrush(QColor("#4caf50")))
        else:
            item.setForeground(2, QBrush(QColor("#888888")))
        item.setData(0, Qt.UserRole, session)  # 携带完整会话数据供恢复使用
        return item

    def _expanded_projects(self) -> set:
        """返回当前处于展开状态的项目 cwd 集合。"""
        expanded = set()
        for i in range(self._tree.topLevelItemCount()):
            top = self._tree.topLevelItem(i)
            if top.isExpanded():
                expanded.add(top.data(0, Qt.UserRole + 1) or "")
        return expanded

    @staticmethod
    def _format_started_at(session: dict) -> str:
        """格式化创建时间：startedAt 为毫秒时间戳，回退到文本字段。"""
        raw = session.get("startedAt")
        if isinstance(raw, (int, float)) and raw > 0:
            dt = QDateTime.fromMSecsSinceEpoch(int(raw))
            return dt.toString("yyyy-MM-dd HH:mm")
        return str(
            session.get("created_at") or session.get("createdAt") or ""
        )

    def _set_status(self, text: str) -> None:
        """更新底部状态文字"""
        self._status_label.setText(text)
