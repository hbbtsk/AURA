"""
RetryStrategy 节点

职责：
  - 根据 retry_count 和质检失败原因，生成重试策略补丁
  - 将策略写入 state["retry_strategy"]，供 ContextAssemble 节点读取并注入到 Prompt 中
  - 纯状态转换节点，不触发任何外部 I/O

设计原则：
  - 与 ContextAssemble 解耦：只负责"生成策略"，不负责"修改 Prompt"
  - 策略格式统一为 Dict，下游节点按约定读取，无需关心策略来源
"""

import time
from typing import TYPE_CHECKING, List, Dict, Any

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


async def retry_strategy_node(state: "AgentState") -> "AgentState":
    """
    根据 retry_count 和质检失败原因生成策略补丁。

    产出 state["retry_strategy"] 结构：
    {
        "inject_constraints": ["额外约束1", "额外约束2"],  # 追加到 CONSTRAINTS 区块
        "inject_output_spec": ["额外输出规范1"],            # 追加到 OUTPUT_SPEC 区块
        "retry_count": int,                                   # 当前重试次数
        "trigger_reasons": ["FormatGuard: ...", "OOCCheck: ..."],  # 触发原因
    }
    """
    t0 = _log_node_start(state, "RetryStrategy")

    retry = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 2)

    # 收集失败原因
    reasons: List[str] = []
    if not state.get("format_passed", True):
        reasons.append(f"FormatGuard: {state.get('format_reason', '')}")
    if not state.get("ooc_passed", True):
        reasons.append(f"OOCCheck: {state.get('ooc_reason', '')}")
    if not state.get("content_passed", True):
        reasons.append(f"ContentFilter: {state.get('content_reason', '')}")

    strategy: Dict[str, Any] = {
        "inject_constraints": [],
        "inject_output_spec": [],
        "retry_count": retry,
        "trigger_reasons": reasons,
    }

    if retry == 1:
        strategy["inject_constraints"].append(
            "⚠️ 警告：上一轮输出未通过质检，本次必须严格遵守所有约束，禁止替用户生成行动或台词。"
        )
        strategy["inject_output_spec"].append(
            "自检：输出前逐项检查是否包含越权内容。"
        )
    elif retry >= 2:
        strategy["inject_constraints"].append(
            "🚨 最终警告：已连续两轮未通过质检，本次输出必须完全合规，否则将强制截断。"
        )
        strategy["inject_constraints"].append(
            "严禁替用户生成任何台词、行动、心理活动。只渲染环境和 NPC 反应。"
        )
        strategy["inject_output_spec"].append(
            "逐条自检：①是否越权 ②是否OOC ③格式是否正确 ④长度是否合规。"
        )

    summary = f"retry={retry}/{max_retries}, 原因: {'; '.join(reasons) if reasons else '无'}"
    if strategy["inject_constraints"]:
        summary += f", 追加约束: {len(strategy['inject_constraints'])}条"

    _log_node_end(state, "RetryStrategy", t0, summary)

    return {
        **state,
        "retry_strategy": strategy,
    }
