"""
AURA SQLite 存储层

职责：
  - 原始对话存储（raw_dialogues）
  - 会话管理（sessions）
  - 动态状态（dynamic_state）
  - 剧情锚点（plot_anchors）
  - 关系图谱（relationship_graph）
  - TAVO 对话同步（处理编辑/撤回）
"""
import sqlite3
import logging
from typing import List, Dict, Any

logger = logging.getLogger("aura.memory")


class SQLiteStore:
    """SQLite 原始对话与结构化数据存储"""

    def __init__(self, db_path: str = "aura.db"):
        self.db_path = db_path
        self._round_counter: Dict[str, int] = {}

    def init_schema(self) -> None:
        """创建 SQLite 表结构"""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS raw_dialogues (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    round_number INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    character_id TEXT,
                    model_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS dynamic_state (
                    session_id TEXT NOT NULL,
                    entity_name TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (session_id, entity_name)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS plot_anchors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    event_text TEXT NOT NULL,
                    importance REAL DEFAULT 0.5,
                    is_active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS relationship_graph (
                    session_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    target TEXT NOT NULL,
                    relation_type TEXT,
                    weight REAL DEFAULT 0.0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (session_id, source, target)
                )
            """)

            conn.commit()
            logger.info("[AURA→记忆] SQLite 表结构已就绪")
        finally:
            conn.close()

    # --- 对话存储 ---

    async def save_dialogue(self, session_id: str, role: str, content: str, round_number: int) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO raw_dialogues (session_id, role, content, round_number) VALUES (?, ?, ?, ?)",
                (session_id, role, content, round_number)
            )
            conn.commit()
        finally:
            conn.close()

    async def get_recent_messages(self, session_id: str, n: int = 20) -> List[dict]:
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT role, content, round_number FROM raw_dialogues
                   WHERE session_id = ? ORDER BY round_number DESC LIMIT ?""",
                (session_id, n)
            )
            rows = cursor.fetchall()
            return [
                {"role": row[0], "content": row[1], "round_number": row[2]}
                for row in reversed(rows)
            ]
        finally:
            conn.close()

    async def get_dialogue_count(self, session_id: str) -> int:
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(DISTINCT round_number) FROM raw_dialogues WHERE session_id = ?",
                (session_id,)
            )
            return cursor.fetchone()[0] or 0
        finally:
            conn.close()

    # --- TAVO 同步 ---

    async def sync_dialogue_from_tavo(self, session_id: str, tavo_messages: List[dict]) -> None:
        """倒序匹配 TAVO 发来的对话与本地数据库，处理用户编辑/撤回操作"""
        if not tavo_messages:
            return

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            cursor.execute(
                """SELECT id, role, content, round_number FROM raw_dialogues
                   WHERE session_id = ? ORDER BY round_number ASC, id ASC""",
                (session_id,)
            )
            db_rows = cursor.fetchall()

            if not db_rows:
                logger.info(f"[AURA→同步] 数据库为空，直接写入 {len(tavo_messages)} 条消息")
                for msg in tavo_messages:
                    cursor.execute(
                        "INSERT INTO raw_dialogues (session_id, role, content, round_number) VALUES (?, ?, ?, ?)",
                        (session_id, msg.get("role", "user"), msg.get("content", ""), 1)
                    )
                conn.commit()
                return

            match_count = 0
            min_len = min(len(tavo_messages), len(db_rows))

            for i in range(min_len):
                tavo_idx = len(tavo_messages) - 1 - i
                db_idx = len(db_rows) - 1 - i

                tavo_content = tavo_messages[tavo_idx].get("content", "").strip()
                db_content = db_rows[db_idx][2].strip()

                if tavo_content != db_content:
                    break
                match_count += 1

            if match_count == len(tavo_messages) and match_count == len(db_rows):
                logger.debug(f"[AURA→同步] 对话完全一致，无需同步 | 会话: {session_id}")
                return

            keep_from_db = match_count
            truncate_at = len(db_rows) - keep_from_db

            if truncate_at < len(db_rows):
                truncate_round = db_rows[truncate_at][3]
                cursor.execute(
                    "DELETE FROM raw_dialogues WHERE session_id = ? AND round_number >= ?",
                    (session_id, truncate_round)
                )
                deleted_count = cursor.rowcount
                logger.info(
                    f"[AURA→同步] 截断数据库 | 会话: {session_id} | "
                    f"从 round {truncate_round} 开始删除 | 删除 {deleted_count} 条 | "
                    f"保留尾部 {keep_from_db} 条"
                )
            else:
                deleted_count = 0

            new_messages = tavo_messages[:len(tavo_messages) - keep_from_db]
            if new_messages:
                cursor.execute(
                    "SELECT COALESCE(MAX(round_number), 0) FROM raw_dialogues WHERE session_id = ?",
                    (session_id,)
                )
                current_max_round = cursor.fetchone()[0]

                for i, msg in enumerate(new_messages):
                    round_num = current_max_round + (i // 2) + 1
                    cursor.execute(
                        "INSERT INTO raw_dialogues (session_id, role, content, round_number) VALUES (?, ?, ?, ?)",
                        (session_id, msg.get("role", "user"), msg.get("content", ""), round_num)
                    )

                conn.commit()
                logger.info(
                    f"[AURA→同步] 写入 {len(new_messages)} 条新消息 | "
                    f"会话: {session_id} | 匹配: {match_count}/{min_len}"
                )

            if session_id in self._round_counter:
                del self._round_counter[session_id]

        except Exception as e:
            logger.error(f"[AURA→同步] 对话同步失败 | 会话: {session_id} | 错误: {e}")
        finally:
            conn.close()

    # --- 会话管理 ---

    async def get_or_create_session(self, session_id: str, character_id: str = "", model_name: str = "") -> dict:
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
            row = cursor.fetchone()

            if row:
                return {"id": row[0], "character_id": row[1], "model_name": row[2], "created_at": row[3]}

            cursor.execute(
                "INSERT INTO sessions (id, character_id, model_name) VALUES (?, ?, ?)",
                (session_id, character_id, model_name)
            )
            conn.commit()
            return {"id": session_id, "character_id": character_id, "model_name": model_name}
        finally:
            conn.close()

    async def get_round_number(self, session_id: str) -> int:
        if session_id not in self._round_counter:
            count = await self.get_dialogue_count(session_id)
            self._round_counter[session_id] = count
        self._round_counter[session_id] += 1
        return self._round_counter[session_id]

    # --- 动态状态 ---

    async def update_dynamic_state(self, session_id: str, entity_name: str, state_json: str) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT OR REPLACE INTO dynamic_state (session_id, entity_name, state_json, updated_at)
                   VALUES (?, ?, ?, CURRENT_TIMESTAMP)""",
                (session_id, entity_name, state_json)
            )
            conn.commit()
        finally:
            conn.close()

    async def get_dynamic_state(self, session_id: str) -> Dict[str, str]:
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT entity_name, state_json FROM dynamic_state WHERE session_id = ?",
                (session_id,)
            )
            rows = cursor.fetchall()
            return {row[0]: row[1] for row in rows}
        finally:
            conn.close()
