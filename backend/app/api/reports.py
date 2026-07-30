"""报告导出接口."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, PlainTextResponse

from app.api.response import error, get_request_id, success
from app.core.config import settings
from app.core.exceptions import ErrorCode
from app.core.logging import get_logger
from app.models.database import get_session
from app.models.schemas import Project

logger = get_logger(__name__)
router = APIRouter()


@router.get("/projects/{project_id}/report")
def get_report_content(
    project_id: str,
    request: Request,
    format: str = "md",
) -> dict:
    """获取报告内容（返回 Markdown 文本）."""
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

    report_path = settings.report_dir / f"{project_id}.md"
    if not report_path.exists():
        return error(
            ErrorCode.REPORT_RENDER_FAILED,
            "报告尚未生成，请先触发 pipeline 完成",
            request_id=rid,
            status_code=404,
        )

    try:
        content = report_path.read_text(encoding="utf-8")
    except OSError as e:
        return error(
            ErrorCode.REPORT_RENDER_FAILED,
            f"读取报告失败: {e}",
            request_id=rid,
            status_code=500,
        )
    return success({"content": content, "format": "md"}, request_id=rid)


@router.get("/projects/{project_id}/report/download")
def download_report(
    project_id: str,
    request: Request,
    format: str = "md",
):
    """下载报告文件.

    支持 format=md（P0）。format=pdf 为 P1，当前返回 501。
    """
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

    if format == "pdf":
        return error(
            ErrorCode.REPORT_RENDER_FAILED,
            "PDF 导出为 P1 功能，暂未实现",
            request_id=rid,
            status_code=501,
        )

    report_path = settings.report_dir / f"{project_id}.md"
    if not report_path.exists():
        return error(
            ErrorCode.REPORT_RENDER_FAILED,
            "报告尚未生成，请先触发 pipeline 完成",
            request_id=rid,
            status_code=404,
        )

    return FileResponse(
        path=str(report_path),
        media_type="text/markdown; charset=utf-8",
        filename=f"voc_radar_report_{project_id}.md",
    )
