"""
AURA 维测系统 — FastAPI 调试路由（v2.0）

挂载路径：/debug
端点清单：
  GET /debug/latest                    → 最新状态快照（兼容旧版）
  GET /debug/snapshots                 → 快照列表（兼容旧版）
  GET /debug/snapshot/{eid}            → 指定事件快照（兼容旧版）

  # --- 新增：轮次全链路查询 ---
  GET /debug/sessions                  → 所有会话列表
  GET /debug/session/{sid}/turns       → 某会话的轮次摘要列表
  GET /debug/session/{sid}/turn/{turn} → 单轮次完整记录（引擎面板数据源）
  GET /debug/session/{sid}/latest      → 某会话最新轮次

  # --- 新增：Prompt / LLM 专用查询 ---
  GET /debug/session/{sid}/turn/{turn}/prompt   → 仅返回 Prompt 编译产物
  GET /debug/session/{sid}/turn/{turn}/llm      → 仅返回 LLM 交互详情

  # --- 预留：对接前端观测台 ---
  GET /api/session/{sid}/engine/{turn} → 引擎面板格式（与前端开发文档对齐）

设计原则：
  - 所有数据来自 turn_records 表（TurnRecorder 写入）
  - JSON 字段自动反序列化，中文可读
  - 大文本字段（System Prompt、messages_list）在响应中保留完整内容
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.debug.recorder import get_latest_snapshot, get_snapshots_list, get_snapshot_by_event_id
from app.debug.turn_recorder import turn_recorder

# ------------------------------------------------------------------
# 辅助：截断超大字段，避免 API 响应超过几 MB
# ------------------------------------------------------------------

def _truncate_response_fields(record: Dict[str, Any], max_len: int = 8000) -> Dict[str, Any]:
    """对响应中的大文本字段进行截断，保持 API 响应在合理大小（< 200KB）。"""
    if not record:
        return record
    result = dict(record)

    # 1. 顶层文本字段截断
    text_fields = [
        "original_system", "optimized_system", "working_memory_text",
        "llm_response_content", "llm_reasoning_content", "response_content",
    ]
    for field in text_fields:
        if field in result and isinstance(result[field], str) and len(result[field]) > max_len:
            result[field] = result[field][:max_len] + f"\n... [截断，原长度 {len(result[field])} 字符]"

    # 2. decomposed（PromptDecomposer 产出）可能包含超大 dict，递归截断其中的字符串
    if "decomposed" in result and isinstance(result["decomposed"], dict):
        result["decomposed"] = _truncate_nested(result["decomposed"], max_len=5000)

    # 3. blocks（9 区块列表）截断每个 block
    if "blocks" in result and isinstance(result["blocks"], list):
        result["blocks"] = [
            (b[:max_len] + f"\n... [截断，原长度 {len(b)} 字符]" if isinstance(b, str) and len(b) > max_len else b)
            for b in result["blocks"]
        ]

    # 4. messages_list 截断每条消息的内容
    if "messages_list" in result and isinstance(result["messages_list"], list):
        for msg in result["messages_list"]:
            if isinstance(msg, dict) and "content" in msg:
                content = msg["content"]
                if isinstance(content, str) and len(content) > max_len:
                    msg["content"] = content[:max_len] + f"\n... [截断，原长度 {len(content)} 字符]"

    # 5. llm_payload 截断 messages
    if "llm_payload" in result and isinstance(result["llm_payload"], dict):
        payload = result["llm_payload"]
        if "messages" in payload and isinstance(payload["messages"], list):
            for msg in payload["messages"]:
                if isinstance(msg, dict) and "content" in msg:
                    content = msg["content"]
                    if isinstance(content, str) and len(content) > max_len:
                        msg["content"] = content[:max_len] + f"\n... [截断，原长度 {len(content)} 字符]"

    # 6. llm_raw_response 只保留关键字段
    if "llm_raw_response" in result and isinstance(result["llm_raw_response"], dict):
        raw = result["llm_raw_response"]
        slim = {}
        if "usage" in raw:
            slim["usage"] = raw["usage"]
        if "choices" in raw and raw["choices"]:
            choice = raw["choices"][0]
            slim_choice = {}
            if "message" in choice:
                msg = choice["message"]
                slim_choice["message"] = {
                    k: (v[:max_len] + "... [截断]" if isinstance(v, str) and len(v) > max_len else v)
                    for k, v in msg.items()
                }
            if "finish_reason" in choice:
                slim_choice["finish_reason"] = choice["finish_reason"]
            slim["choices"] = [slim_choice]
        result["llm_raw_response"] = slim

    return result


def _truncate_nested(obj: Any, max_len: int = 5000) -> Any:
    """递归截断 dict/list 中的超长字符串。"""
    if isinstance(obj, str) and len(obj) > max_len:
        return obj[:max_len] + f"\n... [截断，原长度 {len(obj)} 字符]"
    elif isinstance(obj, dict):
        return {k: _truncate_nested(v, max_len) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_truncate_nested(v, max_len) for v in obj]
    return obj

# ------------------------------------------------------------------
# 路由实例
# ------------------------------------------------------------------
debug_router = APIRouter(tags=["debug"])


# ================================================================
# 兼容旧版端点（基于 state_snapshots 表）
# ================================================================

@debug_router.get("/latest")
async def debug_latest() -> Dict[str, Any]:
    """获取最新状态快照（世界状态 + 角色状态）。"""
    row = get_latest_snapshot()
    if row is None:
        return JSONResponse(status_code=404, content={"error": "未找到快照"})
    return {
        "event_id": row.get("event_id"),
        "timestamp": row.get("timestamp"),
        "causality_triggered_by": row.get("causality_triggered_by"),
        "world_state": row.get("world_state", {}),
        "role_states": row.get("role_states", {}),
    }


@debug_router.get("/snapshots")
async def debug_snapshots(
    limit: int = Query(50, ge=1, le=500, description="返回条数上限")
) -> Dict[str, Any]:
    """获取最近快照列表（仅摘要）。"""
    snapshots = get_snapshots_list(limit=limit)
    return {"count": len(snapshots), "snapshots": snapshots}


@debug_router.get("/snapshot/{event_id}")
async def debug_snapshot_by_event_id(event_id: str) -> Dict[str, Any]:
    """按 event_id 获取指定事件的历史状态快照。"""
    row = get_snapshot_by_event_id(event_id)
    if row is None:
        return JSONResponse(status_code=404, content={"error": "未找到快照"})
    return {
        "event_id": row.get("event_id"),
        "timestamp": row.get("timestamp"),
        "causality_triggered_by": row.get("causality_triggered_by"),
        "world_state": row.get("world_state", {}),
        "role_states": row.get("role_states", {}),
    }


# ================================================================
# 新增：轮次全链路查询（基于 turn_records 表）
# ================================================================

@debug_router.get("/sessions")
async def debug_sessions(
    limit: int = Query(50, ge=1, le=200, description="返回条数上限")
) -> Dict[str, Any]:
    """
    获取所有会话列表。

    返回：
      {
        "count": int,
        "sessions": [
          {"session_id": str, "last_time": float, "turn_count": int, "max_turn": int},
          ...
        ]
      }
    """
    sessions = turn_recorder.get_sessions(limit=limit)
    return {"count": len(sessions), "sessions": sessions}


@debug_router.get("/session/{session_id}/turns")
async def debug_session_turns(
    session_id: str,
    limit: int = Query(50, ge=1, le=200, description="返回条数上限")
) -> Dict[str, Any]:
    """
    获取某会话的所有轮次（摘要列表，不含完整 Prompt/LLM 数据）。

    返回：
      {
        "session_id": str,
        "count": int,
        "turns": [
          {"turn_num": int, "timestamp": float, "mode": str, "player_input": str, ...},
          ...
        ]
      }
    """
    turns = turn_recorder.get_turns_by_session(session_id, limit=limit)
    return {"session_id": session_id, "count": len(turns), "turns": turns}


@debug_router.get("/session/{session_id}/turn/{turn_num}")
async def debug_session_turn(
    session_id: str,
    turn_num: int,
) -> Dict[str, Any]:
    """
    获取单轮次完整记录 —— 这是维测系统的核心端点。

    包含：输入层、Prompt 编译层、意图&记忆、LLM 交互层、质检层、节点日志、输出层。
    这是排查"AURA 运行正确性"的第一现场。

    返回结构与 TurnRecord 字段一一对应。
    """
    record = turn_recorder.get_turn(session_id, turn_num)
    if record is None:
        return JSONResponse(
            status_code=404,
            content={"error": f"未找到记录 | session={session_id} | turn={turn_num}"},
        )
    return _truncate_response_fields(record)


@debug_router.get("/session/{session_id}/latest")
async def debug_session_latest(session_id: str) -> Dict[str, Any]:
    """获取某会话的最新一轮完整记录。"""
    record = turn_recorder.get_latest_turn(session_id)
    if record is None:
        return JSONResponse(
            status_code=404,
            content={"error": f"未找到记录 | session={session_id}"},
        )
    return _truncate_response_fields(record)


# ================================================================
# 新增：Prompt / LLM 专用查询（快速定位问题）
# ================================================================

@debug_router.get("/session/{session_id}/turn/{turn_num}/prompt")
async def debug_turn_prompt(session_id: str, turn_num: int) -> Dict[str, Any]:
    """
    仅返回 Prompt 编译产物 —— 用于快速排查 Prompt 组装是否正确。

    返回：
      {
        "original_system": str,      # TAVO 原始 System Prompt
        "decomposed": dict,          # PromptDecomposer 拆解结果
        "blocks": list,              # 9 区块列表
        "optimized_system": str,     # 重组后的 System Prompt
        "messages_list": list,       # 最终发给 LLM 的 messages
        "working_memory_text": str,  # 追加到 user 消息的内容
      }
    """
    record = turn_recorder.get_turn(session_id, turn_num)
    if record is None:
        return JSONResponse(status_code=404, content={"error": "未找到记录"})
    return {
        "original_system": record.get("original_system", ""),
        "decomposed": record.get("decomposed", {}),
        "blocks": record.get("blocks", []),
        "optimized_system": record.get("optimized_system", ""),
        "messages_list": record.get("messages_list", []),
        "working_memory_text": record.get("working_memory_text", ""),
    }


@debug_router.get("/session/{session_id}/turn/{turn_num}/llm")
async def debug_turn_llm(session_id: str, turn_num: int) -> Dict[str, Any]:
    """
    仅返回 LLM 交互详情 —— 用于快速排查 LLM 调用是否正常。

    返回：
      {
        "llm_payload": dict,           # 发给 LLM 的请求体
        "llm_response_content": str,   # LLM 生成的内容
        "llm_reasoning_content": str,  # LLM 思考过程
        "llm_raw_response": dict,      # LLM 原始 JSON 响应
        "actual_backend": str,         # 实际使用的后端
        "fallback_triggered": bool,
        "fallback_reason": str,
        "prompt_tokens": int,
        "completion_tokens": int,
      }
    """
    record = turn_recorder.get_turn(session_id, turn_num)
    if record is None:
        return JSONResponse(status_code=404, content={"error": "未找到记录"})
    return {
        "llm_payload": record.get("llm_payload", {}),
        "llm_response_content": record.get("llm_response_content", ""),
        "llm_reasoning_content": record.get("llm_reasoning_content", ""),
        "llm_raw_response": record.get("llm_raw_response", {}),
        "actual_backend": record.get("actual_backend", ""),
        "fallback_triggered": record.get("fallback_triggered", False),
        "fallback_reason": record.get("fallback_reason", ""),
        "prompt_tokens": record.get("prompt_tokens", 0),
        "completion_tokens": record.get("completion_tokens", 0),
    }


# ================================================================
# 预留：对接前端观测台（与开发文档对齐）
# ================================================================

@debug_router.get("/api/session/{session_id}/engine/{turn_num}")
async def debug_engine_turn(session_id: str, turn_num: int) -> Dict[str, Any]:
    """
    引擎面板数据源 —— 与前端开发文档的 `loadTurn()` 数据格式对齐。

    将 turn_records 中的数据转换为前端引擎面板所需的 5 步链路格式：
      0. 对话记录
      1. 记忆检索结果
      2. 记忆压缩
      3. 意图识别
      4. 最终 Prompt

    这是前端 `index.html` 中引擎面板的直接数据源。
    """
    record = turn_recorder.get_turn(session_id, turn_num)
    if record is None:
        return JSONResponse(status_code=404, content={"error": "未找到记录"})

    # 从记录中提取前端需要的数据
    player_input = record.get("player_input", "")
    response_content = record.get("response_content", "")
    intent_result = record.get("intent_result", {}) or {}
    retrieved_memories = record.get("retrieved_memories", []) or []
    decomposed = record.get("decomposed", {}) or {}
    messages_list = record.get("messages_list", []) or []
    node_logs = record.get("node_logs", []) or []

    # 截断大文本，避免引擎面板响应过大
    def trunc(txt, maxlen=5000):
        if not txt or len(txt) <= maxlen:
            return txt
        return txt[:maxlen] + f"\n... [截断，原长度 {len(txt)} 字符]"

    # 构建引擎面板格式的 5 步链路
    engine_data = {
        "turn_num": turn_num,
        "session_id": session_id,
        "timestamp": record.get("timestamp", 0),
        "latency_ms": record.get("latency_ms", 0),

        # Step 0: 对话记录
        "player": trunc(player_input, 1000),
        "char": trunc(response_content, 3000),

        # Step 1: 记忆检索（从 retrieved_memories 构建）
        "memories": [
            {"score": 0.9, "text": mem}
            for mem in retrieved_memories[:5]
        ] if retrieved_memories else [],

        # Step 2: 记忆压缩（从 decomposed 或近期对话构建）
        "compress": {
            "before": trunc("\n".join(retrieved_memories), 2000) if retrieved_memories else "（无记忆）",
            "after": trunc("\n".join(retrieved_memories[:3]), 1000) + "..." if retrieved_memories else "（无）",
        },

        # Step 3: 意图识别
        "intent": intent_result.get("input_type", []),
        "directive": trunc(intent_result.get("implicit_instruction", ""), 500),

        # Step 4: 最终 Prompt
        "prompt": {
            "system": trunc(record.get("optimized_system", ""), 5000),
            "memory": trunc("\n".join(retrieved_memories), 2000) if retrieved_memories else "",
            "recent": "",
            "user": trunc(player_input, 1000),
        },
        "tokens": record.get("prompt_tokens", 0) + record.get("completion_tokens", 0),

        # 元信息
        "backend": record.get("actual_backend", record.get("backend", "")),
        "model": record.get("model", ""),
        "fallback_triggered": record.get("fallback_triggered", False),
        "fallback_reason": record.get("fallback_reason", ""),

        # 节点执行日志
        "node_logs": node_logs,
    }

    return engine_data
