"""
演示：LangGraph 状态机在 AURA 各节点间的数据流转

运行方式: python demo_state_flow.py
"""
import json
from typing import Dict, Any


# 打印 state 的辅助函数
def show_state(title: str, state: Dict[str, Any]):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")
    for key, value in state.items():
        if key == "messages_list":
            # 消息列表太长，只显示第一条 system 的长度
            v = f"[列表，{len(value)} 条消息，system={len(value[0]['content'])} 字]"
        elif key == "node_logs":
            v = f"[{len(value)} 条日志]"
        elif isinstance(value, str) and len(value) > 100:
            v = f"{value[:80]}... ({len(value)} 字)"
        elif isinstance(value, dict):
            v = json.dumps(value, ensure_ascii=False, indent=2)[:100] + "..."
        else:
            v = value
        print(f"  {key:25s} = {v}")


# ================================================================
# 初始状态（chat_completion() 组装后注入）
# ================================================================
state = {
    "session_id": "aura_1715923456_140234567890",
    "backend": "deepseek",
    "model": "deepseek-chat",
    "temperature": 0.7,
    "user_content": "（微笑着走近）你在这里啊，我找了你好久了。",
    "round_num": 0,
    "node_logs": [],
}

show_state("Step 0: 初始状态（由 completions.py 注入）", state)


# ================================================================
# Step 1: InputReceive
# ================================================================
print("\n  → 执行 input_receive_node:")
print("     提取用户名: '李雷'")
print("     调用 IntentTagger → 解析出意图结构...")

state["user_name"] = "李雷"
state["intent_result"] = {
    "input_type": "roleplay_interaction",
    "confidence": 0.92,
    "implicit_instruction": "用户正在主动靠近角色，表达寻找和关心的情感，期待角色给出温暖回应。",
    "structure": {
        "scene_type": "情感互动",
        "action_type": "靠近",
        "emotional_tone": "温柔、关心",
        "tension_description": "轻微紧张但温馨",
    }
}
state["node_logs"].append({
    "node": "InputReceive",
    "elapsed_ms": 420,
    "summary": "用户名=李雷, 意图=情感互动",
})

show_state("Step 1: InputReceive 执行后", state)


# ================================================================
# Step 2: ParallelPreparation（6个节点并行）
# ================================================================
print("\n  → 执行 parallel_preparation_node:")
print("     [并行] entity_extract → 发现实体: ['李雷']")
print("     [并行] emotion_analyze → 情绪: 温柔/关心")
print("     [并行] memory_retrieve → FAISS 召回 3 条记忆...")
print("     [并行] state_manager → 当前状态占位")
print("     [并行] style_injection → 当前为空")
print("     [并行] model_dialect_compiler → 当前为空")

state["active_entity_ids"] = ["李雷"]
state["character_situation"] = "（状态管理器尚未实现）"
state["retrieved_memories"] = [
    "李雷上周在图书馆遇到了角色，两人一起讨论了古典文学。",
    "角色记得李雷喜欢喝抹茶拿铁。",
    "李雷曾经提到他家养了一只叫'橘子'的橘猫。",
]
state["node_logs"].append({
    "node": "ParallelPreparation",
    "elapsed_ms": 65,
    "summary": "entity+emotion+memory+state+style+dialect 并行完成",
})

show_state("Step 2: ParallelPreparation 执行后", state)


# ================================================================
# Step 3: ContextAssemble
# ================================================================
print("\n  → 执行 context_assemble_node:")
print("     1. PromptDecomposer 拆解原始 System Prompt")
print("     2. 组装 9 区块 Prompt")
print("     3. WORKING_MEMORY 追加到最后一条 user 消息")

state["decomposed"] = {"system_prompt": {"authority_ban": "...", "character_card": "..."}}
state["blocks"] = [
    "[MAIN_PROMPT]",
    "[PROTOCOL]",
    "[CONSTRAINTS]",
    "[CHARACTER_CARD]",
    "[USER_PROFILE]",
    "[LONG_TERM_MEMORY]",
    "[OUTPUT_SPEC]",
]
state["optimized_system"] = (
    "[MAIN_PROMPT]\n你是私立樱华女子学院的文学少女..."
    "\n\n[PROTOCOL]\n'对话内容'=台词, **动作**=行为..."
    "\n\n[CONSTRAINTS]\n禁止替李雷生成任何行动或台词..."
    "\n\n[LONG_TERM_MEMORY]\n- 李雷上周在图书馆..."
    "\n\n[OUTPUT_SPEC]\n长度：400-600 字..."
)
state["working_memory_text"] = (
    "[WORKING_MEMORY]\n（以下为最近 5 轮对话...）\n"
    "  [当前输入] 李雷: （微笑着走近）你在这里啊...\n\n"
    "[USER_INTENT_TAG]\n用户正在主动靠近角色，表达寻找和关心的情感..."
)
state["messages_list"] = [
    {"role": "system", "content": state["optimized_system"]},
    {"role": "user", "content": "（微笑着走近）你在这里啊，我找了你好久了。\n\n[系统约束] 禁止生成用户的台词和行动\n\n" + state["working_memory_text"]},
]
state["node_logs"].append({
    "node": "ContextAssemble",
    "elapsed_ms": 12,
    "summary": "区块: 7, 字符: 3847, user_msg: 2",
})

show_state("Step 3: ContextAssemble 执行后", state)


# ================================================================
# Step 4: LLMGenerate
# ================================================================
print("\n  → 执行 llm_generate_node:")
print("     发送非流式请求到 DeepSeek API...")
print("     收到响应，内容长度: 487 字")

state["llm_response_content"] = (
    "秋日的阳光透过银杏叶的缝隙，在她翻开的书页上投下斑驳的光影。"
    "她微微抬起头，几缕碎发从耳后滑落，在颊边轻轻晃动。\n\n"
    "*指尖不自觉地捏紧了书脊，指节泛出淡淡的白色*\n\n"
    "\"你……你怎么知道我在这里？\""
    "她的声音轻得像一片落叶，目光却迅速垂向地面，"
    "耳尖悄然染上一抹淡红。\n\n"
    "*她往书架的方向退了一小步，后背抵上冰凉的木质书架*\n\n"
    "\"我、我只是恰好今天没课……\""
)
state["llm_reasoning_content"] = "（模型思考过程...）"
state["node_logs"].append({
    "node": "LLMGenerate",
    "elapsed_ms": 2850,
    "summary": "内容长度: 487字, prompt_tokens: 2156, completion_tokens: 312",
})

show_state("Step 4: LLMGenerate 执行后", state)


# ================================================================
# Step 5: ParallelQualityCheck
# ================================================================
print("\n  → 执行 parallel_quality_check_node:")
print("     [并行] FormatGuard → 通过")
print("     [并行] OOCCheck → 通过")
print("     [并行] ContentFilter → 通过")

state["format_passed"] = True
state["ooc_passed"] = True
state["content_passed"] = True
state["node_logs"].append({
    "node": "ParallelQualityCheck",
    "elapsed_ms": 3,
    "summary": "format+ooc+content 并行质检完成",
})

show_state("Step 5: ParallelQualityCheck 执行后", state)


# ================================================================
# Step 6: 条件边判断
# ================================================================
print("\n  → 执行 should_retry_after_check:")
print("     format_passed=True, ooc_passed=True, content_passed=True")
print("     → 全部通过，路由到 output_return")


# ================================================================
# Step 7: OutputReturn
# ================================================================
print("\n  → 执行 output_return_node:")
print("     包装为 ChatCompletionResponse 格式")

state["response"] = {
    "id": f"aura-{state['session_id']}",
    "object": "chat.completion",
    "created": 1715923462,
    "model": state["model"],
    "choices": [{
        "index": 0,
        "message": {
            "role": "assistant",
            "content": state["llm_response_content"],
        },
        "finish_reason": "stop",
    }],
}
state["node_logs"].append({
    "node": "OutputReturn",
    "elapsed_ms": 1,
    "summary": "内容: 487字",
})

show_state("Step 7: OutputReturn 执行后", state)


# ================================================================
# Step 8: MemoryExtract
# ================================================================
print("\n  → 执行 memory_extract_node:")
print("     保存 user 输入到 SQLite dialogues 表")
print("     保存 assistant 回复到 SQLite dialogues 表")
print("     round_num=0 < 5，不触发总结")

state["round_num"] = 1
state["node_logs"].append({
    "node": "MemoryExtract",
    "elapsed_ms": 8,
    "summary": "同步: 2条, user: 18字, assistant: 487字",
})

show_state("Step 8: MemoryExtract 执行后（本轮结束）", state)


# ================================================================
# 总结
# ================================================================
print("\n" + "="*70)
print("  总结：State 在各节点的关键变化")
print("="*70)
print(f"""
  InputReceive          : + user_name, + intent_result
  ParallelPreparation   : + retrieved_memories, + active_entity_ids, + character_situation
  ContextAssemble       : + optimized_system, + messages_list, + working_memory_text, + blocks
  LLMGenerate           : + llm_response_content, + llm_reasoning_content
  ParallelQualityCheck  : + format_passed, + ooc_passed, + content_passed
  OutputReturn          : + response
  MemoryExtract         : round_num 0 → 1

  最终产物: state["response"] 就是返回给 TAVO 的 JSON
""")
