"""评论查询接口."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.response import PageVO, error, get_request_id, success
from app.core.exceptions import ErrorCode
from app.core.logging import get_logger
from app.models.database import get_session
from app.models.schemas import Review

logger = get_logger(__name__)
router = APIRouter()


# ---------- 视图模型 ----------
class ReviewVO(BaseModel):
    """评论视图对象."""

    id: str
    project_id: str
    asin: str
    product_name: str | None
    rating: int
    title: str | None
    body: str
    date: str | None
    variant: str | None
    helpful_votes: int
    is_vp: bool
    has_image: bool
    image_urls: list[str]
    is_negative: bool | None
    cluster_id: int | None
    is_representative: bool
    is_suspicious: bool
    created_at: str

    @classmethod
    def from_orm(cls, r: Review) -> "ReviewVO":
        return cls(
            id=r.id,
            project_id=r.project_id,
            asin=r.asin,
            product_name=r.product_name,
            rating=r.rating,
            title=r.title,
            body=r.body,
            date=r.date.isoformat() if r.date else None,
            variant=r.variant,
            helpful_votes=r.helpful_votes,
            is_vp=r.is_vp,
            has_image=r.has_image,
            image_urls=r.image_url_list,
            is_negative=r.is_negative,
            cluster_id=r.cluster_id,
            is_representative=r.is_representative,
            is_suspicious=r.is_suspicious,
            created_at=r.created_at.isoformat() if r.created_at else "",
        )


# ---------- 接口 ----------
@router.get("/projects/{project_id}/reviews")
def list_reviews(
    project_id: str,
    request: Request,
    cluster_id: int | None = Query(None, description="按簇筛选"),
    asin: str | None = Query(None, description="按 ASIN 筛选"),
    is_negative: bool | None = Query(None, description="按差评筛选"),
    is_representative: bool | None = Query(None, description="仅看代表性评论"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> dict:
    """评论列表（按簇/ASIN/差评筛选）."""
    rid = get_request_id(request)
    with get_session() as session:
        stmt = select(Review).where(Review.project_id == project_id)
        count_stmt = select(func.count(Review.id)).where(Review.project_id == project_id)

        if cluster_id is not None:
            stmt = stmt.where(Review.cluster_id == cluster_id)
            count_stmt = count_stmt.where(Review.cluster_id == cluster_id)
        if asin:
            stmt = stmt.where(Review.asin == asin)
            count_stmt = count_stmt.where(Review.asin == asin)
        if is_negative is not None:
            stmt = stmt.where(Review.is_negative.is_(is_negative))
            count_stmt = count_stmt.where(Review.is_negative.is_(is_negative))
        if is_representative is not None:
            stmt = stmt.where(Review.is_representative.is_(is_representative))
            count_stmt = count_stmt.where(Review.is_representative.is_(is_representative))

        total = session.execute(count_stmt).scalar() or 0
        offset = (page - 1) * size
        reviews = (
            session.execute(
                stmt.order_by(Review.helpful_votes.desc()).offset(offset).limit(size)
            )
            .scalars()
            .all()
        )
        items = [ReviewVO.from_orm(r).model_dump() for r in reviews]
        pages = (total + size - 1) // size
        page_vo = PageVO[ReviewVO](
            items=items, total=total, page=page, size=size, pages=pages
        )
        return success(page_vo.model_dump(), request_id=rid)


@router.get("/reviews/{review_id}")
def get_review(review_id: str, request: Request) -> dict:
    """评论详情."""
    rid = get_request_id(request)
    with get_session() as session:
        review = session.get(Review, review_id)
        if review is None:
            return error(
                ErrorCode.PROJECT_NOT_FOUND,
                f"评论不存在: {review_id}",
                request_id=rid,
                status_code=404,
            )
        return success(ReviewVO.from_orm(review).model_dump(), request_id=rid)
