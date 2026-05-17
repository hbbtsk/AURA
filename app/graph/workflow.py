"""
AURA LangGraph 工作流 — 15 节点 Agent 状态机

设计原则：
- 每个节点只调用已有业务代码，不修改原有逻辑
- 原有 completions.py 中的 Prompt 编译 / RAG / LLM 调用逻辑，
  在 ContextAssemble 节点中完整保留（复制粘贴，不抽取）
- 当前为 v0.8.2 骨架：mock 节点直接返回空值，真实逻辑后续填充
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

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from app.graph.state import AgentState
from app.utils import get_logger

from app.graph.nodes import (
    input_receive_node,
    entity_extract_node,
    emotion_analyze_node,
    memory_decision_node,
    memory_retrieve_node,
    state_manager_node,
    style_injection_node,
    model_dialect_compiler_node,
    context_assemble_node,
    llm_generate_node,
    format_guard_node,
    ooc_check_node,
    content_filter_node,
    output_return_node,
    memory_extract_node,
    should_retry_after_check,
)

logger = get_logger("aura-graph")

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
