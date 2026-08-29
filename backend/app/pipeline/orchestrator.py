"""Pipeline 编排器：串联 7 阶段 + 异常降级 + 日志 + SSE 进度推送.

设计要点:
- 每个阶段有 progress 阈值（0.0~1.0）
- 通过 on_progress 回调推送 SSE 事件（由 API 层订阅）
- StageError 区分 recoverable:
  - 不可降级 → 标记 project.status=failed，推送 error 事件，中止
  - 可降级 → 记录 warning，推送 stage_warning 事件，继续下一阶段
- 支持断点恢复（检查 project.current_stage，已完成则跳过）—— 原型简化为整段重跑
- 完成后标记 project.status=completed，推送 complete 事件
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import update

from app.core.config import settings
from app.core.exceptions import StageError
from app.core.logging import get_logger
from app.models.database import get_session
from app.models.schemas import Project, ProjectStatus, PipelineStage
from app.pipeline.stages.s1_ingest import IngestResult, run_s1_ingest
from app.pipeline.stages.s2_preprocess import PreprocessResult, run_s2_preprocess
from app.pipeline.stages.s3_cluster import ClusterStageResult, run_s3_cluster
from app.pipeline.stages.s4_label import LabelStageResult, run_s4_label
from app.pipeline.stages.s5_attribute import AttributeStageResult, run_s5_attribute
from app.pipeline.stages.s6_suggest import SuggestStageResult, run_s6_suggest
from app.pipeline.stages.s7_report import ReportStageResult, run_s7_report

logger = get_logger(__name__)


# ---------- 进度回调类型 ----------
ProgressCallback = Callable[[dict[str, Any]], Awaitable[None] | None]
"""进度回调，接收 SSE 事件 dict，可为同步或异步"""


# ---------- SSE 事件类型 ----------
class EventType:
    PROGRESS = "progress"
    STAGE_DONE = "stage_done"
    STAGE_WARNING = "stage_warning"
    ERROR = "error"
    COMPLETE = "complete"


# ---------- 阶段定义 ----------
@dataclass
class StageDef:
    """阶段定义."""

    name: str
    """阶段名（如 s1_ingest）"""

    fn: Callable[[str], Any]
    """阶段执行函数，入参 project_id"""

    progress: float
    """完成此阶段后的整体进度（0.0~1.0）"""

    recoverable: bool = True
    """StageError 时是否可降级继续（s1/s3 不可降级）"""

    description: str = ""
    """阶段描述（用于 SSE 消息）"""


STAGES: list[StageDef] = [
    StageDef(
        name="s1_ingest",
        fn=run_s1_ingest,
        progress=0.15,
        recoverable=False,
        description="评论入库",
    ),
    StageDef(
        name="s2_preprocess",
        fn=run_s2_preprocess,
        progress=0.25,
        recoverable=True,
        description="评论预处理",
    ),
    StageDef(
        name="s3_cluster",
        fn=run_s3_cluster,
        progress=0.45,
        recoverable=False,
        description="向量化与聚类",
    ),
    StageDef(
        name="s4_label",
        fn=run_s4_label,
        progress=0.60,
        recoverable=True,
        description="痛点标签生成",
    ),
    StageDef(
        name="s5_attribute",
        fn=run_s5_attribute,
        progress=0.80,
        recoverable=True,
        description="根因归因",
    ),
    StageDef(
        name="s6_suggest",
        fn=run_s6_suggest,
        progress=0.92,
        recoverable=True,
        description="改进建议生成",
    ),
    StageDef(
        name="s7_report",
        fn=run_s7_report,
        progress=1.00,
        recoverable=True,
        description="报告整合",
    ),
]


# ---------- 编排结果 ----------
@dataclass
class PipelineResult:
    """Pipeline 整体运行结果."""

    project_id: str
    status: str = ProjectStatus.COMPLETED.value
    """最终项目状态"""

    current_stage: str = ""
    """最后执行的阶段"""

    progress: float = 0.0
    """最终进度"""

    stages_completed: list[str] = field(default_factory=list)
    """已完成的阶段名"""

    stages_failed: list[str] = field(default_factory=list)
    """失败的阶段名"""

    stages_skipped: list[str] = field(default_factory=list)
    """被跳过的阶段名"""

    error: str | None = None
    """最终错误（若 status=failed）"""

    stage_results: dict[str, Any] = field(default_factory=dict)
    """各阶段的返回结果摘要"""

    started_at: datetime | None = None
    completed_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "status": self.status,
            "current_stage": self.current_stage,
            "progress": self.progress,
            "stages_completed": self.stages_completed,
            "stages_failed": self.stages_failed,
            "stages_skipped": self.stages_skipped,
            "error": self.error,
            "stage_results": self.stage_results,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


# ---------- 工具：更新项目状态 ----------
def _update_project_status(
    project_id: str,
    *,
    status: str | None = None,
    current_stage: str | None = None,
    progress: float | None = None,
    completed: bool = False,
) -> None:
    """更新项目状态（增量更新）."""
    values: dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}
    if status is not None:
        values["status"] = status
    if current_stage is not None:
        values["current_stage"] = current_stage
    if progress is not None:
        values["progress"] = progress
    if completed:
        values["completed_at"] = datetime.now(timezone.utc)
        values["status"] = ProjectStatus.COMPLETED.value
        values["progress"] = 1.0

    with get_session() as session:
        session.execute(
            update(Project).where(Project.id == project_id).values(**values)
        )
        session.commit()


# ---------- 主编排器 ----------
class PipelineOrchestrator:
    """Pipeline 编排器.

    用法:
        orch = PipelineOrchestrator()
        result = await orch.run(project_id, on_progress=lambda evt: sse_queue.put(evt))
    """

    def __init__(self, stages: list[StageDef] | None = None) -> None:
        self.stages = stages or STAGES

    async def run(
        self,
        project_id: str,
        on_progress: ProgressCallback | None = None,
        config: dict[str, Any] | None = None,
    ) -> PipelineResult:
        """执行完整 pipeline.

        Args:
            project_id: 项目 ID
            on_progress: 进度回调（同步或异步），接收 SSE 事件 dict
            config: pipeline 配置（当前阶段参数由后端 settings 决定，保留此形参以兼容调用方签名）

        Returns:
            PipelineResult
        """
        result = PipelineResult(
            project_id=project_id,
            started_at=datetime.now(timezone.utc),
        )

        logger.info("[orchestrator] 启动 pipeline project_id=%s", project_id)

        # 标记 running
        _update_project_status(
            project_id,
            status=ProjectStatus.RUNNING.value,
            current_stage=self.stages[0].name,
            progress=0.0,
        )

        # 推送初始进度
        await self._emit(
            on_progress,
            EventType.PROGRESS,
            {
                "stage": self.stages[0].name,
                "progress": 0.0,
                "message": f"Pipeline 启动，即将执行 {self.stages[0].description}",
                "timestamp": _now_iso(),
            },
        )

        for stage_def in self.stages:
            result.current_stage = stage_def.name
            _update_project_status(
                project_id,
                current_stage=stage_def.name,
            )

            await self._emit(
                on_progress,
                EventType.PROGRESS,
                {
                    "stage": stage_def.name,
                    "progress": stage_def.progress,
                    "message": f"开始执行 {stage_def.description}",
                    "timestamp": _now_iso(),
                },
            )

            try:
                # 执行阶段（同步函数包到线程池）
                stage_result = await asyncio.to_thread(stage_def.fn, project_id)

                result.stages_completed.append(stage_def.name)
                result.progress = stage_def.progress
                result.stage_results[stage_def.name] = (
                    stage_result.to_dict() if hasattr(stage_result, "to_dict") else str(stage_result)
                )

                # 写回 s3 聚类信息到 project.config（供报告引用）
                if stage_def.name == "s3_cluster" and isinstance(
                    stage_result, ClusterStageResult
                ):
                    self._persist_cluster_info(project_id, stage_result)

                _update_project_status(
                    project_id, progress=stage_def.progress
                )

                await self._emit(
                    on_progress,
                    EventType.STAGE_DONE,
                    {
                        "stage": stage_def.name,
                        "progress": stage_def.progress,
                        "duration_ms": 0,  # 简化：不精确计时
                        "output_summary": self._summarize_stage(stage_def.name, stage_result),
                        "timestamp": _now_iso(),
                    },
                )

            except StageError as e:
                result.stages_failed.append(stage_def.name)
                logger.error(
                    "[orchestrator] 阶段 %s 失败: %s (recoverable=%s)",
                    stage_def.name,
                    e,
                    stage_def.recoverable,
                )

                if not stage_def.recoverable:
                    # 不可降级 → 标记 failed 并中止
                    result.status = ProjectStatus.FAILED.value
                    result.error = f"[{stage_def.name}] {e.message}"
                    _update_project_status(
                        project_id, status=ProjectStatus.FAILED.value
                    )
                    await self._emit(
                        on_progress,
                        EventType.ERROR,
                        {
                            "stage": stage_def.name,
                            "message": e.message,
                            "error_code": e.code,
                            "timestamp": _now_iso(),
                        },
                    )
                    result.completed_at = datetime.now(timezone.utc)
                    return result
                else:
                    # 可降级 → 继续
                    await self._emit(
                        on_progress,
                        EventType.STAGE_WARNING,
                        {
                            "stage": stage_def.name,
                            "message": f"阶段降级继续: {e.message}",
                            "error_code": e.code,
                            "timestamp": _now_iso(),
                        },
                    )

            except Exception as e:
                # 未预期异常 → 视为不可降级
                result.stages_failed.append(stage_def.name)
                logger.exception(
                    "[orchestrator] 阶段 %s 未预期异常", stage_def.name
                )
                result.status = ProjectStatus.FAILED.value
                result.error = f"[{stage_def.name}] 未预期异常: {e}"
                _update_project_status(
                    project_id, status=ProjectStatus.FAILED.value
                )
                await self._emit(
                    on_progress,
                    EventType.ERROR,
                    {
                        "stage": stage_def.name,
                        "message": str(e),
                        "error_code": 5000,
                        "timestamp": _now_iso(),
                    },
                )
                result.completed_at = datetime.now(timezone.utc)
                return result

        # 全部完成
        result.status = ProjectStatus.COMPLETED.value
        result.progress = 1.0
        result.completed_at = datetime.now(timezone.utc)
        _update_project_status(project_id, completed=True)

        await self._emit(
            on_progress,
            EventType.COMPLETE,
            {
                "project_id": project_id,
                "status": ProjectStatus.COMPLETED.value,
                "progress": 1.0,
                "report_url": f"/api/v1/projects/{project_id}/report",
                "timestamp": _now_iso(),
            },
        )

        logger.info(
            "[orchestrator] pipeline 完成 project_id=%s completed=%d failed=%d",
            project_id,
            len(result.stages_completed),
            len(result.stages_failed),
        )
        return result

    # ---------- 内部工具 ----------
    async def _emit(
        self,
        callback: ProgressCallback | None,
        event_type: str,
        data: dict[str, Any],
    ) -> None:
        """推送 SSE 事件."""
        if callback is None:
            return
        event = {"event": event_type, "data": data}
        try:
            ret = callback(event)
            if asyncio.iscoroutine(ret):
                await ret
        except Exception as e:
            logger.warning("进度回调异常: %s", e)

    @staticmethod
    def _summarize_stage(name: str, result: Any) -> str:
        """生成阶段输出摘要."""
        try:
            if isinstance(result, IngestResult):
                return f"入库 {result.inserted} 条（重复 {result.skipped_duplicate}）"
            if isinstance(result, PreprocessResult):
                return f"处理 {result.total} 条，差评 {result.marked_negative} 条"
            if isinstance(result, ClusterStageResult):
                return (
                    f"差评 {result.negative_count} 条 → {result.cluster_k} 簇 "
                    f"(silhouette={result.silhouette_score:.4f})"
                )
            if isinstance(result, LabelStageResult):
                return f"生成 {result.labeled_count} 个痛点标签"
            if isinstance(result, AttributeStageResult):
                return (
                    f"Top5 归因完成: {settings.ATTRIBUTION_MODEL} 成功 "
                    f"{result.primary_success}，降级 {result.fallback_count}"
                )
            if isinstance(result, SuggestStageResult):
                return (
                    f"改进建议 {result.suggestions_generated} 条，"
                    f"Listing 卖点 {result.listing_suggestions_generated} 条"
                )
            if isinstance(result, ReportStageResult):
                return f"报告已生成 ({result.char_count} 字符)"
        except Exception:
            pass
        return str(result)[:100]

    @staticmethod
    def _persist_cluster_info(project_id: str, result: ClusterStageResult) -> None:
        """将聚类质量指标写入 project.config.cluster_info."""
        from sqlalchemy import select

        with get_session() as session:
            project = session.get(Project, project_id)
            if project is None:
                return
            cfg = project.config or {}
            cfg["cluster_info"] = {
                "k": result.cluster_k,
                "silhouette_score": result.silhouette_score,
                "fell_back": result.fell_back,
                "fallback_reason": result.fallback_reason,
                "cluster_sizes": result.cluster_sizes,
                "embedded_count": result.embedded_count,
                "negative_count": result.negative_count,
            }
            project.config = cfg
            session.commit()


def _now_iso() -> str:
    """当前 UTC ISO 时间."""
    return datetime.now(timezone.utc).isoformat()


# ---------- 全局单例 ----------
_orchestrator: PipelineOrchestrator | None = None


def get_orchestrator() -> PipelineOrchestrator:
    """获取全局编排器单例."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = PipelineOrchestrator()
    return _orchestrator


# ---------- 便捷运行 ----------
async def run_pipeline(
    project_id: str,
    on_progress: ProgressCallback | None = None,
    config: dict[str, Any] | None = None,
) -> PipelineResult:
    """便捷函数：执行完整 pipeline."""
    orch = get_orchestrator()
    return await orch.run(project_id, on_progress=on_progress, config=config)
