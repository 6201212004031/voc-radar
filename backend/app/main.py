"""VOC Radar FastAPI 应用入口.

职责:
- 创建 FastAPI 应用
- 配置 CORS
- 挂载 API 路由
- 全局异常处理
- 启动初始化（建表 + 目录）
- 托管前端静态文件（可选）
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import api_router
from app.core.config import settings, ensure_dirs
from app.core.exceptions import (
    ErrorCode,
    ProjectNotFoundError,
    ProjectStatusError,
    VOCRadarError,
)
from app.core.logging import get_logger, setup_logging
from app.models.database import init_db

logger = get_logger(__name__)


# ---------- 生命周期 ----------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动/关闭生命周期."""
    # 启动
    setup_logging()
    logger.info("VOC Radar 启动中...")
    ensure_dirs()
    init_db()
    logger.info("数据库初始化完成: %s", settings.db_path)
    logger.info("Model Router Base URL: %s", settings.MODEL_ROUTER_BASE_URL)
    logger.info("VOC Radar 启动完成")
    yield
    # 关闭
    logger.info("VOC Radar 关闭")


# ---------- 应用 ----------
app = FastAPI(
    title="VOC Radar 评论雷达",
    description="AI+跨境黑客松巅峰赛初赛原型 — 自动化评论分析流水线",
    version="0.1.0",
    lifespan=lifespan,
)


# ---------- CORS ----------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 原型阶段允许所有来源
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- 只读模式（公开演示部署：拦截一切写操作） ----------
@app.middleware("http")
async def read_only_guard(request: Request, call_next):
    if settings.READ_ONLY and request.method not in ("GET", "HEAD", "OPTIONS"):
        return JSONResponse(
            status_code=403,
            content={
                "code": 4103,
                "message": "当前为只读演示模式（READ_ONLY=true），仅开放浏览类接口",
                "data": None,
                "request_id": request.headers.get("X-Request-ID", ""),
            },
        )
    return await call_next(request)


# ---------- 路由挂载 ----------
app.include_router(api_router)


# ---------- 前端静态文件托管 ----------
# backend/app/main.py 向上 4 层: app/main.py -> app -> backend -> voc-radar
_FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"
if _FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")
    logger.info("前端静态文件已挂载: %s", _FRONTEND_DIR)
else:
    logger.warning("前端目录不存在: %s（仅 API 模式）", _FRONTEND_DIR)


# ---------- 全局异常处理 ----------
@app.exception_handler(ProjectNotFoundError)
async def project_not_found_handler(request: Request, exc: ProjectNotFoundError):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.code,
            "message": exc.message,
            "data": None,
            "request_id": request.headers.get("X-Request-ID", ""),
        },
    )


@app.exception_handler(ProjectStatusError)
async def project_status_handler(request: Request, exc: ProjectStatusError):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.code,
            "message": exc.message,
            "data": None,
            "request_id": request.headers.get("X-Request-ID", ""),
        },
    )


@app.exception_handler(VOCRadarError)
async def voc_radar_error_handler(request: Request, exc: VOCRadarError):
    return JSONResponse(
        status_code=400,
        content={
            "code": exc.code,
            "message": exc.message,
            "data": None,
            "request_id": request.headers.get("X-Request-ID", ""),
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("未处理异常: %s", exc)
    return JSONResponse(
        status_code=500,
        content={
            "code": 5000,
            "message": f"服务器内部错误: {exc}",
            "data": None,
            "request_id": request.headers.get("X-Request-ID", ""),
        },
    )


# ---------- 健康检查 ----------
@app.get("/health", tags=["系统"])
def health() -> dict:
    """健康检查."""
    return {"status": "ok", "service": "voc-radar", "version": "0.1.0"}
