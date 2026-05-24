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
    logger.info(
        f"[LangGraph→节点] {node_name} | 结束 | 耗时: {elapsed:.1f}ms | {summary}"
    )
    return {"node_logs": [log_entry]}


# ================================================================
# Node 6: StateManager
# ================================================================
async def state_manager_node(state: "AgentState") -> "AgentState":
    """状态管理：加载 dynamic_state + 关系图谱渲染（mock — Week 2 真实化）

    当前为占位实现，返回统一接口契约字段，下游节点可安全读取。
    """
    t0 = _log_node_start(state, "StateManager")

    # TODO: Week 2 从 SQLite 读取真实动态状态
    character_situation = "（状态管理器尚未实现）"

    log_update = _log_node_end(state, "StateManager", t0, "mock | CHARACTER_SITUATION=空")
    return {
        "character_situation": character_situation,
        **log_update,
    }


# ================================================================
# Node 7: StyleInjection
# ================================================================
async def style_injection_node(state: "AgentState") -> "AgentState":
    """结构随机化 + mes_example 多样化（mock — Week 3 真实化）

    当前为占位实现，返回统一接口契约字段，下游节点可安全读取。
    """
    t0 = _log_node_start(state, "StyleInjection")

    # TODO: Week 3 接入真实文风控制
    style_injections = None

    log_update = _log_node_end(state, "StyleInjection", t0, "mock | 无注入")
    return {
        "style_injections": style_injections,
        **log_update,
    }


# ================================================================
# Node 8: ModelDialectCompiler
# ================================================================
async def model_dialect_compiler_node(state: "AgentState") -> "AgentState":
    """模型方言编译器（mock — 适配不同 LLM 后端特性）

    当前为占位实现，返回统一接口契约字段，下游节点可安全读取。
    真实的方言编译逻辑（如 DeepSeek reasoning 处理、Gemini 系统提示适配等）将在后续版本实现。
    """
    t0 = _log_node_start(state, "ModelDialectCompiler")

    # TODO: 根据 backend 模型特性注入方言适配指令
    model_dialect_notes = None

    log_update = _log_node_end(state, "ModelDialectCompiler", t0, "mock | 无方言适配")
    return {
        "model_dialect_notes": model_dialect_notes,
        **log_update,
    }
