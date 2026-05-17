"""
AURA completions API — LangGraph 编排入口 + 流式返回工具

v0.8.0 架构：
  1. 接收 TAVO 请求 → 保存 Prompt dump 到本地
  2. 组装 AgentState → 调用 aura_workflow.ainvoke()
  3. LangGraph 15 节点状态机执行：
     InputReceive → EntityExtract → EmotionAnalyze → MemoryDecision →
     MemoryRetrieve → StateManager → StyleInjection → ModelDialectCompiler →
     ContextAssemble → LLMGenerate → FormatGuard → OOCCheck → ContentFilter →
     OutputReturn → MemoryExtract
  4. 质检失败后自动重试（条件边回退到 ModelDialectCompiler）
  5. 从最终状态构建响应（非流式/流式统一处理）

保留函数：
  - _build_streaming_response()：将完整内容切割为 SSE chunk 模拟流式返回
"""
import os
import re
import asyncio
import httpx
import json
import time
import logging
from typing import List, Literal, Optional, Dict, Any, Union
from fastapi import APIRouter, HTTPException, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ConfigDict

from app.config import settings, get_llm_config, validate_llm_config, LLMConfig
from app.prompt_decomposer import PromptDecomposer
from app.memory import memory_manager
from app.intent_tagger import intent_tagger
from app.memory.models import IntentStructure, IntentResult
from app.graph.workflow import aura_workflow
from app.utils.logging import setup_logging, get_logger

# 初始化全局日志配置
setup_logging()

logger = get_logger("aura-completions")

# ============================================================
# 全局拆解器实例
# ============================================================
decomposer = PromptDecomposer()

# 会话 ID 映射（TAVO session → AURA session）
_session_map: Dict[str, str] = {}

router = APIRouter()

# --- 请求响应模型 ---
class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str

class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    temperature: Optional[float] = 0.7
    stream: Optional[bool] = False
    max_tokens: Optional[int] = None

class ChatMessageResponse(BaseModel):
    role: str
    content: str

class Choice(BaseModel):
    index: int = 0
    message: ChatMessageResponse
    finish_reason: str = "stop"

class ChatCompletionResponse(BaseModel):
    model_config = ConfigDict(extra="allow")  # 允许额外字段如 usage, system_fingerprint
    id: str = "aura-direct"
    object: str = "chat.completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str
    choices: List[Choice]
    aura_debug: Optional[Dict[str, Any]] = None

# 模型 → 后端名称映射 (可根据需要扩展)
BACKEND_MAP = {
    "deepseek-v4-flash": "deepseek",
    "deepseek-v4-pro": "deepseek",
    # 其他模型可在此添加
}

def get_backend_for_model(model: str) -> str:
    """根据模型名称返回对应的后端标识"""
    if model in BACKEND_MAP:
        return BACKEND_MAP[model]
    # 后备：如果模型名以 deepseek 开头，使用 deepseek 后端
    if model.startswith("deepseek"):
        return "deepseek"
    # 否则使用默认后端
    return settings.default_llm

# --- TAVO兼容接口 ---
@router.get("/models")
async def get_models():
    """获取可用模型列表（TAVO兼容性）"""
    return {
        "object": "list",
        "data": [
            {
                "id": "deepseek-v4-flash",
                "object": "model",
                "created": 1700000000,
                "owned_by": "deepseek"
            },
            {
                "id": "deepseek-v4-pro", 
                "object": "model",
                "created": 1700000000,
                "owned_by": "deepseek"
            }
        ]
    }

# --- 核心API处理 ---
@router.post("/chat/completions")
async def chat_completion(
    request: ChatCompletionRequest,
    x_tavo_debug: Optional[str] = Header(None, alias="X-Tavo-Debug")
):
    """
    AURA 核心 API — LangGraph 编排入口 (v0.8.0)

    原顺序执行逻辑（Prompt 拆解 → RAG → LLM 调用）已迁移到
    app/graph/workflow.py 的 15 节点状态机中。

    当前入口职责：
    1. 请求验证 + 日志 dump（保留）
    2. 组装 AgentState
    3. 调用 aura_workflow.ainvoke() 执行状态图
    4. 从最终状态构建响应（非流式/流式统一处理）
    """
    session_id = f"aura_{int(time.time())}_{id(request)}"

    # [TAVO→AURA] 记录收到的 TAVO 请求
    logger.info(
        f"[TAVO→AURA] 收到请求 | 会话: {session_id} | "
        f"模型: {request.model} | 流式: {request.stream} | "
        f"消息数: {len(request.messages)}"
    )

    # 保存 TAVO 请求到日志文件
    tavo_log_entry = {
        "session_id": session_id,
        "model": request.model,
        "stream": request.stream,
        "message_count": len(request.messages),
        "messages_preview": [
            {"role": m.role, "content_preview": m.content[:100] + "..." if len(m.content) > 100 else m.content}
            for m in request.messages[:3]
        ],
        "temperature": request.temperature,
        "timestamp": int(time.time())
    }
    logger.info(f"[TAVO→AURA] 请求详情: {json.dumps(tavo_log_entry, ensure_ascii=False)}")

    # 1. 请求验证
    if not request.messages:
        raise HTTPException(status_code=400, detail="messages 字段不能为空")
    if not request.model:
        raise HTTPException(status_code=400, detail="model 字段不能为空")

    # ============================================================
    # 1.5 保存完整 Prompt 到本地文件
    # ============================================================
    try:
        prompt_dump_dir = "prompt_dumps"
        os.makedirs(prompt_dump_dir, exist_ok=True)
        time_str = time.strftime("%Y%m%d_%H%M%S")
        dump_file = os.path.join(prompt_dump_dir, f"prompt_{time_str}.txt")
        with open(dump_file, "w", encoding="utf-8") as f:
            f.write(f"=== TAVO 完整请求转储 ===\n")
            f.write(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"模型: {request.model}\n")
            f.write(f"流式: {request.stream}\n")
            f.write(f"消息数: {len(request.messages)}\n")
            f.write(f"{'='*60}\n\n")
            for i, msg in enumerate(request.messages):
                f.write(f"--- 消息 {i} | role: {msg.role} | 长度: {len(msg.content)}字符 ---\n")
                f.write(msg.content)
                f.write("\n\n")
        file_size = os.path.getsize(dump_file)
        logger.info(f"[TAVO→AURA] Prompt 已保存到: {dump_file} ({file_size}字节)")

        tavo_input_file = os.path.join(prompt_dump_dir, f"tavo_input_{time_str}.txt")
        with open(tavo_input_file, "w", encoding="utf-8") as f:
            f.write(f"=== TAVO 原始请求 ===\n")
            f.write(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"模型: {request.model}\n")
            f.write(f"流式: {request.stream}\n")
            f.write(f"消息数: {len(request.messages)}\n")
            f.write(f"{'='*60}\n\n")
            for i, msg in enumerate(request.messages):
                f.write(f"--- 消息 {i} | role: {msg.role} | 长度: {len(msg.content)}字符 ---\n")
                f.write(msg.content)
                f.write("\n\n")
        logger.info(f"[TAVO→AURA] 调试日志已保存: {tavo_input_file}")
    except Exception as e:
        logger.warning(f"[TAVO→AURA] 保存 Prompt 失败: {e}")

    # ============================================================
    # 2. 获取后端配置
    # ============================================================
    backend = get_backend_for_model(request.model)
    llm_config = get_llm_config(backend, scene="main")
    if not llm_config or not llm_config.api_key:
        raise HTTPException(status_code=503, detail=f"后端 {backend} 未正确配置")

    # ============================================================
    # 3. 组装 AgentState 并调用 LangGraph 状态机
    # ============================================================
    import time as _time

    # 提取最后一条 user 消息内容
    user_content = ""
    for msg in reversed(request.messages):
        if msg.role == "user":
            user_content = msg.content
            break

    # 获取 AURA 会话 ID
    aura_session_id = _session_map.get(session_id, session_id)
    _session_map[session_id] = aura_session_id

    initial_state = {
        "request": {
            "model": request.model,
            "messages": [msg.model_dump() for msg in request.messages],
            "temperature": request.temperature,
            "stream": False,  # LangGraph 内部总为非流式（先完整生成 → 再流式返回）
            "max_tokens": request.max_tokens,
        },
        "messages": [msg.model_dump() for msg in request.messages],
        "session_id": session_id,
        "aura_session_id": aura_session_id,
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

    logger.info(f"[LangGraph] 开始执行工作流 | session={session_id} | stream={request.stream}")

    try:
        final_state = await aura_workflow.ainvoke(
            initial_state,
            config={"configurable": {"thread_id": aura_session_id}}
        )
    except Exception as e:
        logger.exception(f"[LangGraph] 工作流执行失败: {e}")
        raise HTTPException(status_code=500, detail=f"工作流执行失败: {str(e)}")

    # ============================================================
    # 4. 从最终状态构建响应
    # ============================================================
    error = final_state.get("error")
    if error:
        raise HTTPException(status_code=500, detail=f"处理失败: {error}")

    response_dict = final_state.get("response")
    if not response_dict:
        raise HTTPException(status_code=500, detail="工作流未产出有效响应")

    llm_message = response_dict.get("choices", [{}])[0].get("message", {})
    llm_content = llm_message.get("content", "")
    llm_reasoning = llm_message.get("reasoning_content", "")
    usage = response_dict.get("usage", {})

    # 打印 LangGraph 节点执行摘要
    node_logs = final_state.get("node_logs", [])
    total_ms = sum(l.get("elapsed_ms", 0) for l in node_logs)
    logger.info(
        f"[LangGraph] 工作流完成 | 总耗时: {total_ms:.1f}ms | "
        f"节点: {len(node_logs)} | 内容: {len(llm_content)}字"
    )
    for log in node_logs:
        logger.info(
            f"  → {log['node']}: {log['elapsed_ms']}ms | {log.get('summary', '')}"
        )

    # ============================================================
    # 5. 流式/非流式分别返回
    # ============================================================
    if request.stream:
        # LangGraph 内部已完整生成内容，现在模拟 SSE 流式返回
        return _build_streaming_response(
            llm_content, session_id, request.model, x_tavo_debug,
            reasoning_content=llm_reasoning
        )
    else:
        # 非流式：包装为 ChatCompletionResponse
        choices = [Choice(
            index=0,
            message=ChatMessageResponse(role="assistant", content=llm_content),
            finish_reason="stop",
        )]
        response_obj = ChatCompletionResponse(
            id=response_dict.get("id", f"aura-{session_id}"),
            object="chat.completion",
            created=response_dict.get("created", int(_time.time())),
            model=request.model,
            choices=choices,
        )
        if usage:
            response_obj.usage = usage
        if x_tavo_debug == "true":
            response_obj.aura_debug = {
                "session_id": session_id,
                "timestamp": int(_time.time()),
                "mode": "langgraph",
                "backend": backend,
                "node_count": len(node_logs),
                "total_ms": total_ms,
            }

        logger.info(f"[AURA→TAVO] 返回响应 | 会话: {session_id} | 内容: {len(llm_content)}字")
        return response_obj


def _build_streaming_response(
    full_content: str,
    session_id: str,
    model: str,
    debug_flag: Optional[str],
    reasoning_content: str = "",
) -> StreamingResponse:
    """将完整内容切割为 SSE chunk，模拟流式返回（复用原逻辑）"""
    import re

    async def stream_generator():
        if not full_content and not reasoning_content:
            yield b"data: [DONE]\n\n"
            return

        # 阶段1：先发送 reasoning_content（思考过程）
        if reasoning_content:
            reasoning_segments = _split_into_segments(reasoning_content)
            for seg in reasoning_segments:
                if not seg:
                    continue
                sse_data = {
                    "id": f"aura-{session_id}-{int(time.time())}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [{
                        "index": 0,
                        "delta": {"reasoning_content": seg},
                        "finish_reason": None
                    }]
                }
                yield f"data: {json.dumps(sse_data, ensure_ascii=False)}\n\n".encode('utf-8')
                delay = min(0.05, max(0.02, len(seg) * 0.002))
                await asyncio.sleep(delay)

        # 阶段2：发送 content（正式回复）
        if full_content:
            content_segments = _split_into_segments(full_content)
            logger.info(
                f"[AURA→TAVO] 模拟流式返回 | 会话: {session_id} | "
                f"总字符: {len(full_content)} | 思考: {len(reasoning_content)}字 | "
                f"切分段数: {len(content_segments)}"
            )

            for segment in content_segments:
                if not segment:
                    continue
                sse_data = {
                    "id": f"aura-{session_id}-{int(time.time())}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [{
                        "index": 0,
                        "delta": {"content": segment},
                        "finish_reason": None
                    }]
                }
                yield f"data: {json.dumps(sse_data, ensure_ascii=False)}\n\n".encode('utf-8')
                delay = min(0.08, max(0.03, len(segment) * 0.003))
                await asyncio.sleep(delay)

        yield b"data: [DONE]\n\n"
        logger.info(f"[AURA→TAVO] 流式返回完成 | 会话: {session_id}")

    extra_headers = {}
    if debug_flag == "true":
        extra_headers["X-Aura-Debug"] = "true"
        extra_headers["X-Aura-Session"] = session_id

    return StreamingResponse(
        stream_generator(),
        media_type="text/event-stream",
        headers=extra_headers
    )


def _split_into_segments(text: str) -> List[str]:
    """将文本按段落+句子粒度切分为 SSE 块"""
    import re
    paragraphs = text.split('\n\n')
    sentence_delimiters = re.compile(
        r'(?<=[。！？.!?])(?:\s*(?=[\u4e00-\u9fff"「「*]))'
        r'|(?<=[。！？.!?])'
    )

    segments = []
    for i, para in enumerate(paragraphs):
        if not para.strip():
            continue
        raw_sentences = sentence_delimiters.split(para)
        para_sentences = [s.strip() for s in raw_sentences if s.strip()]
        if not para_sentences:
            para_text = para.strip()
        else:
            para_text = ''.join(para_sentences)
        if i < len(paragraphs) - 1:
            para_text += '\n\n'
        segments.append(para_text)

    if not segments:
        segments = [text[i:i+20] for i in range(0, len(text), 20)]

    return segments

async def _handle_non_streaming_request(
    url: str,
    headers: Dict[str, str],
    payload: Dict[str, Any],
    session_id: str,
    debug_flag: Optional[str],
    model_name: str,
    llm_config: Optional[LLMConfig] = None,
    aura_session_id: str = "",
    round_num: int = 0
) -> ChatCompletionResponse:
    """处理非流式请求：发送普通 POST 请求，返回标准 JSON 响应"""
    timeout = llm_config.timeout if llm_config else 60
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, read=timeout)) as client:
        try:
            response = await client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException:
            logger.error(f"[AURA→LLM] 请求超时 | 会话: {session_id}")
            raise HTTPException(status_code=504, detail="LLM后端请求超时")
        except httpx.ConnectError:
            logger.error(f"[AURA→LLM] 连接失败 | 会话: {session_id}")
            raise HTTPException(status_code=503, detail="无法连接LLM后端")
        except Exception as e:
            logger.exception(f"[AURA→LLM] 请求异常 | 会话: {session_id}")
            raise HTTPException(status_code=500, detail=f"请求后端时出错: {str(e)}")

        if response.status_code != 200:
            error_text = response.text[:500]
            logger.error(f"[AURA→LLM] 后端返回错误 | 状态码: {response.status_code} | 错误: {error_text}")
            raise HTTPException(status_code=response.status_code, detail=f"LLM后端错误: {error_text}")

        # 解析 JSON 响应
        try:
            llm_data = response.json()
        except json.JSONDecodeError as e:
            logger.error(f"[LLM→AURA] JSON解析失败 | 会话: {session_id} | 原始响应前500字符: {response.text[:500]}")
            raise HTTPException(status_code=500, detail=f"后端响应格式错误: {str(e)}")

        # [LLM→AURA] 记录 LLM 响应信息
        llm_response_id = llm_data.get("id", "unknown")
        llm_model = llm_data.get("model", model_name)
        usage_info = llm_data.get("usage", {})
        logger.info(f"[LLM→AURA] 收到响应 | 会话: {session_id} | 响应ID: {llm_response_id} | 模型: {llm_model}")
        
        if settings.debug_mode:
            logger.debug(f"[LLM→AURA] 响应结构: {list(llm_data.keys())}")
            if usage_info:
                logger.debug(f"[LLM→AURA] Token用量: {json.dumps(usage_info, ensure_ascii=False)}")

        # 提取并记录响应内容预览
        try:
            for i, choice_data in enumerate(llm_data.get("choices", [])):
                msg_data = choice_data.get("message", {})
                content = msg_data.get("content", "")
                content_preview = content[:300] + "..." if len(content) > 300 else content
                finish_reason = choice_data.get("finish_reason", "stop")
                logger.info(
                    f"[LLM→AURA] 选择 {i} | finish_reason: {finish_reason} | "
                    f"内容长度: {len(content)}字符 | 预览: {content_preview}"
                )
        except Exception as e:
            logger.warning(f"[LLM→AURA] 提取内容预览时出错: {e}")

        # 构建标准响应对象
        try:
            choices = []
            for choice_data in llm_data.get("choices", []):
                msg_data = choice_data.get("message", {})
                choices.append(Choice(
                    index=choice_data.get("index", 0),
                    message=ChatMessageResponse(
                        role=msg_data.get("role", "assistant"),
                        content=msg_data.get("content", "")
                    ),
                    finish_reason=choice_data.get("finish_reason", "stop")
                ))

            response_obj = ChatCompletionResponse(
                id=llm_data.get("id", f"aura-{session_id}"),
                object=llm_data.get("object", "chat.completion"),
                created=llm_data.get("created", int(time.time())),
                model=model_name,
                choices=choices
            )
            # 附加额外字段（如 usage, system_fingerprint）
            if "usage" in llm_data:
                response_obj.usage = llm_data["usage"]  # extra="allow" 允许
            if "system_fingerprint" in llm_data:
                response_obj.system_fingerprint = llm_data["system_fingerprint"]

            # 调试信息注入
            if debug_flag == "true":
                response_obj.aura_debug = {
                    "session_id": session_id,
                    "timestamp": int(time.time()),
                    "mode": "direct_forward",
                    "backend": url
                }
                logger.debug(f"[AURA→TAVO] 已注入调试信息 | 会话: {session_id}")

            # 保存 LLM 回复到 SQLite（非流式）
            if aura_session_id and round_num > 0:
                try:
                    assistant_content = choices[0].message.content if choices else ""
                    if assistant_content:
                        await memory_manager.save_dialogue(aura_session_id, "assistant", assistant_content, round_num)
                        logger.debug(f"[AURA→记忆] 保存 LLM 回复 | 会话: {aura_session_id} | 轮次: {round_num} | 长度: {len(assistant_content)}字符")
                except Exception as e:
                    logger.warning(f"[AURA→记忆] 保存 LLM 回复失败（不影响返回）: {e}")

            # [AURA→TAVO] 记录返回给 TAVO 的响应
            logger.info(f"[AURA→TAVO] 返回响应 | 会话: {session_id} | 响应ID: {response_obj.id} | choices: {len(choices)}")

            return response_obj

        except Exception as e:
            logger.exception(f"[LLM→AURA] 构建响应对象失败 | 会话: {session_id}")
            raise HTTPException(status_code=500, detail=f"响应格式转换错误: {str(e)}")

async def _handle_streaming_request(
    url: str,
    headers: Dict[str, str],
    payload: Dict[str, Any],
    session_id: str,
    debug_flag: Optional[str],
    llm_config: Optional[LLMConfig] = None,
    aura_session_id: str = "",
    round_num: int = 0
) -> StreamingResponse:
    """
    处理流式请求：先完整收集 LLM 的 SSE 流 → 质检（预留 LangGraph 节点）
    → 再模拟 SSE 流式返回给 TAVO。

    设计说明（参考 Day 3 架构决策）：
    - 流式传输的"不可撤回"特性（已发送到 TAVO 的内容无法收回）
    - 因此采用"先完整生成 → 质检 → 再流式返回"策略
    - LLM 请求使用流式模式（AURA 内部聚合），质检通过后切割为 SSE chunk 模拟流式返回
    - Day 3 LangGraph 集成时，质检节点（FormatGuard/OOCCheck/ContentFilter）
      将在阶段1和阶段2之间介入
    - 对于重度 RP 用户，10-30 秒的等待换取 Sonnet 级别的沉浸体验，是完全可接受的
    """
    async def stream_generator():
        full_content_parts: List[str] = []
        raw_chunks: List[bytes] = []
        chunk_count = 0
        has_content = False

        try:
            # ================================================================
            # 阶段1: 完整收集 LLM 的 SSE 流（聚合所有 chunk）
            # ================================================================
            stream_timeout = llm_config.timeout if llm_config else 60
            async with httpx.AsyncClient(timeout=httpx.Timeout(stream_timeout, read=None)) as client:
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    if response.status_code != 200:
                        error_body = await response.aread()
                        error_text = error_body.decode('utf-8', errors='replace')[:500]
                        logger.error(f"流式请求后端错误 | 状态码: {response.status_code} | 错误: {error_text}")
                        yield f"data: {json.dumps({'error': f'后端错误 {response.status_code}: {error_text}'})}\n\n"
                        return

                    logger.info(f"[LLM→AURA] 流式响应开始 | 会话: {session_id} | 后端: {url}")

                    async for chunk in response.aiter_bytes():
                        if not chunk:
                            continue

                        chunk_count += 1
                        raw_chunks.append(chunk)
                        chunk_str = chunk.decode('utf-8', errors='replace')

                        # 提取 content 文本并收集（用于后续 SQLite 保存 + 质检）
                        for line in chunk_str.split('\n'):
                            if line.startswith('data: ') and line != 'data: [DONE]':
                                try:
                                    data_json = json.loads(line[6:])
                                    delta = data_json.get('choices', [{}])[0].get('delta', {})
                                    content = delta.get('content', '')
                                    if content:
                                        full_content_parts.append(content)
                                        has_content = True
                                except (json.JSONDecodeError, IndexError, KeyError):
                                    pass

            # ================================================================
            # 阶段1.5: 质检节点（预留 Day 3 LangGraph 介入点）
            # ================================================================
            full_content = ''.join(full_content_parts)
            content_preview = full_content[:200] + '...' if len(full_content) > 200 else full_content
            logger.info(
                f"[LLM→AURA] 流式响应收集完成 | 会话: {session_id} | "
                f"chunk数: {chunk_count} | 内容长度: {len(full_content)}字符"
            )
            if settings.debug_mode and content_preview:
                logger.debug(f"[LLM→AURA] 流式响应内容预览: {content_preview}")

            # [调试] 检查 LLM 返回内容是否包含段落分隔符
            has_double_newline = '\\n\\n' in repr(full_content)
            has_single_newline = '\\n' in repr(full_content)
            logger.info(
                f"[LLM→AURA] 内容格式检查 | 含双换行(段落): {has_double_newline} | "
                f"含单换行: {has_single_newline} | "
                f"repr前100: {repr(full_content[:150])}"
            )

            # 【预留】Day 3 LangGraph 质检节点介入点：
            #   - FormatGuard: 越权输出检测 + 关系一致性检测
            #   - OOCCheck: 人设一致性校验
            #   - ContentFilter: 文风污染过滤
            #   - 质检不通过 → 触发 retry → ModelDialectCompiler 调整策略 → 重新生成
            #   - 质检通过 → 继续阶段2

            # 保存 LLM 回复到 SQLite（在质检后、返回前保存）
            if aura_session_id and round_num > 0 and has_content:
                try:
                    await memory_manager.save_dialogue(aura_session_id, "assistant", full_content, round_num)
                    logger.debug(f"[AURA→记忆] 保存 LLM 回复（流式）| 会话: {aura_session_id} | 轮次: {round_num} | 长度: {len(full_content)}字符")
                except Exception as e:
                    logger.warning(f"[AURA→记忆] 保存 LLM 回复失败（不影响返回）: {e}")

            # ================================================================
            # 阶段2: 模拟 SSE 流式返回给 TAVO
            # ================================================================
            if not has_content:
                # 没有内容时直接返回 [DONE]
                yield b"data: [DONE]\n\n"
                logger.info(f"[AURA→TAVO] 流式返回完成（无内容）| 会话: {session_id}")
                return

            # 将完整内容按段落+句子粒度切分，模拟流式效果
            # 注意：必须保留段落之间的空行（\n\n），否则 TAVO 端渲染时会丢失分段
            import re

            # 第一步：按双换行（段落边界）切分，保留段落结构
            paragraphs = full_content.split('\n\n')
            
            # 第二步：对每个段落，再按句子边界切分（用于流式效果）
            sentence_delimiters = re.compile(
                r'(?<=[。！？.!?])(?:\s*(?=[\u4e00-\u9fff"「「*]))'
                r'|(?<=[。！？.!?])'
            )
            
            segments = []
            for i, para in enumerate(paragraphs):
                if not para.strip():
                    # 空行段落 → 跳过（段落分隔由前一段落末尾的 \n 处理）
                    continue
                
                # 对段落内按句子切分
                raw_sentences = sentence_delimiters.split(para)
                para_sentences = [s.strip() for s in raw_sentences if s.strip()]
                
                if not para_sentences:
                    # 如果段落内没有可切分的句子，整个段落作为一个 segment
                    para_text = para.strip()
                else:
                    para_text = ''.join(para_sentences)
                
                # 段落末尾追加 \n\n，保留段落间距
                # 最后一段不加（避免末尾多余空行）
                if i < len(paragraphs) - 1:
                    para_text += '\n\n'
                
                segments.append(para_text)
            
            if not segments:
                # 如果没有成功切分，按固定长度切分
                segments = [full_content[i:i+20] for i in range(0, len(full_content), 20)]
            
            seg_count = len(segments)
            logger.info(
                f"[AURA→TAVO] 模拟流式返回 | 会话: {session_id} | "
                f"总字符: {len(full_content)} | 切分段数: {seg_count}"
            )

            # 逐段 yield，每段之间加短暂延迟模拟流式效果
            for i, segment in enumerate(segments):
                if not segment:
                    continue
                
                # 构建 SSE data 行
                sse_data = {
                    "id": f"aura-{session_id}-{int(time.time())}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": payload.get("model", "unknown"),
                    "choices": [{
                        "index": 0,
                        "delta": {"content": segment},
                        "finish_reason": None
                    }]
                }
                yield f"data: {json.dumps(sse_data, ensure_ascii=False)}\n\n".encode('utf-8')
                
                # 每段之间延迟 30-80ms，模拟真实流式节奏
                # 句子越长延迟越大，让 TAVO 端感知到自然的流式效果
                delay = min(0.08, max(0.03, len(segment) * 0.003))
                await asyncio.sleep(delay)

            # 发送结束标记
            yield b"data: [DONE]\n\n"

            logger.info(
                f"[AURA→TAVO] 流式返回完成 | 会话: {session_id} | "
                f"总字符: {len(full_content)} | 切分段数: {seg_count}"
            )

        except httpx.TimeoutException:
            logger.error(f"流式请求超时 | 会话: {session_id}")
            yield f"data: {json.dumps({'error': '请求超时'})}\n\n".encode('utf-8')
        except Exception as e:
            logger.exception(f"流式处理异常 | 会话: {session_id}")
            yield f"data: {json.dumps({'error': f'内部错误: {str(e)}'})}\n\n".encode('utf-8')

    # 可选：在响应头中加入调试标识
    extra_headers = {}
    if debug_flag == "true":
        extra_headers["X-Aura-Debug"] = "true"
        extra_headers["X-Aura-Session"] = session_id
        logger.debug(f"流式请求调试模式 | 会话: {session_id}")

    return StreamingResponse(
        stream_generator(),
        media_type="text/event-stream",
        headers=extra_headers
    )

# --- 健康检查 ---
@router.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "service": "AURA",
        "version": "0.8.0",
        "mode": "langgraph-state-machine",
        "debug": settings.debug_mode
    }

# --- 初始化函数 ---
async def initialize_aura():
    """初始化AURA系统"""
    try:
        logger.info("AURA 初始化完成")
        logger.info(f"服务模式: LangGraph 状态机 + 3层记忆 + 意图感知 (v0.8.0)")
        logger.info(f"调试模式: {'启用' if settings.debug_mode else '禁用'}")

        # 验证LLM配置
        config_status = validate_llm_config()
        active_backends = [name for name, status in config_status.items() if status]
        logger.info(f"激活的LLM后端: {active_backends}")

        if not active_backends:
            logger.warning("没有配置有效的LLM后端，请检查环境变量")

        # 初始化记忆管理器（v0.6.0）
        await memory_manager.initialize()
        mem_count = await memory_manager.get_memory_count()
        logger.info(f"[AURA→记忆] MemoryManager 就绪 | FAISS 记忆数: {mem_count}")

    except Exception as e:
        logger.exception("AURA初始化失败")
        raise