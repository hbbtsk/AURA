"""
AURA 本地 Embedding 服务 — bge-small-zh-v1.5

职责：
  - 懒加载本地 sentence-transformers 模型
  - 提供文本 → 512 维向量的编码接口
  - 异常时降级返回零向量
"""
import os
import time
import asyncio
from typing import List, Optional

import numpy as np
from sentence_transformers import SentenceTransformer

from app.utils.logging import get_logger

logger = get_logger("aura.memory")


class EmbeddingService:
    """本地 embedding 模型封装"""

    def __init__(self, dimension: int = 512):
        self._dimension = dimension
        self._embedding_model: Optional[SentenceTransformer] = None

    def _load_model(self) -> None:
        """懒加载本地 embedding 模型（bge-small-zh-v1.5）"""
        if self._embedding_model is not None:
            return

        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

        base_dir = os.path.dirname(os.path.abspath(__file__))
        local_model_path = os.path.join(base_dir, "..", "..", "models", "BAAI", "bge-small-zh-v1___5")
        alt_model_path = os.path.join(base_dir, "..", "..", "models", "BAAI", "bge-small-zh-v1.5")

        if os.path.exists(local_model_path):
            model_name = local_model_path
        elif os.path.exists(alt_model_path):
            model_name = alt_model_path
        else:
            model_name = "BAAI/bge-small-zh-v1.5"

        logger.info(f"[AURA→向量] 加载本地 embedding 模型: {model_name}")
        start = time.time()
        self._embedding_model = SentenceTransformer(model_name, device="cpu")
        elapsed = time.time() - start
        logger.info(f"[AURA→向量] 模型加载完成 | 耗时: {elapsed:.2f}s | 维度: {self._dimension}")

    async def encode(self, text: str) -> List[float]:
        """使用本地模型生成文本 embedding，异常时返回零向量"""
        try:
            loop = asyncio.get_event_loop()

            def _encode():
                self._load_model()
                embedding = self._embedding_model.encode(text, normalize_embeddings=True)
                return embedding.tolist()

            return await loop.run_in_executor(None, _encode)
        except Exception as e:
            logger.error(f"[AURA→向量] 本地 embedding 失败: {e}")
            return [0.0] * self._dimension

    @property
    def dimension(self) -> int:
        return self._dimension
