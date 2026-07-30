"""触发 pipeline + SSE 进度流 + 状态查询."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.response import error, get_request_id, success
from app.core.exceptions import ErrorCode
from app.core.logging import get_logger
from app.models.database import get_session
from app.models.schemas import Project, ProjectStatus
from app.pipeline.orchestrator import EventType, get_orchestrator
from app.pipeline.progress import (
    format_sse,
    get_progress_manager,
)
from sse_starlette.sse import EventSourceResponse

logger = get_logger(__name__)
router = APIRouter()


# ---------- 请求/响应模型 ----------
class AnalyzeRequest(BaseModel):
    """触发 pipeline 请求."""

    config: dict[str, Any] | None = Field(None, description="pipeline 配置")


class AnalyzeResponse(BaseModel):
    """触发响应."""

    task_id: str
    status: str


class StatusResponse(BaseModel):
    """状态响应."""

    status: str
    current_stage: str | None
    progress: float | None
    error: str | None = None


# ---------- 接口 ----------
@router.post("/projects/{project_id}/analyze")
async def trigger_analyze(
    project_id: str, payload: AnalyzeRequest, request: Request
) -> dict:
    """触发 pipeline（异步执行，立即返回 task_id）.

    pipeline 在后台执行，客户端通过 /progress 端点订阅进度。
    """
    rid = get_request_id(request)

    # 校验项目存在
    with get_session() as session:
        project = session.get(Project, project_id)
        if project is None:
            return error(
                ErrorCode.PROJECT_NOT_FOUND,
                f"项目不存在: {project_id}",
                request_id=rid,
                status_code=404,
            )
        if project.status == ProjectStatus.RUNNING.value:
            return error(
                ErrorCode.PROJECT_STATUS_INVALID,
                "项目正在运行中，无法重复触发",
                request_id=rid,
                status_code=409,
            )

    # 后台启动 pipeline
    task_id = project_id  # 原型简化：task_id = project_id
    asyncio.create_task(
        _run_pipeline_background(project_id, payload.config or {})
    )

    return success(
        AnalyzeResponse(task_id=task_id, status="running").model_dump(),
        request_id=rid,
    )


async def _run_pipeline_background(project_id: str, config: dict[str, Any]) -> None:
    """后台执行 pipeline，将进度事件推送到 ProgressManager."""
    mgr = get_progress_manager()
    orch = get_orchestrator()

    async def on_progress(event: dict[str, Any]) -> None:
        await mgr.publish(project_id, event)

    try:
        result = await orch.run(project_id, on_progress=on_progress, config=config)
        logger.info(
            "[analyze] pipeline 结束 project=%s status=%s",
            project_id,
            result.status,
        )
    except Exception as e:
        logger.exception("[analyze] pipeline 未预期异常 project=%s", project_id)
        await mgr.publish(
            project_id,
            {
                "event": EventType.ERROR,
                "data": {
                    "stage": "orchestrator",
                    "message": f"未预期异常: {e}",
                    "error_code": 5000,
                },
            },
        )
    finally:
        # 延迟清理（让客户端取完事件）
        await mgr.close_project(project_id, delay=5.0)


@router.get("/projects/{project_id}/progress")
async def progress_stream(project_id: str, request: Request):
    """SSE 进度流.

    返回 text/event-stream，事件格式:
        event: progress
        data: {"stage":"s3_cluster","progress":0.45,"message":"...","timestamp":"..."}

        event: stage_done
        data: {...}

        event: complete
        data: {...}
    """
    # 校验项目存在
    with get_session() as session:
        project = session.get(Project, project_id)
        if project is None:
            return error(
                ErrorCode.PROJECT_NOT_FOUND,
                f"项目不存在: {project_id}",
                request_id="",
                status_code=404,
            )

    mgr = get_progress_manager()
    sub = await mgr.subscribe(project_id)

    async def event_generator():
        try:
            # 立即推送当前状态
            with get_session() as session:
                p = session.get(Project, project_id)
                if p is not None:
                    yield {
                        "event": "progress",
                        "data": {
                            "stage": p.current_stage or "idle",
                            "progress": p.progress or 0.0,
                            "message": f"当前状态: {p.status}",
                            "timestamp": _now_iso(),
                        },
                    }
                    # 若项目已完成，推送 complete 后关闭
                    if p.status == ProjectStatus.COMPLETED.value:
                        yield {
                            "event": "complete",
                            "data": {
                                "project_id": project_id,
                                "status": "completed",
                                "progress": 1.0,
                                "report_url": f"/api/v1/projects/{project_id}/report",
                                "timestamp": _now_iso(),
                            },
                        }
                        return
                    if p.status == ProjectStatus.FAILED.value:
                        yield {
                            "event": "error",
                            "data": {
                                "stage": p.current_stage or "unknown",
                                "message": "项目已失败",
                                "timestamp": _now_iso(),
                            },
                        }
                        return

            # 持续读取队列
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(sub.queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    # 发心跳保持连接
                    yield {"event": "ping", "data": {"timestamp": _now_iso()}}
                    continue
                event_type = event.get("event", "message")
                data = event.get("data", {})
                yield {"event": event_type, "data": data}

                # complete / error 后结束
                if event_type in (EventType.COMPLETE, EventType.ERROR):
                    break
        finally:
            await mgr.unsubscribe(project_id, sub)

    return EventSourceResponse(event_generator())


@router.get("/projects/{project_id}/status")
def get_status(project_id: str, request: Request) -> dict:
    """查询状态（非流式）."""
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
        return success(
            StatusResponse(
                status=project.status,
                current_stage=project.current_stage,
                progress=project.progress,
                error=None,
            ).model_dump(),
            request_id=rid,
        )


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
