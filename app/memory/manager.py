"""
AURA 记忆管理器 — SQLite（原始对话）+ FAISS（向量记忆）

方案 B：AURA 自建记忆数据库
- DeepSeek → 生成（对话主模型）
- Kimi → 总结（记忆提取，便宜模型）
- 每 5 轮调用 Kimi 总结一次，新记忆存入 FAISS
- 每轮根据用户输入语义召回 Top-5（时间加权 RAG）
- 使用 LLM API 生成 embedding（无需本地模型）
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

logger = logging.getLogger("aura.memory")

import faiss


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
        self._dimension = 1536  # Kimi text-embedding-v2 / DeepSeek text-embedding-v2 均为 1536 维
        self._next_seq = 0     # 单调递增序列号：AURA 生成记忆的时序标记

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

    # ============ FAISS 记忆管理 ============

    async def _get_embedding(self, text: str) -> List[float]:
        """使用 LLM API 生成文本 embedding

        优先使用 Kimi（便宜），回退 DeepSeek
        如果都不可用，返回随机向量（降级）
        """
        # 尝试 Kimi → DeepSeek 依次尝试
        for provider in ["kimi", "deepseek"]:
            try:
                llm_config = get_llm_config(provider)
            except Exception:
                logger.debug(f"[AURA→向量] {provider} 配置不可用，跳过")
                continue

            if not llm_config or not llm_config.api_key:
                continue

            try:
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {llm_config.api_key}"
                }

                # Kimi 使用独立的 embedding API
                if provider == "kimi":
                    embed_url = "https://api.moonshot.cn/v1/embeddings"
                    payload = {
                        "model": "text-embedding-v2",
                        "input": text
                    }
                else:
                    # DeepSeek embedding
                    embed_url = f"{llm_config.base_url.rstrip('/')}/embeddings"
                    payload = {
                        "model": "text-embedding-v2",
                        "input": text
                    }

                async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                    response = await client.post(embed_url, headers=headers, json=payload)

                if response.status_code == 200:
                    data = response.json()
                    embedding = data["data"][0]["embedding"]
                    return embedding
                else:
                    logger.debug(f"[AURA→向量] {provider} embedding API 返回 {response.status_code}: {response.text[:100]}")
                    continue

            except Exception as e:
                logger.debug(f"[AURA→向量] {provider} embedding 失败: {e}")
                continue

        # 降级：返回零向量
        logger.warning("[AURA→向量] 所有 embedding API 均不可用，返回零向量")
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
        """语义检索：用 query 生成 embedding → FAISS 搜索 → 时间加权重排"""
        if not self.index or len(self.documents) == 0:
            logger.warning("[AURA→记忆] FAISS 不可用或为空，返回空结果")
            return []

        try:
            # 生成 query 的 embedding
            query_emb = await self._get_embedding(query)
            query_array = np.array([query_emb], dtype=np.float32)

            # FAISS 搜索：召回候选池（top_k * 2）
            k = min(top_k * 2, len(self.documents))
            distances, indices = self.index.search(query_array, k)

            if len(indices) == 0 or len(indices[0]) == 0:
                return []

            # 动态时间归一化：基于当前全量数据的 insert_seq 范围
            all_seqs = [m.get("insert_seq", 0) for m in self.metadatas]
            min_seq = min(all_seqs)
            max_seq = max(all_seqs)
            seq_range = max(max_seq - min_seq, 1)

            gamma = settings.rag_time_gamma
            semantic_weight = settings.rag_semantic_weight
            time_weight_base = 1.0 - semantic_weight

            scored = []
            for i, idx in enumerate(indices[0]):
                if idx < 0 or idx >= len(self.documents):
                    continue
                # L2 距离 → 相似度（越大越相似）
                semantic = 1.0 / (1.0 + distances[0][i])
                meta = self.metadatas[idx]
                seq = meta.get("insert_seq", min_seq)
                # 动态归一化 + 幂次增强（gamma）
                normalized = (seq - min_seq) / seq_range
                time_weight = normalized ** gamma
                final_score = semantic * semantic_weight + time_weight * time_weight_base
                scored.append((final_score, idx))

            # 按分数降序排列，取 Top-K
            scored.sort(key=lambda x: x[0], reverse=True)
            top_results = [self.documents[idx] for score, idx in scored[:top_k]]

            logger.info(
                f"[AURA→RAG] 检索 \"{query[:50]}...\" → "
                f"召回 {len(top_results)} 条 (共 {len(self.documents)} 条, "
                f"seq范围[{min_seq},{max_seq}], γ={gamma})"
            )
            return top_results

        except Exception as e:
            logger.error(f"[AURA→RAG] 检索失败: {e}")
            return []

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
        """调用 Kimi 总结最近对话 → 提取新记忆 → 存入 FAISS"""
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

                kimi_config = get_llm_config("kimi")
                new_memories = await self._call_llm_for_summary(
                    kimi_config, summary_prompt
                )

                if new_memories:
                    for mem in new_memories:
                        await self.add_memory(mem, {
                            "source": "aura_summary",
                            "session_id": session_id,
                            "summarized_at": datetime.now().isoformat(),
                        })
                    logger.info(f"[AURA→总结] Kimi 提取了 {len(new_memories)} 条新记忆")
                else:
                    logger.info("[AURA→总结] Kimi 未提取到新记忆")

            except Exception as e:
                logger.error(f"[AURA→总结] 记忆总结失败: {e}")

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
            "max_tokens": 2048
        }

        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
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