"""项目管理接口：创建/列表/详情/删除."""
from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.api.response import PageVO, ApiResponse, error, get_request_id, success
from app.core.exceptions import ErrorCode, ProjectNotFoundError, ProjectStatusError
from app.core.logging import get_logger
from app.models.database import get_session
from app.models.schemas import (
    Attribution,
    PainPoint,
    Project,
    ProjectStatus,
    Review,
    Suggestion,
    ListingSuggestion,
)

logger = get_logger(__name__)
router = APIRouter()


# ---------- 请求/响应模型 ----------
class ProjectCreate(BaseModel):
    """创建项目请求."""

    name: str = Field(..., min_length=1, max_length=255, description="项目名")
    category: str = Field(..., min_length=1, max_length=255, description="品类关键词")
    competitor_asins: list[str] = Field(
        default_factory=list, description="竞品 ASIN 列表"
    )
    config: dict[str, Any] | None = Field(None, description="项目配置")


class ProjectVO(BaseModel):
    """项目视图对象."""

    id: str
    name: str
    category: str
    competitor_asins: list[str]
    status: str
    current_stage: str | None
    progress: float | None
    config: dict[str, Any]
    created_at: str
    updated_at: str
    completed_at: str | None

    @classmethod
    def from_orm(cls, p: Project) -> "ProjectVO":
        return cls(
            id=p.id,
            name=p.name,
            category=p.category,
            competitor_asins=p.competitor_asin_list,
            status=p.status,
            current_stage=p.current_stage,
            progress=p.progress,
            config=p.config,
            created_at=p.created_at.isoformat() if p.created_at else "",
            updated_at=p.updated_at.isoformat() if p.updated_at else "",
            completed_at=p.completed_at.isoformat() if p.completed_at else None,
        )


class ProjectDetailVO(ProjectVO):
    """项目详情（含统计）."""

    review_count: int = 0
    negative_review_count: int = 0
    pain_point_count: int = 0
    # 真实归因记录数（成功产出 Attribution 的条数）
    attribution_count: int = 0
    # 旧字段名兼容别名，语义同 attribution_count
    r1_attribution_count: int = 0


# ---------- 接口 ----------
@router.post("/projects", response_model=ApiResponse[ProjectVO])
def create_project(
    payload: ProjectCreate, request: Request
) -> dict:
    """创建分析项目."""
    rid = get_request_id(request)
    try:
        with get_session() as session:
            project = Project(
                name=payload.name,
                category=payload.category,
                status=ProjectStatus.PENDING.value,
                progress=0.0,
            )
            project.competitor_asin_list = payload.competitor_asins
            # 合并 config；显式指定竞品 ASIN 时打标记，
            # s1_ingest 据此过滤（区别于入库后自动回填的列表）
            merged_config: dict[str, Any] = dict(payload.config or {})
            if payload.competitor_asins:
                merged_config["asins_user_specified"] = True
            if merged_config:
                project.config = merged_config
            session.add(project)
            session.commit()
            session.refresh(project)
            vo = ProjectVO.from_orm(project)
            return success(vo.model_dump(), request_id=rid)
    except SQLAlchemyError as e:
        logger.error("创建项目失败: %s", e)
        return error(
            ErrorCode.PROJECT_STATUS_INVALID,
            f"创建项目失败: {e}",
            request_id=rid,
            status_code=500,
        )


@router.get("/projects", response_model=ApiResponse[PageVO[ProjectVO]])
def list_projects(
    request: Request,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> dict:
    """项目列表."""
    rid = get_request_id(request)
    with get_session() as session:
        total = session.execute(select(func.count(Project.id))).scalar() or 0
        offset = (page - 1) * size
        projects = (
            session.execute(
                select(Project)
                .order_by(Project.created_at.desc())
                .offset(offset)
                .limit(size)
            )
            .scalars()
            .all()
        )
        items = [ProjectVO.from_orm(p).model_dump() for p in projects]
        pages = (total + size - 1) // size
        page_vo = PageVO[ProjectVO](
            items=items, total=total, page=page, size=size, pages=pages
        )
        return success(page_vo.model_dump(), request_id=rid)


@router.get("/projects/{project_id}", response_model=ApiResponse[ProjectDetailVO])
def get_project(project_id: str, request: Request) -> dict:
    """项目详情（含统计）."""
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

        # 统计（归因数 = Attribution 实际产出记录数，非 is_top5 标记数）
        review_count = session.execute(
            select(func.count(Review.id)).where(Review.project_id == project_id)
        ).scalar() or 0
        negative_count = session.execute(
            select(func.count(Review.id))
            .where(Review.project_id == project_id)
            .where(Review.is_negative.is_(True))
        ).scalar() or 0
        pain_point_count = session.execute(
            select(func.count(PainPoint.id)).where(PainPoint.project_id == project_id)
        ).scalar() or 0
        attribution_count = session.execute(
            select(func.count(Attribution.id)).where(
                Attribution.project_id == project_id
            )
        ).scalar() or 0

        vo = ProjectDetailVO(
            **ProjectVO.from_orm(project).model_dump(),
            review_count=review_count,
            negative_review_count=negative_count,
            pain_point_count=pain_point_count,
            attribution_count=attribution_count,
            r1_attribution_count=attribution_count,
        )
        return success(vo.model_dump(), request_id=rid)


@router.delete("/projects/{project_id}", response_model=ApiResponse[None])
def delete_project(project_id: str, request: Request) -> dict:
    """删除项目（级联删除关联数据）."""
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
        session.delete(project)
        session.commit()
        return success(None, message="已删除", request_id=rid)
