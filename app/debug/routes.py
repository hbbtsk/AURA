"""
AURA 维测系统 — FastAPI 调试路由

挂载路径：/debug
端点：
  GET /debug/latest          → 最新快照（含完整状态）
  GET /debug/snapshots       → 快照列表（摘要）
  GET /debug/snapshot/{eid}  → 指定事件快照（含完整状态）

集成方式：
  在 app/main.py 中：
      from app.debug.routes import debug_router
      app.include_router(debug_router, prefix="/debug")
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query

from app.debug.recorder import get_latest_snapshot, get_snapshots_list, get_snapshot_by_event_id

# ------------------------------------------------------------------
# 路由实例
# ------------------------------------------------------------------
debug_router = APIRouter(tags=["debug"])


# ------------------------------------------------------------------
# 辅助：构建统一响应
# ------------------------------------------------------------------

def _build_snapshot_response(row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """将数据库行转换为 API 响应格式。"""
    if row is None:
        raise HTTPException(status_code=404, detail="未找到快照")

    return {
        "event_id": row.get("event_id"),
        "timestamp": row.get("timestamp"),
        "causality_triggered_by": row.get("causality_triggered_by"),
        "world_state": row.get("world_state", {}),
        "role_states": row.get("role_states", {}),
    }


# ------------------------------------------------------------------
# 端点
# ------------------------------------------------------------------

@debug_router.get("/latest")
async def debug_latest() -> Dict[str, Any]:
    """
    获取最新状态快照。

    返回：
      {
        "event_id": str,
        "timestamp": float,
        "causality_triggered_by": str | null,
        "world_state": dict,
        "role_states": dict
      }
    """
    row = get_latest_snapshot()
    return _build_snapshot_response(row)


@debug_router.get("/snapshots")
async def debug_snapshots(
    limit: int = Query(50, ge=1, le=500, description="返回条数上限")
) -> Dict[str, Any]:
    """
    获取最近快照列表（不含完整状态，仅摘要）。

    返回：
      {
        "count": int,
        "snapshots": [
          {"event_id": str, "timestamp": float},
          ...
        ]
      }
    """
    snapshots = get_snapshots_list(limit=limit)
    return {
        "count": len(snapshots),
        "snapshots": snapshots,
    }


@debug_router.get("/snapshot/{event_id}")
async def debug_snapshot_by_event_id(event_id: str) -> Dict[str, Any]:
    """
    按 event_id 获取指定事件的历史状态快照。

    返回结构与 /debug/latest 相同。
    """
    row = get_snapshot_by_event_id(event_id)
    return _build_snapshot_response(row)
