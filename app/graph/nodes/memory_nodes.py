"""
Memory 相关节点

Node 4: MemoryDecision（mock — 默认 true）
Node 5: MemoryRetrieve（RAG，已真实化）
Node 15: MemoryExtract（保存对话 + 触发总结，已真实化）
"""
import asyncio
import time
from typing import TYPE_CHECKING

from app.utils import get_logger
from app.core.config import settings
from app.memory import memory_manager

if TYPE_CHECKING:
    from app.graph.state import AgentState

logger = get_logger("aura-graph")


def _log_node_start(state: "AgentState", node_name: str) -> float:
    t0 = time.time()
    logger.info(f"[LangGraph→节点] {node_name} | 开始 | session={state.get('aura_session_id', '?')}")
    return t0


def _log_node_end(state: "AgentState", node_name: str, t0: float, summary: str = ""):
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


# ================================================================
# Node 5: MemoryRetrieve
# ================================================================
async def memory_retrieve_node(state: "AgentState") -> "AgentState":
    """记忆检索：FAISS RAG 召回（已真实化）"""
    t0 = _log_node_start(state, "MemoryRetrieve")

    intent_result = state.get("intent_result")
    last_input = state.get("user_content", "")
    query_text = last_input or state.get("user_name", "")

    try:
        if intent_result and intent_result.should_use():
            rag_memories = await memory_manager.structured_aware_search(
                query=intent_result.expanded_scene or query_text,
                top_k=10,
                query_structure=intent_result.structure,
            )
            summary = f"结构化召回: {len(rag_memories)}条, query={query_text[:30]}..."
        else:
            rag_memories = await memory_manager.search(query_text, top_k=10)
            summary = f"传统召回: {len(rag_memories)}条, query={query_text[:30]}..."
    except Exception as e:
        logger.warning(f"[MemoryRetrieve] RAG 失败: {e}")
        rag_memories = []
        summary = f"RAG 失败: {e}"

    _log_node_end(state, "MemoryRetrieve", t0, summary)
    return {
        **state,
        "retrieved_memories": rag_memories,
    }


# ================================================================
# Node 15: MemoryExtract
# ================================================================
async def memory_extract_node(state: "AgentState") -> "AgentState":
    """保存对话 + 触发 Kimi 总结（已真实化）"""
    t0 = _log_node_start(state, "MemoryExtract")

    aura_session_id = state.get("aura_session_id", "")
    round_num = state.get("round_num", 0)
    # 新消息的轮次 = 已有轮数 + 1
    new_round = round_num + 1
    user_content = state.get("user_content", "")
    tavo_dialogue = state.get("tavo_dialogue_messages", [])

    summary_parts = []

    try:
        # 1. 对话同步
        if tavo_dialogue:
            await memory_manager.sync_dialogue_from_tavo(aura_session_id, tavo_dialogue)
            summary_parts.append(f"同步: {len(tavo_dialogue)}条")

        # 2. 保存用户输入
        if user_content:
            await memory_manager.save_dialogue(aura_session_id, "user", user_content, new_round)
            summary_parts.append(f"user: {len(user_content)}字")

        # 3. 保存 LLM 回复
        llm_content = state.get("llm_response_content", "")
        if llm_content:
            await memory_manager.save_dialogue(
                aura_session_id, "assistant", llm_content, new_round
            )
            summary_parts.append(f"assistant: {len(llm_content)}字")

        # 4. 触发总结（每 memory_summary_interval 轮触发一次）
        if new_round > 0 and new_round % settings.memory_summary_interval == 0:
            recent = await memory_manager.get_recent_messages(aura_session_id, n=10)
            if recent:
                asyncio.ensure_future(
                    memory_manager.summarize_and_store(aura_session_id, recent)
                )
                summary_parts.append(f"触发总结(轮={new_round})")

    except Exception as e:
        logger.warning(f"[MemoryExtract] 保存失败（不影响返回）: {e}")
        summary_parts.append(f"失败: {e}")

    _log_node_end(state, "MemoryExtract", t0, ", ".join(summary_parts) or "无操作")
    return state
