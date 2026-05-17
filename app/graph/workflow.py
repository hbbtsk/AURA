"""
AURA LangGraph 工作流 — 9 显式节点 + 6 并行子任务

设计原则：
- 每个节点只调用已有业务代码，不修改原有逻辑
- 原有 completions.py 中的 Prompt 编译 / RAG / LLM 调用逻辑，
  在 ContextAssemble 节点中完整保留（复制粘贴，不抽取）
- 当前为 v0.8.2 骨架：mock 节点直接返回空值，真实逻辑后续填充
- 质检失败后通过条件边自动重试 LLMGenerate

节点清单（10个显式节点 + 6个并行子任务）：
1. InputReceive         → 收输入，解析请求
2. ParallelPreparation  → 并行：EntityExtract + EmotionAnalyze + MemoryRetrieve + StateManager + StyleInjection + ModelDialectCompiler
3. ContextAssemble      → Prompt 区块化重组（已真实化）
4. LLMGenerate          → LLM 生成（已真实化，非流式）
5. FormatGuard          → 格式质检（mock，默认通过）
6. OOCCheck             → 人设质检（mock，默认通过）
7. ContentFilter        → 内容质检（mock，默认通过）
8. OutputReturn         → 构建响应返回
9. MemoryExtract        → 保存对话 + 触发总结（已真实化）
"""

import asyncio
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from app.graph.state import AgentState
from app.utils import get_logger

from app.graph.nodes import (
    # --- 输入层：接收 & 理解用户输入 ---
    input_receive_node,             # 接收 TAVO 请求，提取用户名、解析意图标签
    entity_extract_node,            # 从对话中抽取角色/实体（预留）
    emotion_analyze_node,           # 分析用户输入的情绪倾向（预留）

    # --- 记忆层：记忆检索 ---
    memory_retrieve_node,           # FAISS 向量检索 + 结构化感知匹配 Top-K

    # --- 状态 & 风格层：角色状态维护 & Prompt 编译 ---
    state_manager_node,             # 维护角色状态 / 时间线 / dynamic_state
    style_injection_node,           # 注入文风控制指令（预留）
    model_dialect_compiler_node,    # 模型方言编译（预留，适配不同 LLM 特性）
    context_assemble_node,          # 9 区块 Prompt 组装（核心编译逻辑）

    # --- LLM 生成层：调用大模型 ---
    llm_generate_node,              # 调用 LLM 后端生成回复（httpx 非流式）

    # --- 质检层：多级内容过滤（并行） ---
    parallel_quality_check_node,    # 并行执行 FormatGuard + OOCCheck + ContentFilter

    # --- 输出层：返回 & 记忆固化 ---
    output_return_node,             # 组装最终响应，写入 state["response"]
    memory_extract_node,            # 提取本轮对话要点，写入 FAISS + SQLite

    # --- 条件边：质检失败时重试 ---
    should_retry_after_check,       # 判断是否需要回退到 ModelDialectCompiler 重试
)

logger = get_logger("aura-graph")


# ================================================================
# 并行准备节点：生成前所有独立任务并行执行
# ================================================================
async def parallel_preparation_node(state: AgentState) -> AgentState:
    """
    并行执行生成前的所有准备节点。

    这些节点之间无依赖，各自读写 state 中不同的 key，
    因此可以并行执行，减少总延迟。
    """
    t0 = time.time()

    # 传入独立拷贝，避免节点间通过可变对象互相干扰
    base_state = dict(state)
    base_state.setdefault("node_logs", [])

    tasks = [
        entity_extract_node(base_state),
        emotion_analyze_node(base_state),
        memory_retrieve_node(base_state),
        state_manager_node(base_state),
        style_injection_node(base_state),
        model_dialect_compiler_node(base_state),
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    merged = dict(state)
    for result in results:
        if isinstance(result, Exception):
            logger.warning(f"[ParallelPreparation] 子任务失败: {result}")
            continue
        # 合并各节点返回的字段（排除 node_logs，由本节点统一记录）
        for key, value in result.items():
            if key != "node_logs":
                merged[key] = value

    # 统一记录并行节点耗时
    elapsed = (time.time() - t0) * 1000
    logs = merged.get("node_logs", [])
    logs.append({
        "node": "ParallelPreparation",
        "elapsed_ms": round(elapsed, 1),
        "summary": "entity+emotion+memory+state+style+dialect 并行完成",
    })
    merged["node_logs"] = logs

    logger.info(f"[ParallelPreparation] 并行准备完成 | 耗时: {elapsed:.1f}ms")
    return merged


# ================================================================
# 构建 StateGraph
# ================================================================

workflow = StateGraph(AgentState)

# 注册所有节点
workflow.add_node("input_receive", input_receive_node)
workflow.add_node("parallel_preparation", parallel_preparation_node)
workflow.add_node("context_assemble", context_assemble_node)
workflow.add_node("llm_generate", llm_generate_node)
workflow.add_node("parallel_quality_check", parallel_quality_check_node)
workflow.add_node("output_return", output_return_node)
workflow.add_node("memory_extract", memory_extract_node)

# 设置入口
workflow.set_entry_point("input_receive")

# 主链路：InputReceive → 并行准备 → ContextAssemble → LLMGenerate → 质检链 → Output → MemoryExtract → END
workflow.add_edge("input_receive", "parallel_preparation")
workflow.add_edge("parallel_preparation", "context_assemble")
workflow.add_edge("context_assemble", "llm_generate")
workflow.add_edge("llm_generate", "parallel_quality_check")

# 条件边：并行质检后 → 通过则 OutputReturn，不通过则回退到并行准备重试
workflow.add_conditional_edges(
    "parallel_quality_check",
    should_retry_after_check,
    {
        "output_return": "output_return",
        "retry": "parallel_preparation",
    },
)

# OutputReturn → MemoryExtract → END
workflow.add_edge("output_return", "memory_extract")
workflow.add_edge("memory_extract", END)

# 编译
# checkpointer: 内存级别状态持久化（开发用），生产环境可换 RedisSaver
memory_saver = MemorySaver()
aura_workflow = workflow.compile(checkpointer=memory_saver)

logger.info("[LangGraph] AURA 工作流编译完成 | 显式节点: 7 | 并行子任务: 9 | checkpointer: MemorySaver")
