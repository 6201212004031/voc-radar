"""Stage 1: 评论入库（含去重）.

职责:
- 从 data_loader 拿到 RawReview 列表
- 关联到 project（设置 asin/product_name 等）
- 去重：同一 project_id 下，按 (asin, body, rating) 去重；review_id 非空时优先按 review_id 去重
- 写入 reviews 表

输入: project_id（已存在的项目）
输出: 入库条数（含新增 / 跳过重复）

异常:
- DatasetError: 数据集缺失
- ProjectNotFoundError: 项目不存在
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import DatasetError, StageError
from app.core.logging import get_logger
from app.models.database import get_session
from app.models.schemas import Project, Review
from app.services.data_loader import DataLoader, RawReview
from app.utils.time import parse_date

logger = get_logger(__name__)


@dataclass
class IngestResult:
    """s1 入库结果."""

    total_loaded: int = 0
    """从数据源加载的总条数"""

    inserted: int = 0
    """实际入库条数"""

    skipped_duplicate: int = 0
    """因重复跳过的条数"""

    skipped_invalid: int = 0
    """因字段非法跳过的条数"""

    by_asin: dict[str, int] = None  # type: ignore[assignment]
    """按 ASIN 统计入库条数"""

    def __post_init__(self) -> None:
        if self.by_asin is None:
            self.by_asin = {}

    @property
    def skipped_total(self) -> int:
        return self.skipped_duplicate + self.skipped_invalid

    def to_dict(self) -> dict:
        return {
            "total_loaded": self.total_loaded,
            "inserted": self.inserted,
            "skipped_duplicate": self.skipped_duplicate,
            "skipped_invalid": self.skipped_invalid,
            "by_asin": self.by_asin,
        }


def run_s1_ingest(
    project_id: str,
    raw_dir: str | None = None,
    *,
    reviews_override: Iterable[RawReview] | None = None,
) -> IngestResult:
    """执行 s1_ingest 阶段.

    Args:
        project_id: 项目 ID（必须存在）
        raw_dir: 自定义数据目录；None 时用 settings.data_raw_dir
        reviews_override: 直接传入评论列表（测试用），跳过文件加载

    Returns:
        IngestResult 统计

    Raises:
        StageError: 阶段错误
        DatasetError: 数据集缺失
    """
    logger.info("[s1_ingest] 开始 project_id=%s", project_id)

    # 1. 校验项目
    with get_session() as session:
        project = session.get(Project, project_id)
        if project is None:
            raise StageError(
                "s1_ingest",
                f"项目不存在: {project_id}",
                code=1001,
                recoverable=False,
            )
        existing_asins = set(project.competitor_asin_list)

    # 2. 加载评论
    if reviews_override is not None:
        raw_reviews = list(reviews_override)
    else:
        loader = DataLoader()
        try:
            raw_reviews = loader.load_dir()
        except DatasetError as e:
            raise StageError(
                "s1_ingest",
                f"数据集加载失败: {e.message}",
                code=2001,
                cause=e,
                recoverable=False,
            ) from e

    total = len(raw_reviews)
    logger.info("[s1_ingest] 加载到 %d 条原始评论", total)
    if total == 0:
        raise StageError(
            "s1_ingest",
            "数据集中无评论",
            code=2001,
            recoverable=False,
        )

    # 3. 去重 + 入库
    result = IngestResult(total_loaded=total)

    # 预取已有去重指纹（避免逐条查询）
    with get_session() as session:
        # 已存在的 (asin, body, rating) 集合（仅本项目）
        stmt = select(Review.asin, Review.body, Review.rating).where(
            Review.project_id == project_id
        )
        existing_rows = session.execute(stmt).all()
        existing_fingerprints: set[tuple[str, str, int]] = {
            (asin, body, rating) for asin, body, rating in existing_rows
        }

        # 已存在的 review_id（数据集自带 id）
        stmt_rid = select(Review.raw_json).where(Review.project_id == project_id)
        existing_review_ids: set[str] = set()
        for (raw_json,) in session.execute(stmt_rid).all():
            if not raw_json:
                continue
            try:
                data = json.loads(raw_json)
                rid = data.get("review_id") or data.get("id")
                if rid:
                    existing_review_ids.add(str(rid))
            except json.JSONDecodeError:
                continue

    # 写入（批量，每 500 条提交一次）
    batch_size = 500
    pending: list[Review] = []
    asin_counter: dict[str, int] = {}

    def _flush(session) -> None:
        nonlocal pending
        if pending:
            session.add_all(pending)
            session.commit()
            pending = []

    try:
        with get_session() as session:
            for raw in raw_reviews:
                # 字段校验
                if not raw.asin or not raw.body:
                    result.skipped_invalid += 1
                    continue
                if not (1 <= raw.rating <= 5):
                    result.skipped_invalid += 1
                    continue

                # 去重 1: review_id
                if raw.review_id and raw.review_id in existing_review_ids:
                    result.skipped_duplicate += 1
                    continue

                # 去重 2: (asin, body, rating)
                fingerprint = (raw.asin, raw.body, raw.rating)
                if fingerprint in existing_fingerprints:
                    result.skipped_duplicate += 1
                    continue

                # 构造 Review
                date_dt = parse_date(raw.date)
                review = Review(
                    project_id=project_id,
                    asin=raw.asin,
                    product_name=raw.product_name or None,
                    rating=raw.rating,
                    title=raw.title or None,
                    body=raw.body,
                    date=date_dt,
                    variant=raw.variant or None,
                    helpful_votes=raw.helpful_votes,
                    is_vp=raw.verified_purchase if raw.verified_purchase is not None else True,
                    has_image=bool(raw.image_urls),
                    is_negative=(raw.rating <= 3),  # s2 会重新标记，这里先填
                    raw_json=json.dumps(raw.raw, ensure_ascii=False) if raw.raw else None,
                )
                review.image_url_list = raw.image_urls  # 通过 property 序列化

                pending.append(review)
                existing_fingerprints.add(fingerprint)
                if raw.review_id:
                    existing_review_ids.add(raw.review_id)
                asin_counter[raw.asin] = asin_counter.get(raw.asin, 0) + 1
                result.inserted += 1

                if len(pending) >= batch_size:
                    _flush(session)

            _flush(session)

    except SQLAlchemyError as e:
        logger.error("[s1_ingest] 数据库写入失败: %s", e)
        raise StageError(
            "s1_ingest",
            f"数据库写入失败: {e}",
            code=2002,
            cause=e,
            recoverable=False,
        ) from e

    result.by_asin = asin_counter

    # 4. 同步项目竞品 ASIN 列表（若为空）
    with get_session() as session:
        project = session.get(Project, project_id)
        if project is not None:
            current_asins = set(project.competitor_asin_list)
            new_asins = current_asins | set(asin_counter.keys())
            if new_asins != current_asins:
                project.competitor_asin_list = sorted(new_asins)
                session.commit()
                logger.info(
                    "[s1_ingest] 更新项目竞品 ASIN: %s",
                    project.competitor_asin_list,
                )

    logger.info(
        "[s1_ingest] 完成 inserted=%d duplicate=%d invalid=%d",
        result.inserted,
        result.skipped_duplicate,
        result.skipped_invalid,
    )
    return result


# ---------- 命令行入口 ----------
if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="s1_ingest: 评论入库")
    parser.add_argument("--project-id", required=True, help="项目 ID")
    parser.add_argument("--raw-dir", help="自定义数据目录")
    args = parser.parse_args()

    try:
        r = run_s1_ingest(args.project_id, raw_dir=args.raw_dir)
        print(
            f"入库完成: 加载 {r.total_loaded} 条, "
            f"新增 {r.inserted} 条, 重复 {r.skipped_duplicate} 条, "
            f"非法 {r.skipped_invalid} 条"
        )
        for asin, cnt in r.by_asin.items():
            print(f"  ASIN {asin}: {cnt} 条")
    except StageError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)
