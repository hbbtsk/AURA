"""
条件边：质检 → 重试 or 放行
"""
from typing import Dict, Any

from app.utils import get_logger

logger = get_logger("aura-graph")


def should_retry_after_check(state: Dict[str, Any]) -> str:
    """
    FormatGuard/OOCCheck/ContentFilter 后的条件路由。
    任一不通过 → 重试（最多 max_retries 次）
    全部通过或超过重试次数 → 放行到 OutputReturn
    """
    retry = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 2)

    format_ok = state.get("format_passed", True)
    ooc_ok = state.get("ooc_passed", True)
    content_ok = state.get("content_passed", True)

    if format_ok and ooc_ok and content_ok:
        logger.info(f"[LangGraph→条件] 全部通过 → OutputReturn")
        return "output_return"

    if retry >= max_retries:
        logger.warning(
            f"[LangGraph→条件] 质检不通过但 retry={retry} >= max={max_retries}, 强制放行"
        )
        return "output_return"

    # 不通过且未超重试次数 → 重试
    reasons = []
    if not format_ok:
        reasons.append(f"FormatGuard: {state.get('format_reason', '')}")
    if not ooc_ok:
        reasons.append(f"OOCCheck: {state.get('ooc_reason', '')}")
    if not content_ok:
        reasons.append(f"ContentFilter: {state.get('content_reason', '')}")

    logger.warning(
        f"[LangGraph→条件] 质检不通过 → 重试(retry={retry+1}/{max_retries}) | 原因: {'; '.join(reasons)}"
    )
    # 更新 retry_count，路由回并行准备节点
    state["retry_count"] = retry + 1
    return "retry"
