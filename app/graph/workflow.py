"""
AURA LangGraph 工作流 — 图结构真实化重构 v0.9.0

设计原则：
- 并行子任务注册为 LangGraph 真实节点（非 Python 包装器）
- Prompt 拆解从 ContextAssemble 剥离为独立节点
- 质检失败回退到 RetryStrategy → ContextAssemble → LLMGenerate（精准回退）
- 每个节点职责单一，接口契约统一

节点清单（12 个显式节点）：
1. InputReceive         → 收输入，解析请求 + 意图标签
2. PromptDecomposer     → 拆解 TAVO 原始 Prompt 为结构化组件
3. EntityExtract        → 从对话中抽取角色/实体（预留）
4. EmotionAnalyze       → 分析用户输入的情绪倾向（预留）
5. MemoryRetrieve       → FAISS 向量检索 + 结构化感知匹配 Top-K
6. StateManager         → 维护角色状态 / 时间线 / dynamic_state
7. StyleInjection       → 注入文风控制指令（预留）
8. ModelDialectCompiler → 模型方言编译（预留，适配不同 LLM 特性）
9. ContextAssemble      → 9 区块 Prompt 组装（核心编译逻辑）
10. LLMGenerate         → LLM 生成（已真实化，非流式）
11. ParallelQualityCheck→ 并行执行 FormatGuard + OOCCheck + ContentFilter
12. RetryStrategy       → 根据失败原因生成重试策略补丁
13. OutputReturn        → 构建响应返回
14. MemoryExtract       → 保存对话 + 触发总结（已真实化）
"""

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from app.graph.state import AgentState
from app.utils import get_logger

from app.graph.nodes import (
    # --- 输入层 ---
    input_receive_node,             # 接收 TAVO 请求
    prompt_decomposer_node,         # Prompt 拆解为结构化组件

    # --- 并行准备层（LangGraph 真实节点）---
    entity_extract_node,            # 实体抽取（预留）
    emotion_analyze_node,           # 情绪分析（预留）
    memory_retrieve_node,           # 记忆检索
    state_manager_node,             # 状态管理（预留）
    style_injection_node,           # 文风注入（预留）
    model_dialect_compiler_node,    # 模型方言编译（预留）

    # --- 编译层 ---
    context_assemble_node,          # 9 区块 Prompt 组装

    # --- LLM 生成层 ---
    llm_generate_node,              # LLM 生成

    # --- 质检层 ---
    parallel_quality_check_node,    # 并行质检

    # --- 重试策略层 ---
    retry_strategy_node,            # 重试策略生成

    # --- 输出层 ---
    output_return_node,             # 响应构建
    memory_extract_node,            # 记忆固化

    # --- 条件边 ---
    should_retry_after_check,       # 质检失败判断
)

logger = get_logger("aura-graph")


# ================================================================
# 构建 StateGraph
# ================================================================

workflow = StateGraph(AgentState)

# 注册所有节点
workflow.add_node("input_receive", input_receive_node)
workflow.add_node("prompt_decomposer", prompt_decomposer_node)
workflow.add_node("entity_extract", entity_extract_node)
workflow.add_node("emotion_analyze", emotion_analyze_node)
workflow.add_node("memory_retrieve", memory_retrieve_node)
workflow.add_node("state_manager", state_manager_node)
workflow.add_node("style_injection", style_injection_node)
workflow.add_node("model_dialect_compiler", model_dialect_compiler_node)
workflow.add_node("context_assemble", context_assemble_node)
workflow.add_node("llm_generate", llm_generate_node)
workflow.add_node("parallel_quality_check", parallel_quality_check_node)
workflow.add_node("retry_strategy", retry_strategy_node)
workflow.add_node("output_return", output_return_node)
workflow.add_node("memory_extract", memory_extract_node)

# 设置入口
workflow.set_entry_point("input_receive")

# ================================================================
# 主链路
# ================================================================

# 输入层
workflow.add_edge("input_receive", "prompt_decomposer")

# 并行准备层：从 PromptDecomposer 分叉到 6 个并行子任务
workflow.add_edge("prompt_decomposer", "entity_extract")
workflow.add_edge("prompt_decomposer", "emotion_analyze")
workflow.add_edge("prompt_decomposer", "memory_retrieve")
workflow.add_edge("prompt_decomposer", "state_manager")
workflow.add_edge("prompt_decomposer", "style_injection")
workflow.add_edge("prompt_decomposer", "model_dialect_compiler")

# 编译层：6 个并行子任务完成后汇入 ContextAssemble
workflow.add_edge("entity_extract", "context_assemble")
workflow.add_edge("emotion_analyze", "context_assemble")
workflow.add_edge("memory_retrieve", "context_assemble")
workflow.add_edge("state_manager", "context_assemble")
workflow.add_edge("style_injection", "context_assemble")
workflow.add_edge("model_dialect_compiler", "context_assemble")

# 生成层
workflow.add_edge("context_assemble", "llm_generate")
workflow.add_edge("llm_generate", "parallel_quality_check")

# ================================================================
# 条件边：质检 → 通过则 OutputReturn，不通过则 RetryStrategy → 重新编译 → 重新生成
# ================================================================
workflow.add_conditional_edges(
    "parallel_quality_check",
    should_retry_after_check,
    {
        "output_return": "output_return",
        "retry_strategy": "retry_strategy",
    },
)

# 重试链路：RetryStrategy → ContextAssemble → LLMGenerate → 再次质检
workflow.add_edge("retry_strategy", "context_assemble")
# context_assemble → llm_generate 已在主链路中注册，无需重复

# ================================================================
# 输出层
# ================================================================
workflow.add_edge("output_return", "memory_extract")
workflow.add_edge("memory_extract", END)

# 编译
memory_saver = MemorySaver()
aura_workflow = workflow.compile(checkpointer=memory_saver)

logger.info(
    "[LangGraph] AURA 工作流编译完成 | "
    "显式节点: 14 | 并行子任务: 6（图上真实节点）| 条件边: 1 | checkpointer: MemorySaver"
)
