"""痛点查询接口 + 看板概览."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.response import error, get_request_id, success
from app.core.exceptions import ErrorCode
from app.core.logging import get_logger
from app.models.database import get_session
from app.models.schemas import (
    Attribution,
    PainPoint,
    Project,
    Review,
    Suggestion,
    ListingSuggestion,
)

logger = get_logger(__name__)
router = APIRouter()


# ---------- 视图模型 ----------
class PainPointVO(BaseModel):
    """痛点视图对象."""

    id: str
    project_id: str
    cluster_id: int
    label: str
    description: str | None
    review_count: int
    impact_ratio: float
    avg_rating: float | None
    trend: str | None
    is_common_weakness: bool
    suitable_for_reasoning: bool
    reasoning_reason: str | None
    rank_by_impact: int | None
    is_top5: bool
    competitor_breakdown: list[dict[str, Any]]
    created_at: str

    @classmethod
    def from_orm(cls, p: PainPoint) -> "PainPointVO":
        return cls(
            id=p.id,
            project_id=p.project_id,
            cluster_id=p.cluster_id,
            label=p.label,
            description=p.description,
            review_count=p.review_count,
            impact_ratio=p.impact_ratio,
            avg_rating=p.avg_rating,
            trend=p.trend,
            is_common_weakness=p.is_common_weakness,
            suitable_for_reasoning=p.suitable_for_reasoning,
            reasoning_reason=p.reasoning_reason,
            rank_by_impact=p.rank_by_impact,
            is_top5=p.is_top5,
            competitor_breakdown=p.competitor_breakdown_dict,
            created_at=p.created_at.isoformat() if p.created_at else "",
        )


class AttributionVO(BaseModel):
    """归因视图对象."""

    id: str
    pain_point_id: str
    root_cause: str
    evidence: list[dict[str, Any]]
    improvement_measures: list[dict[str, Any]]
    model_used: str
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: int | None
    created_at: str

    @classmethod
    def from_orm(cls, a: Attribution) -> "AttributionVO":
        return cls(
            id=a.id,
            pain_point_id=a.pain_point_id,
            root_cause=a.root_cause,
            evidence=a.evidence_list,
            improvement_measures=a.measures_list,
            model_used=a.model_used,
            prompt_tokens=a.prompt_tokens,
            completion_tokens=a.completion_tokens,
            latency_ms=a.latency_ms,
            created_at=a.created_at.isoformat() if a.created_at else "",
        )


class SuggestionVO(BaseModel):
    """改进建议视图对象."""

    id: str
    pain_point_id: str
    type: str
    content: str
    cost: str | None
    priority: str | None
    quadrant: str | None
    created_at: str


class PainPointDetailVO(BaseModel):
    """痛点详情（含归因 + 代表性评论 + 竞品对比）."""

    pain_point: PainPointVO
    attribution: AttributionVO | None
    representative_reviews: list[dict[str, Any]]
    suggestions: list[SuggestionVO]
    competitor_comparison: list[dict[str, Any]]


# ---------- 接口 ----------
@router.get("/projects/{project_id}/overview")
def get_overview(project_id: str, request: Request) -> dict:
    """看板概览（KPI + 热力图 + 矩阵 + 卖点）."""
    rid = get_request_id(request)
    with get_session() as session:
        project = session.get(Project, project_id)
        if project is None:
            return error(
                ErrorCode.PROJECT_NOT_FOUND,
                f"项目不存在: {project_id}",
                request_id=rid,
                status_code=404,
            )

        # KPI
        review_count = session.execute(
            select(func.count(Review.id)).where(Review.project_id == project_id)
        ).scalar() or 0
        negative_count = session.execute(
            select(func.count(Review.id))
            .where(Review.project_id == project_id)
            .where(Review.is_negative.is_(True))
        ).scalar() or 0
        pain_points = (
            session.execute(
                select(PainPoint)
                .where(PainPoint.project_id == project_id)
                .order_by(PainPoint.rank_by_impact.asc())
            )
            .scalars()
            .all()
        )
        # 真实成功归因数：Attribution 表中实际产出记录的条数（is_top5 标记数
        # 在归因全部降级失败时仍为 5，不能作为"归因完成"口径）
        attribution_count = (
            session.execute(
                select(func.count(Attribution.id)).where(
                    Attribution.project_id == project_id
                )
            )
            .scalar()
            or 0
        )

        kpis = {
            "competitor_count": len(project.competitor_asin_list),
            "review_count": review_count,
            "negative_review_count": negative_count,
            "pain_point_count": len(pain_points),
            # 新口径：真实归因记录数（Top5 进入深度归因后的成功产出）
            "attribution_count": attribution_count,
            # 旧字段名兼容（语义同 attribution_count），前端/模板已切换，仅防旧引用断裂
            "r1_attribution_count": attribution_count,
        }

        # 热力图数据
        heatmap = [
            {
                "pain_point_id": p.id,
                "label": p.label,
                "impact_ratio": p.impact_ratio,
                "review_count": p.review_count,
                "avg_rating": p.avg_rating,
                "trend": p.trend,
                "is_top5": p.is_top5,
            }
            for p in pain_points
        ]

        # 矩阵数据（按 quadrant 分组）
        # quadrant 在 suggestions 表，按 pain_point 关联
        sug_by_pp: dict[str, str] = {}
        suggestions = (
            session.execute(
                select(Suggestion)
                .where(Suggestion.project_id == project_id)
                .order_by(Suggestion.priority.desc())
            )
            .scalars()
            .all()
        )
        for s in suggestions:
            if s.pain_point_id not in sug_by_pp and s.quadrant:
                sug_by_pp[s.pain_point_id] = s.quadrant

        matrix = [
            {
                "pain_point_id": p.id,
                "label": p.label,
                "impact_ratio": p.impact_ratio,
                "difficulty_score": _infer_difficulty(sug_by_pp.get(p.id)),
                "quadrant": sug_by_pp.get(p.id, "strategic"),
                "priority": _max_priority(
                    [s.priority for s in suggestions if s.pain_point_id == p.id]
                ),
            }
            for p in pain_points
        ]

        # Listing 卖点
        listing_suggestions = (
            session.execute(
                select(ListingSuggestion)
                .where(ListingSuggestion.project_id == project_id)
                .order_by(ListingSuggestion.priority.desc())
            )
            .scalars()
            .all()
        )
        listing_data = [
            {
                "id": ls.id,
                "competitor_weakness": ls.competitor_weakness,
                "suggested_selling_point": ls.suggested_selling_point,
                "listing_field": ls.listing_field,
                "priority": ls.priority,
                "rationale": ls.rationale,
            }
            for ls in listing_suggestions
        ]

        overview = {
            "project": {
                "id": project.id,
                "name": project.name,
                "category": project.category,
                "status": project.status,
                "created_at": project.created_at.isoformat() if project.created_at else None,
                "completed_at": project.completed_at.isoformat()
                if project.completed_at
                else None,
            },
            "kpis": kpis,
            "heatmap": heatmap,
            "matrix": matrix,
            "listing_suggestions": listing_data,
        }
        return success(overview, request_id=rid)


@router.get("/projects/{project_id}/pain-points")
def list_pain_points(
    project_id: str,
    request: Request,
    top5_only: bool = Query(False, description="仅返回 Top 5"),
    sort_by: str = Query("impact", description="排序: impact/rating"),
) -> dict:
    """痛点列表."""
    rid = get_request_id(request)
    with get_session() as session:
        stmt = select(PainPoint).where(PainPoint.project_id == project_id)
        if top5_only:
            stmt = stmt.where(PainPoint.is_top5.is_(True))
        if sort_by == "rating":
            stmt = stmt.order_by(PainPoint.avg_rating.asc())
        else:
            stmt = stmt.order_by(PainPoint.impact_ratio.desc())
        pain_points = session.execute(stmt).scalars().all()
        items = [PainPointVO.from_orm(p).model_dump() for p in pain_points]
        return success(items, request_id=rid)


@router.get("/pain-points/{pain_point_id}")
def get_pain_point_detail(pain_point_id: str, request: Request) -> dict:
    """痛点详情（含归因 + 代表性评论 + 竞品对比）."""
    rid = get_request_id(request)
    with get_session() as session:
        pp = session.get(PainPoint, pain_point_id)
        if pp is None:
            return error(
                ErrorCode.PROJECT_NOT_FOUND,
                f"痛点不存在: {pain_point_id}",
                request_id=rid,
                status_code=404,
            )
        # 归因
        attr = (
            session.execute(
                select(Attribution).where(Attribution.pain_point_id == pain_point_id)
            )
            .scalars()
            .first()
        )
        # 代表性评论
        rep_reviews = (
            session.execute(
                select(Review)
                .where(Review.project_id == pp.project_id)
                .where(Review.cluster_id == pp.cluster_id)
                .order_by(Review.is_representative.desc(), Review.helpful_votes.desc())
                .limit(10)
            )
            .scalars()
            .all()
        )
        rep_data = [
            {
                "id": r.id,
                "rating": r.rating,
                "title": r.title,
                "body": r.body,
                "date": r.date.isoformat() if r.date else None,
                "variant": r.variant,
                "helpful_votes": r.helpful_votes,
                "asin": r.asin,
                "has_image": r.has_image,
                "image_urls": r.image_url_list,
                "is_representative": r.is_representative,
            }
            for r in rep_reviews
        ]
        # 建议
        suggestions = (
            session.execute(
                select(Suggestion)
                .where(Suggestion.pain_point_id == pain_point_id)
                .order_by(Suggestion.priority.desc())
            )
            .scalars()
            .all()
        )
        sug_data = [
            SuggestionVO(
                id=s.id,
                pain_point_id=s.pain_point_id,
                type=s.type,
                content=s.content,
                cost=s.cost,
                priority=s.priority,
                quadrant=s.quadrant,
                created_at=s.created_at.isoformat() if s.created_at else "",
            ).model_dump()
            for s in suggestions
        ]

        detail = PainPointDetailVO(
            pain_point=PainPointVO.from_orm(pp),
            attribution=AttributionVO.from_orm(attr) if attr else None,
            representative_reviews=rep_data,
            suggestions=sug_data,
            competitor_comparison=pp.competitor_breakdown_dict,
        )
        return success(detail.model_dump(), request_id=rid)


# ---------- 工具 ----------
def _infer_difficulty(quadrant: str | None) -> float:
    """从象限推断难度评分（0~1）."""
    if quadrant == "quick_win":
        return 0.3
    if quadrant == "filler":
        return 0.3
    if quadrant == "strategic":
        return 0.7
    if quadrant == "thankless":
        return 0.7
    return 0.5


def _max_priority(priorities: list[str | None]) -> str:
    """取最高优先级."""
    if not priorities:
        return "medium"
    if "high" in priorities:
        return "high"
    if "medium" in priorities:
        return "medium"
    return "low"
