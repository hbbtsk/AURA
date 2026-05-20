"""
Node 3: EmotionAnalyze（mock — Week 3 真实化）

情绪走向分析
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


async def emotion_analyze_node(state: "AgentState") -> "AgentState":
    """情绪走向分析（mock — Week 3 真实化）

    当前为占位实现，返回统一接口契约字段，下游节点可安全读取。
    """
    t0 = _log_node_start(state, "EmotionAnalyze")

    # TODO: Week 3 接入真实情绪分析模型
    emotion_analysis = None

    _log_node_end(state, "EmotionAnalyze", t0, "mock | emotion=中性")
    return {
        **state,
        "emotion_analysis": emotion_analysis,
    }
