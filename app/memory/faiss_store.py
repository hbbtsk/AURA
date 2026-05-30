"""
AURA FAISS 向量记忆存储

职责：
  - FAISS 索引的加载/创建/保存
  - 语义检索（传统 embedding + 时间加权）
  - 结构化感知检索（semantic + structure + time 三阶段）
  - 记忆的添加与持久化
"""
import json
import os
import logging
from datetime import datetime
from typing import List, Optional

import faiss
import numpy as np

from app.core.config import settings
from app.memory.models import IntentStructure, SEARCH_WEIGHTS
from app.memory.embedding import EmbeddingService

logger = logging.getLogger("aura.memory")


class FAISSStore:
    """FAISS 向量记忆存储"""

    def __init__(self, embedding_service: EmbeddingService):
        self._embed = embedding_service
        self.index: Optional[faiss.Index] = None
        self.documents: List[str] = []
        self.metadatas: List[dict] = []
        self._next_seq = 0

    async def initialize(self) -> None:
        """加载已有 FAISS 索引或创建新索引"""
        index_path = "faiss_index.bin"
        meta_path = "faiss_meta.json"

        try:
            if os.path.exists(index_path) and os.path.exists(meta_path):
                self.index = faiss.read_index(index_path)
                with open(meta_path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    self.documents = saved.get("documents", [])
                    self.metadatas = saved.get("metadatas", [])
                    if self.metadatas:
                        max_seq = max(
                            (m.get("insert_seq", 0) for m in self.metadatas),
                            default=-1
                        )
                        self._next_seq = max_seq + 1
                logger.info(
                    f"[AURA→记忆] FAISS 索引已加载，记忆数: {len(self.documents)}, "
                    f"next_seq={self._next_seq}"
                )
            else:
                self.index = faiss.IndexFlatL2(self._embed.dimension)
                logger.info(f"[AURA→记忆] FAISS 索引已创建（维度: {self._embed.dimension}）")
        except Exception as e:
            logger.error(f"[AURA→记忆] FAISS 初始化失败: {e}")
            raise RuntimeError(f"FAISS 初始化失败，请检查 faiss-cpu 是否已正确安装: {e}")

    async def add(self, text: str, metadata: Optional[dict] = None) -> None:
        """新增单条记忆到 FAISS"""
        if not self.index:
            return

        try:
            embedding = await self._embed.encode(text)
            emb_array = np.array([embedding], dtype=np.float32)
            self.index.add(emb_array)

            meta = metadata or {}
            meta["insert_seq"] = self._next_seq
            self._next_seq += 1

            self.documents.append(text)
            self.metadatas.append(meta)
            await self._save()
            logger.info(f"[AURA→记忆] 新增记忆(seq={meta['insert_seq']}): {text}")
        except Exception as e:
            logger.error(f"[AURA→记忆] 新增记忆失败: {e}")

    async def search(self, query: str, top_k: int = 5) -> List[str]:
        """语义检索（兼容旧接口）"""
        return await self.structured_aware_search(query, top_k=top_k)

    async def structured_aware_search(
        self,
        query: str,
        top_k: int = 5,
        query_structure: Optional[IntentStructure] = None,
    ) -> List[str]:
        """
        意图感知的结构化检索（三阶段：粗排→精排→复合评分）
        """
        if not self.index or len(self.documents) == 0:
            logger.warning("[AURA→记忆] FAISS 不可用或为空，返回空结果")
            return []

        try:
            query_emb = await self._embed.encode(query)
            query_array = np.array([query_emb], dtype=np.float32)

            k = min(top_k * 3, len(self.documents))
            distances, indices = self.index.search(query_array, k)

            if len(indices) == 0 or len(indices[0]) == 0:
                return []

            all_seqs = [m.get("insert_seq", 0) for m in self.metadatas]
            min_seq = min(all_seqs)
            max_seq = max(all_seqs)
            seq_range = max(max_seq - min_seq, 1)
            gamma = settings.rag_time_gamma

            sem_w = SEARCH_WEIGHTS["semantic"]
            struct_w = SEARCH_WEIGHTS["structure"]
            time_w = SEARCH_WEIGHTS["time"]

            scored = []
            for i, idx in enumerate(indices[0]):
                if idx < 0 or idx >= len(self.documents):
                    continue

                meta = self.metadatas[idx]
                semantic = 1.0 / (1.0 + distances[0][i])

                structure_score = 0.0
                if query_structure is not None and not query_structure.is_empty():
                    mem_struct_dict = meta.get("structure")
                    if mem_struct_dict:
                        mem_struct = IntentStructure.from_dict(mem_struct_dict)
                        structure_score = await self._calc_structure_similarity(
                            query_structure, mem_struct
                        )

                seq = meta.get("insert_seq", min_seq)
                normalized = (seq - min_seq) / seq_range
                time_score = normalized ** gamma

                if query_structure is not None and not query_structure.is_empty():
                    final_score = (
                        semantic * sem_w
                        + structure_score * struct_w
                        + time_score * time_w
                    )
                else:
                    sem_weight = settings.rag_semantic_weight
                    final_score = (
                        semantic * sem_weight
                        + time_score * (1.0 - sem_weight)
                    )

                scored.append((final_score, idx, semantic, structure_score, time_score))

            scored.sort(key=lambda x: x[0], reverse=True)
            top_results = [self.documents[idx] for score, idx, _, _, _ in scored[:top_k]]

            if settings.debug_mode and scored:
                top_detail = []
                for score, idx, sem, struct, t in scored[:top_k]:
                    doc_preview = self.documents[idx][:60]
                    top_detail.append(
                        f"  [{score:.3f}] sem={sem:.3f} struct={struct:.3f} time={t:.3f} | {doc_preview}"
                    )
                logger.debug(
                    f"[AURA→RAG] 结构化检索 \"{query}\"\n"
                    + "\n".join(top_detail)
                )

            logger.info(
                f"[AURA→RAG] 检索 \"{query}\" → "
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
        """计算两个 IntentStructure 的逐字段加权相似度"""
        text_fields = [
            ("scene_type", 0.20),
            ("action_type", 0.25),
            ("emotional_tone", 0.20),
            ("tension_description", 0.10),
            ("pacing", 0.10),
        ]

        total_weight = sum(w for _, w in text_fields) + 0.15
        weighted_sum = 0.0

        for field_name, weight in text_fields:
            q_val = getattr(qs, field_name, "") or ""
            m_val = getattr(ms, field_name, "") or ""

            if not q_val or not m_val:
                continue

            q_emb = await self._embed.encode(q_val)
            m_emb = await self._embed.encode(m_val)

            sim = sum(a * b for a, b in zip(q_emb, m_emb))
            sim = max(0.0, min(1.0, sim))
            weighted_sum += sim * weight

        q_entities = set(e.strip() for e in qs.entities if e.strip())
        m_entities = set(e.strip() for e in ms.entities if e.strip())

        if q_entities and m_entities:
            intersection = q_entities & m_entities
            union = q_entities | m_entities
            jaccard = len(intersection) / len(union) if union else 0.0
            weighted_sum += jaccard * 0.15

        return weighted_sum / total_weight if total_weight > 0 else 0.0

    async def _save(self) -> None:
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

    async def get_count(self) -> int:
        return len(self.documents)

    async def get_recent(self, n: int = 5) -> str:
        """获取最近 N 条记忆文本（用于总结上下文）"""
        if not self.documents:
            return "（无）"
        try:
            recent = self.documents[-n:]
            return "\n".join([f"- {doc}" for doc in recent])
        except:
            return "（无）"

    async def import_from_tavo(self, memories: List[str], session_id: str = "tavo_import") -> int:
        """从 TAVO System Prompt 导入已有记忆到 FAISS"""
        if not self.index:
            logger.warning("[AURA→记忆] FAISS 不可用，跳过导入")
            return 0

        try:
            seen = set()
            unique_memories = []
            for mem in memories:
                normalized = mem.strip().rstrip("。，.!！?？")
                if normalized and normalized not in seen:
                    seen.add(normalized)
                    unique_memories.append(mem)

            already = set(self.documents)
            unique_memories = [m for m in unique_memories if m not in already]
            if not unique_memories:
                logger.info("[AURA→记忆] 所有 TAVO 记忆均已存在，跳过导入")
                return 0

            imported = 0
            for i, mem in enumerate(unique_memories):
                embedding = await self._embed.encode(mem)
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

                if imported % 10 == 0:
                    await self._save()

            await self._save()
            logger.info(f"[AURA→记忆] 从 TAVO 导入 {imported} 条记忆到 FAISS")
            return imported

        except Exception as e:
            logger.error(f"[AURA→记忆] 导入 TAVO 记忆失败: {e}")
            return 0
