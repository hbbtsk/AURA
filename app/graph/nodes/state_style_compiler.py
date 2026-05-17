"""
State / Style / Compiler 节点

Node 6: StateManager（mock — Week 2 真实化）
Node 7: StyleInjection（mock — Week 3 真实化）
Node 8: ModelDialectCompiler（mock，透传）
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


# ================================================================
# Node 6: StateManager
# ================================================================
async def state_manager_node(state: "AgentState") -> "AgentState":
    """状态管理：加载 dynamic_state + 关系图谱渲染（mock）"""
    t0 = _log_node_start(state, "StateManager")
    _log_node_end(state, "StateManager", t0, "当前为 mock，CHARACTER_SITUATION=空")
    return {
        **state,
        "character_situation": "（状态管理器尚未实现）",
    }


# ================================================================
# Node 7: StyleInjection
# ================================================================
async def style_injection_node(state: "AgentState") -> "AgentState":
    """结构随机化 + mes_example 多样化（mock）"""
    t0 = _log_node_start(state, "StyleInjection")
    _log_node_end(state, "StyleInjection", t0, "当前为 mock")
    return state


# ================================================================
# Node 8: ModelDialectCompiler
# ================================================================
async def model_dialect_compiler_node(state: "AgentState") -> "AgentState":
    """模型方言编译器（mock，透传）

    Retry 时的策略调整：
    - retry_count == 1 → 在 CONTRAINTS 中追加更强约束
    - retry_count == 2 → 在 OUTPUT_SPEC 中追加逐条自检 COT
    """
    t0 = _log_node_start(state, "ModelDialectCompiler")

    retry = state.get("retry_count", 0)
    summary = f"当前为 mock，透传（retry={retry}）"

    if retry == 1:
        summary += " | 已追加更强约束（模拟）"
    elif retry >= 2:
        summary += " | 已追加 COT 自检（模拟）"

    _log_node_end(state, "ModelDialectCompiler", t0, summary)
    return state
