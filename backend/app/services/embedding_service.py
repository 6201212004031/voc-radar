"""text-embedding-v4 向量化服务（批量 + 缓存）.

职责:
- 屏蔽 Model Router 调用细节
- 自动按 EMBEDDING_BATCH_SIZE 批处理
- 基于内容 hash 的内存缓存（同进程内不重复调用）
- 进度回调（便于 SSE 推送）

注意:
- 缓存仅在同一进程内有效（原型够用）；如需跨进程持久化，可后续扩展到 SQLite
- 向量维度由模型决定（text-embedding-v4 默认 1024 维，按实际返回为准）
"""
from __future__ import annotations

import hashlib
import logging
from typing import Callable, Optional

from app.core.config import settings
from app.core.exceptions import EmbeddingError
from app.services.model_router import ModelRouterClient, get_model_router

logger = logging.getLogger(__name__)


ProgressCallback = Callable[[int, int], None]
"""进度回调: (已处理条数, 总条数) -> None"""


class EmbeddingService:
    """向量化服务（批量 + 缓存）.

    使用场景:
        svc = EmbeddingService()
        vectors = await svc.embed(texts, on_progress=lambda d, t: print(d, t))
    """

    def __init__(
        self,
        client: ModelRouterClient | None = None,
        batch_size: int | None = None,
        cache_enabled: bool | None = None,
    ) -> None:
        self.client = client or get_model_router()
        self.batch_size = batch_size or settings.EMBEDDING_BATCH_SIZE
        self.cache_enabled = (
            cache_enabled if cache_enabled is not None else settings.EMBEDDING_CACHE_ENABLED
        )
        # key: sha256(text), value: vector
        self._cache: dict[str, list[float]] = {}
        # 统计
        self._hits = 0
        self._misses = 0

    async def embed(
        self,
        texts: list[str],
        model: str | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> list[list[float]]:
        """批量向量化（带缓存）.

        Args:
            texts: 待向量化的文本列表
            model: 模型名，默认 settings.MODEL_EMBEDDING
            on_progress: 进度回调 (done, total)

        Returns:
            与 texts 等长的向量列表

        Raises:
            EmbeddingError: 向量化失败
        """
        if not texts:
            return []

        model = model or settings.MODEL_EMBEDDING
        total = len(texts)

        # 1. 区分缓存命中 / 未命中
        results: list[list[float] | None] = [None] * total
        to_fetch_idx: list[int] = []
        to_fetch_texts: list[str] = []

        for i, text in enumerate(texts):
            if not text:
                # 空文本占位（避免 API 报错）
                results[i] = []
                continue
            key = self._hash(text)
            if self.cache_enabled and key in self._cache:
                results[i] = self._cache[key]
                self._hits += 1
            else:
                to_fetch_idx.append(i)
                to_fetch_texts.append(text)
                self._misses += 1

        # 2. 批量调用 API（按 batch_size 分批）
        done = total - len(to_fetch_texts)
        if on_progress and done > 0:
            on_progress(done, total)

        if to_fetch_texts:
            fetched_vectors = await self._fetch_in_batches(
                to_fetch_texts, model=model, on_progress=lambda d, _t: on_progress and on_progress(done + d, total)
            )

            # 3. 写回结果 + 缓存
            for idx, text, vec in zip(to_fetch_idx, to_fetch_texts, fetched_vectors):
                results[idx] = vec
                if self.cache_enabled and vec:
                    self._cache[self._hash(text)] = vec

        # 4. 类型断言（确保无 None）
        return [r if r is not None else [] for r in results]

    async def embed_one(self, text: str, model: str | None = None) -> list[float]:
        """单条向量化（便捷方法）.

        Returns:
            向量（float 列表）
        """
        if not text:
            return []
        vecs = await self.embed([text], model=model)
        return vecs[0] if vecs else []

    def clear_cache(self) -> None:
        """清空缓存."""
        self._cache.clear()
        self._hits = 0
        self._misses = 0

    def stats(self) -> dict[str, int]:
        """返回缓存统计."""
        return {
            "cache_size": len(self._cache),
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": (
                round(self._hits / (self._hits + self._misses), 4)
                if (self._hits + self._misses)
                else 0.0
            ),
        }

    # ---------- 内部 ----------
    async def _fetch_in_batches(
        self,
        texts: list[str],
        model: str,
        on_progress: ProgressCallback | None = None,
    ) -> list[list[float]]:
        """按 batch_size 分批调用 model_router.embed."""
        all_vecs: list[list[float]] = []
        n = len(texts)
        for i in range(0, n, self.batch_size):
            batch = texts[i : i + self.batch_size]
            try:
                batch_vecs = await self.client.embed(batch, model=model)
                all_vecs.extend(batch_vecs)
            except EmbeddingError:
                # 上抛让调用方决定是否中止
                raise
            if on_progress:
                on_progress(min(i + self.batch_size, n), n)
        return all_vecs

    @staticmethod
    def _hash(text: str) -> str:
        """计算文本的 SHA256（用作缓存 key）."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------- 全局单例 ----------
_embedding_service: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    """获取全局 EmbeddingService 单例."""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
