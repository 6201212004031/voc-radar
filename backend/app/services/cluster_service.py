"""K-Means 聚类服务 + k 值选择（silhouette）.

职责:
- 输入: 向量矩阵（list[list[float]] 或 numpy.ndarray）
- 在 k_min ~ k_max 区间内逐个跑 K-Means，计算 silhouette score
- 选 silhouette 最高的 k 作为最终聚类（兜底: 若都低于阈值，降级到 k=10 并 warning）
- 输出: 聚类标签 + 最优 k + silhouette 分数 + 每簇统计

注意:
- 本模块只处理向量与聚类，不关心向量化（向量化在 s3_cluster 中调用 embedding_service）
- 输入向量数 < k_min 时降级处理
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

from app.core.config import settings
from app.core.exceptions import ClusterError
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ClusterResult:
    """聚类结果."""

    labels: np.ndarray
    """每个样本的簇编号（0 ~ k-1）"""

    k: int
    """最终选择的簇数"""

    silhouette_score: float
    """最终 silhouette 分数"""

    all_scores: dict[int, float] = field(default_factory=dict)
    """各 k 的 silhouette 分数"""

    cluster_sizes: dict[int, int] = field(default_factory=dict)
    """每簇样本数"""

    fell_back: bool = False
    """是否触发了降级（silhouette 都低于阈值）"""

    fallback_reason: str = ""
    """降级原因（如有）"""

    def to_dict(self) -> dict:
        return {
            "k": self.k,
            "silhouette_score": float(self.silhouette_score),
            "all_scores": {int(k): float(v) for k, v in self.all_scores.items()},
            "cluster_sizes": {int(k): int(v) for k, v in self.cluster_sizes.items()},
            "fell_back": self.fell_back,
            "fallback_reason": self.fallback_reason,
        }


def cluster_reviews(
    vectors: list[list[float]] | np.ndarray,
    k_min: int | None = None,
    k_max: int | None = None,
    *,
    random_state: int = 42,
    fallback_k: int = 10,
    silhouette_floor: float | None = None,
) -> ClusterResult:
    """对评论向量做 K-Means 聚类，自动选择最优 k.

    Args:
        vectors: 向量列表（n_samples × n_dim）
        k_min: K-Means 最小簇数，默认 settings.CLUSTER_K_MIN
        k_max: 最大簇数，默认 settings.CLUSTER_K_MAX
        random_state: 随机种子（保证可复现）
        fallback_k: silhouette 全部低于阈值时降级使用的 k 值
        silhouette_floor: silhouette 下限阈值

    Returns:
        ClusterResult

    Raises:
        ClusterError: 样本数不足或聚类失败
    """
    k_min = k_min or settings.CLUSTER_K_MIN
    k_max = k_max or settings.CLUSTER_K_MAX
    silhouette_floor = (
        silhouette_floor if silhouette_floor is not None else settings.CLUSTER_SILHOUETTE_FLOOR
    )

    # 1. 输入校验
    if vectors is None or len(vectors) == 0:
        raise ClusterError("聚类输入向量为空")

    try:
        X = np.asarray(vectors, dtype=np.float32)
    except Exception as e:
        raise ClusterError(f"向量转换为 numpy 失败: {e}", cause=e) from e

    if X.ndim != 2:
        raise ClusterError(f"向量维度应为 2，实际为 {X.ndim}")

    n_samples = X.shape[0]
    if n_samples < 2:
        raise ClusterError(f"样本数不足: {n_samples}（至少需要 2 条）")

    # 2. 动态调整 k 区间
    # k 不能超过样本数 - 1（silhouette 要求）
    effective_k_max = min(k_max, n_samples - 1)
    effective_k_min = min(k_min, effective_k_max)
    if effective_k_max < 2:
        # 退化：样本数太少，强制 k=1（实际不聚类）
        logger.warning(
            "样本数 %d 过少，无法聚类，所有样本归为簇 0", n_samples
        )
        labels = np.zeros(n_samples, dtype=np.int32)
        return ClusterResult(
            labels=labels,
            k=1,
            silhouette_score=0.0,
            cluster_sizes={0: n_samples},
            fell_back=True,
            fallback_reason=f"样本数 {n_samples} 过少，无法聚类",
        )

    logger.info(
        "开始聚类: n_samples=%d n_dim=%d k_range=[%d, %d]",
        n_samples,
        X.shape[1],
        effective_k_min,
        effective_k_max,
    )

    # 3. 在 k 区间内跑 K-Means + silhouette
    all_scores: dict[int, float] = {}
    best_k: int = effective_k_min
    best_score: float = -1.0
    best_labels: np.ndarray | None = None

    for k in range(effective_k_min, effective_k_max + 1):
        try:
            km = KMeans(
                n_clusters=k,
                random_state=random_state,
                n_init=10,
                init="k-means++",
            )
            labels = km.fit_predict(X)
            # 至少 2 个非空簇才能算 silhouette
            unique_labels = set(labels.tolist())
            if len(unique_labels) < 2:
                logger.warning("k=%d 只产生 %d 个簇，跳过 silhouette", k, len(unique_labels))
                all_scores[k] = -1.0
                continue
            score = float(silhouette_score(X, labels, metric="euclidean"))
            all_scores[k] = score
            logger.debug("k=%d silhouette=%.4f", k, score)

            if score > best_score:
                best_score = score
                best_k = k
                best_labels = labels
        except Exception as e:
            logger.warning("k=%d 聚类失败: %s", k, e)
            all_scores[k] = -1.0
            continue

    if best_labels is None:
        raise ClusterError(
            f"所有 k 值聚类均失败 (k_range=[{effective_k_min},{effective_k_max}])"
        )

    # 4. 降级判断
    fell_back = False
    fallback_reason = ""
    if best_score < silhouette_floor:
        logger.warning(
            "最优 silhouette=%.4f 低于阈值 %.2f，降级到 k=%d",
            best_score,
            silhouette_floor,
            fallback_k,
        )
        # 降级到 fallback_k
        actual_fallback_k = min(fallback_k, effective_k_max)
        actual_fallback_k = max(actual_fallback_k, effective_k_min)
        try:
            km = KMeans(
                n_clusters=actual_fallback_k,
                random_state=random_state,
                n_init=10,
                init="k-means++",
            )
            best_labels = km.fit_predict(X)
            best_k = actual_fallback_k
            # 重新计算 silhouette
            unique = set(best_labels.tolist())
            if len(unique) >= 2:
                best_score = float(silhouette_score(X, best_labels, metric="euclidean"))
                all_scores[best_k] = best_score
            else:
                best_score = 0.0
            fell_back = True
            fallback_reason = (
                f"silhouette 全部低于阈值 {silhouette_floor}，"
                f"降级使用 k={actual_fallback_k}"
            )
        except ClusterError:
            raise
        except Exception as e:
            raise ClusterError(
                f"降级聚类失败 k={actual_fallback_k}: {e}", cause=e
            ) from e

    # 5. 统计每簇样本数
    cluster_sizes: dict[int, int] = {}
    for lab in best_labels.tolist():
        cluster_sizes[int(lab)] = cluster_sizes.get(int(lab), 0) + 1

    logger.info(
        "聚类完成: k=%d silhouette=%.4f (fallback=%s)",
        best_k,
        best_score,
        fell_back,
    )

    return ClusterResult(
        labels=best_labels,
        k=best_k,
        silhouette_score=best_score,
        all_scores=all_scores,
        cluster_sizes=cluster_sizes,
        fell_back=fell_back,
        fallback_reason=fallback_reason,
    )


def select_representative_indices(
    cluster_labels: np.ndarray,
    scores: list[float] | np.ndarray,
    cluster_id: int,
    top_n: int | None = None,
) -> list[int]:
    """从指定簇中按 score 降序选代表性评论的索引.

    代表性评分建议: helpful_votes * 0.6 + body_length * 0.4
    （在 s3_cluster 中计算后传入）

    Args:
        cluster_labels: 所有样本的簇编号
        scores: 所有样本的代表性评分
        cluster_id: 目标簇编号
        top_n: 取前 N 条，默认 settings.CLUSTER_REPRESENTATIVE_TOP_N

    Returns:
        全局索引列表（按评分降序）
    """
    top_n = top_n or settings.CLUSTER_REPRESENTATIVE_TOP_N
    labels = np.asarray(cluster_labels)
    scores_arr = np.asarray(scores)

    # 找出属于该簇的样本索引
    member_mask = labels == cluster_id
    member_indices = np.where(member_mask)[0]
    if len(member_indices) == 0:
        return []

    # 按 score 降序
    member_scores = scores_arr[member_indices]
    sorted_order = np.argsort(-member_scores)  # 降序
    selected = member_indices[sorted_order[:top_n]].tolist()
    return [int(i) for i in selected]


def compute_representative_score(
    helpful_votes: list[int],
    body_lengths: list[int],
) -> list[float]:
    """计算代表性评分: helpful_votes * 0.6 + body_length * 0.4.

    输入两列数值（同长度），输出每条样本的得分。
    会做 min-max 归一化以保证两列量纲一致。

    Args:
        helpful_votes: 每条评论的点赞数
        body_lengths: 每条评论的正文长度

    Returns:
        评分列表
    """
    hv = np.asarray(helpful_votes, dtype=np.float32)
    bl = np.asarray(body_lengths, dtype=np.float32)

    def _norm(arr: np.ndarray) -> np.ndarray:
        if arr.size == 0:
            return arr
        mn, mx = arr.min(), arr.max()
        if mx == mn:
            return np.zeros_like(arr)
        return (arr - mn) / (mx - mn)

    hv_n = _norm(hv)
    bl_n = _norm(bl)
    return (hv_n * 0.6 + bl_n * 0.4).tolist()
