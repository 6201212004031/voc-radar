"""Stage 3: 向量化差评 + 聚类 + 代表性评论标记.

职责:
1. 取项目下所有差评（is_negative=true）
2. 调用 EmbeddingService 批量向量化（带缓存）
3. 调用 ClusterService 做 K-Means 聚类（k=8-15，silhouette 选最优）
4. 计算每条评论的代表性评分（helpful_votes * 0.6 + body_length * 0.4）
5. 每簇按代表性评分取 Top N 标记 is_representative=True
6. 更新 reviews.cluster_id 与 reviews.is_representative

输入: project_id
输出: ClusterStageResult 统计
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import select, update

from app.core.config import settings
from app.core.exceptions import EmbeddingError, ClusterError, StageError
from app.core.logging import get_logger
from app.models.database import get_session
from app.models.schemas import Project, Review
from app.services.cluster_service import (
    ClusterResult,
    cluster_reviews,
    compute_representative_score,
    select_representative_indices,
)
from app.services.embedding_service import EmbeddingService, get_embedding_service
from app.utils.text import combine_review_text

logger = get_logger(__name__)


@dataclass
class ClusterStageResult:
    """s3 聚类阶段结果."""

    negative_count: int = 0
    """差评总数"""

    embedded_count: int = 0
    """实际向量化的条数"""

    cluster_k: int = 0
    """最终簇数"""

    silhouette_score: float = 0.0
    """最优 silhouette 分数"""

    fell_back: bool = False
    """是否触发了降级"""

    fallback_reason: str = ""

    representative_count: int = 0
    """代表性评论标记条数"""

    cluster_sizes: dict[int, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "negative_count": self.negative_count,
            "embedded_count": self.embedded_count,
            "cluster_k": self.cluster_k,
            "silhouette_score": float(self.silhouette_score),
            "fell_back": self.fell_back,
            "fallback_reason": self.fallback_reason,
            "representative_count": self.representative_count,
            "cluster_sizes": {int(k): int(v) for k, v in self.cluster_sizes.items()},
        }


def run_s3_cluster(
    project_id: str,
    *,
    embedding_service: EmbeddingService | None = None,
    k_min: int | None = None,
    k_max: int | None = None,
) -> ClusterStageResult:
    """执行 s3_cluster 阶段（同步入口，内部调度异步向量化）.

    Args:
        project_id: 项目 ID
        embedding_service: 注入的 EmbeddingService（测试用）
        k_min: K-Means 最小簇数
        k_max: 最大簇数

    Returns:
        ClusterStageResult

    Raises:
        StageError: 项目不存在 / 无差评 / 向量化失败 / 聚类失败
    """
    logger.info("[s3_cluster] 开始 project_id=%s", project_id)
    result = ClusterStageResult()

    # 1. 校验项目 + 拉取差评
    with get_session() as session:
        project = session.get(Project, project_id)
        if project is None:
            raise StageError(
                "s3_cluster",
                f"项目不存在: {project_id}",
                code=1001,
                recoverable=False,
            )

        reviews = (
            session.execute(
                select(Review)
                .where(Review.project_id == project_id)
                .where(Review.is_negative.is_(True))
                .order_by(Review.helpful_votes.desc())
            )
            .scalars()
            .all()
        )
        result.negative_count = len(reviews)

    if result.negative_count == 0:
        raise StageError(
            "s3_cluster",
            "项目无差评可聚类（is_negative=true 的评论为 0）",
            code=3002,
            recoverable=False,
        )

    if result.negative_count < 2:
        raise StageError(
            "s3_cluster",
            f"差评数 {result.negative_count} 过少，无法聚类",
            code=3002,
            recoverable=False,
        )

    logger.info("[s3_cluster] 差评数=%d", result.negative_count)

    # 2. 构造向量化输入
    review_ids: list[str] = [r.id for r in reviews]
    texts: list[str] = [
        combine_review_text(r.title, r.body) for r in reviews
    ]
    helpful_votes: list[int] = [r.helpful_votes or 0 for r in reviews]
    body_lengths: list[int] = [len(r.body or "") for r in reviews]

    # 3. 向量化
    embedding_svc = embedding_service or get_embedding_service()
    try:
        vectors = asyncio.run(
            embedding_svc.embed(
                texts,
                on_progress=lambda d, t: logger.debug(
                    "[s3_cluster] 向量化进度 %d/%d", d, t
                ),
            )
        )
        result.embedded_count = len(vectors)
    except EmbeddingError as e:
        raise StageError(
            "s3_cluster",
            f"向量化失败: {e.message}",
            code=3001,
            cause=e,
            recoverable=False,
        ) from e

    if result.embedded_count != result.negative_count:
        logger.warning(
            "[s3_cluster] 向量数 %d != 差评数 %d",
            result.embedded_count,
            result.negative_count,
        )

    # 4. 聚类
    try:
        cluster_result: ClusterResult = cluster_reviews(
            vectors=vectors,
            k_min=k_min,
            k_max=k_max,
        )
    except ClusterError as e:
        raise StageError(
            "s3_cluster",
            f"聚类失败: {e.message}",
            code=3002,
            cause=e,
            recoverable=False,
        ) from e

    result.cluster_k = cluster_result.k
    result.silhouette_score = cluster_result.silhouette_score
    result.fell_back = cluster_result.fell_back
    result.fallback_reason = cluster_result.fallback_reason
    result.cluster_sizes = cluster_result.cluster_sizes

    # 5. 计算代表性评分 + 选每簇 Top N
    rep_scores = compute_representative_score(helpful_votes, body_lengths)
    representative_indices: set[int] = set()
    for cluster_id in range(cluster_result.k):
        top_idx = select_representative_indices(
            cluster_labels=cluster_result.labels,
            scores=rep_scores,
            cluster_id=cluster_id,
        )
        representative_indices.update(top_idx)

    result.representative_count = len(representative_indices)

    # 6. 写回 reviews 表
    # 先重置（防止重复执行时残留）
    with get_session() as session:
        session.execute(
            update(Review)
            .where(Review.project_id == project_id)
            .where(Review.is_negative.is_(True))
            .values(cluster_id=None, is_representative=False)
        )
        session.commit()

    # 逐条更新（仅更新差评）
    labels = cluster_result.labels.tolist()
    with get_session() as session:
        for i, review_id in enumerate(review_ids):
            cluster_id = int(labels[i])
            is_rep = i in representative_indices
            session.execute(
                update(Review)
                .where(Review.id == review_id)
                .values(cluster_id=cluster_id, is_representative=is_rep)
            )
        session.commit()

    logger.info(
        "[s3_cluster] 完成 k=%d silhouette=%.4f representative=%d (fallback=%s)",
        result.cluster_k,
        result.silhouette_score,
        result.representative_count,
        result.fell_back,
    )
    return result


# ---------- 命令行入口 ----------
if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="s3_cluster: 向量化 + 聚类")
    parser.add_argument("--project-id", required=True, help="项目 ID")
    parser.add_argument("--k-min", type=int, default=None, help="K-Means 最小簇数")
    parser.add_argument("--k-max", type=int, default=None, help="K-Means 最大簇数")
    args = parser.parse_args()

    try:
        r = run_s3_cluster(
            args.project_id,
            k_min=args.k_min,
            k_max=args.k_max,
        )
        print(
            f"聚类完成: 差评={r.negative_count} 向量化={r.embedded_count} "
            f"k={r.cluster_k} silhouette={r.silhouette_score:.4f} "
            f"representative={r.representative_count}"
        )
        if r.fell_back:
            print(f"  降级原因: {r.fallback_reason}")
        for cid, size in r.cluster_sizes.items():
            print(f"  簇 {cid}: {size} 条")
    except StageError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)
