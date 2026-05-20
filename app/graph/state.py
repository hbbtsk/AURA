"""
AURA AgentState — LangGraph 统一状态容器

设计原则：
- 所有节点通过 state 传递数据，不通过局部变量
- total=False 确保所有字段可选，避免 LangGraph 序列化问题
- 每个节点的输入输出都必须是 AgentState 的子集
- structlog 可逐节点打印状态摘要
"""

from typing import TypedDict, List, Dict, Any, Optional
from app.memory.models import IntentResult


class AgentState(TypedDict, total=False):
    """AURA 15 节点状态机的统一状态容器（所有字段可选）"""

    # ================================================================
    # 输入层（由 chat_completion() 组装后注入）
    # ================================================================
    request: Dict[str, Any]           # ChatCompletionRequest 的字典形式
    messages: List[Dict[str, str]]    # 原始消息列表
    session_id: str                   # TAVO 会话 ID
    aura_session_id: str              # AURA 内部会话 ID
    backend: str                      # LLM 后端名称（deepseek/gemini/...）
    model: str                        # 模型名称
    stream: bool                      # 是否流式（LangGraph 内部总为 False）
    temperature: float                # 温度
    max_tokens: Optional[int]         # 最大 token
    x_tavo_debug: Optional[str]       # 调试请求头

    # ================================================================
    # Prompt 编译层（ContextAssemble 节点产出）
    # ================================================================
    decomposed: Optional[Dict[str, Any]]   # PromptDecomposer 输出
    original_system: str                   # 原始 System Prompt
    blocks: List[str]                      # 9 区块列表
    intent_result: Optional[IntentResult]  # IntentTagger 输出
    retrieved_memories: List[str]          # RAG 召回的记忆
    working_memory_text: str               # WORKING_MEMORY 文本
    optimized_system: str                  # 重组后的 System Prompt
    messages_list: List[Dict[str, str]]    # 最终转发的消息列表
    user_name: str                         # 提取的用户名
    has_user_prefix: bool                  # 是否有用户自定义前缀

    # ================================================================
    # 实体 & 关系图谱层（Week 3 扩展）
    # ================================================================
    active_entity_ids: List[str]           # 当前活跃实体
    relationship_subgraph: Optional[Dict]  # BFS 召回的关系子图
    character_situation: str               # 渲染后的 [CHARACTER_SITUATION]

    # ================================================================
    # 并行准备子任务层（LangGraph 真实节点产出）
    # ================================================================
    emotion_analysis: Optional[str]        # 情绪分析结果（EmotionAnalyze 节点产出）
    style_injections: Optional[List[str]]  # 文风注入指令（StyleInjection 节点产出）
    model_dialect_notes: Optional[str]     # 模型方言编译备注（ModelDialectCompiler 节点产出）

    # ================================================================
    # 对话管理层
    # ================================================================
    round_num: int                    # 当前轮次编号
    user_content: str                 # 最后一条 user 消息内容
    tavo_dialogue_messages: List[Dict[str, str]]  # TAVO 发来的对话消息

    # ================================================================
    # LLM 生成层
    # ================================================================
    llm_payload: Dict[str, Any]       # 转发给 LLM 的请求体（stream=False）
    llm_response_content: str         # LLM 生成的完整文本
    llm_reasoning_content: str        # LLM 的思考过程（reasoning_content）
    llm_raw_response: Dict[str, Any]  # LLM 原始 JSON 响应

    # ================================================================
    # 质检层（FormatGuard / OOCCheck / ContentFilter）
    # ================================================================
    format_passed: bool               # FormatGuard 是否通过
    format_reason: str                # 未通过原因
    ooc_passed: bool                  # OOCCheck 是否通过
    ooc_reason: str                   # 未通过原因
    content_passed: bool              # ContentFilter 是否通过
    content_reason: str               # 未通过原因
    retry_count: int                  # 当前重试次数
    max_retries: int                  # 最大重试次数
    retry_strategy: Dict[str, Any]    # 重试策略补丁（RetryStrategy 节点产出）

    # ================================================================
    # 输出层
    # ================================================================
    response: Optional[Any]           # 响应对象占位（不序列化 FastAPI 对象）
    error: Optional[str]              # 错误信息

    # ================================================================
    # 调试 & 可观测性
    # ================================================================
    node_logs: List[Dict[str, Any]]   # 节点执行日志（名称、耗时、状态摘要）
    start_time: float                 # 请求开始时间戳