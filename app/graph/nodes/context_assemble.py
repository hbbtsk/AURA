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
    logger.info(
        f"[LangGraph→节点] {node_name} | 结束 | 耗时: {elapsed:.1f}ms | {summary}"
    )
    return {"node_logs": [log_entry]}


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
        backend = state.get("backend", "deepseek")  # 当前 LLM 后端，用于模型专属约束

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

        # --- [CONSTRAINTS] — 模型专属约束 ---
        # DeepSeek 天生保守，约束要松一点，允许适当推进；Gemini 推进过猛，约束要严格
        if backend == "deepseek":
            plot_constraint = "你可以适当推进剧情（如环境变化、NPC自发行动），但不要替用户做决定"
            length_hint = "DeepSeek 容易输出过短：请充分展开描写，每段至少 2-3 句话"
        elif backend == "gemini":
            plot_constraint = "严格禁止推进主线剧情；只渲染当前场景的氛围和NPC反应"
            length_hint = "Gemini 容易输出过长：控制篇幅，聚焦当前画面，不要铺陈未来"
        else:  # kimi / 默认
            plot_constraint = "适当推进剧情，但核心决策权留给用户"
            length_hint = ""

        constraints_lines = [
            "[CONSTRAINTS]",
            f"- LLM 角色声明：你是旁白/NPC扮演者，禁止替 {user_name or '用户'} 生成任何行动或台词",
            f"- 剧情推进：{plot_constraint}",
            "- 文风：禁止生成臀腿腰胸等垃圾小说描写",
            f"- 输出格式：环境描写 + NPC 反应 + {user_name or '用户'} 行动空间",
            "",
            "# 叙事分段约束（最高优先级，必须遵守）",
            "- 单段只做一件事：要么写景，要么写对话，要么写动作，要么写内心。禁止同一段混合两件以上",
            "- 角色台词独占一段，台词前后不加动作描写。动作另起一段，动作段落不超过2句话",
            "- 对话每段不超过3句，每句不超过30字。叙述句每句不超过25字，长句必须拆成短句",
            "- 删除'轻轻''缓缓''微微'等弱化词。动作描写极简，禁止连续相同句式超过2次",
        ]
        if length_hint:
            constraints_lines.append(f"- 长度控制：{length_hint}")
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
        else:
            blocks.append("[CHARACTER_CARD]\n（未识别：当前卡带未提供角色卡数据）")

        # --- [USER_PROFILE] ---
        if sys_comp["user_profile"]:
            blocks.append(f"[USER_PROFILE]\n{sys_comp['user_profile']}")
        else:
            blocks.append("[USER_PROFILE]\n（未识别：当前卡带未提供用户画像数据）")

        # --- [CURRENT_STATE] ---
        current_state_block = """[CURRENT_STATE]
- [state: 当前场景: 待初始化]
- [state: 时间线: 待初始化]
- （此区块将在 Day 4 由 StateManager 从数据库读取真实状态后生成）"""
        blocks.append(current_state_block)

        # --- WORKING_MEMORY（不加入 blocks，稍后追加到 user 消息）---
        # 辅助：去掉 user 消息末尾追加的 [系统约束]，只保留原始对话内容
        def _strip_user_constraint(text: str) -> str:
            idx = text.find("\n\n[系统约束]")
            if idx >= 0:
                return text[:idx].rstrip()
            return text

        working_memory_lines = ["[WORKING_MEMORY]"]
        working_memory_lines.append("（以下为最近 5 轮对话，反映当前即时语境）")
        working_memory_lines.append("")
        if recent_rounds:
            for i, rd in enumerate(recent_rounds):
                um = _strip_user_constraint(rd.get("user", ""))
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
            li = _strip_user_constraint(last_input)
            li_s = li[:200] + ("..." if len(li) > 200 else "")
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
        else:
            blocks.append("[LONG_TERM_MEMORY]\n（未识别：暂无长期记忆数据）")

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
            else:
                blocks.append("[RECENT_MEMORY]\n（未识别：暂无近期记忆摘要）")
        except Exception:
            blocks.append("[RECENT_MEMORY]\n（未识别：暂无近期记忆摘要）")

        # --- [USER_INTENT_TAG] → 合并到 WORKING_MEMORY ---
        if intent_result and intent_result.should_use() and intent_result.implicit_instruction:
            inst = intent_result.implicit_instruction.rstrip()
            if not inst.endswith("。"):
                inst += "。"
            working_memory_text += f"\n\n[USER_INTENT_TAG]\n{inst}"

        # --- [WORLD_CONTEXT] ---
        if sys_comp.get("world_book") and sys_comp["world_book"].strip():
            blocks.append(f"[WORLD_CONTEXT]\n{sys_comp['world_book'].strip()}")
        else:
            blocks.append("[WORLD_CONTEXT]\n（未识别：当前卡带未提供世界观设定）")

        # --- [OUTPUT_SPEC] ---
        output_spec_lines = [
            "[OUTPUT_SPEC]",
            "- 长度：400-600 字",
            "- 结构：环境描写(30%) + NPC内心/对话(40%) + 留给user的行动空间(30%)",
            "- 标记规范：",
            '  "对话内容"（双引号 = 角色台词）',
            "  **动作描写**（星号 = 角色动作/表情）",
            "  （心理活动）（小括号 = 角色内心独白）",
            "- 禁止：替 user 做决定、推进剧情、OOC、括号注释（如'（苦笑）'）",
            "",
            "# 呼吸点规则（按场景切换）",
            "- [非紧张场景：日常/探索/交谈] 每3-4段对话/动作后，插入1段环境/内心/他人反应（≤2句）",
            "- [紧张场景：对峙/战斗/审讯/逃亡] 允许连续5-6段不加环境，靠短句和断行制造窒息感",
            "",
            "# 输出格式示例（必须严格模仿此格式）",
            "阳光透过铁艺大门，在地面投下斑驳纹路。银杏叶被风卷起，在喷泉边打转。",
            "",
            "**魏丝的手指停在剑柄上，指节发白。**",
            "",
            '"你来了。"',
            "",
            '**她抬起头。**',
            "",
            '"我等你很久了。"',
            "",
            "校门口的石狮静默矗立。风停了。",
            "",
            "注意：",
            "- 每段之间必须空一行",
            "- 每段只做一件事：景 / 对话 / 动作 / 内心，禁止混用",
            "- 台词独占一段，前后不加动作。动作另起一段",
            "- 叙述句每句≤25字，对话每句≤30字",
            "- 禁止括号注释，情绪通过动作和台词传达",
            "",
            "# 输出前自我校验（COT）",
            "在生成最终回复前，请按以下步骤逐项检查：",
            "1. 是否有替 user 生成行动或台词？→ 有则删除",
            "2. 是否推进了主线剧情？→ 是则改为环境或NPC反应",
            "3. 是否有同一段混合两件事（如台词+动作）？→ 是则拆段",
            "4. 是否有'轻轻''缓缓'等弱化词？→ 有则删除",
            "5. 是否有括号注释（如'（苦笑）'）？→ 有则改为动作描写",
            "6. 标记是否正确（台词用\", 动作用**, 心理用()）？→ 否则修正",
            "7. 长度是否在400-600字？→ 否则调整",
            "8. 段与段之间是否空了一行？→ 否则补空行",
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

        # 向实时日志流推送 Prompt 组装事件
        try:
            from app.utils.log_stream import log_ring, LogEntry
            import time
            t = time.localtime()
            time_str = time.strftime("%H:%M:%S", t) + ".{:03d}".format(int((time.time() % 1) * 1000))
            block_names = []
            for b in blocks:
                if b.startswith("[") and "]" in b:
                    block_names.append(b.split("]")[0][1:])
            log_ring.append(LogEntry(
                timestamp=time.time(),
                time_str=time_str,
                node="director",
                node_name="aura-graph",
                level="INFO",
                action=f"Prompt 组装完成 | 区块: {len(blocks)} ({', '.join(block_names[:5])}{'...' if len(block_names) > 5 else ''})",
                detail=f"字符: {len(optimized_system)}",
                duration_ms=0,
                status="ok",
                full_action=f"Prompt 组装完成 | 区块: {len(blocks)}\n区块列表: {', '.join(block_names)}",
            ))
        except Exception:
            pass

        # 替换 System Prompt
        if messages_list and messages_list[0].get("role") == "system":
            messages_list[0]["content"] = optimized_system

        # --- 近因效应：追加 WORKING_MEMORY 到最后一条 user 消息 ---
        # user 消息末尾的约束也要模型化：DeepSeek 允许适当推进，Gemini 严格限制
        # 近因效应追加约束（追加到最后一条 user 消息末尾，遵循率最高）
        narrative_rules = (
            "\n"
            "4. 单段只做一件事：景/对话/动作/内心，禁止混用\n"
            "5. 台词独占一段，前后不加动作；动作另起一段，≤2句\n"
            "6. 叙述句每句≤25字，对话每句≤30字，长句必拆\n"
            "7. 删除'轻轻''缓缓'等弱化词；禁止括号注释\n"
            "8. 段与段之间必须空一行"
        )
        if backend == "deepseek":
            user_constraint = (
                "\n\n[系统约束] 请严格遵守以下规则：\n"
                "1. 禁止生成用户的台词和行动\n"
                "2. 可以生成其他NPC的台词、行动和环境描写\n"
                "3. 适当推进剧情（如环境变化、NPC自发行动），但核心决策留给用户"
                + narrative_rules
            )
        elif backend == "gemini":
            user_constraint = (
                "\n\n[系统约束] 请严格遵守以下规则：\n"
                "1. 禁止生成用户的台词和行动\n"
                "2. 可以生成其他NPC的台词、行动和环境描写\n"
                "3. 严格禁止推进剧情；只渲染当前场景，等用户输入后再推进"
                + narrative_rules
            )
        else:  # kimi / 默认
            user_constraint = (
                "\n\n[系统约束] 请严格遵守以下规则：\n"
                "1. 禁止生成用户的台词和行动\n"
                "2. 可以生成其他NPC的台词、行动和环境描写\n"
                "3. 适当推进剧情，但核心决策留给用户"
                + narrative_rules
            )
        # 先清理所有历史 user 消息中已追加的 [系统约束]，避免 token 浪费和重复
        for msg in messages_list:
            if msg.get("role") == "user":
                msg["content"] = _strip_user_constraint(msg["content"])

        # 找到最后一条 user 消息，只在此处追加 [系统约束] 和 WORKING_MEMORY
        last_user_idx = -1
        for i in range(len(messages_list) - 1, -1, -1):
            if messages_list[i].get("role") == "user":
                last_user_idx = i
                break

        if last_user_idx >= 0:
            messages_list[last_user_idx]["content"] = (
                messages_list[last_user_idx]["content"].rstrip() + user_constraint
            )
            if working_memory_text:
                messages_list[last_user_idx]["content"] = (
                    messages_list[last_user_idx]["content"].rstrip() + "\n\n" + working_memory_text
                )

        # 把追加到 user 消息的模块也加入 blocks（供调试面板查看完整拼装）
        blocks.append(f"[USER_CONSTRAINT]\n{user_constraint.strip()}")
        if working_memory_text:
            blocks.append(working_memory_text)

        summary = f"区块: {len(blocks)}, 字符: {len(optimized_system)}, user_msg: {len(messages_list)}"

    except Exception as e:
        logger.warning(f"[ContextAssemble] 组装失败，降级为原始透传: {e}")
        messages_list = [m.copy() for m in raw_messages]
        optimized_system = ""
        intent_result = None
        working_memory_text = ""
        summary = f"降级透传: {e}"

    log_update = _log_node_end(state, "ContextAssemble", t0, summary)
    return {
        "decomposed": decomposed if 'decomposed' in locals() else None,
        "original_system": original_system if 'original_system' in locals() else "",
        "blocks": blocks if 'blocks' in locals() else [],
        "intent_result": intent_result,
        "working_memory_text": working_memory_text if 'working_memory_text' in locals() else "",
        "optimized_system": optimized_system if 'optimized_system' in locals() else "",
        "messages_list": messages_list,
        "has_user_prefix": has_user_prefix if 'has_user_prefix' in locals() else True,
        **log_update,
    }
