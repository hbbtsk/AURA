"""
AURA LangGraph 工作流 — 图结构真实化重构 v2.0.0

设计原则：
- 并行子任务注册为 LangGraph 真实节点（非 Python 包装器）
- Prompt 拆解从 ContextAssemble 剥离为独立节点
- LLM 调用已抽离到 completions.py，工作流只负责 Prompt 编译
- 每个节点职责单一，接口契约统一

节点清单（9 个显式节点）：
1. InputReceive         → 收输入，解析请求 + 意图标签
2. PromptDecomposer     → 拆解 TAVO 原始 Prompt 为结构化组件
3. EntityExtract        → 从对话中抽取角色/实体（预留）
4. EmotionAnalyze       → 分析用户输入的情绪倾向（预留）
5. MemoryRetrieve       → FAISS 向量检索 + 结构化感知匹配 Top-K
6. StateManager         → 维护角色状态 / 时间线 / dynamic_state
7. StyleInjection       → 注入文风控制指令（预留）
8. ModelDialectCompiler → 模型方言编译（预留，适配不同 LLM 特性）
9. ContextAssemble      → 9 区块 Prompt 组装（核心编译逻辑）

v2.0.0 变更：
- LLMGenerate、OutputReturn、MemoryExtract 节点抽离到 completions.py
- 工作流终点改为 ContextAssemble，产出编译好的 messages_list
- completions.py 直接调用 LLM API（流式/非流式），实现真正的实时流式传输
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

# 工作流终点：ContextAssemble 产出编译好的 messages_list
workflow.add_edge("context_assemble", END)

# 编译
memory_saver = MemorySaver()
aura_workflow = workflow.compile(checkpointer=memory_saver)

logger.info(
    "[LangGraph] AURA 工作流编译完成 | "
    "显式节点: 9 | 并行子任务: 6（图上真实节点）| 条件边: 0 | checkpointer: MemorySaver | "
    "模式: Prompt 编译器（LLM 调用已外置）"
)
