"""
AURA completions API — LangGraph 编排入口

v2.0.0 架构变更：
  1. LangGraph 工作流只负责 Prompt 编译（InputReceive → ... → ContextAssemble）
  2. LLM 调用已抽离到 completions.py，直接调用 LLM API
  3. 流式请求：直接 stream=true 调用 LLM，边收边转发给 TAVO（真正的实时流式）
  4. 非流式请求：等待完整响应后包装返回
  5. 保留主备故障转移逻辑
  6. 记忆保存改为异步后台执行
"""
import asyncio
import json
import time as _time
from typing import Optional, Dict, Any, AsyncGenerator

import httpx
from fastapi import HTTPException, Header
from fastapi.responses import StreamingResponse

from app.core.config import settings, get_llm_config
from app.memory import memory_manager
from app.graph.workflow import aura_workflow
from app.utils.logging import setup_logging, get_logger

from app.api.router import (
    router,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessageResponse,
    Choice,
    get_backend_for_model,
    WorldCompletionRequest,
)

# 路线B：平台模式导入
from app.world import world_runtime
from app.director import director
from app.npc import NPCAgent

# 初始化全局日志配置
setup_logging()

logger = get_logger("aura-completions")


# ================================================================
# 内部辅助：单次 LLM 调用（非流式）
# ================================================================
async def _call_single_llm(
    backend: str,
    model_name: Optional[str],
    payload: Dict[str, Any],
    timeout: int,
) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    """执行单次非流式 LLM 调用。Returns: (llm_data, error_msg)"""
    llm_config = get_llm_config(backend, scene="main", model_name=model_name)
    if not llm_config or not llm_config.api_key:
        return None, f"后端 {backend} 未正确配置"

    api_key = llm_config.api_key.strip()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    url = f"{llm_config.base_url.rstrip('/')}/chat/completions"

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
# 内部辅助：非流式 LLM 调用（含主备故障转移）
# ================================================================
async def _call_llm_non_stream(
    backend: str,
    model_name: Optional[str],
    messages_list: list,
    temperature: float,
    max_tokens: Optional[int],
) -> tuple[str, str, str, Dict[str, Any], bool, str]:
    """
    非流式调用 LLM，支持主备故障转移。

    Returns:
        (content, reasoning_content, actual_backend, raw_response, fallback_triggered, fallback_reason)
    """
    payload = {
        "model": model_name or "deepseek-v4-flash",
        "messages": messages_list,
        "temperature": temperature,
        "stream": False,
    }
    if max_tokens:
        payload["max_tokens"] = max_tokens

    # 第一轮：主模型（受 ttfb_timeout 限制）
    llm_data: Optional[Dict[str, Any]] = None
    error_msg: Optional[str] = None
    actual_backend = backend
    fallback_triggered = False
    fallback_reason = ""

    try:
        llm_data, error_msg = await asyncio.wait_for(
            _call_single_llm(backend, model_name, payload, timeout=settings.llm_main_timeout),
            timeout=settings.llm_main_ttfb_timeout,
        )
    except asyncio.TimeoutError:
        fallback_triggered = True
        fallback_reason = f"ttfb_timeout: {backend}"
        logger.warning(
            f"[LLM] 主模型 {backend} 首 token 超时 ({settings.llm_main_ttfb_timeout}s)，"
            f"触发故障转移 → {settings.llm_main_fallback_provider}"
        )
    except Exception as e:
        fallback_triggered = True
        fallback_reason = f"exception: {backend} | {type(e).__name__}: {e}"
        logger.warning(
            f"[LLM] 主模型 {backend} 调用异常，触发故障转移 → "
            f"{settings.llm_main_fallback_provider} | 异常: {type(e).__name__}: {e}"
        )

    # 第二轮：fallback 模型
    if fallback_triggered:
        fallback_backend = settings.llm_main_fallback_provider
        try:
            llm_data, error_msg = await _call_single_llm(
                fallback_backend, None, payload, timeout=settings.llm_main_timeout
            )
            actual_backend = fallback_backend
        except Exception as e:
            logger.exception(f"[LLM] fallback 模型 {fallback_backend} 调用失败")
            raise HTTPException(status_code=503, detail=f"LLM调用失败: 主模型故障且fallback失败: {e}")

    if error_msg or llm_data is None:
        raise HTTPException(status_code=503, detail=error_msg or "LLM 调用未知错误")

    message = llm_data.get("choices", [{}])[0].get("message", {})
    content = message.get("content", "")
    reasoning_content = message.get("reasoning_content", "")

    logger.info(
        f"[LLM] 非流式调用完成 | backend={actual_backend} | "
        f"内容: {len(content)}字 | 思考: {len(reasoning_content)}字 | "
        f"fallback={fallback_triggered}"
    )

    return content, reasoning_content, actual_backend, llm_data, fallback_triggered, fallback_reason


# ================================================================
# 内部辅助：流式 LLM 调用（含主备故障转移，实时转发）
# ================================================================
async def _stream_llm_direct(
    backend: str,
    model_name: Optional[str],
    messages_list: list,
    temperature: float,
    max_tokens: Optional[int],
    session_id: str,
    request_model: str,
    x_tavo_debug: Optional[str],
    user_content: str = "",
    tavo_dialogue: list = None,
    round_num: int = 0,
) -> StreamingResponse:
    """
    流式调用 LLM，边收 chunk 边转发给 TAVO。
    支持主备故障转移。
    """
    payload = {
        "model": model_name or "deepseek-v4-flash",
        "messages": messages_list,
        "temperature": temperature,
        "stream": True,
    }
    if max_tokens:
        payload["max_tokens"] = max_tokens

    extra_headers = {}
    if x_tavo_debug == "true":
        extra_headers["X-Aura-Debug"] = "true"
        extra_headers["X-Aura-Session"] = session_id

    async def _try_stream_llm(
        target_backend: str,
        target_model: Optional[str],
        ttfb_timeout: Optional[float] = None,
    ) -> AsyncGenerator[bytes, None]:
        """尝试流式调用指定后端，失败时抛出异常由上层处理故障转移。"""
        llm_config = get_llm_config(target_backend, scene="main", model_name=target_model)
        if not llm_config or not llm_config.api_key:
            raise RuntimeError(f"后端 {target_backend} 未正确配置")

        api_key = llm_config.api_key.strip()
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        url = f"{llm_config.base_url.rstrip('/')}/chat/completions"

        actual_payload = dict(payload)
        actual_payload["model"] = llm_config.model
        actual_payload["temperature"] = llm_config.temperature

        stream_timeout = settings.llm_main_timeout
        read_timeout = None  # 流式读取不设超时，让连接保持

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(stream_timeout, read=read_timeout)
        ) as client:
            response = await client.send(
                client.build_request("POST", url, headers=headers, json=actual_payload),
                stream=True,
            )

            if response.status_code != 200:
                error_body = await response.aread()
                error_text = error_body.decode("utf-8", errors="replace")[:500]
                raise RuntimeError(f"后端错误 {response.status_code}: {error_text}")

            logger.info(
                f"[LLM→AURA] 流式响应开始 | 会话: {session_id} | 后端: {target_backend}"
            )

            first_chunk_received = False
            buffer = b""

            async for chunk in response.aiter_bytes():
                if not chunk:
                    continue
                buffer += chunk

                # 按行分割处理
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    line_str = line.decode("utf-8", errors="replace").strip()
                    if not line_str:
                        continue

                    if line_str == "data: [DONE]":
                        yield b"data: [DONE]\n\n"
                        return

                    if line_str.startswith("data: "):
                        if not first_chunk_received:
                            first_chunk_received = True
                            logger.info(
                                f"[LLM→AURA] 收到首 chunk | 会话: {session_id} | "
                                f"后端: {target_backend}"
                            )

                        try:
                            data = json.loads(line_str[6:])
                        except json.JSONDecodeError:
                            continue

                        # 重建 OpenAI 格式 chunk 转发给 TAVO
                        sse_data = {
                            "id": f"aura-{session_id}-{_time.time():.6f}",
                            "object": "chat.completion.chunk",
                            "created": int(_time.time()),
                            "model": request_model,
                            "choices": data.get("choices", [{}]),
                        }
                        yield f"data: {json.dumps(sse_data, ensure_ascii=False)}\n\n".encode("utf-8")

            # 处理 buffer 中剩余的内容
            if buffer:
                line_str = buffer.decode("utf-8", errors="replace").strip()
                if line_str.startswith("data: ") and line_str != "data: [DONE]":
                    try:
                        data = json.loads(line_str[6:])
                        sse_data = {
                            "id": f"aura-{session_id}-{_time.time():.6f}",
                            "object": "chat.completion.chunk",
                            "created": int(_time.time()),
                            "model": request_model,
                            "choices": data.get("choices", [{}]),
                        }
                        yield f"data: {json.dumps(sse_data, ensure_ascii=False)}\n\n".encode("utf-8")
                    except json.JSONDecodeError:
                        pass

            yield b"data: [DONE]\n\n"

    async def stream_generator():
        """带故障转移的流式生成器。"""
        actual_backend = backend
        fallback_triggered = False
        fallback_reason = ""
        full_content_parts = []  # 收集完整内容用于保存

        # 第一轮：主模型
        try:
            async for chunk in _try_stream_llm(backend, model_name, ttfb_timeout=settings.llm_main_ttfb_timeout):
                yield chunk
                # 从 chunk 中提取 content 用于保存
                try:
                    line = chunk.decode("utf-8", errors="replace").strip()
                    if line.startswith("data: ") and line != "data: [DONE]":
                        data = json.loads(line[6:])
                        delta = data.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            full_content_parts.append(content)
                except (json.JSONDecodeError, IndexError, KeyError):
                    pass
            logger.info(f"[AURA→TAVO] 流式返回完成 | 会话: {session_id} | 后端: {backend}")
        except asyncio.TimeoutError:
            fallback_triggered = True
            fallback_reason = f"ttfb_timeout: {backend}"
            logger.warning(
                f"[LLM] 主模型 {backend} 流式首 token 超时，"
                f"触发故障转移 → {settings.llm_main_fallback_provider}"
            )
        except Exception as e:
            fallback_triggered = True
            fallback_reason = f"exception: {backend} | {type(e).__name__}: {e}"
            logger.warning(
                f"[LLM] 主模型 {backend} 流式调用异常，"
                f"触发故障转移 → {settings.llm_main_fallback_provider}"
            )

        # 第二轮：fallback
        if fallback_triggered:
            fallback_backend = settings.llm_main_fallback_provider
            try:
                async for chunk in _try_stream_llm(fallback_backend, None):
                    yield chunk
                    # 从 chunk 中提取 content 用于保存
                    try:
                        line = chunk.decode("utf-8", errors="replace").strip()
                        if line.startswith("data: ") and line != "data: [DONE]":
                            data = json.loads(line[6:])
                            delta = data.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                full_content_parts.append(content)
                    except (json.JSONDecodeError, IndexError, KeyError):
                        pass
                logger.info(
                    f"[AURA→TAVO] 流式返回完成（fallback）| "
                    f"会话: {session_id} | 后端: {fallback_backend}"
                )
            except Exception as e:
                logger.exception(f"[LLM] fallback 模型 {fallback_backend} 流式调用失败")
                error_sse = {
                    "id": f"aura-{session_id}",
                    "object": "chat.completion.chunk",
                    "created": int(_time.time()),
                    "model": request_model,
                    "choices": [{
                        "index": 0,
                        "delta": {"content": f"[AURA错误] LLM调用失败: {e}"},
                        "finish_reason": "stop",
                    }],
                }
                yield f"data: {json.dumps(error_sse, ensure_ascii=False)}\n\n".encode("utf-8")
                yield b"data: [DONE]\n\n"

        # 流式完成后，后台保存对话
        assistant_content = "".join(full_content_parts)
        if assistant_content or user_content:
            _save_dialogue_async(
                session_id, round_num, user_content, assistant_content, tavo_dialogue or []
            )

    return StreamingResponse(
        stream_generator(),
        media_type="text/event-stream",
        headers=extra_headers,
    )


# ================================================================
# 内部辅助：异步保存对话到记忆
# ================================================================
def _save_dialogue_async(
    aura_session_id: str,
    round_num: int,
    user_content: str,
    assistant_content: str,
    tavo_dialogue: list,
):
    """后台异步保存对话（不阻塞响应）"""
    async def _do_save():
        try:
            if tavo_dialogue:
                await memory_manager.sync_dialogue_from_tavo(aura_session_id, tavo_dialogue)
            if user_content:
                await memory_manager.save_dialogue(aura_session_id, "user", user_content, round_num + 1)
            if assistant_content:
                await memory_manager.save_dialogue(aura_session_id, "assistant", assistant_content, round_num + 1)

            # 触发总结
            new_round = round_num + 1
            if new_round > 0 and new_round % settings.memory_summary_interval == 0:
                recent = await memory_manager.get_recent_messages(aura_session_id, n=10)
                if recent:
                    asyncio.ensure_future(
                        memory_manager.summarize_and_store(aura_session_id, recent)
                    )
                    logger.info(f"[记忆] 触发总结(轮={new_round}) | 会话: {aura_session_id}")
        except Exception as e:
            logger.warning(f"[记忆] 保存对话失败（不影响返回）: {e}")

    asyncio.ensure_future(_do_save())


# ================================================================
# 核心 API：chat/completions
# ================================================================
@router.post("/chat/completions")
async def chat_completion(
    request: ChatCompletionRequest,
    x_tavo_debug: Optional[str] = Header(None, alias="X-Tavo-Debug")
):
    """
    AURA 核心 API — v2.0.0

    流程：
    1. 请求验证
    2. LangGraph 工作流执行 Prompt 编译（产出 messages_list）
    3. 直接调用 LLM API（流式/非流式）
    4. 异步保存对话到记忆
    """
    session_id = f"aura_{int(_time.time())}_{id(request)}"

    logger.info(
        f"[TAVO→AURA] 收到请求 | 会话: {session_id} | "
        f"模型: {request.model} | 流式: {request.stream} | 消息数: {len(request.messages)}"
    )

    # 1. 请求验证
    if not request.messages:
        raise HTTPException(status_code=400, detail="messages 字段不能为空")
    if not request.model:
        raise HTTPException(status_code=400, detail="model 字段不能为空")

    backend, actual_model = get_backend_for_model(request.model)
    llm_config = get_llm_config(backend, scene="main", model_name=actual_model)
    if not llm_config or not llm_config.api_key:
        raise HTTPException(status_code=503, detail=f"后端 {backend} 未正确配置")

    # 提取最后一条 user 消息
    user_content = ""
    for msg in reversed(request.messages):
        if msg.role == "user":
            user_content = msg.content
            break

    # ============================================================
    # 2. LangGraph 工作流：Prompt 编译
    # ============================================================
    initial_state = {
        "request": {
            "model": request.model,
            "messages": [msg.model_dump() for msg in request.messages],
            "temperature": request.temperature,
            "stream": False,
            "max_tokens": request.max_tokens,
        },
        "session_id": session_id,
        "backend": backend,
        "model": request.model,
        "stream": False,
        "temperature": request.temperature,
        "max_tokens": request.max_tokens,
        "x_tavo_debug": x_tavo_debug,
        "user_content": user_content,
        "round_num": 0,
        "node_logs": [],
        "start_time": _time.time(),
    }

    logger.info(f"[LangGraph] 开始 Prompt 编译 | session={session_id}")

    try:
        final_state = await aura_workflow.ainvoke(
            initial_state,
            config={"configurable": {"thread_id": session_id}}
        )
    except Exception as e:
        logger.exception(f"[LangGraph] 工作流执行失败: {e}")
        raise HTTPException(status_code=500, detail=f"Prompt 编译失败: {str(e)}")

    # 从工作流状态获取编译结果
    messages_list = final_state.get("messages_list", [])
    if not messages_list:
        raise HTTPException(status_code=500, detail="Prompt 编译未产出有效消息列表")

    node_logs = final_state.get("node_logs", [])
    compile_ms = sum(l.get("elapsed_ms", 0) for l in node_logs)
    logger.info(
        f"[LangGraph] Prompt 编译完成 | 耗时: {compile_ms:.1f}ms | "
        f"节点: {len(node_logs)} | 消息数: {len(messages_list)}"
    )
    for log in node_logs:
        logger.info(f"  → {log['node']}: {log['elapsed_ms']}ms | {log.get('summary', '')}")

    # ============================================================
    # 3. 直接调用 LLM（流式/非流式）
    # ============================================================
    if request.stream:
        # 流式：直接 stream=true 调用 LLM，边收边转发
        logger.info(f"[LLM] 开始流式调用 | session={session_id}")
        return await _stream_llm_direct(
            backend=backend,
            model_name=actual_model,
            messages_list=messages_list,
            temperature=request.temperature or 0.7,
            max_tokens=request.max_tokens,
            session_id=session_id,
            request_model=request.model,
            x_tavo_debug=x_tavo_debug,
            user_content=user_content,
            tavo_dialogue=final_state.get("tavo_dialogue_messages", []),
            round_num=final_state.get("round_num", 0),
        )
    else:
        # 非流式：等待完整响应
        logger.info(f"[LLM] 开始非流式调用 | session={session_id}")
        content, reasoning_content, actual_backend, raw_response, fallback_triggered, fallback_reason = \
            await _call_llm_non_stream(
                backend=backend,
                model_name=actual_model,
                messages_list=messages_list,
                temperature=request.temperature or 0.7,
                max_tokens=request.max_tokens,
            )

        usage = raw_response.get("usage", {})
        logger.info(
            f"[LLM] 非流式完成 | backend={actual_backend} | "
            f"内容: {len(content)}字 | 思考: {len(reasoning_content)}字 | "
            f"prompt_tokens: {usage.get('prompt_tokens', '?')} | "
            f"completion_tokens: {usage.get('completion_tokens', '?')}"
        )

        # 构建响应
        message = {"role": "assistant", "content": content}
        if reasoning_content:
            message["reasoning_content"] = reasoning_content

        choices = [Choice(
            index=0,
            message=ChatMessageResponse(**message),
            finish_reason="stop",
        )]
        response_obj = ChatCompletionResponse(
            id=f"aura-{session_id}",
            object="chat.completion",
            created=int(_time.time()),
            model=request.model,
            choices=choices,
        )
        if "usage" in raw_response:
            response_obj.usage = raw_response["usage"]
        if x_tavo_debug == "true":
            response_obj.aura_debug = {
                "session_id": session_id,
                "timestamp": int(_time.time()),
                "mode": "direct",
                "backend": backend,
                "actual_backend": actual_backend,
                "fallback_triggered": fallback_triggered,
                "fallback_reason": fallback_reason,
                "node_count": len(node_logs),
                "compile_ms": compile_ms,
            }

        logger.info(f"[AURA→TAVO] 返回响应 | 会话: {session_id} | 内容: {len(content)}字")

        # 异步保存对话
        tavo_dialogue = final_state.get("tavo_dialogue_messages", [])
        round_num = final_state.get("round_num", 0)
        _save_dialogue_async(session_id, round_num, user_content, content, tavo_dialogue)

        return response_obj


# ============================================================
# 路线B：平台模式 API — 文字冒险入口（不变）
# ============================================================
@router.post("/world/completions")
async def world_completion(
    request: WorldCompletionRequest,
    x_tavo_debug: Optional[str] = Header(None, alias="X-Tavo-Debug")
):
    """
    AURA 平台模式 API — 文字冒险入口

    与 /chat/completions（TAVO 兼容模式）并行存在。
    此端点使用 Director + NPC Agent 架构，而非 LangGraph 状态机。
    """
    session_id = f"aura_world_{int(_time.time())}_{id(request)}"
    logger.info(
        f"[WorldMode] 收到请求 | 会话: {session_id} | "
        f"卡带: {request.cartridge or '(已加载)'} | 输入: {request.message[:50]}..."
    )

    # ---------- 1. 世界加载 ----------
    if not world_runtime.is_loaded():
        if not request.cartridge:
            raise HTTPException(
                status_code=400,
                detail="世界未加载，请提供 cartridge 参数指定卡带"
            )
        try:
            world_runtime.load_cartridge(request.cartridge)
        except Exception as e:
            logger.exception(f"[WorldMode] 卡带加载失败: {e}")
            raise HTTPException(status_code=500, detail=f"卡带加载失败: {str(e)}")

    world = world_runtime.world
    if not world:
        raise HTTPException(status_code=500, detail="世界状态异常")

    # ---------- 2. Director 处理 ----------
    field = director.get_field_snapshot(request.location_id)
    logger.info(
        f"[WorldMode] 场域快照 | 地点: {field.location_id} | "
        f"在场: {field.present_entities} | 时间: {field.time}"
    )

    mentioned_entity = director.resolve_mention(request.message, field)
    if mentioned_entity:
        logger.info(f"[WorldMode] 指代消解: {mentioned_entity}")

    violated, rule_reason = director.check_rule_violation(
        request.message, request.player_entity_id, field.location_id
    )
    if violated:
        logger.warning(f"[WorldMode] 规则违规: {rule_reason}")

    npc_ids = director.schedule_npcs(field)
    logger.info(f"[WorldMode] NPC 调度: {npc_ids}")

    if not npc_ids:
        ambient = director.render_ambient(field)
        content = ambient or "四周一片寂静，只有风吹过树叶的声音。"
        return ChatCompletionResponse(
            id=f"aura-world-{session_id}",
            model=request.model,
            choices=[Choice(
                index=0,
                message=ChatMessageResponse(role="assistant", content=content),
                finish_reason="stop",
            )],
        )

    # ---------- 3. NPC Agent 生成回应 ----------
    backend, actual_model = get_backend_for_model(request.model)
    npc_outputs = {}

    target_npc_id = npc_ids[0]
    agent = NPCAgent(target_npc_id)
    field_slice = director.get_npc_field_slice(target_npc_id, field)

    try:
        npc_response = await agent.generate_response(
            player_input=request.message,
            field_slice=field_slice,
            backend=backend,
            temperature=request.temperature,
        )
        npc_outputs[target_npc_id] = npc_response
        logger.info(
            f"[WorldMode] NPC 回应 | {target_npc_id} | 长度: {len(npc_response)}字"
        )
    except Exception as e:
        logger.exception(f"[WorldMode] NPC 生成失败: {e}")
        raise HTTPException(status_code=500, detail=f"NPC 生成失败: {str(e)}")

    # ---------- 4. Director 仲裁 ----------
    final_content = director.arbitrate_outputs(npc_outputs)

    # ---------- 5. 构建响应 ----------
    choices = [Choice(
        index=0,
        message=ChatMessageResponse(role="assistant", content=final_content),
        finish_reason="stop",
    )]
    response_obj = ChatCompletionResponse(
        id=f"aura-world-{session_id}",
        model=request.model,
        choices=choices,
    )

    if x_tavo_debug == "true":
        response_obj.aura_debug = {
            "session_id": session_id,
            "timestamp": int(_time.time()),
            "mode": "world",
            "cartridge": world_runtime._cartridge_name,
            "location_id": field.location_id,
            "present_entities": field.present_entities,
            "scheduled_npcs": npc_ids,
            "mentioned_entity": mentioned_entity,
            "rule_violated": violated,
            "rule_reason": rule_reason,
        }

    logger.info(f"[WorldMode] 返回响应 | 会话: {session_id} | 内容: {len(final_content)}字")
    return response_obj


# --- 初始化函数 ---
async def initialize_aura():
    """初始化AURA系统"""
    try:
        logger.info("AURA 初始化完成")
        logger.info("服务模式: LangGraph Prompt编译器 + 直接LLM调用 (v2.0.0)")
        logger.info(f"调试模式: {'启用' if settings.debug_mode else '禁用'}")

        # 验证LLM配置
        from app.core.config import validate_llm_config
        config_status = validate_llm_config()
        active_backends = [name for name, status in config_status.items() if status]
        logger.info(f"激活的LLM后端: {active_backends}")

        if not active_backends:
            logger.warning("没有配置有效的LLM后端，请检查环境变量")

        # 初始化记忆管理器
        await memory_manager.initialize()
        mem_count = await memory_manager.get_memory_count()
        logger.info(f"[AURA→记忆] MemoryManager 就绪 | FAISS 记忆数: {mem_count}")

        # 路线B：预加载卡带列表
        from app.cartridge import CartridgeLoader
        loader = CartridgeLoader("cartridges")
        available = loader.list_available()
        if available:
            logger.info(f"[AURA→卡带] 可用卡带: {available}")

    except Exception as e:
        logger.exception("AURA初始化失败")
        raise
