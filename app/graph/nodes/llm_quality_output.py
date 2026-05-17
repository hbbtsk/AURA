"""
LLM 生成 + 质检 + 输出 节点

Node 10: LLMGenerate（已真实化）
Node 11: FormatGuard（mock）
Node 12: OOCCheck（mock）
Node 13: ContentFilter（mock）
Node 14: OutputReturn
"""
import time
from typing import TYPE_CHECKING

import httpx

from app.utils import get_logger
from app.core.config import settings, get_llm_config

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
# Node 10: LLMGenerate
# ================================================================
async def llm_generate_node(state: "AgentState") -> "AgentState":
    """LLM 生成 — 非流式调用（已真实化）"""
    t0 = _log_node_start(state, "LLMGenerate")

    backend = state.get("backend", settings.default_llm)
    llm_config = get_llm_config(backend, scene="main")
    if not llm_config or not llm_config.api_key:
        _log_node_end(state, "LLMGenerate", t0, "LLM 配置缺失")
        return {
            **state,
            "error": f"后端 {backend} 未正确配置",
            "llm_response_content": "",
        }

    messages_list = state.get("messages_list", [])
    payload = {
        "model": state.get("model", "deepseek-v4-flash"),
        "messages": messages_list,
        "temperature": state.get("temperature", 0.7),
        "stream": False,
    }
    if state.get("max_tokens"):
        payload["max_tokens"] = state["max_tokens"]

    api_key = llm_config.api_key.strip()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    url = f"{llm_config.base_url.rstrip('/')}/chat/completions"

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(llm_config.timeout, read=llm_config.timeout)
        ) as client:
            response = await client.post(url, headers=headers, json=payload)

        if response.status_code != 200:
            err = response.text[:500]
            logger.error(f"[LLMGenerate] 后端错误: {response.status_code} | {err}")
            _log_node_end(state, "LLMGenerate", t0, f"后端错误: {response.status_code}")
            return {
                **state,
                "error": f"LLM后端错误: {err}",
                "llm_response_content": "",
            }

        llm_data = response.json()
        message = llm_data.get("choices", [{}])[0].get("message", {})
        content = message.get("content", "")
        reasoning_content = message.get("reasoning_content", "")
        usage = llm_data.get("usage", {})

        summary_parts = [f"内容长度: {len(content)}字"]
        if reasoning_content:
            summary_parts.append(f"思考: {len(reasoning_content)}字")
        summary_parts.append(f"prompt_tokens: {usage.get('prompt_tokens', '?')}")
        summary_parts.append(f"completion_tokens: {usage.get('completion_tokens', '?')}")

        _log_node_end(state, "LLMGenerate", t0, ", ".join(summary_parts))

        return {
            **state,
            "llm_payload": payload,
            "llm_response_content": content,
            "llm_reasoning_content": reasoning_content,
            "llm_raw_response": llm_data,
        }

    except Exception as e:
        logger.exception("[LLMGenerate] 异常")
        _log_node_end(state, "LLMGenerate", t0, f"异常: {e}")
        return {
            **state,
            "error": str(e),
            "llm_response_content": "",
        }


# ================================================================
# Node 11: FormatGuard
# ================================================================
async def format_guard_node(state: "AgentState") -> "AgentState":
    """格式质检：越权输出检测 + 关系一致性检测（mock，默认通过）"""
    t0 = _log_node_start(state, "FormatGuard")
    _log_node_end(state, "FormatGuard", t0, "通过（mock）")
    return state


# ================================================================
# Node 12: OOCCheck
# ================================================================
async def ooc_check_node(state: "AgentState") -> "AgentState":
    """人设一致性质检（mock，默认通过）"""
    t0 = _log_node_start(state, "OOCCheck")
    _log_node_end(state, "OOCCheck", t0, "通过（mock）")
    return state


# ================================================================
# Node 13: ContentFilter
# ================================================================
async def content_filter_node(state: "AgentState") -> "AgentState":
    """文风污染过滤（mock，默认通过）"""
    t0 = _log_node_start(state, "ContentFilter")
    _log_node_end(state, "ContentFilter", t0, "通过（mock）")
    return state


# ================================================================
# Node 14: OutputReturn
# ================================================================
async def output_return_node(state: "AgentState") -> "AgentState":
    """构建标准响应返回"""
    t0 = _log_node_start(state, "OutputReturn")

    error = state.get("error")
    if error:
        _log_node_end(state, "OutputReturn", t0, f"错误: {error}")
        # 注意：这里不能直接 raise HTTPException，因为 LangGraph 节点内 raise
        # 会被捕获为节点异常。我们在 completions.py 中检查 state["error"]
        return state

    content = state.get("llm_response_content", "")
    reasoning_content = state.get("llm_reasoning_content", "")
    session_id = state.get("session_id", "unknown")
    model = state.get("model", "unknown")

    # 构建与 ChatCompletionResponse 等价的字典
    message = {
        "role": "assistant",
        "content": content,
    }
    if reasoning_content:
        message["reasoning_content"] = reasoning_content

    response_dict = {
        "id": f"aura-{session_id}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": message,
            "finish_reason": "stop",
        }],
    }
    raw = state.get("llm_raw_response", {})
    if "usage" in raw:
        response_dict["usage"] = raw["usage"]

    summary = f"内容: {len(content)}字"
    if reasoning_content:
        summary += f", 思考: {len(reasoning_content)}字"
    _log_node_end(state, "OutputReturn", t0, summary)
    return {
        **state,
        "response": response_dict,
    }
