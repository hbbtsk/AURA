"""
AURA completions API — 核心转发 + Prompt 区块重组 + RAG 记忆召回

工作流程：
  1. 接收 TAVO 请求 → 保存 Prompt dump 到本地
  2. PromptDecomposer 拆解 System Prompt → 9 区块重组
  3. RAG 语义召回（FAISS）替代全量长记忆注入
  4. 两头约束：开头 [MAIN_PROMPT] + 结尾 user 消息追加约束
  5. 保存对话到 SQLite，每 5 轮触发 Kimi 记忆总结
  6. 转发给 LLM 后端（流式/非流式）

v0.6.0 特性：
  - AURA 自建记忆数据库（SQLite + FAISS）
  - RAG 语义召回替代全量长记忆注入
  - Kimi 每 5 轮自动总结记忆
  - 两头约束（Priming + Recency Effect）
"""
import os
import re
import asyncio
import httpx
import json
import time
import logging
from logging.handlers import RotatingFileHandler
from typing import List, Literal, Optional, Dict, Any, Union
from fastapi import APIRouter, HTTPException, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ConfigDict

from app.config import settings, get_llm_config, validate_llm_config, LLMConfig
from app.prompt_decomposer import PromptDecomposer
from app.memory import memory_manager
from app.intent_tagger import intent_tagger
from app.memory.models import IntentStructure, IntentResult

# 确保日志目录存在
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

# 配置日志（使用 RotatingFileHandler 带轮转，输出到 logs/ 目录）
_log_level = logging.DEBUG if settings.debug_mode else logging.INFO

# 文件处理器 - 每个文件 5MB，保留 3 个备份
_file_handler = RotatingFileHandler(
    os.path.join(LOG_DIR, "aura.log"),
    maxBytes=5 * 1024 * 1024,
    backupCount=3,
    encoding="utf-8"
)
_file_handler.setLevel(logging.DEBUG)  # 文件记录所有级别

# 控制台处理器 - 只输出 INFO 及以上，减少终端噪音
_console_handler = logging.StreamHandler()
_console_handler.setLevel(logging.INFO)

# 统一格式
_formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
_file_handler.setFormatter(_formatter)
_console_handler.setFormatter(_formatter)

# 配置根日志器
logging.basicConfig(
    level=_log_level,
    handlers=[_file_handler, _console_handler]
)

# 抑制 httpx 和 httpcore 的 DEBUG 日志（太嘈杂）
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger("aura-completions")

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
    AURA 核心 API — 接收 Tavo 请求，经 Prompt 区块重组 + RAG 记忆召回后转发给 LLM 后端
    1. 接收 Tavo 请求（支持流式）
    2. Prompt 拆解 + 9 区块重组 + RAG 语义召回
    3. 转发给配置的 LLM 后端
    4. 非流式：返回标准 JSON；流式：透传 SSE 流
    """
    session_id = f"aura_{int(time.time())}_{id(request)}"
    
    # [TAVO→AURA] 记录收到的 TAVO 请求
    logger.info(f"[TAVO→AURA] 收到请求 | 会话: {session_id} | 模型: {request.model} | 流式: {request.stream} | 消息数: {len(request.messages)}")
    
    # 保存 TAVO 请求到日志文件（兼容旧版日志格式）
    tavo_log_entry = {
        "session_id": session_id,
        "model": request.model,
        "stream": request.stream,
        "message_count": len(request.messages),
        "messages_preview": [
            {"role": m.role, "content_preview": m.content[:100] + "..." if len(m.content) > 100 else m.content}
            for m in request.messages[:3]  # 只记录前3条消息的预览
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
    # 1.5 保存完整 Prompt 到本地文件（用于调试和分析世界书格式）
    # ============================================================
    try:
        prompt_dump_dir = "prompt_dumps"
        os.makedirs(prompt_dump_dir, exist_ok=True)
        # 使用可读的系统时间作为文件名
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
        # 统计文件大小
        file_size = os.path.getsize(dump_file)
        logger.info(f"[TAVO→AURA] Prompt 已保存到: {dump_file} ({file_size}字节)")

        # [调试日志] 同时保存 TAVO 原始请求到独立文件（tavo_input_YYYYMMDD_HHMMSS.txt）
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
    # 3. Prompt 拆解 + 区块化重组（核心优化环节）
    # ============================================================
    try:
        # 3a. 拆解原始请求
        decomposed = decomposer.decompose({
            "model": request.model,
            "messages": [msg.model_dump() for msg in request.messages],
            "temperature": request.temperature,
            "stream": request.stream,
            "max_tokens": request.max_tokens,
        })

        # 记录拆解统计
        sys_comp = decomposed["system_prompt"]
        logger.info(
            f"[AURA→拆解] System Prompt 组件: "
            f"越权禁令={len(sys_comp['authority_ban'])}字符, "
            f"长记忆={len(sys_comp['long_term_memory'])}条, "
            f"角色卡={len(sys_comp['character_card'])}字符, "
            f"世界书={len(sys_comp['world_book'])}字符, "
            f"XML角色卡={len(sys_comp['xml_character_cards'])}张, "
            f"对话={decomposed['dialogue']['total_rounds']}轮"
        )

        # 3b. 检测用户是否写了自定义提示词
        has_user_prefix = sys_comp.get("has_user_prefix", True)

        # 从对话中提取用户名（最准确的方式）
        # TAVO 格式：user 消息内容为 "用户名: 对话内容"
        user_name = ""
        raw_messages = decomposed.get("dialogue", {}).get("raw_messages", [])
        for msg in raw_messages:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                colon_pos = content.find("：")
                if colon_pos == -1:
                    colon_pos = content.find(":")
                if colon_pos > 0 and colon_pos < 50:  # 用户名通常在开头50字符内
                    user_name = content[:colon_pos].strip()
                break
        # 后备：从 user_profile 正则提取
        if not user_name and sys_comp["user_profile"]:
            profile_match = re.match(r"^(.+?)是\1", sys_comp["user_profile"])
            if profile_match:
                user_name = profile_match.group(1)

        # 提取时间线状态
        timeline_state = ""
        if sys_comp["authority_ban"]:
            ban_lines = sys_comp["authority_ban"].split("\n")
            for bl in ban_lines:
                if "当前时间线" in bl:
                    timeline_state = bl.strip()
                    break

        # ============================================================
        # 3c. 构建最终的 System Prompt — 统一区块化重组
        #
        # 无论用户是否写了自定义提示词，都走区块组装流程：
        # - has_user_prefix == True  → 保留为 [MAIN_PROMPT] 区块，再组装其他区块
        # - has_user_prefix == False → 直接组装 8 个标准区块
        #
        # v0.6.0 新增：RAG 语义召回替代全量长记忆注入
        # v0.7.0 新增：3 层记忆（WORKING + RECENT + LONG_TERM）+ IntentTagger
        #
        # 区块位置策略（v0.7.1）：
        # - System Prompt 区块（blocks）：MAIN_PROMPT / PROTOCOL / CONSTRAINTS /
        #   CHARACTER_CARD / USER_PROFILE / CURRENT_STATE / RECENT_MEMORY /
        #   LONG_TERM_MEMORY / WORLD_CONTEXT / OUTPUT_SPEC
        # - 近因区块（追加到最后一条 user 消息）：WORKING_MEMORY + USER_INTENT_TAG
        #   利用近因效应，让 LLM 在生成回复时最近看到的就是当前语境+导演指令
        # ============================================================
        messages_list = [msg.model_dump() for msg in request.messages]
        original_system = decomposed["raw"]["system_content"]
        blocks = []

        # --- 区块0（条件）：[MAIN_PROMPT] 用户自定义提示词（仅保留第一行） ---
        # 只取第一个 ===== 标记之前的内容（用户写的 MAIN PROMPT 头部）
        # 后面的 =====长记忆===== / =====角色卡===== 等由各专用区块负责
        if has_user_prefix:
            main_prompt_lines = original_system.split("\n")
            main_prompt_head = []
            for line in main_prompt_lines:
                if line.startswith("====="):
                    break
                main_prompt_head.append(line)
            main_prompt_text = "\n".join(main_prompt_head).strip()
            if main_prompt_text:
                # 在 MAIN_PROMPT 末尾追加"开头限制"——设定角色边界（Priming Effect）
                main_prompt_text += """

# 核心约束（必须遵守）
- 禁止生成用户的台词和行动
- 可以生成其他NPC的台词、行动和环境描写
- 替用户留出行动空间，不要推进剧情"""
                blocks.append(f"[MAIN_PROMPT]\n{main_prompt_text}")

        # --- 区块1: [PROTOCOL] 通信标记约定（静态模板） ---
        protocol_block = """[PROTOCOL]
- "对话内容"（双引号）= 角色台词，表示角色说出口的话
- **动作描写**（星号）= 角色动作、表情、行为
- （心理活动）（小括号）= 角色内心独白，未说出口的想法
- 输入格式：user 的消息会使用上述标记，LLM 需正确理解
- 输出格式：LLM 的回复也必须使用上述标记，保持格式一致"""
        blocks.append(protocol_block)

        # --- 区块2: [CONSTRAINTS] 角色边界 + 负向指令（静态模板） ---
        constraints_block = f"""[CONSTRAINTS]
- LLM 角色声明：你是旁白/NPC扮演者，禁止替 {user_name or '用户'} 生成任何行动或台词
- 负向指令：禁止生成臀腿腰胸等垃圾小说描写；禁止推进剧情
- 输出格式：环境描写 + NPC 反应 + {user_name or '用户'} 行动空间"""
        blocks.append(constraints_block)

        # --- 区块3: [CHARACTER_CARD] 角色卡（拆解自 TAVO，完整保留） ---
        if sys_comp["character_card"]:
            blocks.append(f"[CHARACTER_CARD]\n{sys_comp['character_card']}")

        # --- 区块4: [USER_PROFILE] 用户设定（拆解自 TAVO，完整保留） ---
        if sys_comp["user_profile"]:
            blocks.append(f"[USER_PROFILE]\n{sys_comp['user_profile']}")

        # --- 区块5: [CURRENT_STATE] 实体当前状态（Mock，待 Day 4 实现） ---
        current_state_block = """[CURRENT_STATE]
- [state: 当前场景: 待初始化]
- [state: 时间线: 待初始化]
- （此区块将在 Day 4 由 StateManager 从数据库读取真实状态后生成）"""
        blocks.append(current_state_block)

        # ================================================================
        # 3c-1. IntentTagger：解析用户输入意图（v0.7.0）
        # ================================================================
        dialogue = decomposed.get("dialogue", {})
        recent_rounds = dialogue.get("recent_rounds", [])
        last_input = dialogue.get("last_user_input", "")

        intent_result = None
        if last_input:
            try:
                # 构建上下文信息
                context = {
                    "scene_type": "未知",
                    "active_entities": [],
                }
                # 尝试从角色卡中提取活跃角色
                if sys_comp.get("character_card"):
                    # 简单提取：取角色卡第一行作为当前角色
                    first_line = sys_comp["character_card"].split("\n")[0].strip()
                    if first_line:
                        context["active_entities"] = [first_line]

                intent_result = await intent_tagger.analyze(last_input, context=context)
                if intent_result and intent_result.should_use():
                    logger.info(
                        f"[AURA→意图] 意图解析成功 | "
                        f"type={intent_result.input_type}, "
                        f"confidence={intent_result.confidence:.2f}"
                    )
                else:
                    logger.debug(
                        f"[AURA→意图] 意图解析置信度不足或为空 "
                        f"(confidence={intent_result.confidence if intent_result else 0}), 跳过意图修正"
                    )
                    intent_result = None
            except Exception as e:
                logger.warning(f"[AURA→意图] 意图解析失败（不影响主流程）: {e}")
                intent_result = None

        # ================================================================
        # 3c-2. 3 层记忆注入（v0.7.0）
        # ================================================================

        # --- 区块6a: [WORKING_MEMORY] 工作记忆 — 最近 5 轮对话 ---
        # 注意：WORKING_MEMORY 不加入 blocks（System Prompt），
        # 而是在 3d 阶段合并到最后一条 user 消息末尾，利用近因效应
        working_memory_lines = ["[WORKING_MEMORY]"]
        working_memory_lines.append("（以下为最近 5 轮对话，反映当前即时语境）")
        working_memory_lines.append("")
        if recent_rounds:
            for i, round_data in enumerate(recent_rounds):
                user_msg = round_data.get("user", "")
                assistant_msg = round_data.get("assistant", "")
                if user_msg:
                    working_memory_lines.append("  [%d] %s: %s%s" % (i+1, user_name or "用户", user_msg[:200], "..." if len(user_msg) > 200 else ""))
                if assistant_msg:
                    working_memory_lines.append("  [%d] NPC: %s%s" % (i+1, assistant_msg[:200], "..." if len(assistant_msg) > 200 else ""))
        else:
            working_memory_lines.append("  （无最近对话记录）")

        if last_input:
            working_memory_lines.append("  [当前输入] %s: %s%s" % (user_name or "用户", last_input[:200], "..." if len(last_input) > 200 else ""))

        # 暂存 WORKING_MEMORY 文本，稍后合并到 user 消息末尾
        working_memory_text = "\n".join(working_memory_lines)

        # --- 区块6b: [RECENT_MEMORY] 近时记忆 — 最近 10 条记忆摘要 ---
        try:
            recent_summaries = await memory_manager._get_recent_memories_for_context(10)
            if recent_summaries and recent_summaries != "（无）":
                recent_memory_lines = ["[RECENT_MEMORY]"]
                recent_memory_lines.append("（以下为最近 10 条记忆摘要，反映近期剧情发展）")
                recent_memory_lines.append("")
                for line in recent_summaries.split("\n"):
                    line = line.strip()
                    if line:
                        recent_memory_lines.append(line)
                blocks.append("\n".join(recent_memory_lines))
        except Exception as e:
            logger.debug(f"[AURA→记忆] 获取近时记忆失败（跳过）: {e}")

        # ================================================================
        # --- 区块7: [LONG_TERM_MEMORY] 长记忆 — 结构化 RAG 召回（v0.7.0）
        # ================================================================
        # 策略：
        # 1. 如果有 IntentResult，用 expanded_scene 做 embedding 粗排 + query_structure 做逐字段精排
        # 2. 如果没有 IntentResult，降级为传统 embedding + 时间加权
        # ================================================================
        query_text = last_input or user_name or ""

        if intent_result and intent_result.should_use():
            # 结构化 RAG 召回
            rag_memories = await memory_manager.structured_aware_search(
                query=intent_result.expanded_scene or query_text,
                top_k=5,
                query_structure=intent_result.structure,
            )
            logger.info(
                f"[AURA→RAG] 结构化召回 | query=\"{query_text[:40]}...\" | "
                f"召回 {len(rag_memories)} 条 | "
                f"意图: {intent_result.input_type}"
            )
        else:
            # 降级：传统 embedding + 时间加权
            rag_memories = await memory_manager.search(query_text, top_k=5)
            logger.info(
                f"[AURA→RAG] 传统召回 | query=\"{query_text[:40]}...\" | "
                f"召回 {len(rag_memories)} 条"
            )

        # 构建记忆区块
        if rag_memories:
            # RAG 有数据 → 使用结构化召回结果
            memory_lines = ["[LONG_TERM_MEMORY]"]
            memory_lines.append("（以下为与当前场景最相关的长期记忆，由 AURA RAG 系统召回）")
            memory_lines.append("")
            for mem in rag_memories:
                memory_lines.append("- %s" % mem)
            memory_lines.append("")
            memory_lines.append("# 记忆应用")
            memory_lines.append("- 像朋友般自然运用这些记忆，不要一次性提及所有记忆")
            memory_lines.append("- 选择与当前场景最相关的记忆自然融入叙述")
            memory_lines.append("- 避免机械式表达如\"根据我的记忆...\"")
            memory_lines.append("- 共同经历时可温情回忆：\"上次我们讨论很有趣\"")
            memory_lines.append("")
            memory_lines.append("记忆是丰富对话的工具，而非对话焦点。")
            blocks.append("\n".join(memory_lines))

            logger.info(
                f"[AURA→记忆] 区块注入完成 | "
                f"{len(rag_memories)}条 | 总字符: {sum(len(m) for m in rag_memories)}"
            )
        elif sys_comp.get("long_term_memory"):
            # RAG 无数据（FAISS 为空）→ 透传 TAVO 原始长记忆
            tavo_memories = sys_comp["long_term_memory"]
            memory_lines = ["[LONG_TERM_MEMORY]"]
            memory_lines.append("（以下为 TAVO 原始长记忆，AURA RAG 系统尚未积累数据）")
            memory_lines.append("")
            for mem in tavo_memories:
                memory_lines.append("- %s" % mem)
            memory_lines.append("")
            memory_lines.append("# 记忆应用")
            memory_lines.append("- 像朋友般自然运用这些记忆，不要一次性提及所有记忆")
            memory_lines.append("- 选择与当前场景最相关的记忆自然融入叙述")
            memory_lines.append("- 避免机械式表达如\"根据我的记忆...\"")
            memory_lines.append("- 共同经历时可温情回忆：\"上次我们讨论很有趣\"")
            memory_lines.append("")
            memory_lines.append("记忆是丰富对话的工具，而非对话焦点。")
            blocks.append("\n".join(memory_lines))

            logger.info(
                f"[AURA→记忆] 透传 TAVO 原始长记忆 | "
                f"{len(tavo_memories)}条 | 总字符: {sum(len(m) for m in tavo_memories)}"
            )
        else:
            logger.debug("[AURA→记忆] 无长记忆数据，跳过 [LONG_TERM_MEMORY] 区块")

        # ================================================================
        # --- [USER_INTENT_TAG] 用户意图标签（v0.7.0）
        #     由 IntentTagger 解析用户输入后生成，指导主 LLM 生成方向
        #     仅当置信度 >= 0.6 时注入
        #
        # 设计原则：只注入自然语言段落，不注入结构化数据。
        # 结构化数据（input_type, user_expectation, confidence）仅用于 RAG 匹配，
        # 不传递给主 LLM，避免诱导 LLM 进行结构化输出或破坏 RP 沉浸感。
        #
        # 位置策略：不放入 System Prompt blocks，而是合并到 WORKING_MEMORY 中，
        # 一起追加到最后一条 user 消息末尾，利用近因效应让 LLM 优先遵循。
        #
        # 分段策略：不再在 USER_INTENT_TAG 中写分段要求（DeepSeek 对指令不敏感），
        # 改为在 OUTPUT_SPEC 中用 few-shot 示例约束输出格式（模仿 > 指令）。
        # ================================================================
        if intent_result and intent_result.should_use() and intent_result.implicit_instruction:
            # 只注入 implicit_instruction（自然语言导演指令），
            # 去掉 input_type / user_expectation / confidence 等结构化字段
            # 分段要求已移至 OUTPUT_SPEC 的 few-shot 示例中，此处不再重复
            intent_instruction = intent_result.implicit_instruction.rstrip()
            if not intent_instruction.endswith("。"):
                intent_instruction += "。"

            # 合并到 WORKING_MEMORY 文本中
            working_memory_text += "\n\n" + f"""[USER_INTENT_TAG]
{intent_instruction}"""
            logger.info(
                f"[AURA→意图] [USER_INTENT_TAG] 已合并到 WORKING_MEMORY | "
                f"指令: {intent_result.implicit_instruction[:80]}..."
            )

        # --- 区块8: [WORLD_CONTEXT] 世界书（有则注入，无则跳过） ---
        if sys_comp["world_book"] and sys_comp["world_book"].strip():
            blocks.append(f"[WORLD_CONTEXT]\n{sys_comp['world_book'].strip()}")

        # --- 区块9: [OUTPUT_SPEC] 输出格式规范（静态模板）+ COT 自我校验 ---
        # 注意：DeepSeek 对"指令"不敏感，但对"示例"非常敏感。
        # 因此用 few-shot 示例替代"请分段"指令，让模型通过模仿来分段。
        output_spec_block = """[OUTPUT_SPEC]
- 长度：400-600 字
- 结构：环境描写(30%) + NPC内心/对话(40%) + 留给user的行动空间(30%)
- 标记规范：
  "对话内容"（双引号 = 角色台词）
  **动作描写**（星号 = 角色动作/表情）
  （心理活动）（小括号 = 角色内心独白）
- 禁止：替 user 做决定、推进剧情、OOC

# 输出格式示例（必须严格模仿此格式）
你的输出格式应如下例：

阳光透过女子学校的铁艺大门，在地面投下斑驳的纹路。秋天的银杏叶被风卷起，在门口的喷泉边打转。

几个正抱着课本路过的女生停下脚步，目光警惕地打量着门口这位不速之客。

校门口的石狮静默矗立，等待着这位闯入者迈出第一步。

注意：
- 每段之间必须空一行
- 每段是一个独立的画面
- 段落长度应错落有致，不要每段等长

# 输出前自我校验（COT）
在生成最终回复前，请按以下步骤逐项检查：
1. 这段回复中是否有替 user 生成行动或台词？→ 如果有，删除对应部分
2. 这段回复是否推进了主线剧情？→ 如果是，改为环境描写或NPC反应
3. 这段回复是否符合角色设定和当前场景？→ 如果否，重新调整
4. 标记使用是否正确（台词用"", 动作用**, 心理用()）？→ 如果否，修正
5. 回复长度是否在 400-600 字范围内？→ 如果否，压缩或扩展
6. 回复格式是否与上述示例一致（每段空行分隔、每段一个独立画面）？→ 如果否，重新分段"""
        blocks.append(output_spec_block)

        optimized_system = "\n\n".join(blocks)
        logger.info(
            f"[AURA→区块重组] System Prompt 重组完成 | "
            f"区块数: {len(blocks)} | "
            f"原始: {len(original_system)}字符 → 重组: {len(optimized_system)}字符 | "
            f"变化: {len(optimized_system) - len(original_system):+d}字符"
        )

        # [AURA→日志] 打印重组前后的 System Prompt 内容
        # 同时保存重组后的完整 Prompt 到单独文件，方便查看
        try:
            reassembled_dir = "prompt_dumps"
            os.makedirs(reassembled_dir, exist_ok=True)
            time_str = time.strftime("%Y%m%d_%H%M%S")
            reassembled_file = os.path.join(reassembled_dir, f"reassembled_{time_str}.txt")
            with open(reassembled_file, "w", encoding="utf-8") as f:
                f.write("=== AURA 重组后 System Prompt ===\n")
                f.write(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"原始长度: {len(original_system)}字符 → 重组后: {len(optimized_system)}字符\n")
                f.write(f"区块数: {len(blocks)}\n")
                f.write(f"RAG来源: aura_faiss\n")
                f.write(f"{'='*60}\n\n")
                f.write(optimized_system)
            logger.info(f"[AURA→日志] 重组后 Prompt 已保存到: {reassembled_file} ({len(optimized_system)}字符)")
        except Exception as e:
            logger.warning(f"[AURA→日志] 保存重组后 Prompt 失败: {e}")

        # 替换 System Prompt
        if messages_list and messages_list[0]["role"] == "system":
            messages_list[0]["content"] = optimized_system

        # ================================================================
        # 3d. 结尾限制：利用近因效应（Recency Effect）
        #     将 WORKING_MEMORY + USER_INTENT_TAG 追加到最后一条 user 消息末尾
        #     同时给所有 user 消息追加 [系统约束]
        #
        # 策略：
        # - 所有 user 消息末尾追加 [系统约束]（简短约束）
        # - 最后一条 user 消息额外追加 WORKING_MEMORY（含 USER_INTENT_TAG）
        #   这样 LLM 在生成回复时，最近看到的就是当前语境+导演指令
        # ================================================================
        user_constraint = (
            "\n\n[系统约束] 请严格遵守以下规则：\n"
            "1. 禁止生成用户的台词和行动\n"
            "2. 可以生成其他NPC的台词、行动和环境描写\n"
            "3. 替用户留出行动空间，不要推进剧情"
        )

        # 找到最后一条 user 消息的索引
        last_user_idx = -1
        for i in range(len(messages_list) - 1, -1, -1):
            if messages_list[i]["role"] == "user":
                last_user_idx = i
                break

        for i, msg in enumerate(messages_list):
            if msg["role"] == "user":
                # 避免重复追加（如果已经追加过则跳过）
                if "[系统约束]" not in msg["content"]:
                    msg["content"] = msg["content"].rstrip() + user_constraint

                # 最后一条 user 消息额外追加 WORKING_MEMORY（含 USER_INTENT_TAG）
                if i == last_user_idx and working_memory_text:
                    msg["content"] = msg["content"].rstrip() + "\n\n" + working_memory_text
                    logger.info(
                        f"[AURA→近因] WORKING_MEMORY 已追加到最后一条 user 消息末尾 | "
                        f"长度: {len(working_memory_text)}字符"
                    )

        logger.debug(
            f"[AURA→约束] 已对 {sum(1 for m in messages_list if m['role'] == 'user')} 条 user 消息追加结尾约束"
        )

    except Exception as e:
        # 拆解/注入失败不应阻断转发，降级为原始透传
        logger.warning(f"[AURA→拆解] 拆解/注入失败，降级为原始透传: {e}")
        messages_list = [msg.model_dump() for msg in request.messages]

    # ============================================================
    # 3.5 对话同步 + 保存到 SQLite + 触发记忆总结（v0.6.0）
    # ============================================================
    try:
        # 获取或创建 AURA 会话 ID
        aura_session_id = _session_map.get(session_id, session_id)
        _session_map[session_id] = aura_session_id

        # ================================================================
        # 3.5a 对话同步：倒序匹配 TAVO 发来的对话与本地数据库
        #      处理用户在 TAVO 中的编辑/撤回操作
        #      在保存新对话之前执行，确保数据库与 TAVO 一致
        # ================================================================
        # 提取 TAVO 发来的所有非 system 消息（user + assistant）
        tavo_dialogue_messages = [
            {"role": msg.role, "content": msg.content}
            for msg in request.messages
            if msg.role in ("user", "assistant")
        ]
        if tavo_dialogue_messages:
            await memory_manager.sync_dialogue_from_tavo(aura_session_id, tavo_dialogue_messages)

        # 获取轮次编号
        round_num = await memory_manager.get_round_number(aura_session_id)

        # 保存用户输入
        user_content = ""
        for msg in reversed(request.messages):
            if msg.role == "user":
                user_content = msg.content
                break
        if user_content:
            await memory_manager.save_dialogue(aura_session_id, "user", user_content, round_num)

        # 每 5 轮触发 Kimi 总结（异步，不阻塞）
        if round_num > 0 and round_num % settings.memory_summary_interval == 0:
            recent = await memory_manager.get_recent_messages(aura_session_id, n=10)
            if recent:
                # 异步触发总结，不等待完成
                asyncio.ensure_future(
                    memory_manager.summarize_and_store(aura_session_id, recent)
                )
                logger.info(f"[AURA→记忆] 触发 Kimi 记忆总结 | 会话: {aura_session_id} | 轮次: {round_num}")

    except Exception as e:
        logger.warning(f"[AURA→记忆] 保存对话失败（不影响主流程）: {e}")

    # ============================================================
    # 4. 构建转发请求体
    # ============================================================
    forward_payload = {
        "model": request.model,
        "messages": messages_list,
        "temperature": request.temperature,
        "stream": request.stream
    }
    if request.max_tokens:
        forward_payload["max_tokens"] = request.max_tokens

    # 清理 API Key 并准备请求头
    api_key = llm_config.api_key.strip()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    url = f"{llm_config.base_url.rstrip('/')}/chat/completions"

    # [AURA→LLM] 记录转发到 LLM 的请求
    logger.info(f"[AURA→LLM] 转发请求 | 会话: {session_id} | URL: {url} | 后端: {backend} | 模型: {request.model}")

    # [调试日志] 保存 AURA→LLM 的转发内容到独立文件（aura_output_YYYYMMDD_HHMMSS.txt）
    try:
        prompt_dump_dir = "prompt_dumps"
        os.makedirs(prompt_dump_dir, exist_ok=True)
        time_str = time.strftime("%Y%m%d_%H%M%S")
        aura_output_file = os.path.join(prompt_dump_dir, f"aura_output_{time_str}.txt")
        with open(aura_output_file, "w", encoding="utf-8") as f:
            f.write(f"=== AURA→LLM 转发请求 ===\n")
            f.write(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"会话: {session_id}\n")
            f.write(f"后端: {backend}\n")
            f.write(f"模型: {request.model}\n")
            f.write(f"流式: {request.stream}\n")
            f.write(f"{'='*60}\n\n")
            # 写入完整的 messages 列表
            for i, msg in enumerate(forward_payload.get("messages", [])):
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                f.write(f"--- 消息 {i} | role: {role} | 长度: {len(content)}字符 ---\n")
                f.write(content)
                f.write("\n\n")
            # 写入其他参数
            f.write(f"{'='*60}\n")
            f.write(f"其他参数: temperature={forward_payload.get('temperature')}, ")
            f.write(f"max_tokens={forward_payload.get('max_tokens', 'N/A')}, ")
            f.write(f"stream={forward_payload.get('stream')}\n")
        logger.info(f"[AURA→LLM] 调试日志已保存: {aura_output_file}")
    except Exception as e:
        logger.warning(f"[AURA→LLM] 保存转发内容失败: {e}")

    if settings.debug_mode:
        masked_key = api_key[:6] + "***" + api_key[-4:] if len(api_key) > 10 else "***"
        logger.debug(f"[AURA→LLM] API Key: {masked_key}")
        logger.debug(f"[AURA→LLM] 请求体: {json.dumps(forward_payload, ensure_ascii=False)[:500]}")

    # 4. 根据是否流式选择不同处理方式
    if request.stream:
        return await _handle_streaming_request(
            url, headers, forward_payload, session_id, x_tavo_debug,
            llm_config=llm_config,
            aura_session_id=aura_session_id, round_num=round_num
        )
    else:
        return await _handle_non_streaming_request(
            url, headers, forward_payload, session_id, x_tavo_debug, request.model,
            llm_config=llm_config,
            aura_session_id=aura_session_id, round_num=round_num
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
        "version": "0.6.0",
        "mode": "block-reassembly",
        "debug": settings.debug_mode
    }

# --- 初始化函数 ---
async def initialize_aura():
    """初始化AURA系统"""
    try:
        logger.info("AURA 初始化完成")
        logger.info(f"服务模式: 区块化重组 + 3层记忆 + 意图感知 (v0.7.0)")
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
