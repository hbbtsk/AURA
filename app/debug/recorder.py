"""
AURA 维测系统 — SQLite 状态快照记录器

职责：
  - 初始化 SQLite 数据库（含表 + 索引）
  - 每次 EventPatch 成功应用后，记录世界状态 + 角色状态快照

设计原则：
  - 自动创建 data/ 目录
  - JSON 序列化使用 ensure_ascii=False，确保中文可读
  - 线程安全（SQLite 单连接串行写入）
  - 调用方（WorldRuntime.apply_patch 或 Director）显式触发 save_snapshot
"""

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Optional

# ------------------------------------------------------------------
# 配置
# ------------------------------------------------------------------
DB_PATH = Path("data/debug.db")

# ------------------------------------------------------------------
# 初始化
# ------------------------------------------------------------------

def init_db() -> None:
    """
    初始化 SQLite 数据库。

    - 自动创建 data/ 目录
    - 创建 state_snapshots 表
    - 创建 event_id、timestamp 索引
    """
    # 确保目录存在
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(DB_PATH))
    try:
        cursor = conn.cursor()

        # 主表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS state_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL,
                timestamp REAL NOT NULL,
                causality_triggered_by TEXT,
                world_state_json TEXT NOT NULL,
                role_states_json TEXT NOT NULL
            )
        """)

        # 索引
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_snapshots_event_id
            ON state_snapshots(event_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_snapshots_timestamp
            ON state_snapshots(timestamp)
        """)

        conn.commit()
    finally:
        conn.close()


# ------------------------------------------------------------------
# 写入快照
# ------------------------------------------------------------------

def save_snapshot(
    event_id: str,
    world_state: Dict[str, Any],
    role_states: Dict[str, Any],
    triggered_by: Optional[str] = None,
) -> None:
    """
    保存一次状态快照。

    Args:
        event_id: EventPatch 的 id（唯一标识本次事件）
        world_state: 当前世界状态（global_state dict）
        role_states: 所有角色的 8 层模型 dict，key 为角色名
        triggered_by: 触发本次事件的父事件 ID（causality.triggered_by）

    Raises:
        sqlite3.Error: 数据库写入失败时抛出
    """
    # JSON 序列化，ensure_ascii=False 保证中文可读
    world_state_json = json.dumps(world_state, ensure_ascii=False, default=_json_default)
    role_states_json = json.dumps(role_states, ensure_ascii=False, default=_json_default)

    conn = sqlite3.connect(str(DB_PATH))
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO state_snapshots
                (event_id, timestamp, causality_triggered_by, world_state_json, role_states_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (event_id, time.time(), triggered_by, world_state_json, role_states_json),
        )
        conn.commit()
    finally:
        conn.close()


# ------------------------------------------------------------------
# 查询接口（供 routes.py 使用，避免重复打开连接）
# ------------------------------------------------------------------

def get_latest_snapshot() -> Optional[Dict[str, Any]]:
    """返回最新的一条快照记录（含完整 JSON 数据）。"""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, event_id, timestamp, causality_triggered_by,
                   world_state_json, role_states_json
            FROM state_snapshots
            ORDER BY timestamp DESC
            LIMIT 1
            """
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return _row_to_dict(row)
    finally:
        conn.close()


def get_snapshots_list(limit: int = 50) -> list[Dict[str, Any]]:
    """返回最近 N 条快照的摘要列表（不含完整 JSON 数据）。"""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT event_id, timestamp
            FROM state_snapshots
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cursor.fetchall()
        return [{"event_id": r["event_id"], "timestamp": r["timestamp"]} for r in rows]
    finally:
        conn.close()


def get_snapshot_by_event_id(event_id: str) -> Optional[Dict[str, Any]]:
    """按 event_id 查询单条快照（含完整 JSON 数据）。"""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, event_id, timestamp, causality_triggered_by,
                   world_state_json, role_states_json
            FROM state_snapshots
            WHERE event_id = ?
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (event_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return _row_to_dict(row)
    finally:
        conn.close()


# ------------------------------------------------------------------
# 内部辅助
# ------------------------------------------------------------------

def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    """将 sqlite3.Row 转换为标准 dict，并反序列化 JSON 字段。"""
    result = dict(row)
    # 反序列化 JSON 字段
    for key in ("world_state_json", "role_states_json"):
        if key in result and result[key] is not None:
            try:
                result[key.replace("_json", "")] = json.loads(result[key])
            except json.JSONDecodeError:
                result[key.replace("_json", "")] = {}
            # 删除原始 json 字符串，保持响应简洁
            del result[key]
    return result


def _json_default(obj: Any) -> Any:
    """处理无法直接 JSON 序列化的对象（如 Pydantic BaseModel）。"""
    # Pydantic v2
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    # Pydantic v1 fallback
    if hasattr(obj, "dict"):
        return obj.dict()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")
