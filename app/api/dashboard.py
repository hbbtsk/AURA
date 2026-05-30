"""
AURA 观测台 — Dashboard API

前端 index.html 的数据接口层。
将后端维测数据（turn_records / state_snapshots）转换为前端所需格式。

挂载路径：/api
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.debug.turn_recorder import turn_recorder
from app.debug.recorder import get_latest_snapshot, get_snapshot_by_event_id
from app.world import world_runtime

router = APIRouter(tags=["dashboard"])


# ------------------------------------------------------------------
# 辅助函数
# ------------------------------------------------------------------

def _safe_json(val: Any) -> Any:
    """安全返回 JSON 兼容值。"""
    if val is None:
        return {}
    if isinstance(val, (dict, list, str, int, float, bool)):
        return val
    return str(val)


def _sanitize_json_text(val: Any) -> Any:
    """
    递归清理字符串中的 JSON-breaking 字符。

    移除 \u2028（行分隔符）和 \u2029（段分隔符），
    这些字符在 Python json.dumps 中合法，但会导致浏览器 JSON.parse 失败。
    """
    if isinstance(val, str):
        # 替换 JSON-breaking 字符 + 其他控制字符
        return val.replace('\u2028', ' ').replace('\u2029', ' ').replace('\x00', '')
    if isinstance(val, dict):
        return {k: _sanitize_json_text(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_sanitize_json_text(v) for v in val]
    return val


# ------------------------------------------------------------------
# Chat 列表（多轮对话）
# ------------------------------------------------------------------

@router.get("/chats")
async def list_chats(
    limit: int = Query(50, ge=1, le=200),
) -> Dict[str, Any]:
    """
    获取所有 Chat 列表（一个 chat = 用户和某角色卡的一次完整剧情）。
    """
    chats = turn_recorder.get_chats(limit=limit)
    return {
        "count": len(chats),
        "chats": [
            {
                "chat_id": c["chat_id"],
                "cartridge_id": c.get("cartridge_id", ""),
                "created_at": c.get("created_at", 0),
                "updated_at": c.get("updated_at", 0),
                "turn_count": c.get("turn_count", 0),
            }
            for c in chats
        ],
    }


@router.get("/chat/{chat_id}/turns")
async def get_chat_turns(
    chat_id: str,
    limit: int = Query(200, ge=1, le=500),
) -> Dict[str, Any]:
    """
    获取某 Chat 下的所有轮次（按 turn_num 升序）。
    """
    turns = turn_recorder.get_turns_by_chat(chat_id, limit=limit)
    return {
        "chat_id": chat_id,
        "count": len(turns),
        "turns": [
            {
                "session_id": t.get("session_id", ""),
                "turn_num": t.get("turn_num", 0),
                "timestamp": t.get("timestamp", 0),
                "mode": t.get("mode", "chat"),
                "player_input": t.get("player_input", ""),
                "latency_ms": t.get("latency_ms", 0),
                "backend": t.get("backend", ""),
                "fallback_triggered": t.get("fallback_triggered", False),
            }
            for t in turns
        ],
    }


# ------------------------------------------------------------------
# 会话列表（兼容旧接口）
# ------------------------------------------------------------------

@router.get("/sessions")
async def list_sessions(
    limit: int = Query(50, ge=1, le=200),
) -> Dict[str, Any]:
    """
    获取所有会话列表。

    数据来自 turn_records 表，按 session_id 分组。
    """
    sessions = turn_recorder.get_sessions(limit=limit)
    return {
        "count": len(sessions),
        "sessions": [
            {
                "session_id": s["session_id"],
                "last_time": s.get("last_time", 0),
                "turn_count": s.get("turn_count", 0),
                "max_turn": s.get("max_turn", 0),
            }
            for s in sessions
        ],
    }


# ------------------------------------------------------------------
# 角色相关
# ------------------------------------------------------------------

@router.get("/session/{session_id}/characters")
async def get_characters(session_id: str) -> Dict[str, Any]:
    """
    获取某会话的角色列表。

    如果世界已加载，从 world_runtime 读取实体列表。
    否则从 turn_records 推断角色名（基于 player_input 和 response_content）。
    """
    characters = []

    # 优先从 world_runtime 读取
    if world_runtime.is_loaded() and world_runtime.world:
        for eid, entity in world_runtime.world.entities.items():
            characters.append({
                "id": eid,
                "name": entity.get_name("zh") if hasattr(entity, "get_name") else eid,
                "role": "主角" if eid == "player" else "配角",
                "role_tag": "tag-blue" if eid == "player" else "tag-purple",
            })

    if characters:
        return {"session_id": session_id, "count": len(characters), "characters": characters}

    # Fallback：从 turn_records 推断（只有一个 player 和一个 assistant）
    latest = turn_recorder.get_latest_turn(session_id)
    if latest:
        return {
            "session_id": session_id,
            "count": 2,
            "characters": [
                {"id": "player", "name": "玩家", "role": "你自己", "role_tag": "tag-blue"},
                {"id": "assistant", "name": "助手", "role": "AI", "role_tag": "tag-purple"},
            ],
        }

    return {"session_id": session_id, "count": 0, "characters": []}


@router.get("/session/{session_id}/character/{char_id}/layers")
async def get_character_layers(session_id: str, char_id: str) -> Dict[str, Any]:
    """
    获取角色的八层状态。

    优先从 state_snapshots 读取 role_states。
    如果无数据，返回基于 turn_records 的推断状态。
    """
    # 尝试从最新快照读取
    snap = get_latest_snapshot()
    role_states = snap.get("role_states", {}) if snap else {}
    char_state = role_states.get(char_id, {})

    if char_state and "layers" in char_state:
        return {
            "session_id": session_id,
            "char_id": char_id,
            "layers": char_state["layers"],
        }

    # Fallback：从 turn_records 推断情绪/状态
    latest = turn_recorder.get_latest_turn(session_id)
    if latest:
        # 从节点日志中推断状态
        node_logs = latest.get("node_logs", [])
        emotion = "calm"
        for log in node_logs:
            if "emotion" in str(log).lower():
                emotion = "conflicted"
                break

        return {
            "session_id": session_id,
            "char_id": char_id,
            "layers": [
                {"name": "一层 体格", "status": "ok", "value": "（未配置）"},
                {"name": "二层 声纹", "status": "ok", "value": "（未配置）"},
                {"name": "三层 根源", "status": "ok", "value": "（未配置）"},
                {"name": "四层 人际", "status": "ok", "value": "（未配置）"},
                {"name": "五层 核心", "status": "warn" if emotion != "calm" else "ok", "value": emotion},
                {"name": "六层 张力", "status": "ok", "value": "（未配置）"},
                {"name": "七层 轨迹", "status": "ok", "value": "（未配置）"},
                {"name": "八层 钩子", "status": "ok", "value": "（未配置）"},
            ],
        }

    return {"session_id": session_id, "char_id": char_id, "layers": []}


@router.get("/session/{session_id}/character/{char_id}/relations")
async def get_character_relations(session_id: str, char_id: str) -> Dict[str, Any]:
    """
    获取角色的关系数据（有向图）。

    优先从 state_snapshots 读取 role_states 中的 relationships。
    """
    snap = get_latest_snapshot()
    role_states = snap.get("role_states", {}) if snap else {}
    char_state = role_states.get(char_id, {})
    relations = char_state.get("relationships", []) if isinstance(char_state, dict) else []

    if relations:
        return {
            "session_id": session_id,
            "char_id": char_id,
            "relations": relations,
        }

    # Fallback：从 world_runtime 读取
    if world_runtime.is_loaded() and world_runtime.world:
        entity = world_runtime.world.entities.get(char_id)
        if entity and hasattr(entity, "relationships"):
            rels = []
            for target_id, rel in entity.relationships.items():
                target = world_runtime.world.entities.get(target_id)
                target_name = target.get_name("zh") if target and hasattr(target, "get_name") else target_id
                rels.append({
                    "from": entity.get_name("zh") if hasattr(entity, "get_name") else char_id,
                    "to": target_name,
                    "type": rel.relation_type if hasattr(rel, "relation_type") else "unknown",
                    "level": "trust-basic",
                    "label": rel.current_narrative if hasattr(rel, "current_narrative") else "未知",
                    "tags": [],
                })
            return {"session_id": session_id, "char_id": char_id, "relations": rels}

    return {"session_id": session_id, "char_id": char_id, "relations": []}


# ------------------------------------------------------------------
# 事件相关
# ------------------------------------------------------------------

@router.get("/session/{session_id}/events/latest")
async def get_latest_event(session_id: str) -> Dict[str, Any]:
    """
    获取最新事件补丁。

    从 turn_records 最新轮次构建 EventPatch 格式。
    """
    record = turn_recorder.get_latest_turn(session_id)
    if not record:
        return JSONResponse(status_code=404, content={"error": "未找到记录"})

    return {
        "session_id": session_id,
        "event_id": f"evt_{record.get('turn_num', 0)}",
        "event_type": "对话" if record.get("mode") == "chat" else "世界事件",
        "initiator": "玩家",
        "target": "助手",
        "intent": record.get("intent_result", {}).get("input_type", []),
        "visibility": "公开",
        "world_impact": [],
        "timestamp": record.get("timestamp", 0),
    }


# ------------------------------------------------------------------
# 世界状态
# ------------------------------------------------------------------

@router.get("/session/{session_id}/world")
async def get_world_state(session_id: str) -> Dict[str, Any]:
    """
    获取当前世界状态。

    优先从 state_snapshots 读取 world_state。
    其次从 world_runtime 读取。
    """
    # 1. 从快照读取
    snap = get_latest_snapshot()
    if snap and snap.get("world_state"):
        ws = snap["world_state"]
        return {
            "session_id": session_id,
            "location": ws.get("location", {}),
            "physical": ws.get("physical", {}),
            "present_entities": ws.get("present_entities", []),
            "active_rules": ws.get("active_rules", []),
            "global_state": ws.get("global_state", {}),
        }

    # 2. 从 world_runtime 读取
    if world_runtime.is_loaded() and world_runtime.world:
        field = world_runtime.get_field()
        loc = world_runtime.world.locations.get(field.location_id)
        entities_at = world_runtime.get_entities_at(field.location_id)

        return {
            "session_id": session_id,
            "location": {
                "id": field.location_id,
                "name": loc.name if loc else field.location_id,
                "description": "",
            },
            "physical": {
                "lighting": "未知",
                "temperature": "未知",
                "locked": False,
            },
            "present_entities": [
                {
                    "id": e.identity.entity_id if hasattr(e, "identity") else str(e),
                    "name": e.get_name("zh") if hasattr(e, "get_name") else str(e),
                    "role": "参与者",
                }
                for e in entities_at
            ],
            "active_rules": [
                {"id": r.rule_id, "description": r.description}
                for r in world_runtime.world.rules
                if not r.scope or field.location_id in r.scope
            ],
            "global_state": world_runtime.world.global_state,
        }

    # 3. Fallback
    return {
        "session_id": session_id,
        "location": {"id": "", "name": "未加载", "description": ""},
        "physical": {},
        "present_entities": [],
        "active_rules": [],
        "global_state": {},
    }


# ------------------------------------------------------------------
# 引擎面板（轮次链路）
# ------------------------------------------------------------------

@router.get("/session/{session_id}/engine/{turn_num}")
async def get_engine_turn(session_id: str, turn_num: int) -> Dict[str, Any]:
    """
    引擎面板数据源 —— 与前端 `loadTurn()` 数据格式对齐。

    将 turn_records 中的数据转换为前端引擎面板所需的 5 步链路格式：
      0. 对话记录
      1. 记忆检索结果
      2. 记忆压缩
      3. 意图识别
      4. 最终 Prompt
    """
    record = turn_recorder.get_turn(session_id, turn_num)
    if record is None:
        return JSONResponse(status_code=404, content={"error": "未找到记录"})

    player_input = record.get("player_input", "")
    response_content = record.get("response_content", "")
    intent_result = record.get("intent_result", {}) or {}
    retrieved_memories = record.get("retrieved_memories", []) or []
    decomposed = record.get("decomposed", {}) or {}
    node_logs = record.get("node_logs", []) or []

    def trunc(txt, maxlen=5000):
        if not txt or len(txt) <= maxlen:
            return txt
        return txt[:maxlen] + f"\n... [截断，原长度 {len(txt)} 字符]"

    # 从 messages_list 提取 system / memory / recent / user
    messages_list = record.get("messages_list", []) or []
    system_msg = ""
    memory_msg = ""
    recent_msg = ""
    user_msg = player_input
    for msg in messages_list:
        if isinstance(msg, dict):
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "system":
                system_msg = content
            elif role == "user":
                user_msg = content

    # 从 optimized_system 作为 system prompt（messages_list 中无 system 时兜底）
    if not system_msg:
        system_msg = record.get("optimized_system", "")

    # 从 retrieved_memories 构建 memory
    if not memory_msg and retrieved_memories:
        memory_msg = "\n".join(retrieved_memories[:10])

    # 从 messages_list 提取 recent 对话原始内容（完整不截断，调试需要看到真实数据）
    recent_lines = []
    for msg in messages_list:
        if isinstance(msg, dict) and msg.get("role") in ("user", "assistant"):
            role_label = "玩家" if msg["role"] == "user" else "NPC"
            # 完整内容，不做任何截断，确保调试面板显示的就是 LLM 实际收到的原始数据
            recent_lines.append(f"[{role_label}] {msg.get('content', '')}")
    if recent_lines:
        recent_msg = "\n".join(recent_lines[-10:])

    # 意图识别：input_type 是字符串，需兼容前端数组格式
    raw_input_type = intent_result.get("input_type", "")
    if isinstance(raw_input_type, str):
        intent_list = [raw_input_type] if raw_input_type.strip() else []
    elif isinstance(raw_input_type, list):
        intent_list = raw_input_type
    else:
        intent_list = []

    # token 数：只计算输入（prompt）token，不计算 LLM 返回 token
    pt = record.get("prompt_tokens", 0)
    if pt == 0:
        # 基于字符数粗略估算输入 token（中文约1字符/token，英文约4字符/token）
        prompt_text = system_msg + memory_msg + recent_msg + user_msg
        prompt_cn = sum(1 for c in prompt_text if '\u4e00' <= c <= '\u9fff')
        pt = prompt_cn + max(1, (len(prompt_text) - prompt_cn) // 4)

    # 构建引擎面板格式的 5 步链路
    engine_data = {
        "turn_num": turn_num,
        "session_id": session_id,
        "timestamp": record.get("timestamp", 0),
        "latency_ms": record.get("latency_ms", 0),

        # Step 0: 对话记录
        "player": trunc(player_input, 2000),
        "char": trunc(response_content, 5000),

        # Step 1: 记忆检索（从 retrieved_memories 构建）
        "memories": [
            {"score": round(0.95 - i * 0.05, 2), "text": mem}
            for i, mem in enumerate(retrieved_memories[:10])
        ] if retrieved_memories else [],

        # Step 2: 记忆压缩（从 decomposed 或近期对话构建）
        "compress": {
            "before": trunc("\n".join(retrieved_memories), 5000) if retrieved_memories else "（无记忆）",
            "after": trunc("\n".join(retrieved_memories[:5]), 2000) + "..." if retrieved_memories else "（无）",
        },

        # Step 3: 意图识别
        "intent": intent_list,
        "directive": trunc(intent_result.get("implicit_instruction", ""), 1000),

        # Step 4: 最终 Prompt（调试面板必须显示原始数据，不做任何截断）
        "prompt": {
            "system": system_msg,
            "memory": memory_msg,
            "recent": recent_msg,
            "user": user_msg,
        },
        "tokens": pt,
        "prompt_tokens": pt,
        "completion_tokens": 0,

        # 元信息
        "backend": record.get("actual_backend", record.get("backend", "")),
        "model": record.get("model", ""),
        "fallback_triggered": record.get("fallback_triggered", False),
        "fallback_reason": record.get("fallback_reason", ""),

        # 9 区块 Prompt（供前端展开查看）
        "blocks": record.get("blocks", []),
        "original_system": record.get("original_system", ""),
        "optimized_system": record.get("optimized_system", ""),

        # 节点执行日志
        "node_logs": node_logs,
    }

    # 清理可能导致浏览器 JSON.parse 失败的字符
    return _sanitize_json_text(engine_data)


# ------------------------------------------------------------------
# 运行日志（节点链路）
# ------------------------------------------------------------------

@router.get("/session/{session_id}/logs/{turn_num}")
async def get_turn_logs(session_id: str, turn_num: int) -> Dict[str, Any]:
    """
    获取某轮次的运行日志（节点执行链路）。

    将 node_logs 转换为前端日志面板格式。
    """
    record = turn_recorder.get_turn(session_id, turn_num)
    if record is None:
        return JSONResponse(status_code=404, content={"error": "未找到记录"})

    node_logs = record.get("node_logs", []) or []
    logs = []

    for i, log in enumerate(node_logs):
        node_name = log.get("node", "unknown")
        elapsed = log.get("elapsed_ms", 0)
        summary = log.get("summary", "")

        # 映射节点名到日志类型
        node_type_map = {
            "InputReceive": "director",
            "PromptDecomposer": "director",
            "MemoryRetrieve": "memory",
            "ContextAssemble": "character",
            "LLMGenerate": "character",
            "FormatGuard": "review",
            "OutputReturn": "system",
            "MemoryExtract": "memory",
        }
        node_type = node_type_map.get(node_name, "system")

        logs.append({
            "time": f"+{elapsed:.0f}ms",
            "node": node_type,
            "node_name": node_name,
            "action": summary or f"{node_name} 执行完成",
            "detail": f"耗时 {elapsed}ms",
            "duration": f"{elapsed}ms",
            "status": "ok",
        })

    return {
        "session_id": session_id,
        "turn_num": turn_num,
        "total_duration": record.get("latency_ms", 0),
        "node_count": len(logs),
        "logs": logs,
    }


# ------------------------------------------------------------------
# 轮次列表（时序面板）
# ------------------------------------------------------------------

@router.get("/session/{session_id}/turns")
async def get_session_turns(
    session_id: str,
    limit: int = Query(50, ge=1, le=200),
) -> Dict[str, Any]:
    """
    获取某会话的所有轮次列表（摘要）。
    """
    turns = turn_recorder.get_turns_by_session(session_id, limit=limit)
    return {
        "session_id": session_id,
        "count": len(turns),
        "turns": [
            {
                "turn_num": t.get("turn_num", 0),
                "timestamp": t.get("timestamp", 0),
                "mode": t.get("mode", "chat"),
                "player_input": t.get("player_input", "")[:100],
                "latency_ms": t.get("latency_ms", 0),
                "backend": t.get("backend", ""),
                "fallback_triggered": t.get("fallback_triggered", False),
            }
            for t in turns
        ],
    }


# ------------------------------------------------------------------
# 实时日志流（SSE）
# ------------------------------------------------------------------

@router.get("/logs/stream")
async def log_stream(
    node: Optional[str] = Query("all", description="节点过滤: all/director/memory/character/review/world/system")
):
    """
    实时日志流 —— SSE 推送。

    前端通过 EventSource('/api/logs/stream') 连接，
    每条新日志产生时自动推送到前端运行日志面板。

    可选 query 参数 `node` 进行节点过滤。
    """
    from fastapi.responses import StreamingResponse
    from app.utils.log_stream import log_stream_generator

    return StreamingResponse(
        log_stream_generator(node_filter=node),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲
        },
    )


@router.get("/logs/recent")
async def log_recent(
    limit: int = Query(100, ge=1, le=500),
    node: Optional[str] = Query("all", description="节点过滤"),
) -> Dict[str, Any]:
    """
    获取最近 N 条日志（历史回溯，非实时）。

    用于前端首次加载时填充日志列表，随后切换到 SSE 实时推送。
    """
    from app.utils.log_stream import log_ring

    entries = log_ring.get_recent(limit=limit, node_filter=node if node != "all" else None)
    return {
        "count": len(entries),
        "logs": [
            {
                "time": e.time_str,
                "node": e.node,
                "node_name": e.node_name,
                "action": e.action,
                "detail": e.detail,
                "duration": str(e.duration_ms) + "ms" if e.duration_ms else "—",
                "status": e.status,
                "level": e.level,
                "full_action": e.full_action,
            }
            for e in entries
        ],
    }
