"""API 路由聚合.

所有接口统一前缀 /api/v1，响应体统一格式:
{
  "code": 0,
  "message": "ok",
  "data": {...} | null,
  "request_id": "uuid"
}
"""
from __future__ import annotations

from fastapi import APIRouter

from app.api.analyze import router as analyze_router
from app.api.painpoints import router as painpoints_router
from app.api.projects import router as projects_router
from app.api.reports import router as reports_router
from app.api.reviews import router as reviews_router

api_router = APIRouter(prefix="/api/v1")

# 挂载子路由
api_router.include_router(projects_router, tags=["项目管理"])
api_router.include_router(analyze_router, tags=["Pipeline 编排"])
api_router.include_router(reviews_router, tags=["评论查询"])
api_router.include_router(painpoints_router, tags=["痛点与看板"])
api_router.include_router(reports_router, tags=["报告导出"])
