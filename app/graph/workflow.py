"""
AURA LangGraph 工作流 — 15 节点 Agent 状态机

设计原则：
- 每个节点只调用已有业务代码，不修改原有逻辑
- 原有 completions.py 中的 Prompt 编译 / RAG / LLM 调用逻辑，
  在 ContextAssemble 节点中完整保留（复制粘贴，不抽取）
- 当前为 v0.8.0 骨架：mock 节点直接返回空值，真实逻辑后续填充
- 质检失败后通过条件边自动重试 LLMGenerate

节点清单（15个）：
1. InputReceive      → 收输入，解析请求
2. EntityExtract     → 实体识别（mock，Week 3 实现）
3. EmotionAnalyze    → 情绪分析（mock，Week 3 实现）
4. MemoryDecision    → 记忆决策（mock，默认 true）
5. MemoryRetrieve    → 记忆检索（RAG，已真实化）
6. StateManager      → 状态加载（mock，默认空）
7. StyleInjection    → 风格注入（mock，默认空）
8. ModelDialectCompiler → 方言编译（mock，透传）
9. ContextAssemble   → Prompt 区块化重组（已真实化，原 completions.py 核心逻辑）
10. LLMGenerate      → LLM 生成（已真实化，非流式）
11. FormatGuard      → 格式质检（mock，默认通过）
12. OOCCheck         → 人设质检（mock，默认通过）
13. ContentFilter    → 内容质检（mock，默认通过）
14. OutputReturn     → 构建响应返回
15. MemoryExtract    → 保存对话 + 触发总结（已真实化）
"""

import os
import re
import asyncio
import time
from typing import Optional, Dict, Any

from app.utils import get_logger
logger = get_logger("aura-graph")

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from app.graph.state import AgentState
from app.core.config import settings, get_llm_config, LLMConfig
from app.core.prompt_decomposer import PromptDecomposer
from app.memory import memory_manager
from app.core.intent_tagger import intent_tagger
from app.memory.models import IntentResult

decomposer = PromptDecomposer()

# ================================================================
# 辅助：节点执行日志记录
# ================================================================

def _log_node_start(state: AgentState, node_name: str) -> float:
    """记录节点开始执行"""
    t0 = time.time()
    logger.info(f"[LangGraph→节点] {node_name} | 开始 | session={state.get('aura_session_id', '?')}")
    return t0


def _log_node_end(state: AgentState, node_name: str, t0: float, summary: str = ""):
    """记录节点执行结束，更新状态日志"""
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
# Node 1: InputReceive
# ================================================================

async def input_receive_node(state: AgentState) -> AgentState:
    """接收输入，提取对话消息，建立会话映射 + 意图解析"""
    t0 = _log_node_start(state, "InputReceive")

    request = state["request"]
    raw_messages = request.get("messages", [])

    # 提取对话消息（user + assistant）
    tavo_dialogue_messages = [
        {"role": m["role"], "content": m["content"]}
        for m in raw_messages
        if m.get("role") in ("user", "assistant")
    ]

    # 提取用户名（最准确的方式）
    user_name = ""
    for m in reversed(raw_messages):
        if m.get("role") == "user":
            content = m.get("content", "")
            colon_pos = content.find("：")
            if colon_pos == -1:
                colon_pos = content.find(":")
            if colon_pos > 0 and colon_pos < 50:
                user_name = content[:colon_pos].strip()
            break

    # 提取最后一条 user 消息用于意图解析
    last_input = state.get("user_content", "")
    if not last_input:
        for m in reversed(raw_messages):
            if m.get("role") == "user":
                last_input = m.get("content", "")
                break

    # 意图解析（提前执行，供 MemoryRetrieve 使用结构化召回）
    intent_result = None
    if last_input:
        try:
            context = {
                "scene_type": "未知",
                "active_entities": [user_name] if user_name else [],
            }
            intent_result = await intent_tagger.analyze(last_input, context=context)
            if intent_result and intent_result.should_use():
                logger.info(
                    f"[InputReceive] 意图解析: "
                    f"type={intent_result.input_type}, confidence={intent_result.confidence:.2f}"
                )
        except Exception as e:
            logger.warning(f"[InputReceive] 意图分析失败（不影响主流程）: {e}")

    # 获取当前对话轮次（用于 MemoryExtract 保存对话和触发总结）
    aura_session_id = state.get("aura_session_id", "")
    round_num = 0
    if aura_session_id:
        try:
            round_num = await memory_manager.get_dialogue_count(aura_session_id)
        except Exception as e:
            logger.warning(f"[InputReceive] 获取对话轮次失败: {e}")

    summary_parts = [
        f"消息数: {len(raw_messages)}",
        f"对话消息: {len(tavo_dialogue_messages)}",
        f"user_name: {user_name or '?'}",
        f"round: {round_num}",
    ]
    if intent_result and intent_result.should_use():
        summary_parts.append(f"意图: {intent_result.input_type}({intent_result.confidence:.2f})")
    summary = " | ".join(summary_parts)
    _log_node_end(state, "InputReceive", t0, summary)

    return {
        **state,
        "messages": raw_messages,
        "tavo_dialogue_messages": tavo_dialogue_messages,
        "user_name": user_name,
        "intent_result": intent_result,
        "round_num": round_num,
        "retry_count": 0,
        "max_retries": 2,
        "format_passed": True,
        "ooc_passed": True,
        "content_passed": True,
        "format_reason": "",
        "ooc_reason": "",
        "content_reason": "",
        "node_logs": state.get("node_logs", []),
    }


# ================================================================
# Node 2: EntityExtract（mock — Week 3 真实化）
# ================================================================

async def entity_extract_node(state: AgentState) -> AgentState:
    """实体识别：从用户输入 + 最近对话提取活跃实体"""
    t0 = _log_node_start(state, "EntityExtract")

    # TODO: Week 3 实现真实实体提取
    # 当前从角色卡第一行简单提取
    active_entities = []
    decomposed_data = state.get("decomposed")
    if decomposed_data:
        char_card = decomposed_data.get("system_prompt", {}).get("character_card", "")
        if char_card:
            first_line = char_card.split("\n")[0].strip()
            if first_line:
                active_entities.append(first_line)

    _log_node_end(state, "EntityExtract", t0, f"活跃实体: {active_entities}")
    return {
        **state,
        "active_entity_ids": active_entities,
    }


# ================================================================
# Node 3: EmotionAnalyze（mock — Week 3 真实化）
# ================================================================

async def emotion_analyze_node(state: AgentState) -> AgentState:
    """情绪走向分析（mock）"""
    t0 = _log_node_start(state, "EmotionAnalyze")
    _log_node_end(state, "EmotionAnalyze", t0, "当前为 mock，情绪=中性")
    return state


# ================================================================
# Node 4: MemoryDecision（mock — 默认 true）
# ================================================================

async def memory_decision_node(state: AgentState) -> AgentState:
    """记忆决策：是否查询记忆（mock，始终 true）"""
    t0 = _log_node_start(state, "MemoryDecision")
    _log_node_end(state, "MemoryDecision", t0, "决策: 查询记忆")
    return state


# ================================================================
# Node 5: MemoryRetrieve
# ================================================================

async def memory_retrieve_node(state: AgentState) -> AgentState:
    """记忆检索：FAISS RAG 召回（已真实化）"""
    t0 = _log_node_start(state, "MemoryRetrieve")

    intent_result = state.get("intent_result")
    last_input = state.get("user_content", "")
    query_text = last_input or state.get("user_name", "")

    try:
        if intent_result and intent_result.should_use():
            rag_memories = await memory_manager.structured_aware_search(
                query=intent_result.expanded_scene or query_text,
                top_k=10,
                query_structure=intent_result.structure,
            )
            summary = f"结构化召回: {len(rag_memories)}条, query={query_text[:30]}..."
        else:
            rag_memories = await memory_manager.search(query_text, top_k=10)
            summary = f"传统召回: {len(rag_memories)}条, query={query_text[:30]}..."
    except Exception as e:
        logger.warning(f"[MemoryRetrieve] RAG 失败: {e}")
        rag_memories = []
        summary = f"RAG 失败: {e}"

    _log_node_end(state, "MemoryRetrieve", t0, summary)
    return {
        **state,
        "retrieved_memories": rag_memories,
    }


# ================================================================
# Node 6: StateManager（mock — Week 2 真实化）
# ================================================================

async def state_manager_node(state: AgentState) -> AgentState:
    """状态管理：加载 dynamic_state + 关系图谱渲染（mock）"""
    t0 = _log_node_start(state, "StateManager")
    _log_node_end(state, "StateManager", t0, "当前为 mock，CHARACTER_SITUATION=空")
    return {
        **state,
        "character_situation": "（状态管理器尚未实现）",
    }


# ================================================================
# Node 7: StyleInjection（mock — Week 3 真实化）
# ================================================================

async def style_injection_node(state: AgentState) -> AgentState:
    """结构随机化 + mes_example 多样化（mock）"""
    t0 = _log_node_start(state, "StyleInjection")
    _log_node_end(state, "StyleInjection", t0, "当前为 mock")
    return state


# ================================================================
# Node 8: ModelDialectCompiler（mock — Week 2 真实化）
# ================================================================

async def model_dialect_compiler_node(state: AgentState) -> AgentState:
    """模型方言编译器（mock，透传）

    Retry 时的策略调整：
    - retry_count == 1 → 在 CONTRAINTS 中追加更强约束
    - retry_count == 2 → 在 OUTPUT_SPEC 中追加逐条自检 COT
    """
    t0 = _log_node_start(state, "ModelDialectCompiler")

    retry = state.get("retry_count", 0)
    summary = f"当前为 mock，透传（retry={retry}）"

    if retry == 1:
        summary += " | 已追加更强约束（模拟）"
    elif retry >= 2:
        summary += " | 已追加 COT 自检（模拟）"

    _log_node_end(state, "ModelDialectCompiler", t0, summary)
    return state


# ================================================================
# Node 9: ContextAssemble
# ================================================================

async def context_assemble_node(state: AgentState) -> AgentState:
    """Prompt 区块化重组 — 原 completions.py 核心逻辑（已真实化）"""
    t0 = _log_node_start(state, "ContextAssemble")

    request = state["request"]
    model = request.get("model", "")
    raw_messages = request.get("messages", [])
    messages_list = [m.copy() for m in raw_messages]

    try:
        # 1. Prompt 拆解
        decomposed = decomposer.decompose({
            "model": model,
            "messages": raw_messages,
            "temperature": request.get("temperature"),
            "stream": request.get("stream"),
            "max_tokens": request.get("max_tokens"),
        })
        sys_comp = decomposed["system_prompt"]

        # 2. 提取用户信息
        has_user_prefix = sys_comp.get("has_user_prefix", True)
        user_name = state.get("user_name", "")
        timeline_state = ""
        if sys_comp["authority_ban"]:
            for line in sys_comp["authority_ban"].split("\n"):
                if "当前时间线" in line:
                    timeline_state = line.strip()
                    break

        # 3. 从 state 读取意图解析结果（已在 InputReceive 节点中提前执行）
        dialogue = decomposed.get("dialogue", {})
        recent_rounds = dialogue.get("recent_rounds", [])
        last_input = dialogue.get("last_user_input", "")

        intent_result = state.get("intent_result")
        if intent_result and intent_result.should_use():
            logger.info(
                f"[ContextAssemble] 使用 InputReceive 意图结果: "
                f"type={intent_result.input_type}, confidence={intent_result.confidence:.2f}"
            )

        # 4. 区块组装
        original_system = decomposed["raw"]["system_content"]
        blocks = []

        # --- [MAIN_PROMPT] ---
        if has_user_prefix:
            main_lines = original_system.split("\n")
            head = []
            for line in main_lines:
                if line.startswith("====="):
                    break
                head.append(line)
            main_text = "\n".join(head).strip()
            if main_text:
                main_text += (
                    "\n\n# 核心约束（必须遵守）\n"
                    "- 禁止生成用户的台词和行动\n"
                    "- 可以生成其他NPC的台词、行动和环境描写\n"
                    "- 替用户留出行动空间，不要推进剧情"
                )
                blocks.append(f"[MAIN_PROMPT]\n{main_text}")

        # --- [PROTOCOL] ---
        protocol_block = """[PROTOCOL]
- "对话内容"（双引号）= 角色台词，表示角色说出口的话
- **动作描写**（星号）= 角色动作、表情、行为
- （心理活动）（小括号）= 角色内心独白，未说出口的想法
- 输入格式：user 的消息会使用上述标记，LLM 需正确理解
- 输出格式：LLM 的回复也必须使用上述标记，保持格式一致"""
        blocks.append(protocol_block)

        # --- [CONSTRAINTS] ---
        constraints_block = f"""[CONSTRAINTS]
- LLM 角色声明：你是旁白/NPC扮演者，禁止替 {user_name or '用户'} 生成任何行动或台词
- 负向指令：禁止生成臀腿腰胸等垃圾小说描写；禁止推进剧情
- 输出格式：环境描写 + NPC 反应 + {user_name or '用户'} 行动空间"""
        blocks.append(constraints_block)

        # --- [CHARACTER_CARD] ---
        if sys_comp["character_card"]:
            blocks.append(f"[CHARACTER_CARD]\n{sys_comp['character_card']}")

        # --- [USER_PROFILE] ---
        if sys_comp["user_profile"]:
            blocks.append(f"[USER_PROFILE]\n{sys_comp['user_profile']}")

        # --- [CURRENT_STATE] ---
        current_state_block = """[CURRENT_STATE]
- [state: 当前场景: 待初始化]
- [state: 时间线: 待初始化]
- （此区块将在 Day 4 由 StateManager 从数据库读取真实状态后生成）"""
        blocks.append(current_state_block)

        # --- WORKING_MEMORY（不加入 blocks，稍后追加到 user 消息）---
        working_memory_lines = ["[WORKING_MEMORY]"]
        working_memory_lines.append("（以下为最近 5 轮对话，反映当前即时语境）")
        working_memory_lines.append("")
        if recent_rounds:
            for i, rd in enumerate(recent_rounds):
                um = rd.get("user", "")
                am = rd.get("assistant", "")
                if um:
                    um_s = um[:200] + ("..." if len(um) > 200 else "")
                    working_memory_lines.append(f"  [{i+1}] {user_name or '用户'}: {um_s}")
                if am:
                    am_s = am[:200] + ("..." if len(am) > 200 else "")
                    working_memory_lines.append(f"  [{i+1}] NPC: {am_s}")
        else:
            working_memory_lines.append("  （无最近对话记录）")
        if last_input:
            li_s = last_input[:200] + ("..." if len(last_input) > 200 else "")
            working_memory_lines.append(f"  [当前输入] {user_name or '用户'}: {li_s}")
        working_memory_text = "\n".join(working_memory_lines)

        # --- [LONG_TERM_MEMORY] ---
        rag_memories = state.get("retrieved_memories", [])
        if rag_memories:
            mem_lines = ["[LONG_TERM_MEMORY]"]
            mem_lines.append("（以下为与当前场景最相关的长期记忆，由 AURA RAG 系统召回）")
            mem_lines.append("")
            for mem in rag_memories:
                mem_lines.append(f"- {mem}")
            mem_lines.append("")
            mem_lines.append("# 记忆应用")
            mem_lines.append("- 像朋友般自然运用这些记忆，不要一次性提及所有记忆")
            mem_lines.append("- 选择与当前场景最相关的记忆自然融入叙述")
            mem_lines.append("- 避免机械式表达如\"根据我的记忆...\"")
            mem_lines.append("- 共同经历时可温情回忆：\"上次我们讨论很有趣\"")
            mem_lines.append("")
            mem_lines.append("记忆是丰富对话的工具，而非对话焦点。")
            blocks.append("\n".join(mem_lines))
        elif sys_comp.get("long_term_memory"):
            tavo_mems = sys_comp["long_term_memory"]
            mem_lines = ["[LONG_TERM_MEMORY]"]
            mem_lines.append("（以下为 TAVO 原始长记忆，AURA RAG 系统尚未积累数据）")
            mem_lines.append("")
            for mem in tavo_mems:
                mem_lines.append(f"- {mem}")
            mem_lines.append("")
            mem_lines.append("# 记忆应用")
            mem_lines.append("- 像朋友般自然运用这些记忆，不要一次性提及所有记忆")
            mem_lines.append("- 选择与当前场景最相关的记忆自然融入叙述")
            mem_lines.append("- 避免机械式表达如\"根据我的记忆...\"")
            mem_lines.append("- 共同经历时可温情回忆：\"上次我们讨论很有趣\"")
            mem_lines.append("")
            mem_lines.append("记忆是丰富对话的工具，而非对话焦点。")
            blocks.append("\n".join(mem_lines))

        # --- [RECENT_MEMORY] ---
        try:
            recent_summaries = await memory_manager._get_recent_memories_for_context(10)
            if recent_summaries and recent_summaries != "（无）":
                rml = ["[RECENT_MEMORY]"]
                rml.append("（以下为最近 10 条记忆摘要，反映近期剧情发展）")
                rml.append("")
                for line in recent_summaries.split("\n"):
                    if line.strip():
                        rml.append(line.strip())
                blocks.append("\n".join(rml))
        except Exception:
            pass

        # --- [USER_INTENT_TAG] → 合并到 WORKING_MEMORY ---
        if intent_result and intent_result.should_use() and intent_result.implicit_instruction:
            inst = intent_result.implicit_instruction.rstrip()
            if not inst.endswith("。"):
                inst += "。"
            working_memory_text += f"\n\n[USER_INTENT_TAG]\n{inst}"

        # --- [WORLD_CONTEXT] ---
        if sys_comp.get("world_book") and sys_comp["world_book"].strip():
            blocks.append(f"[WORLD_CONTEXT]\n{sys_comp['world_book'].strip()}")

        # --- [OUTPUT_SPEC] ---
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
4. 标记使用是否正确（台词用\", 动作用**, 心理用()）？→ 如果否，修正
5. 回复长度是否在 400-600 字范围内？→ 如果否，压缩或扩展
6. 回复格式是否与上述示例一致（每段空行分隔、每段一个独立画面）？→ 如果否，重新分段"""
        blocks.append(output_spec_block)

        optimized_system = "\n\n".join(blocks)
        logger.info(
            f"[ContextAssemble] System Prompt 重组 | 区块: {len(blocks)} | "
            f"原始: {len(original_system)} → 重组: {len(optimized_system)}"
        )

        # 替换 System Prompt
        if messages_list and messages_list[0].get("role") == "system":
            messages_list[0]["content"] = optimized_system

        # --- 近因效应：追加 WORKING_MEMORY 到最后一条 user 消息 ---
        user_constraint = (
            "\n\n[系统约束] 请严格遵守以下规则：\n"
            "1. 禁止生成用户的台词和行动\n"
            "2. 可以生成其他NPC的台词、行动和环境描写\n"
            "3. 替用户留出行动空间，不要推进剧情"
        )
        last_user_idx = -1
        for i in range(len(messages_list) - 1, -1, -1):
            if messages_list[i].get("role") == "user":
                last_user_idx = i
                break

        for i, msg in enumerate(messages_list):
            if msg.get("role") == "user":
                if "[系统约束]" not in msg["content"]:
                    msg["content"] = msg["content"].rstrip() + user_constraint
                if i == last_user_idx and working_memory_text:
                    msg["content"] = msg["content"].rstrip() + "\n\n" + working_memory_text

        summary = f"区块: {len(blocks)}, 字符: {len(optimized_system)}, user_msg: {len(messages_list)}"

    except Exception as e:
        logger.warning(f"[ContextAssemble] 组装失败，降级为原始透传: {e}")
        messages_list = [m.copy() for m in raw_messages]
        optimized_system = ""
        intent_result = None
        working_memory_text = ""
        summary = f"降级透传: {e}"

    _log_node_end(state, "ContextAssemble", t0, summary)
    return {
        **state,
        "decomposed": decomposed if 'decomposed' in dir() or 'decomposed' in locals() else None,
        "original_system": original_system if 'original_system' in locals() else "",
        "blocks": blocks if 'blocks' in locals() else [],
        "intent_result": intent_result,
        "working_memory_text": working_memory_text if 'working_memory_text' in locals() else "",
        "optimized_system": optimized_system if 'optimized_system' in locals() else "",
        "messages_list": messages_list,
        "has_user_prefix": has_user_prefix if 'has_user_prefix' in locals() else True,
        "timeline_state": timeline_state if 'timeline_state' in locals() else "",
    }


# ================================================================
# Node 10: LLMGenerate
# ================================================================

async def llm_generate_node(state: AgentState) -> AgentState:
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

    import httpx
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
# Node 11: FormatGuard（mock — Week 2 真实化）
# ================================================================

async def format_guard_node(state: AgentState) -> AgentState:
    """格式质检：越权输出检测 + 关系一致性检测（mock，默认通过）"""
    t0 = _log_node_start(state, "FormatGuard")
    _log_node_end(state, "FormatGuard", t0, "通过（mock）")
    return state


# ================================================================
# Node 12: OOCCheck（mock — Week 2 真实化）
# ================================================================

async def ooc_check_node(state: AgentState) -> AgentState:
    """人设一致性质检（mock，默认通过）"""
    t0 = _log_node_start(state, "OOCCheck")
    _log_node_end(state, "OOCCheck", t0, "通过（mock）")
    return state


# ================================================================
# Node 13: ContentFilter（mock — Week 2 真实化）
# ================================================================

async def content_filter_node(state: AgentState) -> AgentState:
    """文风污染过滤（mock，默认通过）"""
    t0 = _log_node_start(state, "ContentFilter")
    _log_node_end(state, "ContentFilter", t0, "通过（mock）")
    return state


# ================================================================
# Node 14: OutputReturn
# ================================================================

async def output_return_node(state: AgentState) -> AgentState:
    """构建标准响应返回"""
    t0 = _log_node_start(state, "OutputReturn")

    error = state.get("error")
    if error:
        from fastapi import HTTPException
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
# Node 15: MemoryExtract
# ================================================================

async def memory_extract_node(state: AgentState) -> AgentState:
    """保存对话 + 触发 Kimi 总结（已真实化）"""
    t0 = _log_node_start(state, "MemoryExtract")

    aura_session_id = state.get("aura_session_id", "")
    round_num = state.get("round_num", 0)
    # 新消息的轮次 = 已有轮数 + 1
    new_round = round_num + 1
    user_content = state.get("user_content", "")
    tavo_dialogue = state.get("tavo_dialogue_messages", [])

    summary_parts = []

    try:
        # 1. 对话同步
        if tavo_dialogue:
            await memory_manager.sync_dialogue_from_tavo(aura_session_id, tavo_dialogue)
            summary_parts.append(f"同步: {len(tavo_dialogue)}条")

        # 2. 保存用户输入
        if user_content:
            await memory_manager.save_dialogue(aura_session_id, "user", user_content, new_round)
            summary_parts.append(f"user: {len(user_content)}字")

        # 3. 保存 LLM 回复
        llm_content = state.get("llm_response_content", "")
        if llm_content:
            await memory_manager.save_dialogue(
                aura_session_id, "assistant", llm_content, new_round
            )
            summary_parts.append(f"assistant: {len(llm_content)}字")

        # 4. 触发总结（每 memory_summary_interval 轮触发一次）
        if new_round > 0 and new_round % settings.memory_summary_interval == 0:
            recent = await memory_manager.get_recent_messages(aura_session_id, n=10)
            if recent:
                asyncio.ensure_future(
                    memory_manager.summarize_and_store(aura_session_id, recent)
                )
                summary_parts.append(f"触发总结(轮={new_round})")

    except Exception as e:
        logger.warning(f"[MemoryExtract] 保存失败（不影响返回）: {e}")
        summary_parts.append(f"失败: {e}")

    _log_node_end(state, "MemoryExtract", t0, ", ".join(summary_parts) or "无操作")
    return state


# ================================================================
# 条件边：质检 → 重试 or 放行
# ================================================================

def should_retry_after_check(state: AgentState) -> str:
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
    # 更新 retry_count，路由到 ModelDialectCompiler
    state["retry_count"] = retry + 1
    return "model_dialect_compiler"


# ================================================================
# 构建 StateGraph
# ================================================================

workflow = StateGraph(AgentState)

# 注册所有节点
workflow.add_node("input_receive", input_receive_node)
workflow.add_node("entity_extract", entity_extract_node)
workflow.add_node("emotion_analyze", emotion_analyze_node)
workflow.add_node("memory_decision", memory_decision_node)
workflow.add_node("memory_retrieve", memory_retrieve_node)
workflow.add_node("state_manager", state_manager_node)
workflow.add_node("style_injection", style_injection_node)
workflow.add_node("model_dialect_compiler", model_dialect_compiler_node)
workflow.add_node("context_assemble", context_assemble_node)
workflow.add_node("llm_generate", llm_generate_node)
workflow.add_node("format_guard", format_guard_node)
workflow.add_node("ooc_check", ooc_check_node)
workflow.add_node("content_filter", content_filter_node)
workflow.add_node("output_return", output_return_node)
workflow.add_node("memory_extract", memory_extract_node)

# 设置入口
workflow.set_entry_point("input_receive")

# 顺序边（主链路）
workflow.add_edge("input_receive", "entity_extract")
workflow.add_edge("entity_extract", "emotion_analyze")
workflow.add_edge("emotion_analyze", "memory_decision")
workflow.add_edge("memory_decision", "memory_retrieve")
workflow.add_edge("memory_retrieve", "state_manager")
workflow.add_edge("state_manager", "style_injection")
workflow.add_edge("style_injection", "model_dialect_compiler")
workflow.add_edge("model_dialect_compiler", "context_assemble")
workflow.add_edge("context_assemble", "llm_generate")
workflow.add_edge("llm_generate", "format_guard")
workflow.add_edge("format_guard", "ooc_check")
workflow.add_edge("ooc_check", "content_filter")

# 条件边：ContentFilter 后 → 通过则 OutputReturn，不通过则重试
workflow.add_conditional_edges(
    "content_filter",
    should_retry_after_check,
    {
        "output_return": "output_return",
        "model_dialect_compiler": "model_dialect_compiler",
    },
)

# OutputReturn → MemoryExtract → END
workflow.add_edge("output_return", "memory_extract")
workflow.add_edge("memory_extract", END)

# 编译
# checkpointer: 内存级别状态持久化（开发用），生产环境可换 RedisSaver
memory_saver = MemorySaver()
aura_workflow = workflow.compile(checkpointer=memory_saver)

logger.info("[LangGraph] AURA 工作流编译完成 | 节点数: 15 | checkpointer: MemorySaver")