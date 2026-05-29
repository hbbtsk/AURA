"""
Node 1: InputReceive

接收输入，提取对话消息，建立会话映射 + 意图解析
"""
import time
from typing import TYPE_CHECKING

from app.utils import get_logger
from app.memory import memory_manager
from app.core.intent_tagger import intent_tagger

if TYPE_CHECKING:
    from app.graph.state import AgentState

logger = get_logger("aura-graph")


def _log_node_start(state: "AgentState", node_name: str) -> float:
    """记录节点开始执行"""
    t0 = time.time()
    logger.info(f"[LangGraph→节点] {node_name} | 开始 | session={state.get('aura_session_id', '?')}")
    return t0


def _log_node_end(state: "AgentState", node_name: str, t0: float, summary: str = ""):
    """记录节点执行结束，更新状态日志"""
    elapsed = (time.time() - t0) * 1000
    log_entry = {
        "node": node_name,
        "elapsed_ms": round(elapsed, 1),
        "summary": summary,
    }
    logs = state.get("node_logs", [])
    logs.append(log_entry)
    logger.info(
        f"[LangGraph→节点] {node_name} | 结束 | 耗时: {elapsed:.1f}ms | {summary}"
    )
    return {"node_logs": logs}


async def input_receive_node(state: "AgentState") -> "AgentState":
    """接收输入，提取对话消息，建立会话映射 + 意图解析"""
    t0 = _log_node_start(state, "InputReceive")

    request = state["request"]
    raw_messages = request.get("messages", [])

    # 提取对话消息（user + assistant）
    tavo_dialogue_messages = [
        {"role": m["role"], "content": m["content"]}
        for m in raw_messages
        if m.get("role") in ("user", "assistant")
    ]

    # 提取用户名（最准确的方式）
    user_name = ""
    for m in reversed(raw_messages):
        if m.get("role") == "user":
            content = m.get("content", "")
            colon_pos = content.find("：")
            if colon_pos == -1:
                colon_pos = content.find(":")
            if colon_pos > 0 and colon_pos < 50:
                user_name = content[:colon_pos].strip()
            break

    # 提取最后一条 user 消息用于意图解析
    last_input = state.get("user_content", "")
    if not last_input:
        for m in reversed(raw_messages):
            if m.get("role") == "user":
                last_input = m.get("content", "")
                break

    # 意图解析（提前执行，供 MemoryRetrieve 使用结构化召回）
    intent_result = None
    if last_input:
        try:
            # 提取最近 5 轮对话作为意图分析的上下文
            recent_dialogue = [
                {"role": m["role"], "content": m["content"][:300]}
                for m in tavo_dialogue_messages[-10:]
                if m.get("role") in ("user", "assistant")
            ][-5:]
            context = {
                "scene_type": "未知",
                "active_entities": [user_name] if user_name else [],
                "recent_dialogue": recent_dialogue,
            }
            intent_result = await intent_tagger.analyze(last_input, context=context)
            if intent_result and intent_result.should_use():
                logger.info(
                    f"[InputReceive] 意图解析: "
                    f"type={intent_result.input_type}, confidence={intent_result.confidence:.2f}"
                )
        except Exception as e:
            logger.warning(f"[InputReceive] 意图分析失败（不影响主流程）: {e}")

    # 获取当前对话轮次（用于 MemoryExtract 保存对话和触发总结）
    aura_session_id = state.get("aura_session_id", "")
    round_num = 0
    if aura_session_id:
        try:
            round_num = await memory_manager.get_dialogue_count(aura_session_id)
        except Exception as e:
            logger.warning(f"[InputReceive] 获取对话轮次失败: {e}")

    summary_parts = [
        f"消息数: {len(raw_messages)}",
        f"对话消息: {len(tavo_dialogue_messages)}",
        f"user_name: {user_name or '?'}",
        f"round: {round_num}",
    ]
    if intent_result and intent_result.should_use():
        summary_parts.append(f"意图: {intent_result.input_type}({intent_result.confidence:.2f})")
    summary = " | ".join(summary_parts)
    _log_node_end(state, "InputReceive", t0, summary)

    return {
        **state,
        "messages": raw_messages,
        "tavo_dialogue_messages": tavo_dialogue_messages,
        "user_name": user_name,
        "intent_result": intent_result,
        "round_num": round_num,
        "retry_count": 0,
        "max_retries": 2,
        "format_passed": True,
        "ooc_passed": True,
        "content_passed": True,
        "format_reason": "",
        "ooc_reason": "",
        "content_reason": "",
        "node_logs": state.get("node_logs", []),
    }
