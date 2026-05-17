"""
AURA 记忆管理器 — 组合式 Facade

底层子模块：
  - SQLiteStore:   原始对话 + 会话 + 动态状态 + 关系图谱
  - FAISSStore:    向量记忆存储 + 语义检索 + 结构化检索
  - EmbeddingService: 本地 bge-small-zh-v1.5 embedding 编码
  - MemorySummarizer: Kimi/DeepSeek 驱动的记忆总结 + 结构化提取

方案 B：AURA 自建记忆数据库
- DeepSeek → 生成（对话主模型）
- Kimi → 总结（记忆提取，便宜模型）
- 每 5 轮调用 Kimi 总结一次，新记忆存入 FAISS
- 每轮根据用户输入语义召回 Top-5（时间加权 RAG）
- 使用本地 bge-small-zh-v1.5 模型生成 embedding（sentence-transformers）
"""
import asyncio
import logging
from typing import List, Optional, Dict, Any

from app.core.config import settings
from app.memory.embedding import EmbeddingService
from app.memory.sqlite_store import SQLiteStore
from app.memory.faiss_store import FAISSStore
from app.memory.summarizer import MemorySummarizer
from app.memory.models import IntentStructure

logger = logging.getLogger("aura.memory")


class MemoryManager:
    """统一记忆管理接口 — 使用 FAISS 做向量检索 + SQLite 做结构化存储"""

    def __init__(self):
        self._embed = EmbeddingService(dimension=512)
        self._sqlite = SQLiteStore(db_path="aura.db")
        self._faiss = FAISSStore(embedding_service=self._embed)
        self._summarizer = MemorySummarizer(faiss_store=self._faiss, sqlite_store=self._sqlite)
        self._initialized = False
        self._summary_lock = asyncio.Lock()

    async def initialize(self):
        """初始化：创建 SQLite 表 + 初始化 FAISS"""
        if self._initialized:
            return
        self._sqlite.init_schema()
        await self._faiss.initialize()
        self._initialized = True
        logger.info("[AURA→记忆] MemoryManager 初始化完成")

    # ============ 委托给 SQLiteStore ============

    async def save_dialogue(self, session_id: str, role: str, content: str, round_number: int):
        """保存单轮对话到 SQLite"""
        await self._sqlite.save_dialogue(session_id, role, content, round_number)

    async def get_recent_messages(self, session_id: str, n: int = 20) -> List[dict]:
        """从 SQLite 读取最近 N 轮对话"""
        return await self._sqlite.get_recent_messages(session_id, n)

    async def get_dialogue_count(self, session_id: str) -> int:
        """获取某会话的对话轮数"""
        return await self._sqlite.get_dialogue_count(session_id)

    async def sync_dialogue_from_tavo(self, session_id: str, tavo_messages: List[dict]):
        """倒序匹配 TAVO 发来的对话与本地数据库，处理用户编辑/撤回操作"""
        await self._sqlite.sync_dialogue_from_tavo(session_id, tavo_messages)

    async def get_or_create_session(self, session_id: str, character_id: str = "", model_name: str = "") -> dict:
        """获取或创建会话"""
        return await self._sqlite.get_or_create_session(session_id, character_id, model_name)

    async def get_round_number(self, session_id: str) -> int:
        """获取当前会话的轮次编号（自动递增）"""
        return await self._sqlite.get_round_number(session_id)

    async def update_dynamic_state(self, session_id: str, entity_name: str, state_json: str):
        """更新动态状态"""
        await self._sqlite.update_dynamic_state(session_id, entity_name, state_json)

    async def get_dynamic_state(self, session_id: str) -> Dict[str, str]:
        """获取会话的所有动态状态"""
        return await self._sqlite.get_dynamic_state(session_id)

    # ============ 委托给 FAISSStore ============

    async def search(self, query: str, top_k: int = 5) -> List[str]:
        """语义检索（兼容旧接口）"""
        return await self._faiss.search(query, top_k)

    async def structured_aware_search(
        self,
        query: str,
        top_k: int = 5,
        query_structure: Optional[IntentStructure] = None,
    ) -> List[str]:
        """意图感知的结构化检索"""
        return await self._faiss.structured_aware_search(query, top_k, query_structure)

    async def add_memory(self, text: str, metadata: Optional[dict] = None):
        """新增单条记忆到 FAISS"""
        await self._faiss.add(text, metadata)

    async def get_memory_count(self) -> int:
        """获取 FAISS 中的记忆总数"""
        return await self._faiss.get_count()

    async def import_from_tavo(self, memories: List[str], session_id: str = "tavo_import"):
        """从 TAVO System Prompt 导入已有记忆到 FAISS"""
        return await self._faiss.import_from_tavo(memories, session_id)

    # ============ 委托给 MemorySummarizer ============

    async def summarize_and_store(self, session_id: str, recent_dialogues: List[dict]):
        """调用 Kimi 总结最近对话 → 提取新记忆 → 结构化字段提取 → 存入 FAISS"""
        if not recent_dialogues:
            return
        async with self._summary_lock:
            await self._summarizer.summarize_and_store(session_id, recent_dialogues)

    async def _get_recent_memories_for_context(self, n: int = 5) -> str:
        """获取最近 N 条记忆作为总结上下文（内部方法，供其他模块使用）"""
        return await self._faiss.get_recent(n)

    async def _extract_structure(self, memory_text: str) -> Optional[IntentStructure]:
        """对单条记忆文本提取结构化字段"""
        return await self._summarizer._extract_structure(memory_text)


# 全局单例
memory_manager = MemoryManager()
