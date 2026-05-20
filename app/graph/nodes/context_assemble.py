"""
Node 10: ContextAssemble

Prompt 区块化重组 — 从 PromptDecomposer 产出的结构化数据组装 9 区块 System Prompt
"""
import time
from typing import TYPE_CHECKING

from app.utils import get_logger
from app.memory import memory_manager

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


async def context_assemble_node(state: "AgentState") -> "AgentState":
    """Prompt 区块化重组 — 从上游节点产出的结构化数据组装 9 区块 System Prompt"""
    t0 = _log_node_start(state, "ContextAssemble")

    raw_messages = state.get("messages", [])
    messages_list = [m.copy() for m in raw_messages]

    # 从上游 PromptDecomposer 节点读取拆解结果
    decomposed = state.get("decomposed")
    if not decomposed:
        logger.warning("[ContextAssemble] 未收到 decomposed 数据，降级为原始透传")
        _log_node_end(state, "ContextAssemble", t0, "降级透传: 缺少 decomposed")
        return {
            **state,
            "messages_list": messages_list,
            "optimized_system": "",
            "blocks": [],
            "working_memory_text": "",
        }

    try:
        sys_comp = decomposed["system_prompt"]
        has_user_prefix = state.get("has_user_prefix", True)
        user_name = state.get("user_name", "")

        # 从 decomposed 读取对话历史
        dialogue = decomposed.get("dialogue", {})
        recent_rounds = dialogue.get("recent_rounds", [])
        last_input = dialogue.get("last_user_input", "")

        intent_result = state.get("intent_result")
        if intent_result and intent_result.should_use():
            logger.info(
                f"[ContextAssemble] 使用 InputReceive 意图结果: "
                f"type={intent_result.input_type}, confidence={intent_result.confidence:.2f}"
            )

        # 读取重试策略（由 RetryStrategy 节点产出）
        retry_strategy = state.get("retry_strategy", {})
        extra_constraints = retry_strategy.get("inject_constraints", [])
        extra_output_spec = retry_strategy.get("inject_output_spec", [])

        original_system = state.get("original_system", "")
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
        constraints_lines = [
            "[CONSTRAINTS]",
            f"- LLM 角色声明：你是旁白/NPC扮演者，禁止替 {user_name or '用户'} 生成任何行动或台词",
            "- 负向指令：禁止生成臀腿腰胸等垃圾小说描写；禁止推进剧情",
            f"- 输出格式：环境描写 + NPC 反应 + {user_name or '用户'} 行动空间",
        ]
        # 追加重试策略中的额外约束
        if extra_constraints:
            constraints_lines.append("")
            constraints_lines.append("# 重试追加约束（因上一轮未通过质检）")
            for ec in extra_constraints:
                constraints_lines.append(f"- {ec}")
        constraints_block = "\n".join(constraints_lines)
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
        output_spec_lines = [
            "[OUTPUT_SPEC]",
            "- 长度：400-600 字",
            "- 结构：环境描写(30%) + NPC内心/对话(40%) + 留给user的行动空间(30%)",
            "- 标记规范：",
            '  "对话内容"（双引号 = 角色台词）',
            "  **动作描写**（星号 = 角色动作/表情）",
            "  （心理活动）（小括号 = 角色内心独白）",
            "- 禁止：替 user 做决定、推进剧情、OOC",
            "",
            "# 输出格式示例（必须严格模仿此格式）",
            "你的输出格式应如下例：",
            "",
            "阳光透过女子学校的铁艺大门，在地面投下斑驳的纹路。秋天的银杏叶被风卷起，在门口的喷泉边打转。",
            "",
            "几个正抱着课本路过的女生停下脚步，目光警惕地打量着门口这位不速之客。",
            "",
            "校门口的石狮静默矗立，等待着这位闯入者迈出第一步。",
            "",
            "注意：",
            "- 每段之间必须空一行",
            "- 每段是一个独立的画面",
            "- 段落长度应错落有致，不要每段等长",
            "",
            "# 输出前自我校验（COT）",
            "在生成最终回复前，请按以下步骤逐项检查：",
            "1. 这段回复中是否有替 user 生成行动或台词？→ 如果有，删除对应部分",
            "2. 这段回复是否推进了主线剧情？→ 如果是，改为环境描写或NPC反应",
            "3. 这段回复是否符合角色设定和当前场景？→ 如果否，重新调整",
            '4. 标记使用是否正确（台词用\", 动作用**, 心理用()）？→ 如果否，修正',
            "5. 回复长度是否在 400-600 字范围内？→ 如果否，压缩或扩展",
            "6. 回复格式是否与上述示例一致（每段空行分隔、每段一个独立画面）？→ 如果否，重新分段",
        ]
        # 追加重试策略中的额外输出规范
        if extra_output_spec:
            output_spec_lines.append("")
            output_spec_lines.append("# 重试追加输出规范（因上一轮未通过质检）")
            for eo in extra_output_spec:
                output_spec_lines.append(f"- {eo}")
        output_spec_block = "\n".join(output_spec_lines)
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
        "decomposed": decomposed if 'decomposed' in locals() else None,
        "original_system": original_system if 'original_system' in locals() else "",
        "blocks": blocks if 'blocks' in locals() else [],
        "intent_result": intent_result,
        "working_memory_text": working_memory_text if 'working_memory_text' in locals() else "",
        "optimized_system": optimized_system if 'optimized_system' in locals() else "",
        "messages_list": messages_list,
        "has_user_prefix": has_user_prefix if 'has_user_prefix' in locals() else True,
    }
