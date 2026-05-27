"""
AURA 维测（调试）系统

职责：
  - 记录世界状态快照（SQLite）
  - 提供 REST API 供外部查询
  - 供 Gradio UI 消费

表结构：
  state_snapshots
    id INTEGER PRIMARY KEY AUTOINCREMENT
    event_id TEXT
    timestamp REAL
    causality_triggered_by TEXT
    world_state_json TEXT
    role_states_json TEXT
"""
from app.debug.recorder import init_db, save_snapshot

__all__ = ["init_db", "save_snapshot"]
