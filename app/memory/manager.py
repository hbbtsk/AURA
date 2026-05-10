"""
AURA 记忆管理器 — SQLite（原始对话）+ FAISS（向量记忆）

方案 B：AURA 自建记忆数据库
- DeepSeek → 生成（对话主模型）
- Kimi → 总结（记忆提取，便宜模型）
- 每 5 轮调用 Kimi 总结一次，新记忆存入 FAISS
- 每轮根据用户输入语义召回 Top-5（时间加权 RAG）
- 使用本地 bge-small-zh-v1.5 模型生成 embedding（sentence-transformers）
"""

import asyncio
import json
import logging
import os
import sqlite3
import time
import re
from datetime import datetime
from typing import List, Optional, Dict, Any
from pathlib import Path

import httpx
import numpy as np

from app.config import settings, get_llm_config
from app.memory.models import IntentStructure, STRUCTURE_FIELD_WEIGHTS

logger = logging.getLogger("aura.memory")

import faiss
from sentence_transformers import SentenceTransformer


class MemoryManager:
    """统一记忆管理接口 — 使用 FAISS 做向量检索"""

    def __init__(self):
        self.db_path = "aura.db"
        self.index = None          # FAISS 索引
        self.documents: List[str] = []  # 与索引对应的文档列表
        self.metadatas: List[dict] = [] # 与索引对应的元数据列表
        self._initialized = False
        self._round_counter: Dict[str, int] = {}
        self._summary_lock = asyncio.Lock()
        self._dimension = 512  # bge-small-zh-v1.5 输出 512 维
        self._next_seq = 0     # 单调递增序列号：AURA 生成记忆的时序标记
        self._embedding_model: Optional[SentenceTransformer] = None  # 懒加载本地 embedding 模型

    async def initialize(self):
        """初始化：创建 SQLite 表 + 初始化 FAISS"""
        if self._initialized:
            return

        # 1. 初始化 SQLite
        self._init_sqlite()

        # 2. 初始化 FAISS
        try:
            index_path = "faiss_index.bin"
            meta_path = "faiss_meta.json"
            if os.path.exists(index_path) and os.path.exists(meta_path):
                self.index = faiss.read_index(index_path)
                with open(meta_path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    self.documents = saved.get("documents", [])
                    self.metadatas = saved.get("metadatas", [])
                    # 恢复单调序列号：取已有记忆最大 insert_seq + 1
                    if self.metadatas:
                        max_seq = max(
                            (m.get("insert_seq", 0) for m in self.metadatas),
                            default=-1
                        )
                        self._next_seq = max_seq + 1
                logger.info(f"[AURA→记忆] FAISS 索引已加载，记忆数: {len(self.documents)}, next_seq={self._next_seq}")
            else:
                # 创建空索引（使用 L2 距离）
                self.index = faiss.IndexFlatL2(self._dimension)
                logger.info(f"[AURA→记忆] FAISS 索引已创建（维度: {self._dimension}）")
        except Exception as e:
            logger.error(f"[AURA→记忆] FAISS 初始化失败: {e}")
            raise RuntimeError(f"FAISS 初始化失败，请检查 faiss-cpu 是否已正确安装: {e}")

        self._initialized = True
        logger.info("[AURA→记忆] MemoryManager 初始化完成")

    def _init_sqlite(self):
        """创建 SQLite 表结构"""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # 原始对话存储
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS raw_dialogues (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    round_number INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 会话管理
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    character_id TEXT,
                    model_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 动态状态（痛点4）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS dynamic_state (
                    session_id TEXT NOT NULL,
                    entity_name TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (session_id, entity_name)
                )
            """)

            # 剧情锚点（痛点5）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS plot_anchors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    event_text TEXT NOT NULL,
                    importance REAL DEFAULT 0.5,
                    is_active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 关系图谱（痛点10）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS relationship_graph (
                    session_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    target TEXT NOT NULL,
                    relation_type TEXT,
                    weight REAL DEFAULT 0.0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (session_id, source, target)
                )
            """)

            conn.commit()
            logger.info("[AURA→记忆] SQLite 表结构已就绪")
        finally:
            conn.close()

    # ============ 对话存储 ============

    async def save_dialogue(self, session_id: str, role: str, content: str, round_number: int):
        """保存单轮对话到 SQLite"""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO raw_dialogues (session_id, role, content, round_number) VALUES (?, ?, ?, ?)",
                (session_id, role, content, round_number)
            )
            conn.commit()
        finally:
            conn.close()

    async def get_recent_messages(self, session_id: str, n: int = 20) -> List[dict]:
        """从 SQLite 读取最近 N 轮对话"""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT role, content, round_number FROM raw_dialogues
                   WHERE session_id = ? ORDER BY round_number DESC LIMIT ?""",
                (session_id, n)
            )
            rows = cursor.fetchall()
            return [
                {"role": row[0], "content": row[1], "round_number": row[2]}
                for row in reversed(rows)
            ]
        finally:
            conn.close()

    async def get_dialogue_count(self, session_id: str) -> int:
        """获取某会话的对话轮数"""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(DISTINCT round_number) FROM raw_dialogues WHERE session_id = ?",
                (session_id,)
            )
            return cursor.fetchone()[0] or 0
        finally:
            conn.close()

    # ============ 对话同步（TAVO 编辑/撤回处理） ============

    async def sync_dialogue_from_tavo(self, session_id: str, tavo_messages: List[dict]):
        """
        倒序匹配 TAVO 发来的对话与本地数据库，处理用户编辑/撤回操作。

        核心逻辑：
        1. 从尾部开始逐条比较 content 文本（编辑/撤回总是发生在最近的消息上）
        2. 找到第一个不一致的位置 → 截断数据库 → 用 TAVO 数据覆盖
        3. 只处理 raw_dialogues 表，不影响 FAISS 记忆

        Args:
            session_id: AURA 会话 ID
            tavo_messages: TAVO 发来的 messages[]（最近多轮对话）
                           [{"role":"user","content":"..."}, {"role":"assistant","content":"..."}, ...]
        """
        if not tavo_messages:
            return

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # 1. 读取该 session 的所有原始对话（按 round_number ASC）
            cursor.execute(
                """SELECT id, role, content, round_number FROM raw_dialogues
                   WHERE session_id = ? ORDER BY round_number ASC, id ASC""",
                (session_id,)
            )
            db_rows = cursor.fetchall()
            # db_rows: [(id, role, content, round_number), ...]

            if not db_rows:
                # 数据库为空，直接写入所有 TAVO 消息
                logger.info(f"[AURA→同步] 数据库为空，直接写入 {len(tavo_messages)} 条消息")
                for msg in tavo_messages:
                    cursor.execute(
                        "INSERT INTO raw_dialogues (session_id, role, content, round_number) VALUES (?, ?, ?, ?)",
                        (session_id, msg.get("role", "user"), msg.get("content", ""), 1)
                    )
                conn.commit()
                return

            # 2. 倒序匹配：从尾部开始逐条比较 content
            #    只比较 TAVO 消息数量范围内的部分
            match_count = 0
            min_len = min(len(tavo_messages), len(db_rows))

            for i in range(min_len):
                tavo_idx = len(tavo_messages) - 1 - i   # TAVO 倒序索引
                db_idx = len(db_rows) - 1 - i            # DB 倒序索引

                tavo_content = tavo_messages[tavo_idx].get("content", "").strip()
                db_content = db_rows[db_idx][2].strip()  # db_rows[2] = content

                if tavo_content != db_content:
                    break  # 找到第一个不一致的位置
                match_count += 1

            # 3. 如果全部匹配 → 无需操作
            if match_count == len(tavo_messages) and match_count == len(db_rows):
                logger.debug(f"[AURA→同步] 对话完全一致，无需同步 | 会话: {session_id} | 消息数: {len(db_rows)}")
                return

            # 4. 计算截断点
            #    从尾部开始 match_count 条是匹配的，前面的需要替换
            keep_from_db = match_count  # 数据库保留的尾部条数
            truncate_at = len(db_rows) - keep_from_db  # 截断位置（0-based）

            # 获取截断位置对应的 round_number
            if truncate_at < len(db_rows):
                truncate_round = db_rows[truncate_at][3]  # db_rows[3] = round_number
            else:
                truncate_round = 0

            # 5. 截断数据库：删除 truncate_at 及之后的所有记录
            if truncate_at < len(db_rows):
                cursor.execute(
                    """DELETE FROM raw_dialogues
                       WHERE session_id = ? AND round_number >= ?""",
                    (session_id, truncate_round)
                )
                deleted_count = cursor.rowcount
                logger.info(
                    f"[AURA→同步] 截断数据库 | 会话: {session_id} | "
                    f"从 round {truncate_round} 开始删除 | 删除 {deleted_count} 条 | "
                    f"保留尾部 {keep_from_db} 条"
                )
            else:
                deleted_count = 0

            # 6. 写入 TAVO 的新数据（从截断位置开始）
            #    需要写入的是 tavo_messages 中未匹配的部分
            new_messages = tavo_messages[:len(tavo_messages) - keep_from_db]
            if new_messages:
                # 获取当前最大 round_number
                cursor.execute(
                    "SELECT COALESCE(MAX(round_number), 0) FROM raw_dialogues WHERE session_id = ?",
                    (session_id,)
                )
                current_max_round = cursor.fetchone()[0]

                for i, msg in enumerate(new_messages):
                    round_num = current_max_round + (i // 2) + 1  # user+assistant 算一轮
                    cursor.execute(
                        "INSERT INTO raw_dialogues (session_id, role, content, round_number) VALUES (?, ?, ?, ?)",
                        (session_id, msg.get("role", "user"), msg.get("content", ""), round_num)
                    )

                conn.commit()
                logger.info(
                    f"[AURA→同步] 写入 {len(new_messages)} 条新消息 | "
                    f"会话: {session_id} | 匹配: {match_count}/{min_len} | "
                    f"删除: {deleted_count} | 新增: {len(new_messages)}"
                )
            else:
                logger.info(
                    f"[AURA→同步] 无需写入新消息 | 会话: {session_id} | "
                    f"匹配: {match_count}/{min_len} | 删除: {deleted_count}"
                )

            # 7. 重置轮次计数器，确保后续 get_round_number 基于最新数据
            if session_id in self._round_counter:
                del self._round_counter[session_id]

        except Exception as e:
            logger.error(f"[AURA→同步] 对话同步失败 | 会话: {session_id} | 错误: {e}")
        finally:
            conn.close()

    # ============ FAISS 记忆管理 ============

    def _load_embedding_model(self):
        """懒加载本地 embedding 模型（bge-small-zh-v1.5）

        优先从本地 models/ 目录加载（通过 modelscope 下载），
        如果本地不存在则尝试从 huggingface 在线下载
        """
        if self._embedding_model is None:
            # 设置 HuggingFace 镜像源（国内网络环境）
            os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

            # 本地模型路径（通过 modelscope 下载）
            local_model_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "..", "..", "models", "BAAI", "bge-small-zh-v1___5"
            )
            # 也检查不带特殊字符的路径
            alt_model_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "..", "..", "models", "BAAI", "bge-small-zh-v1.5"
            )

            if os.path.exists(local_model_path):
                model_name = local_model_path
            elif os.path.exists(alt_model_path):
                model_name = alt_model_path
            else:
                model_name = "BAAI/bge-small-zh-v1.5"

            logger.info(f"[AURA→向量] 加载本地 embedding 模型: {model_name}")
            start = time.time()
            # 使用 CPU 设备，避免 torch CUDA 警告
            self._embedding_model = SentenceTransformer(
                model_name,
                device="cpu"
            )
            elapsed = time.time() - start
            logger.info(f"[AURA→向量] 模型加载完成 | 耗时: {elapsed:.2f}s | 维度: {self._dimension}")

    async def _get_embedding(self, text: str) -> List[float]:
        """使用本地 bge-small-zh-v1.5 模型生成文本 embedding

        模型在首次调用时自动下载（~60MB），后续从 huggingface 缓存加载
        纯 CPU 推理，单次约 8-12ms
        """
        try:
            # 在事件循环线程中运行同步模型推理
            # SentenceTransformer.encode() 是 CPU 密集型操作，用 run_in_executor 避免阻塞
            loop = asyncio.get_event_loop()

            def _encode():
                self._load_embedding_model()
                # bge-small-zh-v1.5 需要添加 "为这个句子生成表示以用于检索相关文章：" 前缀以获得最佳效果
                # 但角色扮演场景的语义匹配不需要检索式前缀，直接编码即可
                embedding = self._embedding_model.encode(text, normalize_embeddings=True)
                return embedding.tolist()

            embedding = await loop.run_in_executor(None, _encode)
            return embedding

        except Exception as e:
            logger.error(f"[AURA→向量] 本地 embedding 失败: {e}")
            # 降级：返回零向量
            return [0.0] * self._dimension

    async def import_from_tavo(self, memories: List[str], session_id: str = "tavo_import"):
        """从 TAVO System Prompt 导入已有记忆到 FAISS"""
        if not self.index:
            logger.warning("[AURA→记忆] FAISS 不可用，跳过导入")
            return 0

        try:
            # 去重
            seen = set()
            unique_memories = []
            for mem in memories:
                normalized = mem.strip().rstrip("。，.!！?？")
                if normalized and normalized not in seen:
                    seen.add(normalized)
                    unique_memories.append(mem)

            # 简单去重：跳过已在 documents 中的记忆
            already = set(self.documents)
            unique_memories = [m for m in unique_memories if m not in already]
            if not unique_memories:
                logger.info("[AURA→记忆] 所有 TAVO 记忆均已存在，跳过导入")
                return 0

            # 逐条生成 embedding 并添加
            imported = 0
            for i, mem in enumerate(unique_memories):
                embedding = await self._get_embedding(mem)
                emb_array = np.array([embedding], dtype=np.float32)
                self.index.add(emb_array)
                self.documents.append(mem)
                self.metadatas.append({
                    "source": "tavo_import",
                    "index": i,
                    "insert_seq": self._next_seq,
                    "imported_at": datetime.now().isoformat()
                })
                self._next_seq += 1
                imported += 1

                # 每 10 条保存一次进度
                if imported % 10 == 0:
                    await self._save_faiss()

            await self._save_faiss()
            logger.info(f"[AURA→记忆] 从 TAVO 导入 {imported} 条记忆到 FAISS")
            return imported

        except Exception as e:
            logger.error(f"[AURA→记忆] 导入 TAVO 记忆失败: {e}")
            return 0

    async def search(self, query: str, top_k: int = 5) -> List[str]:
        """
        语义检索（兼容旧接口）
        
        如果 query 是 IntentResult 的 expanded_scene，走 structured_aware_search；
        否则走传统 embedding + 时间加权。
        """
        return await self.structured_aware_search(query, top_k=top_k)

    async def structured_aware_search(
        self,
        query: str,
        top_k: int = 5,
        query_structure: Optional[IntentStructure] = None,
    ) -> List[str]:
        """
        意图感知的结构化检索（v2 核心改进）
        
        三阶段：
        1. 粗排：expanded_scene embedding → FAISS 搜索（Top-K*2 候选）
        2. 精排：逐字段结构化匹配（如果候选有 structure metadata）
        3. 复合评分：semantic×0.3 + structure×0.5 + time×0.2
        
        Args:
            query: 搜索文本（通常是 expanded_scene 或用户输入）
            top_k: 返回条数
            query_structure: 可选的查询结构化字段（来自 IntentTagger），
                            如果提供则用于逐字段匹配；否则只用 semantic + time
        
        Returns:
            排序后的记忆文本列表
        """
        if not self.index or len(self.documents) == 0:
            logger.warning("[AURA→记忆] FAISS 不可用或为空，返回空结果")
            return []

        try:
            # ================================================================
            # 阶段1: 粗排 — embedding 搜索
            # ================================================================
            query_emb = await self._get_embedding(query)
            query_array = np.array([query_emb], dtype=np.float32)

            k = min(top_k * 3, len(self.documents))  # 扩大候选池
            distances, indices = self.index.search(query_array, k)

            if len(indices) == 0 or len(indices[0]) == 0:
                return []

            # 时间归一化
            all_seqs = [m.get("insert_seq", 0) for m in self.metadatas]
            min_seq = min(all_seqs)
            max_seq = max(all_seqs)
            seq_range = max(max_seq - min_seq, 1)
            gamma = settings.rag_time_gamma

            # 权重配置
            sem_w = SEARCH_WEIGHTS["semantic"]    # 0.3
            struct_w = SEARCH_WEIGHTS["structure"]  # 0.5
            time_w = SEARCH_WEIGHTS["time"]         # 0.2

            # ================================================================
            # 阶段2: 精排 — 逐字段结构化匹配
            # ================================================================
            scored = []
            for i, idx in enumerate(indices[0]):
                if idx < 0 or idx >= len(self.documents):
                    continue

                meta = self.metadatas[idx]

                # --- 语义分（L2 → 相似度）---
                semantic = 1.0 / (1.0 + distances[0][i])

                # --- 结构化分（如果双方都有 structure）---
                structure_score = 0.0
                if query_structure is not None and not query_structure.is_empty():
                    mem_struct_dict = meta.get("structure")
                    if mem_struct_dict:
                        mem_struct = IntentStructure.from_dict(mem_struct_dict)
                        structure_score = await self._calc_structure_similarity(
                            query_structure, mem_struct
                        )
                    # 如果记忆没有 structure，结构化分为 0（不惩罚，但也不加分）

                # --- 时间分 ---
                seq = meta.get("insert_seq", min_seq)
                normalized = (seq - min_seq) / seq_range
                time_score = normalized ** gamma

                # --- 复合评分 ---
                # 如果 query 没有 structure，退化为 semantic + time 两维
                if query_structure is not None and not query_structure.is_empty():
                    final_score = (
                        semantic * sem_w
                        + structure_score * struct_w
                        + time_score * time_w
                    )
                else:
                    # 退化：只用语义 + 时间
                    sem_weight = settings.rag_semantic_weight
                    final_score = (
                        semantic * sem_weight
                        + time_score * (1.0 - sem_weight)
                    )

                scored.append((final_score, idx, semantic, structure_score, time_score))

            # ================================================================
            # 阶段3: 排序 + 日志
            # ================================================================
            scored.sort(key=lambda x: x[0], reverse=True)
            top_results = [self.documents[idx] for score, idx, _, _, _ in scored[:top_k]]

            # 详细日志（调试用）
            if settings.debug_mode and scored:
                top_detail = []
                for score, idx, sem, struct, t in scored[:top_k]:
                    doc_preview = self.documents[idx][:60]
                    top_detail.append(
                        f"  [{score:.3f}] sem={sem:.3f} struct={struct:.3f} time={t:.3f} | {doc_preview}"
                    )
                logger.debug(
                    f"[AURA→RAG] 结构化检索 \"{query[:40]}...\"\n"
                    + "\n".join(top_detail)
                )

            logger.info(
                f"[AURA→RAG] 检索 \"{query[:40]}...\" → "
                f"召回 {len(top_results)} 条 (共 {len(self.documents)} 条, "
                f"query_struct={'有' if query_structure and not query_structure.is_empty() else '无'})"
            )
            return top_results

        except Exception as e:
            logger.error(f"[AURA→RAG] 结构化检索失败: {e}")
            return []

    async def _calc_structure_similarity(
        self,
        qs: IntentStructure,
        ms: IntentStructure,
    ) -> float:
        """
        计算两个 IntentStructure 的逐字段加权相似度
        
        策略：
        - 文本字段（scene_type, action_type, emotional_tone, tension_description, pacing）：
          各自生成 embedding → cosine 相似度
        - entities 字段：Jaccard 集合相似度（角色名是 proper noun，embedding 不稳定）
        
        Returns:
            0.0 ~ 1.0 的加权相似度
        """
        # 文本字段列表（需要 embedding 匹配）
        text_fields = [
            ("scene_type", 0.20),
            ("action_type", 0.25),
            ("emotional_tone", 0.20),
            ("tension_description", 0.10),
            ("pacing", 0.10),
        ]

        total_weight = sum(w for _, w in text_fields) + 0.15  # entities weight
        weighted_sum = 0.0

        # --- 文本字段：逐字段 embedding 相似度 ---
        for field_name, weight in text_fields:
            q_val = getattr(qs, field_name, "") or ""
            m_val = getattr(ms, field_name, "") or ""

            if not q_val or not m_val:
                # 任一为空，该字段不贡献分数
                continue

            # 各自生成 embedding → cosine 相似度
            q_emb = await self._get_embedding(q_val)
            m_emb = await self._get_embedding(m_val)

            # cosine 相似度（向量已归一化，dot = cosine）
            sim = sum(a * b for a, b in zip(q_emb, m_emb))
            # 限制在 [0, 1] 范围
            sim = max(0.0, min(1.0, sim))

            weighted_sum += sim * weight

        # --- entities 字段：Jaccard 集合相似度 ---
        q_entities = set(e.strip() for e in qs.entities if e.strip())
        m_entities = set(e.strip() for e in ms.entities if e.strip())

        if q_entities and m_entities:
            intersection = q_entities & m_entities
            union = q_entities | m_entities
            jaccard = len(intersection) / len(union) if union else 0.0
            weighted_sum += jaccard * 0.15  # entities weight
        elif not q_entities and not m_entities:
            # 双方都无实体，该字段不扣分
            pass
        # 一方有实体一方无，得 0 分

        # 归一化到 [0, 1]
        return weighted_sum / total_weight if total_weight > 0 else 0.0

    async def add_memory(self, text: str, metadata: Optional[dict] = None):
        """新增单条记忆到 FAISS，自动分配单调 insert_seq"""
        if not self.index:
            return

        try:
            embedding = await self._get_embedding(text)
            emb_array = np.array([embedding], dtype=np.float32)
            self.index.add(emb_array)

            meta = metadata or {}
            # 分配单调递增序列号作为时间代理
            meta["insert_seq"] = self._next_seq
            self._next_seq += 1

            self.documents.append(text)
            self.metadatas.append(meta)

            await self._save_faiss()
            logger.info(f"[AURA→记忆] 新增记忆(seq={meta['insert_seq']}): {text[:80]}...")
        except Exception as e:
            logger.error(f"[AURA→记忆] 新增记忆失败: {e}")

    async def get_memory_count(self) -> int:
        """获取 FAISS 中的记忆总数"""
        return len(self.documents)

    async def _save_faiss(self):
        """保存 FAISS 索引和元数据到磁盘"""
        try:
            if self.index:
                faiss.write_index(self.index, "faiss_index.bin")
            with open("faiss_meta.json", "w", encoding="utf-8") as f:
                json.dump({
                    "documents": self.documents,
                    "metadatas": self.metadatas
                }, f, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"[AURA→记忆] 保存 FAISS 索引失败: {e}")

    # ============ LLM 记忆总结 ============

    async def summarize_and_store(self, session_id: str, recent_dialogues: List[dict]):
        """调用 Kimi 总结最近对话 → 提取新记忆 → 结构化字段提取 → 存入 FAISS"""
        if not recent_dialogues:
            return

        async with self._summary_lock:
            try:
                dialogue_text = self._format_dialogue_for_summary(recent_dialogues)
                existing_memories = await self._get_recent_memories_for_context(5)

                summary_prompt = f"""你是一个角色扮演记忆提取助手。请分析以下对话，提取需要长期记住的关键信息。

提取要求：
1. 只提取**新出现的、重要的**信息（角色关系变化、重要事件、情感转折、承诺誓言等）
2. 不要重复已有记忆中的内容
3. 每条记忆用一段简短而生动的叙述描写，包含场景感（地点、氛围、关键动作/台词）
4. 如果本轮对话没有值得长期记住的内容，返回空列表

输出格式：
请以 JSON 数组格式返回新记忆列表，例如：
[
  "信标学院宿舍。夕阳斜照进窗户，Ruby转身看向Yang，银色的眼睛里闪烁着坚定：'我绝对不会丢下你的。'",
  "图书馆二楼。Weiss和Blake因为战术分歧发生了激烈争执，气氛一度十分紧张。"
]
如果没有新记忆，返回 []

已有记忆（供参考，避免重复）：
{existing_memories}

最近对话：
{dialogue_text}
"""

                kimi_config = get_llm_config("kimi", scene="summary")
                new_memories = await self._call_llm_for_summary(
                    kimi_config, summary_prompt
                )

                if new_memories:
                    for mem in new_memories:
                        # Step 3: 对每条新记忆提取结构化字段（用于后续逐字段 embedding 软匹配）
                        structure = await self._extract_structure(mem)

                        metadata = {
                            "source": "aura_summary",
                            "session_id": session_id,
                            "summarized_at": datetime.now().isoformat(),
                        }

                        # 如果成功提取到结构化字段，存入 metadata
                        if structure and not structure.is_empty():
                            metadata["structure"] = structure.to_dict()
                            logger.debug(
                                f"[AURA→总结] 记忆结构化字段: "
                                f"scene={structure.scene_type}, "
                                f"action={structure.action_type}, "
                                f"emotion={structure.emotional_tone}"
                            )

                        await self.add_memory(mem, metadata)
                    logger.info(f"[AURA→总结] Kimi 提取了 {len(new_memories)} 条新记忆（含结构化字段）")
                else:
                    logger.info("[AURA→总结] Kimi 未提取到新记忆")

            except Exception as e:
                logger.error(f"[AURA→总结] 记忆总结失败: {e}")

    async def _extract_structure(self, memory_text: str) -> Optional[IntentStructure]:
        """
        对单条记忆文本提取结构化字段（scene_type, action_type, emotional_tone 等）

        使用轻量 LLM（Kimi），与 IntentTagger 复用同一 scene="intent" 配置。
        提取失败时返回 None，不影响主流程。
        """
        try:
            llm_config = get_llm_config("kimi", scene="intent")
            if not llm_config or not llm_config.api_key:
                # 如果 Kimi 未配置，尝试用 DeepSeek
                llm_config = get_llm_config("deepseek", scene="intent")
                if not llm_config or not llm_config.api_key:
                    logger.debug("[AURA→总结] 无可用 LLM 配置，跳过结构化字段提取")
                    return None

            system_prompt = """你是一个角色扮演场景的结构化分析助手。
分析以下记忆文本，提取 6 个结构化字段，以 JSON 格式输出（不要解释）：

{
  "scene_type": "场景类型（如'宿舍私聊'、'战斗'、'谈判'）",
  "action_type": "核心行为模式（如'用点烟打破沉默'）",
  "emotional_tone": "情绪基调（如'压抑中寻求突破'）",
  "tension_description": "用自然语言描述张力状态（如'表面平静下的暗流涌动'）",
  "entities": ["涉及角色名列表"],
  "pacing": "节奏感（如'停顿后的小动作'）"
}

如果某个字段无法推断，用空字符串""代替。"""

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {llm_config.api_key}"
            }

            payload = {
                "model": llm_config.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"记忆文本：{memory_text}"}
                ],
                "temperature": llm_config.temperature,
                "max_tokens": llm_config.max_tokens,
            }

            async with httpx.AsyncClient(timeout=httpx.Timeout(llm_config.timeout)) as client:
                response = await client.post(
                    f"{llm_config.base_url}/chat/completions",
                    headers=headers,
                    json=payload
                )

                if response.status_code != 200:
                    logger.warning(
                        f"[AURA→总结] 结构化提取 LLM 调用失败: "
                        f"{response.status_code}"
                    )
                    return None

                result = response.json()
                content = result["choices"][0]["message"]["content"]

                # 解析 JSON（处理可能的 markdown 代码块包裹）
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()

                data = json.loads(content)
                structure = IntentStructure(
                    scene_type=data.get("scene_type", ""),
                    action_type=data.get("action_type", ""),
                    emotional_tone=data.get("emotional_tone", ""),
                    tension_description=data.get("tension_description", ""),
                    entities=data.get("entities", []),
                    pacing=data.get("pacing", ""),
                )

                return structure

        except httpx.TimeoutException:
            logger.debug("[AURA→总结] 结构化提取超时，跳过")
            return None
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.debug(f"[AURA→总结] 结构化提取 JSON 解析失败: {e}")
            return None
        except Exception as e:
            logger.debug(f"[AURA→总结] 结构化提取异常: {e}")
            return None

    def _format_dialogue_for_summary(self, dialogues: List[dict]) -> str:
        """将对话列表格式化为总结用的文本"""
        lines = []
        for d in dialogues:
            role = d.get("role", "unknown")
            content = d.get("content", "")
            if len(content) > 500:
                content = content[:500] + "..."
            lines.append(f"[{role}] {content}")
        return "\n".join(lines)

    async def _get_recent_memories_for_context(self, n: int = 5) -> str:
        """获取最近 N 条记忆作为总结上下文"""
        if not self.documents:
            return "（无）"
        try:
            recent = self.documents[-n:]
            return "\n".join([f"- {doc}" for doc in recent])
        except:
            return "（无）"

    async def _call_llm_for_summary(self, llm_config, prompt: str) -> List[str]:
        """调用 LLM 进行记忆总结"""
        if not llm_config or not llm_config.api_key:
            logger.warning("[AURA→总结] Kimi 未配置，跳过总结")
            return []

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {llm_config.api_key}"
        }

        payload = {
            "model": llm_config.model,
            "messages": [
                {"role": "system", "content": "你是一个记忆提取助手，只输出 JSON 数组。"},
                {"role": "user", "content": prompt}
            ],
            "temperature": llm_config.temperature,
            "max_tokens": llm_config.max_tokens
        }

        async with httpx.AsyncClient(timeout=httpx.Timeout(llm_config.timeout)) as client:
            response = await client.post(
                f"{llm_config.base_url}/chat/completions",
                headers=headers,
                json=payload
            )

            if response.status_code != 200:
                logger.error(f"[AURA→总结] LLM 调用失败: {response.status_code} {response.text[:200]}")
                return []

            data = response.json()
            content = data["choices"][0]["message"]["content"].strip()

            try:
                if content.startswith("["):
                    memories = json.loads(content)
                else:
                    json_match = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', content, re.DOTALL)
                    if json_match:
                        memories = json.loads(json_match.group(1))
                    else:
                        logger.warning(f"[AURA→总结] 无法解析 LLM 输出: {content[:200]}")
                        return []

                if isinstance(memories, list):
                    return [str(m) for m in memories if m]
                return []

            except json.JSONDecodeError as e:
                logger.warning(f"[AURA→总结] JSON 解析失败: {e}, 原始内容: {content[:200]}")
                return []

    # ============ 会话管理 ============

    async def get_or_create_session(self, session_id: str, character_id: str = "", model_name: str = "") -> dict:
        """获取或创建会话"""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
            row = cursor.fetchone()

            if row:
                return {"id": row[0], "character_id": row[1], "model_name": row[2], "created_at": row[3]}

            cursor.execute(
                "INSERT INTO sessions (id, character_id, model_name) VALUES (?, ?, ?)",
                (session_id, character_id, model_name)
            )
            conn.commit()
            return {"id": session_id, "character_id": character_id, "model_name": model_name}

        finally:
            conn.close()

    async def get_round_number(self, session_id: str) -> int:
        """获取当前会话的轮次编号（自动递增）"""
        if session_id not in self._round_counter:
            count = await self.get_dialogue_count(session_id)
            self._round_counter[session_id] = count
        self._round_counter[session_id] += 1
        return self._round_counter[session_id]

    # ============ 状态管理（痛点4骨架） ============

    async def update_dynamic_state(self, session_id: str, entity_name: str, state_json: str):
        """更新动态状态"""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT OR REPLACE INTO dynamic_state (session_id, entity_name, state_json, updated_at)
                   VALUES (?, ?, ?, CURRENT_TIMESTAMP)""",
                (session_id, entity_name, state_json)
            )
            conn.commit()
        finally:
            conn.close()

    async def get_dynamic_state(self, session_id: str) -> Dict[str, str]:
        """获取会话的所有动态状态"""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT entity_name, state_json FROM dynamic_state WHERE session_id = ?",
                (session_id,)
            )
            rows = cursor.fetchall()
            return {row[0]: row[1] for row in rows}
        finally:
            conn.close()


# 全局单例
memory_manager = MemoryManager()