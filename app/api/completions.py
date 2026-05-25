"""
AURA completions API — LangGraph 编排入口

职责：
  - /chat/completions 核心处理逻辑（请求验证、AgentState 组装、LangGraph 调用、响应构建）
  - 系统初始化入口 initialize_aura()

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
"""
import os
import json
import time
from typing import Optional, Dict, Any

from fastapi import HTTPException, Header

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
from app.api.streaming import _build_streaming_response

# 路线B：平台模式导入
from app.world import world_runtime
from app.director import director
from app.npc import NPCAgent

# 初始化全局日志配置
setup_logging()

logger = get_logger("aura-completions")


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
    # 2. 获取后端配置（支持后端切换 + 同后端型号切换）
    # ============================================================
    backend, actual_model = get_backend_for_model(request.model)
    llm_config = get_llm_config(backend, scene="main", model_name=actual_model)
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

    initial_state = {
        "request": {
            "model": request.model,
            "messages": [msg.model_dump() for msg in request.messages],
            "temperature": request.temperature,
            "stream": False,  # LangGraph 内部总为非流式（先完整生成 → 再流式返回）
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

    logger.info(f"[LangGraph] 开始执行工作流 | session={session_id} | stream={request.stream}")

    try:
        final_state = await aura_workflow.ainvoke(
            initial_state,
            config={"configurable": {"thread_id": session_id}}
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
    actual_backend = final_state.get("actual_backend", backend)
    fallback_triggered = final_state.get("fallback_triggered", False)
    logger.info(
        f"[LangGraph] 工作流完成 | 总耗时: {total_ms:.1f}ms | "
        f"节点: {len(node_logs)} | 内容: {len(llm_content)}字 | "
        f"实际后端: {actual_backend}{' | ⚠️ 已故障转移' if fallback_triggered else ''}"
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
                "actual_backend": actual_backend,
                "fallback_triggered": fallback_triggered,
                "fallback_reason": final_state.get("fallback_reason", ""),
                "node_count": len(node_logs),
                "total_ms": total_ms,
            }

        logger.info(f"[AURA→TAVO] 返回响应 | 会话: {session_id} | 内容: {len(llm_content)}字")
        return response_obj


# ============================================================
# 路线B：平台模式 API — 文字冒险入口
# ============================================================
@router.post("/world/completions")
async def world_completion(
    request: WorldCompletionRequest,
    x_tavo_debug: Optional[str] = Header(None, alias="X-Tavo-Debug")
):
    """
    AURA 平台模式 API — 文字冒险入口 (v0.9.0)

    与 /chat/completions（TAVO 兼容模式）并行存在。
    此端点使用 Director + NPC Agent 架构，而非 LangGraph 状态机。

    流程：
    1. 检查/加载世界
    2. Director 获取场域、指代消解、调度 NPC
    3. NPC Agent 独立生成回应（复用路线A的 LLM 调用能力）
    4. Director 仲裁组装最终输出
    5. 返回响应
    """
    session_id = f"aura_world_{int(time.time())}_{id(request)}"
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

    # 指代消解
    mentioned_entity = director.resolve_mention(request.message, field)
    if mentioned_entity:
        logger.info(f"[WorldMode] 指代消解: {mentioned_entity}")

    # 规则判定（mock — 当前只检查关键词匹配）
    violated, rule_reason = director.check_rule_violation(
        request.message, request.player_entity_id, field.location_id
    )
    if violated:
        logger.warning(f"[WorldMode] 规则违规: {rule_reason}")
        # 不阻断，只记录，后续 FormatGuard 层可拦截

    # NPC 调度
    npc_ids = director.schedule_npcs(field)
    logger.info(f"[WorldMode] NPC 调度: {npc_ids}")

    if not npc_ids:
        # 没有 NPC 在场，返回环境描写
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

    # 当前为单 NPC 模式（取第一个在场的 NPC）
    # 后续扩展为多 NPC 并发
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
            f"[WorldMode] NPC 回应 | {target_npc_id} | "
            f"长度: {len(npc_response)}字"
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
            "timestamp": int(time.time()),
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
        logger.info(f"服务模式: LangGraph 状态机 + 3层记忆 + 意图感知 (v0.8.2)")
        logger.info(f"调试模式: {'启用' if settings.debug_mode else '禁用'}")

        # 验证LLM配置
        from app.core.config import validate_llm_config
        config_status = validate_llm_config()
        active_backends = [name for name, status in config_status.items() if status]
        logger.info(f"激活的LLM后端: {active_backends}")

        if not active_backends:
            logger.warning("没有配置有效的LLM后端，请检查环境变量")

        # 初始化记忆管理器（v0.6.0）
        await memory_manager.initialize()
        mem_count = await memory_manager.get_memory_count()
        logger.info(f"[AURA→记忆] MemoryManager 就绪 | FAISS 记忆数: {mem_count}")

        # 路线B：预加载卡带列表（不自动加载，由 API 按需加载）
        from app.cartridge import CartridgeLoader
        loader = CartridgeLoader("cartridges")
        available = loader.list_available()
        if available:
            logger.info(f"[AURA→卡带] 可用卡带: {available}")

    except Exception as e:
        logger.exception("AURA初始化失败")
        raise
