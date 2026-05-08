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

from app.config import settings, get_llm_config, validate_llm_config
from app.prompt_decomposer import PromptDecomposer
from app.memory import memory_manager

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
    AURA简化版本 - 支持真正的流式转发
    1. 接收Tavo请求（支持流式）
    2. 转发给配置的LLM后端
    3. 非流式：返回标准JSON；流式：透传 SSE 流
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
    except Exception as e:
        logger.warning(f"[TAVO→AURA] 保存 Prompt 失败: {e}")

    # ============================================================
    # 2. 获取后端配置
    # ============================================================
    backend = get_backend_for_model(request.model)
    llm_config = get_llm_config(backend)
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

        # --- 区块6: [RECENT_DIALOGUE] 最近 N 轮对话（拆解自 TAVO） ---
        dialogue = decomposed.get("dialogue", {})
        recent_rounds = dialogue.get("recent_rounds", [])
        last_input = dialogue.get("last_user_input", "")

        working_memory_lines = ["[RECENT_DIALOGUE]"]
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

        blocks.append("\n".join(working_memory_lines))

        # ================================================================
        # --- 区块7: [LONG_TERM_MEMORY] 长记忆 — RAG 语义召回（v0.6.0）
        # ================================================================
        # 策略：用当前用户输入作为 query，从 FAISS 召回 Top-5 相关记忆
        # 注意：FAISS 不可用时应直接报错，不应静默降级为全量注入
        # RAG 召回
        query_text = last_input or user_name or ""
        rag_memories = await memory_manager.search(query_text, top_k=5)

        if rag_memories:
            logger.info(
                f"[AURA→RAG] 语义召回成功 | query=\"{query_text[:50]}...\" | "
                f"召回 {len(rag_memories)} 条"
            )
        else:
            logger.info("[AURA→RAG] 召回为空（FAISS 中暂无匹配记忆）")

        # 构建记忆区块
        if rag_memories:
            memory_lines = ["[LONG_TERM_MEMORY]"]
            memory_lines.append("（以下为与当前场景最相关的记忆，由 AURA RAG 系统召回）")
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

        # --- 区块8: [WORLD_CONTEXT] 世界书（有则注入，无则跳过） ---
        if sys_comp["world_book"] and sys_comp["world_book"].strip():
            blocks.append(f"[WORLD_CONTEXT]\n{sys_comp['world_book'].strip()}")

        # --- 区块9: [OUTPUT_SPEC] 输出格式规范（静态模板）+ COT 自我校验 ---
        output_spec_block = """[OUTPUT_SPEC]
- 长度：400-600 字
- 结构：环境描写(30%) + NPC内心/对话(40%) + 留给user的行动空间(30%)
- 标记规范：
  "对话内容"（双引号 = 角色台词）
  **动作描写**（星号 = 角色动作/表情）
  （心理活动）（小括号 = 角色内心独白）
- 禁止：替 user 做决定、推进剧情、OOC

# 输出前自我校验（COT）
在生成最终回复前，请按以下步骤逐项检查：
1. 这段回复中是否有替 user 生成行动或台词？→ 如果有，删除对应部分
2. 这段回复是否推进了主线剧情？→ 如果是，改为环境描写或NPC反应
3. 这段回复是否符合角色设定和当前场景？→ 如果否，重新调整
4. 标记使用是否正确（台词用"", 动作用**, 心理用()）？→ 如果否，修正
5. 回复长度是否在 400-600 字范围内？→ 如果否，压缩或扩展"""
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
        # 3d. 结尾限制：在每个 user 消息末尾追加约束（Recency Effect）
        #     利用近因效应，LLM 对 prompt 末尾的内容记忆最清晰
        #     与开头 [MAIN_PROMPT] 的约束形成"两头堵"效果
        # ================================================================
        user_constraint = (
            "\n\n[系统约束] 请严格遵守以下规则：\n"
            "1. 禁止生成用户的台词和行动\n"
            "2. 可以生成其他NPC的台词、行动和环境描写\n"
            "3. 替用户留出行动空间，不要推进剧情"
        )
        for msg in messages_list:
            if msg["role"] == "user":
                # 避免重复追加（如果已经追加过则跳过）
                if "[系统约束]" not in msg["content"]:
                    msg["content"] = msg["content"].rstrip() + user_constraint

        logger.debug(
            f"[AURA→约束] 已对 {sum(1 for m in messages_list if m['role'] == 'user')} 条 user 消息追加结尾约束"
        )

    except Exception as e:
        # 拆解/注入失败不应阻断转发，降级为原始透传
        logger.warning(f"[AURA→拆解] 拆解/注入失败，降级为原始透传: {e}")
        messages_list = [msg.model_dump() for msg in request.messages]

    # ============================================================
    # 3.5 保存对话到 SQLite + 触发记忆总结（v0.6.0）
    # ============================================================
    try:
        # 获取或创建 AURA 会话 ID
        aura_session_id = _session_map.get(session_id, session_id)
        _session_map[session_id] = aura_session_id

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
    if settings.debug_mode:
        masked_key = api_key[:6] + "***" + api_key[-4:] if len(api_key) > 10 else "***"
        logger.debug(f"[AURA→LLM] API Key: {masked_key}")
        logger.debug(f"[AURA→LLM] 请求体: {json.dumps(forward_payload, ensure_ascii=False)[:500]}")

    # 4. 根据是否流式选择不同处理方式
    if request.stream:
        return await _handle_streaming_request(url, headers, forward_payload, session_id, x_tavo_debug)
    else:
        return await _handle_non_streaming_request(url, headers, forward_payload, session_id, x_tavo_debug, request.model)

async def _handle_non_streaming_request(
    url: str,
    headers: Dict[str, str],
    payload: Dict[str, Any],
    session_id: str,
    debug_flag: Optional[str],
    model_name: str
) -> ChatCompletionResponse:
    """处理非流式请求：发送普通 POST 请求，返回标准 JSON 响应"""
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=60.0)) as client:
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
    debug_flag: Optional[str]
) -> StreamingResponse:
    """处理流式请求：透传后端 SSE 数据流，并记录 LLM 响应数据"""
    async def stream_generator():
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=None)) as client:
            try:
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    if response.status_code != 200:
                        error_body = await response.aread()
                        error_text = error_body.decode('utf-8', errors='replace')[:500]
                        logger.error(f"流式请求后端错误 | 状态码: {response.status_code} | 错误: {error_text}")
                        yield f"data: {json.dumps({'error': f'后端错误 {response.status_code}: {error_text}'})}\n\n"
                        return

                    # 记录流式响应开始
                    logger.info(f"[LLM→AURA] 流式响应开始 | 会话: {session_id} | 后端: {url}")
                    
                    # 用于聚合流式内容的缓冲区（调试用）
                    stream_content_parts = []
                    chunk_count = 0

                    # 逐块透传并记录
                    async for chunk in response.aiter_bytes():
                        if chunk:
                            chunk_count += 1
                            chunk_str = chunk.decode('utf-8', errors='replace')
                            
                            # 记录每个 SSE chunk（调试模式下记录内容预览）
                            if settings.debug_mode:
                                # 提取 data: 行中的内容预览
                                for line in chunk_str.split('\n'):
                                    if line.startswith('data: ') and line != 'data: [DONE]':
                                        try:
                                            data_json = json.loads(line[6:])
                                            delta = data_json.get('choices', [{}])[0].get('delta', {})
                                            content = delta.get('content', '')
                                            if content:
                                                stream_content_parts.append(content)
                                        except (json.JSONDecodeError, IndexError, KeyError):
                                            pass
                            
                            yield chunk

                    # 流式响应结束，打印汇总信息
                    full_content = ''.join(stream_content_parts)
                    content_preview = full_content[:200] + '...' if len(full_content) > 200 else full_content
                    logger.info(
                        f"[LLM→AURA] 流式响应完成 | 会话: {session_id} | "
                        f"chunk数: {chunk_count} | 内容长度: {len(full_content)}字符"
                    )
                    if settings.debug_mode and content_preview:
                        logger.debug(f"[LLM→AURA] 流式响应内容预览: {content_preview}")

            except httpx.TimeoutException:
                logger.error(f"流式请求超时 | 会话: {session_id}")
                yield f"data: {json.dumps({'error': '请求超时'})}\n\n"
            except Exception as e:
                logger.exception(f"流式转发异常 | 会话: {session_id}")
                yield f"data: {json.dumps({'error': f'内部错误: {str(e)}'})}\n\n"

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
        "service": "AURA-Simple",
        "version": "0.6.0",
        "mode": "block-reassembly",
        "debug": settings.debug_mode
    }

# --- 初始化函数 ---
async def initialize_aura():
    """初始化AURA系统"""
    try:
        logger.info("AURA 简化版本初始化完成")
        logger.info(f"服务模式: 区块化重组 + RAG 记忆召回 (v0.6.0)")
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