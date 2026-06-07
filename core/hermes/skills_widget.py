# -*- coding: utf-8 -*-
"""Hermes Agent Skills 管理模块 - 浏览、安装、删除 Skills"""

import os
import re

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
                                QLabel, QPushButton, QLineEdit, QListWidget,
                                QListWidgetItem, QTextBrowser, QMessageBox,
                                QInputDialog, QGroupBox, QFrame)
from PySide6.QtCore import Qt, QThread, Signal, QSize

from function.util import logger


class SkillsWorker(QThread):
    """后台线程执行 Skills 相关操作，避免阻塞 UI"""
    skills_loaded = Signal(list)     # [{name, description, version, tags, content}, ...]
    command_done = Signal(str, str)  # (description, output)
    error = Signal(str)

    def __init__(self, backend, action, **kwargs):
        super().__init__()
        self._backend = backend
        self._action = action
        self._kwargs = kwargs

    def run(self):
        try:
            if self._action == "load_skills":
                self._load_skills()
            elif self._action == "install_skill":
                self._install_skill()
            elif self._action == "delete_skill":
                self._delete_skill()
        except Exception as e:
            logger.error(f"SkillsWorker 异常: {e}")
            self.error.emit(str(e))

    def _load_skills(self):
        hermes_home = self._backend.get_hermes_home()
        skills_dir = os.path.join(hermes_home, "skills")

        if not self._backend.file_exists(skills_dir):
            self.skills_loaded.emit([])
            return

        # skills 目录结构不固定，可能是：
        #   skills/{category}/SKILL.md              (分类级 skill)
        #   skills/{category}/{skill-name}/SKILL.md (两级)
        #   skills/{category}/{sub}/{skill}/SKILL.md(三级)
        # 采用递归查找 SKILL.md 的方式，找到即视为一个 skill
        skills = []
        self._find_skills_recursive(skills_dir, skills_dir, skills, max_depth=4)
        self.skills_loaded.emit(skills)

    def _find_skills_recursive(self, base_dir, current_dir, skills, max_depth=4, depth=0):
        """递归查找包含 SKILL.md 的目录"""
        if depth > max_depth:
            return

        entries = self._backend.list_dir(current_dir)
        if not entries:
            return

        # 先检查当前目录是否包含 SKILL.md
        has_skill_md = False
        if depth > 0:  # 跳过根 skills/ 目录本身
            content = None
            if "SKILL.md" in entries:
                md_path = os.path.join(current_dir, "SKILL.md")
                content = self._backend.read_file(md_path)
            if not content and "skill.md" in entries:
                md_path = os.path.join(current_dir, "skill.md")
                content = self._backend.read_file(md_path)

            if content:
                has_skill_md = True
                # 解析并记录这个 skill
                rel_path = os.path.relpath(current_dir, base_dir)
                parts = rel_path.split(os.sep)
                category = parts[0] if parts else ""
                dir_name = parts[-1] if parts else ""

                meta = _parse_frontmatter(content)
                skills.append({
                    "name": meta.get("name", dir_name),
                    "description": meta.get("description", ""),
                    "version": meta.get("version", ""),
                    "author": meta.get("author", ""),
                    "tags": meta.get("tags", []),
                    "category": category,
                    "content": content,
                    "dir_name": dir_name,
                })

        # 继续递归子目录查找更多 skills
        # （即使当前目录有 SKILL.md，子目录仍可能有独立的 skill）
        for entry in entries:
            if entry.startswith('.') or entry.endswith('.md'):
                continue
            # 跳过常见非 skill 资源目录
            if entry in ("references", "templates", "assets", "examples", "__pycache__"):
                continue
            sub_path = os.path.join(current_dir, entry)
            # 只递归目录
            if self._backend.file_exists(os.path.join(sub_path, ".")):
                # 判断是否为目录（通过尝试 list_dir）
                sub_entries = self._backend.list_dir(sub_path)
                if sub_entries is not None:
                    self._find_skills_recursive(base_dir, sub_path, skills, max_depth, depth + 1)

    def _install_skill(self):
        name = self._kwargs.get("name", "")
        if not name:
            self.error.emit("Skill 名称不能为空")
            return
        output = self._backend.exec_cli(["skills", "install", name])
        self.command_done.emit(f"安装 Skill: {name}", output)

    def _delete_skill(self):
        name = self._kwargs.get("name", "")
        if not name:
            self.error.emit("Skill 名称不能为空")
            return
        output = self._backend.exec_cli(["skills", "remove", name])
        self.command_done.emit(f"删除 Skill: {name}", output)


def _parse_frontmatter(content: str) -> dict:
    """解析 SKILL.md 的 YAML frontmatter（--- 分隔的头部），不依赖 PyYAML"""
    if not content or not content.strip().startswith("---"):
        return {}

    # 找到前后两个 ---
    match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if not match:
        return {}

    frontmatter_text = match.group(1)
    meta = {}

    for line in frontmatter_text.split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        # 解析 key: value
        kv_match = re.match(r'^(\w+)\s*:\s*(.+)$', line)
        if kv_match:
            key = kv_match.group(1)
            value = kv_match.group(2).strip()

            # 解析数组格式 [tag1, tag2, ...]
            if value.startswith('[') and value.endswith(']'):
                items = value[1:-1].split(',')
                meta[key] = [item.strip().strip('"').strip("'") for item in items if item.strip()]
            else:
                # 去除引号
                meta[key] = value.strip('"').strip("'")

    return meta


class SkillsWidget(QWidget):
    """Hermes Agent Skills 管理面板"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._backend = None
        self._skills = []       # 当前加载的所有 skill 数据
        self._worker = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter)

        # ======== 左侧：Skill 列表 ========
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # 搜索/过滤栏
        search_layout = QHBoxLayout()
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText(self.tr("搜索 Skill..."))
        self._search_input.textChanged.connect(self._filter_skills)
        search_layout.addWidget(self._search_input)
        left_layout.addLayout(search_layout)

        # Skill 列表
        self._skill_list = QListWidget()
        self._skill_list.setSpacing(2)
        self._skill_list.setAlternatingRowColors(True)
        self._skill_list.currentItemChanged.connect(self._show_skill_detail)
        left_layout.addWidget(self._skill_list)

        # 操作按钮
        btn_layout = QHBoxLayout()
        self._refresh_btn = QPushButton(self.tr("刷新"))
        self._refresh_btn.clicked.connect(self._load_skills)
        btn_layout.addWidget(self._refresh_btn)

        self._install_btn = QPushButton(self.tr("安装"))
        self._install_btn.clicked.connect(self._install_skill)
        btn_layout.addWidget(self._install_btn)

        self._delete_btn = QPushButton(self.tr("删除"))
        self._delete_btn.clicked.connect(self._delete_selected_skill)
        btn_layout.addWidget(self._delete_btn)

        left_layout.addLayout(btn_layout)
        splitter.addWidget(left_widget)

        # ======== 右侧：Skill 详情 ========
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        detail_group = QGroupBox(self.tr("Skill 详情"))
        detail_layout = QVBoxLayout(detail_group)

        # 标题区域
        self._name_label = QLabel()
        self._name_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        detail_layout.addWidget(self._name_label)

        # 版本 + 作者
        info_layout = QHBoxLayout()
        self._version_label = QLabel()
        self._version_label.setStyleSheet("color: #666;")
        info_layout.addWidget(self._version_label)
        self._author_label = QLabel()
        self._author_label.setStyleSheet("color: #666;")
        info_layout.addWidget(self._author_label)
        info_layout.addStretch()
        detail_layout.addLayout(info_layout)

        # 标签区域
        self._tags_frame = QFrame()
        self._tags_layout = QHBoxLayout(self._tags_frame)
        self._tags_layout.setContentsMargins(0, 4, 0, 4)
        self._tags_layout.setSpacing(6)
        detail_layout.addWidget(self._tags_frame)

        # 内容区域
        self._content_browser = QTextBrowser()
        self._content_browser.setOpenExternalLinks(True)
        detail_layout.addWidget(self._content_browser)

        right_layout.addWidget(detail_group)
        splitter.addWidget(right_widget)

        # 设置分割比例
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        # 初始状态
        self._clear_detail()

    def set_backend(self, backend):
        """设置后端引用（不触发加载）"""
        self._backend = backend

    def refresh(self):
        """当 Tab 被选中时调用，触发数据加载"""
        self._load_skills()

    def _load_skills(self):
        """遍历 ~/.hermes/skills/ 目录，加载所有 skill 信息"""
        if not self._backend:
            return

        self._refresh_btn.setEnabled(False)
        self._worker = SkillsWorker(self._backend, "load_skills")
        self._worker.skills_loaded.connect(self._on_skills_loaded)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(lambda: self._refresh_btn.setEnabled(True))
        self._worker.start()

    def _on_skills_loaded(self, skills: list):
        """加载完成后更新列表"""
        self._skills = skills
        self._populate_list(skills)

    def _populate_list(self, skills: list):
        """填充 skill 列表控件"""
        self._skill_list.clear()
        if not skills:
            item = QListWidgetItem(self.tr("暂无已安装的 Skills"))
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            self._skill_list.addItem(item)
            self._clear_detail()
            return

        for skill in skills:
            name = skill.get("name", "unknown")
            category = skill.get("category", "")
            # 单行显示：名称 + 分类标签，清爽易读
            display_text = name
            if category:
                display_text += f"  [{category}]"
            item = QListWidgetItem(display_text)
            item.setData(Qt.UserRole, skill)
            item.setSizeHint(item.sizeHint().expandedTo(QSize(0, 28)))
            self._skill_list.addItem(item)

    def _show_skill_detail(self, current: QListWidgetItem, _previous=None):
        """显示选中 skill 的详情"""
        if not current:
            self._clear_detail()
            return

        skill = current.data(Qt.UserRole)
        if not skill:
            self._clear_detail()
            return

        # 名称
        self._name_label.setText(skill.get("name", ""))

        # 版本 + 作者
        version = skill.get("version", "")
        self._version_label.setText(f"v{version}" if version else "")
        author = skill.get("author", "")
        self._author_label.setText(f"作者: {author}" if author else "")

        # 标签
        self._clear_tags()
        tags = skill.get("tags", [])
        for tag in tags:
            tag_label = QLabel(tag)
            tag_label.setStyleSheet(
                "background-color: #e0e7ff; color: #3730a3; "
                "border-radius: 4px; padding: 2px 8px; font-size: 12px;"
            )
            self._tags_layout.addWidget(tag_label)
        self._tags_layout.addStretch()

        # Markdown 内容
        content = skill.get("content", "")
        # 去掉 frontmatter 部分，只显示正文
        body = re.sub(r'^---\s*\n.*?\n---\s*\n?', '', content, flags=re.DOTALL)
        self._content_browser.setMarkdown(body.strip())

    def _clear_detail(self):
        """清空右侧详情"""
        self._name_label.setText(self.tr("选择一个 Skill 查看详情"))
        self._version_label.setText("")
        self._author_label.setText("")
        self._clear_tags()
        self._content_browser.clear()

    def _clear_tags(self):
        """清空标签区域"""
        while self._tags_layout.count():
            child = self._tags_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def _install_skill(self):
        """弹出输入框安装新 skill"""
        if not self._backend:
            return

        name, ok = QInputDialog.getText(
            self,
            self.tr("安装 Skill"),
            self.tr("请输入 Skill 名称或 GitHub 路径："),
        )
        if not ok or not name.strip():
            return

        name = name.strip()
        self._install_btn.setEnabled(False)
        self._worker = SkillsWorker(self._backend, "install_skill", name=name)
        self._worker.command_done.connect(self._on_command_done)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(lambda: self._install_btn.setEnabled(True))
        self._worker.start()

    def _delete_selected_skill(self):
        """删除选中的 skill"""
        if not self._backend:
            return

        current = self._skill_list.currentItem()
        if not current:
            return
        skill = current.data(Qt.UserRole)
        if not skill:
            return

        name = skill.get("dir_name") or skill.get("name", "")
        reply = QMessageBox.question(
            self,
            self.tr("确认删除"),
            self.tr(f"确定要删除 Skill「{name}」吗？"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self._delete_btn.setEnabled(False)
        self._worker = SkillsWorker(self._backend, "delete_skill", name=name)
        self._worker.command_done.connect(self._on_command_done)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(lambda: self._delete_btn.setEnabled(True))
        self._worker.start()

    def _filter_skills(self, text: str):
        """根据搜索文本过滤列表"""
        if not text.strip():
            self._populate_list(self._skills)
            return

        keyword = text.strip().lower()
        filtered = [
            s for s in self._skills
            if keyword in s.get("name", "").lower()
            or keyword in s.get("description", "").lower()
            or any(keyword in t.lower() for t in s.get("tags", []))
        ]
        self._populate_list(filtered)

    def _on_command_done(self, description: str, output: str):
        """命令执行完成回调"""
        QMessageBox.information(self, self.tr("操作完成"), f"{description}\n\n{output}")
        # 重新加载列表
        self._load_skills()

    def _on_error(self, msg: str):
        """错误回调"""
        QMessageBox.warning(self, self.tr("错误"), msg)
