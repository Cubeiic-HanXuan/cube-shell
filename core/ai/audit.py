"""
AI 审计日志模块

记录所有通过 AI 模块执行的 SSH 命令，支持查询、导出和统计。
使用 SQLite 存储，线程安全。
"""

import csv
import io
import json
import os
import sqlite3
import threading
import time

import appdirs

# 数据库表结构
_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ai_audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    timestamp   REAL NOT NULL,
    host        TEXT NOT NULL,
    port        INTEGER DEFAULT 22,
    username    TEXT NOT NULL,
    command     TEXT NOT NULL,
    source      TEXT NOT NULL,
    risk_level  TEXT NOT NULL,
    exit_code   INTEGER,
    stdout_snippet TEXT DEFAULT '',
    stderr_snippet TEXT DEFAULT '',
    ai_input    TEXT DEFAULT '',
    ai_model    TEXT DEFAULT '',
    duration_ms INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_audit_host ON ai_audit_log(host);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON ai_audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_risk ON ai_audit_log(risk_level);
"""

# 收藏表结构
_FAVORITES_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ai_favorites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    command TEXT NOT NULL,
    description TEXT DEFAULT '',
    category TEXT DEFAULT 'general',
    use_count INTEGER DEFAULT 0,
    created_at REAL NOT NULL,
    last_used_at REAL
);
"""

# FTS5 全文检索虚拟表
_FTS_SCHEMA_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS ai_audit_fts
    USING fts5(command, ai_input, content=ai_audit_log, content_rowid=id);

CREATE TRIGGER IF NOT EXISTS ai_audit_fts_insert AFTER INSERT ON ai_audit_log BEGIN
    INSERT INTO ai_audit_fts(rowid, command, ai_input) VALUES (new.id, new.command, new.ai_input);
END;

CREATE TRIGGER IF NOT EXISTS ai_audit_fts_delete AFTER DELETE ON ai_audit_log BEGIN
    INSERT INTO ai_audit_fts(ai_audit_fts, rowid, command, ai_input) VALUES ('delete', old.id, old.command, old.ai_input);
END;
"""

# 有效的 source 值
VALID_SOURCES = ("user", "ai_auto", "ai_confirmed")

# 有效的 risk_level 值
VALID_RISK_LEVELS = ("safe", "low", "medium", "high")

# 默认保留策略（天数）
DEFAULT_RETENTION_DAYS = {
    "safe": 7,
    "low": 30,
    "medium": 90,
    "high": 365,
}


class AuditLogger:
    """AI 命令执行审计日志记录器"""

    def __init__(self, db_path: str = None):
        """
        初始化审计日志数据库。
        db_path 默认使用 appdirs.user_data_dir('cube-shell') + '/ai_audit.db'
        """
        if db_path is None:
            data_dir = appdirs.user_data_dir("cube-shell", appauthor=False)
            os.makedirs(data_dir, exist_ok=True)
            db_path = os.path.join(data_dir, "ai_audit.db")

        self._db_path = db_path
        self._lock = threading.Lock()

        # 确保数据库目录存在
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        # 初始化数据库表结构
        self._init_db()

    def _init_db(self):
        """初始化数据库，创建表和索引"""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.executescript(_SCHEMA_SQL)
                conn.executescript(_FAVORITES_SCHEMA_SQL)
                self._init_fts(conn)
                conn.commit()
            finally:
                conn.close()

    def _init_fts(self, conn: sqlite3.Connection):
        """创建 FTS5 全文检索虚拟表和同步触发器"""
        try:
            conn.executescript(_FTS_SCHEMA_SQL)
        except sqlite3.OperationalError:
            # FTS5 扩展不可用时静默跳过
            pass

    def _get_connection(self) -> sqlite3.Connection:
        """获取数据库连接"""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def log_command(
        self,
        *,
        session_id: str,
        host: str,
        username: str,
        command: str,
        source: str,
        risk_level: str,
        port: int = 22,
        exit_code: int = None,
        stdout_snippet: str = "",
        stderr_snippet: str = "",
        ai_input: str = "",
        ai_model: str = "",
        duration_ms: int = 0,
    ) -> None:
        """
        记录一条命令执行审计日志。

        参数:
            session_id: 会话标识
            host: 目标主机地址
            username: 执行用户名
            command: 执行的命令
            source: 命令来源 ("user" | "ai_auto" | "ai_confirmed")
            risk_level: 风险等级 ("safe" | "low" | "medium" | "high")
            port: SSH 端口，默认 22
            exit_code: 命令退出码
            stdout_snippet: 标准输出片段
            stderr_snippet: 标准错误片段
            ai_input: AI 输入的原始提示
            ai_model: 使用的 AI 模型名称
            duration_ms: 命令执行耗时（毫秒）
        """
        # 参数校验
        if source not in VALID_SOURCES:
            raise ValueError(
                f"无效的 source 值: {source!r}，"
                f"有效值为: {VALID_SOURCES}"
            )
        if risk_level not in VALID_RISK_LEVELS:
            raise ValueError(
                f"无效的 risk_level 值: {risk_level!r}，"
                f"有效值为: {VALID_RISK_LEVELS}"
            )

        timestamp = time.time()

        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute(
                    """
                    INSERT INTO ai_audit_log
                        (session_id, timestamp, host, port, username, command,
                         source, risk_level, exit_code, stdout_snippet,
                         stderr_snippet, ai_input, ai_model, duration_ms)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        timestamp,
                        host,
                        port,
                        username,
                        command,
                        source,
                        risk_level,
                        exit_code,
                        stdout_snippet,
                        stderr_snippet,
                        ai_input,
                        ai_model,
                        duration_ms,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def query_history(
        self,
        host: str = None,
        time_range: tuple = None,
        risk_level: str = None,
        source: str = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """
        查询审计日志历史。

        参数:
            host: 按主机筛选
            time_range: 时间范围元组 (start_timestamp, end_timestamp)
            risk_level: 按风险等级筛选
            source: 按来源筛选
            limit: 返回记录数上限，默认 100
            offset: 分页偏移量，默认 0

        返回:
            审计日志记录列表
        """
        conditions = []
        params = []

        if host is not None:
            conditions.append("host = ?")
            params.append(host)

        if time_range is not None:
            start_ts, end_ts = time_range
            conditions.append("timestamp >= ? AND timestamp <= ?")
            params.extend([start_ts, end_ts])

        if risk_level is not None:
            if risk_level not in VALID_RISK_LEVELS:
                raise ValueError(
                    f"无效的 risk_level 值: {risk_level!r}，"
                    f"有效值为: {VALID_RISK_LEVELS}"
                )
            conditions.append("risk_level = ?")
            params.append(risk_level)

        if source is not None:
            if source not in VALID_SOURCES:
                raise ValueError(
                    f"无效的 source 值: {source!r}，"
                    f"有效值为: {VALID_SOURCES}"
                )
            conditions.append("source = ?")
            params.append(source)

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        query = f"""
            SELECT * FROM ai_audit_log
            {where_clause}
            ORDER BY timestamp DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        conn = self._get_connection()
        try:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def export(self, format: str = "json", path: str = None, **filters) -> str:
        """
        导出审计日志为 JSON 或 CSV 格式。

        参数:
            format: 导出格式，"json" 或 "csv"
            path: 导出文件路径，为 None 时返回字符串内容
            **filters: 传递给 query_history 的筛选参数

        返回:
            导出内容的字符串（如果 path 为 None），否则返回文件路径
        """
        if format not in ("json", "csv"):
            raise ValueError(
                f"不支持的导出格式: {format!r}，支持 'json' 和 'csv'"
            )

        # 导出时不限制数量，除非调用者指定了 limit
        if "limit" not in filters:
            filters["limit"] = 999999999

        records = self.query_history(**filters)

        if format == "json":
            content = json.dumps(records, ensure_ascii=False, indent=2)
        else:
            # CSV 格式导出
            if not records:
                content = ""
            else:
                output = io.StringIO()
                fieldnames = list(records[0].keys())
                writer = csv.DictWriter(output, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(records)
                content = output.getvalue()

        if path is not None:
            # 确保目录存在
            dir_name = os.path.dirname(path)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return path

        return content

    def get_stats(self, host: str = None, days: int = 7) -> dict:
        """
        获取统计信息。

        参数:
            host: 按主机筛选，为 None 时统计所有主机
            days: 统计最近多少天的数据，默认 7 天

        返回:
            包含以下字段的字典:
            - total_commands: 总命令数
            - risk_distribution: 风险等级分布 {level: count}
            - source_distribution: 来源分布 {source: count}
            - success_rate: 成功率（exit_code == 0 的比例）
            - avg_duration_ms: 平均执行耗时
            - top_hosts: 最活跃的主机列表
        """
        cutoff = time.time() - days * 86400

        conditions = ["timestamp >= ?"]
        params: list = [cutoff]

        if host is not None:
            conditions.append("host = ?")
            params.append(host)

        where_clause = "WHERE " + " AND ".join(conditions)

        conn = self._get_connection()
        try:
            # 总命令数
            cursor = conn.execute(
                f"SELECT COUNT(*) as cnt FROM ai_audit_log {where_clause}",
                params,
            )
            total_commands = cursor.fetchone()["cnt"]

            # 风险等级分布
            cursor = conn.execute(
                f"""
                SELECT risk_level, COUNT(*) as cnt
                FROM ai_audit_log {where_clause}
                GROUP BY risk_level
                """,
                params,
            )
            risk_distribution = {row["risk_level"]: row["cnt"] for row in cursor.fetchall()}

            # 来源分布
            cursor = conn.execute(
                f"""
                SELECT source, COUNT(*) as cnt
                FROM ai_audit_log {where_clause}
                GROUP BY source
                """,
                params,
            )
            source_distribution = {row["source"]: row["cnt"] for row in cursor.fetchall()}

            # 成功率（exit_code == 0 的比例）
            cursor = conn.execute(
                f"""
                SELECT
                    COUNT(CASE WHEN exit_code = 0 THEN 1 END) as success_count,
                    COUNT(CASE WHEN exit_code IS NOT NULL THEN 1 END) as total_with_exit
                FROM ai_audit_log {where_clause}
                """,
                params,
            )
            row = cursor.fetchone()
            success_count = row["success_count"]
            total_with_exit = row["total_with_exit"]
            success_rate = (
                round(success_count / total_with_exit, 4)
                if total_with_exit > 0
                else 0.0
            )

            # 平均执行耗时
            cursor = conn.execute(
                f"""
                SELECT AVG(duration_ms) as avg_dur
                FROM ai_audit_log {where_clause}
                AND duration_ms > 0
                """,
                params,
            )
            avg_row = cursor.fetchone()
            avg_duration_ms = round(avg_row["avg_dur"] or 0, 2)

            # 最活跃的主机（前 10）
            cursor = conn.execute(
                f"""
                SELECT host, COUNT(*) as cnt
                FROM ai_audit_log {where_clause}
                GROUP BY host
                ORDER BY cnt DESC
                LIMIT 10
                """,
                params,
            )
            top_hosts = [
                {"host": row["host"], "count": row["cnt"]}
                for row in cursor.fetchall()
            ]

            return {
                "total_commands": total_commands,
                "risk_distribution": risk_distribution,
                "source_distribution": source_distribution,
                "success_rate": success_rate,
                "avg_duration_ms": avg_duration_ms,
                "top_hosts": top_hosts,
            }
        finally:
            conn.close()

    def cleanup(self, retention_days: dict = None) -> int:
        """
        根据保留策略清理过期日志。

        参数:
            retention_days: 各风险等级的保留天数字典，
                默认策略:
                - safe: 7 天
                - low: 30 天
                - medium: 90 天
                - high: 365 天

        返回:
            删除的记录总数
        """
        if retention_days is None:
            retention_days = DEFAULT_RETENTION_DAYS.copy()

        now = time.time()
        total_deleted = 0

        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                for level, days in retention_days.items():
                    cutoff = now - days * 86400
                    cursor = conn.execute(
                        """
                        DELETE FROM ai_audit_log
                        WHERE risk_level = ? AND timestamp < ?
                        """,
                        (level, cutoff),
                    )
                    total_deleted += cursor.rowcount
                conn.commit()
            finally:
                conn.close()

        return total_deleted

    # ------------------------------------------------------------------ #
    #  FTS5 全文搜索
    # ------------------------------------------------------------------ #

    def search(self, query: str, limit: int = 50) -> list[dict]:
        """
        全文搜索审计日志。

        Args:
            query: 搜索关键词（支持 FTS5 语法：AND, OR, NOT, 短语 "..."）
            limit: 最大返回数量

        Returns:
            匹配的审计日志记录列表
        """
        if not query or not query.strip():
            return []

        conn = self._get_connection()
        try:
            # 尝试 FTS5 全文搜索
            try:
                cursor = conn.execute(
                    """
                    SELECT a.*
                    FROM ai_audit_fts f
                    JOIN ai_audit_log a ON a.id = f.rowid
                    WHERE ai_audit_fts MATCH ?
                    ORDER BY a.timestamp DESC
                    LIMIT ?
                    """,
                    (query.strip(), limit),
                )
                return [dict(row) for row in cursor.fetchall()]
            except sqlite3.OperationalError:
                # FTS5 不可用或语法错误，回退到 LIKE 模糊搜索
                like_pattern = f"%{query.strip()}%"
                cursor = conn.execute(
                    """
                    SELECT * FROM ai_audit_log
                    WHERE command LIKE ? OR ai_input LIKE ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (like_pattern, like_pattern, limit),
                )
                return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    # ------------------------------------------------------------------ #
    #  收藏功能
    # ------------------------------------------------------------------ #

    def add_favorite(
        self, command: str, description: str = "", category: str = "general"
    ) -> int:
        """将命令添加为收藏（快捷操作）。返回收藏 ID。"""
        now = time.time()
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO ai_favorites (command, description, category, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (command, description, category, now),
                )
                conn.commit()
                return cursor.lastrowid
            finally:
                conn.close()

    def get_favorites(self, category: str = None) -> list[dict]:
        """获取收藏的命令列表。"""
        conn = self._get_connection()
        try:
            if category is not None:
                cursor = conn.execute(
                    "SELECT * FROM ai_favorites WHERE category = ? ORDER BY use_count DESC, created_at DESC",
                    (category,),
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM ai_favorites ORDER BY use_count DESC, created_at DESC"
                )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def remove_favorite(self, favorite_id: int) -> None:
        """删除收藏。"""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute("DELETE FROM ai_favorites WHERE id = ?", (favorite_id,))
                conn.commit()
            finally:
                conn.close()

    def increment_favorite_use(self, favorite_id: int) -> None:
        """增加收藏命令的使用次数。"""
        now = time.time()
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute(
                    "UPDATE ai_favorites SET use_count = use_count + 1, last_used_at = ? WHERE id = ?",
                    (now, favorite_id),
                )
                conn.commit()
            finally:
                conn.close()

    # ------------------------------------------------------------------ #
    #  统计分析增强
    # ------------------------------------------------------------------ #

    def get_frequent_commands(self, host: str = None, limit: int = 10) -> list[dict]:
        """获取最常用的命令。"""
        conn = self._get_connection()
        try:
            if host is not None:
                cursor = conn.execute(
                    """
                    SELECT command, COUNT(*) as count,
                           MAX(timestamp) as last_used,
                           risk_level
                    FROM ai_audit_log
                    WHERE host = ?
                    GROUP BY command
                    ORDER BY count DESC
                    LIMIT ?
                    """,
                    (host, limit),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT command, COUNT(*) as count,
                           MAX(timestamp) as last_used,
                           risk_level
                    FROM ai_audit_log
                    GROUP BY command
                    ORDER BY count DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_recent_sessions(self, limit: int = 10) -> list[dict]:
        """获取最近的会话列表。"""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                """
                SELECT session_id,
                       host,
                       username,
                       MIN(timestamp) as start_time,
                       MAX(timestamp) as end_time,
                       COUNT(*) as command_count
                FROM ai_audit_log
                GROUP BY session_id
                ORDER BY end_time DESC
                LIMIT ?
                """,
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
