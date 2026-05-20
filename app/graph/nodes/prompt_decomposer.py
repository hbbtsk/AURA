"""
PromptDecomposer 节点

职责：
  - 调用 PromptDecomposer 拆解 TAVO 原始 Prompt
  - 产出 decomposed、original_system、user_name、has_user_prefix 等字段
  - 为下游 ContextAssemble 节点提供结构化输入

设计原则：
  - 单一职责：只做拆解，不做区块组装
  - 与 ContextAssemble 解耦，各自可独立测试
"""

import time
from typing import TYPE_CHECKING

from app.utils import get_logger
from app.core.prompt_decomposer import PromptDecomposer

if TYPE_CHECKING:
    from app.graph.state import AgentState

logger = get_logger("aura-graph")

decomposer = PromptDecomposer()


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


async def prompt_decomposer_node(state: "AgentState") -> "AgentState":
    """Prompt 拆解 — 将 TAVO 原始 Prompt 解析为结构化组件"""
    t0 = _log_node_start(state, "PromptDecomposer")

    request = state["request"]
    model = request.get("model", "")
    raw_messages = request.get("messages", [])

    try:
        decomposed = decomposer.decompose({
            "model": model,
            "messages": raw_messages,
            "temperature": request.get("temperature"),
            "stream": request.get("stream"),
            "max_tokens": request.get("max_tokens"),
        })
        sys_comp = decomposed["system_prompt"]

        # 提取用户信息（从 decomposed 中解析，而非重复解析）
        has_user_prefix = sys_comp.get("has_user_prefix", True)
        user_name = state.get("user_name", "")

        # 如果 InputReceive 没有提取到 user_name，尝试从 decomposed 的 dialogue 中补
        dialogue = decomposed.get("dialogue", {})
        if not user_name and dialogue.get("last_user_input"):
            content = dialogue["last_user_input"]
            colon_pos = content.find("：")
            if colon_pos == -1:
                colon_pos = content.find(":")
            if colon_pos > 0 and colon_pos < 50:
                user_name = content[:colon_pos].strip()

        original_system = decomposed["raw"]["system_content"]

        summary = (
            f"拆解成功 | character_card: {'有' if sys_comp.get('character_card') else '无'}, "
            f"user_profile: {'有' if sys_comp.get('user_profile') else '无'}, "
            f"world_book: {'有' if sys_comp.get('world_book') else '无'}, "
            f"user_name: {user_name or '?'}"
        )
        _log_node_end(state, "PromptDecomposer", t0, summary)

        return {
            **state,
            "decomposed": decomposed,
            "original_system": original_system,
            "user_name": user_name,
            "has_user_prefix": has_user_prefix,
        }

    except Exception as e:
        logger.warning(f"[PromptDecomposer] 拆解失败: {e}")
        _log_node_end(state, "PromptDecomposer", t0, f"降级: {e}")
        return {
            **state,
            "decomposed": None,
            "original_system": "",
            "has_user_prefix": True,
        }
