"""
Node 2: EntityExtract（mock — Week 3 真实化）

实体识别：从用户输入 + 最近对话提取活跃实体
"""
import time
from typing import TYPE_CHECKING

from app.utils import get_logger

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


async def entity_extract_node(state: "AgentState") -> "AgentState":
    """实体识别：从用户输入 + 最近对话提取活跃实体"""
    t0 = _log_node_start(state, "EntityExtract")

    # TODO: Week 3 实现真实实体提取
    # 当前从角色卡第一行简单提取
    active_entities = []
    decomposed_data = state.get("decomposed")
    if decomposed_data:
        char_card = decomposed_data.get("system_prompt", {}).get("character_card", "")
        if char_card:
            first_line = char_card.split("\n")[0].strip()
            if first_line:
                active_entities.append(first_line)

    _log_node_end(state, "EntityExtract", t0, f"活跃实体: {active_entities}")
    return {
        **state,
        "active_entity_ids": active_entities,
    }
