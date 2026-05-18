"""
AURA 流式/非流式响应处理工具

职责：
  - SSE 流式响应构建（模拟流式返回）
  - 文本段落/句子粒度切分
  - 遗留的直接转发逻辑（非流式 / 流式直推 LLM）
"""
import json
import asyncio
import time
import re
from typing import List, Optional, Dict, Any

import httpx
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from app.core.config import settings, LLMConfig
from app.api.router import ChatCompletionResponse, Choice, ChatMessageResponse
from app.utils.logging import get_logger
from app.memory import memory_manager

logger = get_logger("aura-streaming")


def _split_into_segments(text: str) -> List[str]:
    """将文本按段落+句子粒度切分为 SSE 块"""
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
        segments = [text[i:i + 20] for i in range(0, len(text), 20)]

    return segments


def _build_streaming_response(
    full_content: str,
    session_id: str,
    model: str,
    debug_flag: Optional[str],
    reasoning_content: str = "",
) -> StreamingResponse:
    """将完整内容切割为 SSE chunk，模拟流式返回（复用原逻辑）"""
    import time

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
    """处理非流式请求：发送普通 POST 请求，返回标准 JSON 响应（遗留逻辑）"""
    import time
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
    → 再模拟 SSE 流式返回给 TAVO。（遗留逻辑）

    设计说明（参考 Day 3 架构决策）：
    - 流式传输的"不可撤回"特性（已发送到 TAVO 的内容无法收回）
    - 因此采用"先完整生成 → 质检 → 再流式返回"策略
    - LLM 请求使用流式模式（AURA 内部聚合），质检通过后切割为 SSE chunk 模拟流式返回
    - Day 3 LangGraph 集成时，质检节点（FormatGuard/OOCCheck/ContentFilter）
      将在阶段1和阶段2之间介入
    - 对于重度 RP 用户，10-30 秒的等待换取 Sonnet 级别的沉浸体验，是完全可接受的
    """
    import time

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
                segments = [full_content[i:i + 20] for i in range(0, len(full_content), 20)]

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
