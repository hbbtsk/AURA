"""
LLM 生成 + 质检 + 输出 节点

Node 11: LLMGenerate（已真实化，支持主备故障转移）
Node 12: FormatGuard（基于规则的越权输出检测）
Node 13: OOCCheck（轻量人设一致性检查）
Node 14: ContentFilter（mock — 由 TAVO/LLM 服务商负责内容安全）
Node 15: OutputReturn

故障转移设计：
    - 主模型调用受 ttfb_timeout 限制（默认 3 秒）
    - 超时后自动切换到 fallback_provider（默认 kimi），使用完整 timeout
    - 切换后重新发送相同 payload，保证用户体验不中断

质检层并行化：
    LLMGenerate → ParallelQualityCheck（FormatGuard + OOCCheck + ContentFilter 并行）
                → OutputReturn
"""
import asyncio
import re
import time
from typing import TYPE_CHECKING, Optional, Dict, Any

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
# 内部辅助：单次 LLM 调用
# ================================================================
async def _call_single_llm(
    backend: str,
    model_name: Optional[str],
    payload: Dict[str, Any],
    timeout: int,
) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    执行单次 LLM 调用。

    Returns:
        (llm_data, error_msg) — llm_data 为 None 时表示调用失败
    """
    llm_config = get_llm_config(backend, scene="main", model_name=model_name)
    if not llm_config or not llm_config.api_key:
        return None, f"后端 {backend} 未正确配置"

    api_key = llm_config.api_key.strip()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    url = f"{llm_config.base_url.rstrip('/')}/chat/completions"

    # 使用 llm_config 中的实际模型名（覆盖 payload 中可能不兼容的模型名）
    # 同时 temperature 已在 get_llm_config 中按模型修正
    actual_payload = dict(payload)
    actual_payload["model"] = llm_config.model
    actual_payload["temperature"] = llm_config.temperature

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout, read=timeout)
    ) as client:
        response = await client.post(url, headers=headers, json=actual_payload)

    if response.status_code != 200:
        err = response.text[:500]
        logger.error(f"[_call_single_llm] 后端错误: {response.status_code} | {err}")
        return None, f"LLM后端错误({backend}): {err}"

    return response.json(), None


# ================================================================
# Node 10: LLMGenerate（支持主备故障转移）
# ================================================================
async def llm_generate_node(state: "AgentState") -> "AgentState":
    """
    LLM 生成 — 非流式调用，支持主备故障转移。

    流程：
        1. 使用主模型（state.backend）调用，受 ttfb_timeout 限制
        2. 若超时（asyncio.TimeoutError）→ 自动切换到 fallback_provider
        3. fallback 使用完整 timeout，不限制首 token 时间
        4. 记录 actual_backend 与 fallback_triggered 到 state
    """
    t0 = _log_node_start(state, "LLMGenerate")

    primary_backend = state.get("backend", settings.default_llm)
    model_name = state.get("model")
    messages_list = state.get("messages_list", [])

    payload = {
        "model": model_name or "deepseek-v4-flash",
        "messages": messages_list,
        "temperature": state.get("temperature", 0.7),
        "stream": False,
    }
    if state.get("max_tokens"):
        payload["max_tokens"] = state["max_tokens"]

    # ---------- 第一轮：主模型（受 ttfb_timeout 限制） ----------
    llm_data: Optional[Dict[str, Any]] = None
    error_msg: Optional[str] = None
    actual_backend = primary_backend
    fallback_triggered = False
    fallback_reason = ""

    try:
        llm_data, error_msg = await asyncio.wait_for(
            _call_single_llm(
                primary_backend,
                model_name,
                payload,
                timeout=settings.llm_main_timeout,
            ),
            timeout=settings.llm_main_ttfb_timeout,
        )
    except asyncio.TimeoutError:
        fallback_triggered = True
        fallback_reason = f"ttfb_timeout: {primary_backend}"
        logger.warning(
            f"[LLMGenerate] 主模型 {primary_backend} 首 token 超时 "
            f"({settings.llm_main_ttfb_timeout}s)，触发故障转移 → {settings.llm_main_fallback_provider}"
        )
    except Exception as e:
        # 连接错误、配置错误等非超时异常也触发 fallback，避免直接暴露给用户
        fallback_triggered = True
        fallback_reason = f"exception: {primary_backend} | {type(e).__name__}: {e}"
        logger.warning(
            f"[LLMGenerate] 主模型 {primary_backend} 调用异常，触发故障转移 → "
            f"{settings.llm_main_fallback_provider} | 异常: {type(e).__name__}: {e}"
        )

    # ---------- 第二轮：fallback 模型（若主模型失败） ----------
    if fallback_triggered:
        fallback_backend = settings.llm_main_fallback_provider
        # fallback 时使用 fallback 后端的默认模型，避免把原模型名透传给不支持的后端
        fallback_model = None  # _call_single_llm 内部会取 get_llm_config 的默认模型
        try:
            llm_data, error_msg = await _call_single_llm(
                fallback_backend,
                fallback_model,
                payload,
                timeout=settings.llm_main_timeout,
            )
            actual_backend = fallback_backend
        except Exception as e:
            logger.exception(f"[LLMGenerate] fallback 模型 {fallback_backend} 调用失败")
            error_msg = f"主模型失败且 fallback 失败: {e}"
            actual_backend = fallback_backend

    # ---------- 错误处理 ----------
    if error_msg or llm_data is None:
        _log_node_end(
            state, "LLMGenerate", t0,
            f"失败 | backend={actual_backend} | fallback={fallback_triggered} | {error_msg}"
        )
        return {
            **state,
            "error": error_msg or "LLM 调用未知错误",
            "llm_response_content": "",
            "actual_backend": actual_backend,
            "fallback_triggered": fallback_triggered,
            "fallback_reason": fallback_reason,
        }

    # ---------- 解析响应 ----------
    message = llm_data.get("choices", [{}])[0].get("message", {})
    content = message.get("content", "")
    reasoning_content = message.get("reasoning_content", "")
    usage = llm_data.get("usage", {})

    summary_parts = [f"backend={actual_backend}", f"内容长度: {len(content)}字"]
    if reasoning_content:
        summary_parts.append(f"思考: {len(reasoning_content)}字")
    if fallback_triggered:
        summary_parts.append(f"⚠️ 已故障转移: {fallback_reason}")
    summary_parts.append(f"prompt_tokens: {usage.get('prompt_tokens', '?')}")
    summary_parts.append(f"completion_tokens: {usage.get('completion_tokens', '?')}")

    _log_node_end(state, "LLMGenerate", t0, ", ".join(summary_parts))

    return {
        **state,
        "llm_payload": payload,
        "llm_response_content": content,
        "llm_reasoning_content": reasoning_content,
        "llm_raw_response": llm_data,
        "actual_backend": actual_backend,
        "fallback_triggered": fallback_triggered,
        "fallback_reason": fallback_reason,
    }


# ================================================================
# Node 12: FormatGuard
# ================================================================
async def format_guard_node(state: "AgentState") -> "AgentState":
    """格式质检：基于规则的越权输出检测 + 文风污染过滤

    规则集：
    1. 检测是否替 user 生成引号台词
    2. 检测垃圾小说描写关键词
    3. 输出长度异常检查
    """
    t0 = _log_node_start(state, "FormatGuard")

    content = state.get("llm_response_content", "")
    user_name = state.get("user_name", "用户")

    # 规则 1：检测替 user 生成台词（user_name + 引号内容）
    # 匹配模式：用户名后跟引号包裹的内容
    quote_pattern = re.compile(
        rf"{re.escape(user_name)}.*?[\"「『](.+?)[\"」』]",
        re.DOTALL
    )
    if quote_pattern.search(content):
        _log_node_end(state, "FormatGuard", t0, f"失败: 检测到替{user_name}生成台词")
        return {
            **state,
            "format_passed": False,
            "format_reason": f"检测到替{user_name}生成台词",
        }

    # 规则 2：检测垃圾小说描写关键词
    trash_keywords = ["臀", "翘臀", "酥胸", "玉腿", "纤腰", "蛮腰"]
    found_trash = [kw for kw in trash_keywords if kw in content]
    if found_trash:
        _log_node_end(state, "FormatGuard", t0, f"失败: 检测到文风污染关键词 {found_trash}")
        return {
            **state,
            "format_passed": False,
            "format_reason": f"检测到文风污染关键词: {', '.join(found_trash)}",
        }

    # 规则 3：输出长度异常
    if len(content) < 50:
        _log_node_end(state, "FormatGuard", t0, f"失败: 输出过短({len(content)}字)")
        return {
            **state,
            "format_passed": False,
            "format_reason": f"输出过短({len(content)}字)",
        }
    if len(content) > 3000:
        _log_node_end(state, "FormatGuard", t0, f"失败: 输出过长({len(content)}字)")
        return {
            **state,
            "format_passed": False,
            "format_reason": f"输出过长({len(content)}字)",
        }

    _log_node_end(state, "FormatGuard", t0, "通过")
    return {
        **state,
        "format_passed": True,
        "format_reason": "",
    }


# ================================================================
# Node 13: OOCCheck
# ================================================================
async def ooc_check_node(state: "AgentState") -> "AgentState":
    """人设一致性质检 — 轻量检查（基于角色卡关键词匹配）

    当前为轻量实现，后续可接入 LLM 深度检查。
    """
    t0 = _log_node_start(state, "OOCCheck")

    content = state.get("llm_response_content", "")
    decomposed = state.get("decomposed")
    char_card = ""
    if decomposed:
        char_card = decomposed.get("system_prompt", {}).get("character_card", "")

    # 轻量规则：如果角色卡中有明确的角色名，检查输出是否提到该角色
    # （这是一个极轻量的检查，避免完全无脑通过）
    ooc_reason = ""
    if char_card:
        # 提取角色卡第一行作为角色名候选
        first_line = char_card.split("\n")[0].strip()
        if first_line and len(first_line) < 30:
            # 如果角色名在角色卡中但输出中未出现，不一定是 OOC（可能是环境描写）
            # 所以这里只记录，不判定失败
            char_mentioned = first_line in content
            ooc_reason = f"角色名{'已' if char_mentioned else '未'}提及（轻量检查）"

    _log_node_end(state, "OOCCheck", t0, f"通过 | {ooc_reason}")
    return {
        **state,
        "ooc_passed": True,
        "ooc_reason": ooc_reason,
    }


# ================================================================
# Node 14: ContentFilter
# ================================================================
async def content_filter_node(state: "AgentState") -> "AgentState":
    """内容安全过滤 — 由 TAVO/LLM 服务商负责，AURA 层保持透传

    设计说明：AURA 的定位是 Prompt 编译器，内容安全由上游（TAVO）和下游（LLM 服务商）负责。
    此节点保留作为扩展点，当前默认通过。
    """
    t0 = _log_node_start(state, "ContentFilter")
    _log_node_end(state, "ContentFilter", t0, "通过（TAVO/LLM 服务商层负责）")
    return {
        **state,
        "content_passed": True,
        "content_reason": "",
    }


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


# ================================================================
# 并行质检节点：FormatGuard + OOCCheck + ContentFilter 并行执行
# ================================================================
async def parallel_quality_check_node(state: "AgentState") -> "AgentState":
    """
    并行执行三级质检：
        - FormatGuard: 输出格式检查（越权输出检测）
        - OOCCheck: 人设一致性检查
        - ContentFilter: 内容安全过滤

    三个质检之间无依赖，共享同一份 llm_response_content，
    并行后可从串行 3×T 降到 max(T1, T2, T3)。
    """
    t0 = time.time()

    base_state = dict(state)
    base_state.setdefault("node_logs", [])

    tasks = [
        format_guard_node(base_state),
        ooc_check_node(base_state),
        content_filter_node(base_state),
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    merged = dict(state)
    for result in results:
        if isinstance(result, Exception):
            logger.warning(f"[ParallelQualityCheck] 子任务失败: {result}")
            continue
        for key, value in result.items():
            if key != "node_logs":
                merged[key] = value

    # 确保质检标志有默认值（mock 阶段默认全部通过）
    merged.setdefault("format_passed", True)
    merged.setdefault("ooc_passed", True)
    merged.setdefault("content_passed", True)

    elapsed = (time.time() - t0) * 1000
    logs = merged.get("node_logs", [])
    logs.append({
        "node": "ParallelQualityCheck",
        "elapsed_ms": round(elapsed, 1),
        "summary": "format+ooc+content 并行质检完成",
    })
    merged["node_logs"] = logs

    logger.info(f"[ParallelQualityCheck] 并行质检完成 | 耗时: {elapsed:.1f}ms")
    return merged
