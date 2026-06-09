"""Skill 加载器 - 递归扫描并加载 ~/.cube-shell/skills/ 目录下的 Skill 定义。"""

import logging
import os
import re
from typing import Optional

logger = logging.getLogger(__name__)


class SkillLoader:
    """加载和管理 AI 助手的 Skill 技能。"""

    # 默认 Skills 目录
    DEFAULT_SKILLS_DIR = os.path.join(os.path.expanduser("~"), ".cube-shell", "skills")

    # 最大递归深度
    MAX_DEPTH = 4

    # 跳过的目录名
    SKIP_DIRS = {
        ".git", "__pycache__", "venv", ".venv",
        "node_modules", "examples", "references", "templates", "assets",
    }

    def __init__(self, skills_dir: str = None):
        """初始化 Skill 加载器。

        Args:
            skills_dir: Skills 根目录，默认 ~/.cube-shell/skills/
        """
        self._skills_dir = skills_dir or self.DEFAULT_SKILLS_DIR
        self._skills: list[dict] = []

    @property
    def skills(self) -> list[dict]:
        """已加载的 Skill 列表。"""
        return self._skills

    def load_all_skills(self) -> list[dict]:
        """扫描并加载所有 Skill。

        Returns:
            Skill 字典列表，每个包含:
            - name: Skill 名称
            - version: 版本号
            - description: 用途说明
            - keywords: 关键词列表
            - allowed_tools: 允许的工具列表
            - content: Skill 正文（去掉 frontmatter）
            - path: Skill 目录的绝对路径
            - has_scripts: 是否包含 scripts/ 目录
            - scripts_dir: scripts 目录绝对路径（仅当 has_scripts 为 True）
        """
        self._skills = []
        skills_dir = self._skills_dir

        if not os.path.isdir(skills_dir):
            logger.warning("Skills 目录不存在: %s", skills_dir)
            return self._skills

        self._find_skills_recursive(skills_dir, skills_dir, self._skills, depth=0)
        logger.info("已加载 %d 个 Skill", len(self._skills))
        return self._skills

    def load_skill(self, skill_name: str) -> Optional[dict]:
        """加载指定名称的 Skill。

        Args:
            skill_name: Skill 名称（匹配 name 字段或目录名）

        Returns:
            Skill 字典，未找到返回 None
        """
        if not self._skills:
            self.load_all_skills()

        for skill in self._skills:
            if skill["name"] == skill_name or skill.get("dir_name") == skill_name:
                return skill
        return None

    def reload(self) -> list[dict]:
        """重新扫描并加载所有 Skill（刷新缓存）。"""
        self._skills = []
        return self.load_all_skills()

    # ------------------------------------------------------------------
    # 内部递归扫描
    # ------------------------------------------------------------------

    def _find_skills_recursive(self, base_dir: str, current_dir: str,
                               skills: list, depth: int = 0):
        """递归查找包含 SKILL.md 的目录。"""
        if depth > self.MAX_DEPTH:
            return

        try:
            entries = os.listdir(current_dir)
        except OSError as e:
            logger.debug("无法列出目录 %s: %s", current_dir, e)
            return

        # 先检查当前目录是否包含 SKILL.md（跳过根目录本身）
        if depth > 0:
            content = None
            md_path = None

            if "SKILL.md" in entries:
                md_path = os.path.join(current_dir, "SKILL.md")
            elif "skill.md" in entries:
                md_path = os.path.join(current_dir, "skill.md")

            if md_path:
                try:
                    with open(md_path, "r", encoding="utf-8") as f:
                        content = f.read()
                except OSError as e:
                    logger.warning("读取 %s 失败: %s", md_path, e)

            if content:
                try:
                    skill_info = self._build_skill_info(base_dir, current_dir, content)
                    skills.append(skill_info)
                except Exception as e:
                    logger.warning("解析 Skill 失败 (%s): %s", current_dir, e)

        # 继续递归子目录
        for entry in sorted(entries):
            # 跳过隐藏目录
            if entry.startswith('.'):
                continue
            # 跳过 .md 文件（非目录）
            if entry.endswith('.md'):
                continue
            # 跳过指定目录
            if entry in self.SKIP_DIRS:
                continue

            sub_path = os.path.join(current_dir, entry)
            if os.path.isdir(sub_path):
                self._find_skills_recursive(base_dir, sub_path, skills, depth + 1)

    def _build_skill_info(self, base_dir: str, skill_dir: str, content: str) -> dict:
        """构建 Skill 信息字典。"""
        meta, body = self.parse_frontmatter(content)

        rel_path = os.path.relpath(skill_dir, base_dir)
        parts = rel_path.split(os.sep)
        dir_name = parts[-1] if parts else ""
        category = parts[0] if len(parts) > 1 else ""

        # 检测 scripts/ 子目录
        scripts_path = os.path.join(skill_dir, "scripts")
        has_scripts = os.path.isdir(scripts_path)

        # 解析 keywords
        keywords = meta.get("keywords", [])
        if isinstance(keywords, str):
            keywords = [k.strip() for k in keywords.split(",") if k.strip()]

        # 解析 allowed-tools
        allowed_tools = meta.get("allowed-tools", meta.get("allowed_tools", []))
        if isinstance(allowed_tools, str):
            allowed_tools = [t.strip() for t in allowed_tools.split(",") if t.strip()]

        skill_info = {
            "name": meta.get("name", dir_name),
            "version": meta.get("version", ""),
            "description": meta.get("description", ""),
            "keywords": keywords,
            "allowed_tools": allowed_tools,
            "content": body,
            "path": os.path.abspath(skill_dir),
            "has_scripts": has_scripts,
            "dir_name": dir_name,
            "category": category,
        }

        if has_scripts:
            skill_info["scripts_dir"] = os.path.abspath(scripts_path)

        return skill_info

    # ------------------------------------------------------------------
    # 静态解析方法
    # ------------------------------------------------------------------

    @staticmethod
    def parse_frontmatter(text: str) -> tuple[dict, str]:
        """解析 YAML frontmatter。

        Args:
            text: 完整的 SKILL.md 文本内容

        Returns:
            (metadata_dict, body_text) 元组
            metadata_dict 包含: name, version, description, keywords, allowed-tools 等
            body_text 是去掉 frontmatter 后的正文
        """
        if not text or not text.strip().startswith("---"):
            return {}, text or ""

        # 找到前后两个 ---
        match = re.match(r'^---\s*\n(.*?)\n---\s*\n?', text, re.DOTALL)
        if not match:
            return {}, text

        frontmatter_text = match.group(1)
        body = text[match.end():]
        meta = {}

        for line in frontmatter_text.split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            # 解析 key: value（支持带连字符的 key，如 allowed-tools）
            kv_match = re.match(r'^([\w-]+)\s*:\s*(.+)$', line)
            if kv_match:
                key = kv_match.group(1)
                value = kv_match.group(2).strip()

                # 解析数组格式 [item1, item2, ...]
                if value.startswith('[') and value.endswith(']'):
                    items = value[1:-1].split(',')
                    meta[key] = [
                        item.strip().strip('"').strip("'")
                        for item in items if item.strip()
                    ]
                else:
                    # 去除首尾引号
                    meta[key] = value.strip('"').strip("'")

        return meta, body
