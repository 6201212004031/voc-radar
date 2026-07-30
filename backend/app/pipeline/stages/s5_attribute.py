"""Stage 5: R1 根因归因（Top 8→Top 5 筛选 + R1 调用 + 证据解析）.

职责:
1. 取 rank_by_impact 前 8 的痛点（candidates）
2. 过滤 suitable_for_reasoning=true 的，取前 5 → Top 5
3. 标记 pain_points.is_top5 = true
4. 对每个 Top 5 痛点调用 DeepSeek-R1:
   - System: 产品根因分析专家，规则：引用原文/不编造/信息不足说明"无法确认"
   - User: 痛点标签 + 代表性评论 Top 10 + [可选]图片缺陷标签
5. 解析 R1 输出（json_helpers 容错解析）
6. 写入 attributions 表（model_used='deepseek-r1'）
7. R1 失败时降级用 qwen3.7-max（model_used='qwen3.7-max'）

输入: project_id
输出: AttributeStageResult 统计
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.exceptions import LLMError, JSONParseError, StageError
from app.core.logging import get_logger
from app.models.database import get_session
from app.models.schemas import Attribution, PainPoint, Project, Review
from app.pipeline.prompts import r1_attribution as r1_prompts
from app.services.model_router import get_model_router

logger = get_logger(__name__)


@dataclass
class AttributeStageResult:
    """s5 归因阶段结果."""

    candidates_count: int = 0
    """Top 8 候选数"""

    top5_count: int = 0
    """实际进入 R1 归因的 Top 5 数"""

    r1_success: int = 0
    """R1 成功调用数"""

    r1_failed: int = 0
    """R1 失败数（已降级到 qwen-max）"""

    qwen_fallback_count: int = 0
    """降级到 qwen-max 的次数"""

    by_pain_point: dict[str, dict[str, Any]] = field(default_factory=dict)
    """每个 Top 5 痛点的归因结果摘要"""

    def to_dict(self) -> dict:
        return {
            "candidates_count": self.candidates_count,
            "top5_count": self.top5_count,
            "r1_success": self.r1_success,
            "r1_failed": self.r1_failed,
            "qwen_fallback_count": self.qwen_fallback_count,
            "by_pain_point": self.by_pain_point,
        }


def _review_to_dict(r: Review) -> dict:
    """Review 转 prompt 所需 dict."""
    return {
        "review_id": r.id,
        "rating": r.rating,
        "title": r.title or "",
        "body": r.body or "",
        "helpful_votes": r.helpful_votes or 0,
        "asin": r.asin,
    }


def _select_top5(project_id: str) -> tuple[list[PainPoint], list[PainPoint]]:
    """选择 Top 8 候选 + Top 5.

    Returns:
        (candidates_top8, top5) — top5 是 candidates_top8 的子集
    """
    with get_session() as session:
        # 取 rank_by_impact 前 8
        candidates = (
            session.execute(
                select(PainPoint)
                .where(PainPoint.project_id == project_id)
                .order_by(PainPoint.rank_by_impact.asc())
                .limit(settings.TOP_N_CANDIDATES)
            )
            .scalars()
            .all()
        )
        # 过滤 suitable_for_reasoning=true，取前 5
        top5_list = [p for p in candidates if p.suitable_for_reasoning][
            : settings.TOP_N_FOR_R1
        ]
        # detach
        session.expunge_all()
    return list(candidates), list(top5_list)


def _fetch_representative_reviews(
    project_id: str, cluster_id: int, top_n: int = 10
) -> list[Review]:
    """取该簇的代表性评论 Top N."""
    with get_session() as session:
        reviews = (
            session.execute(
                select(Review)
                .where(Review.project_id == project_id)
                .where(Review.cluster_id == cluster_id)
                .order_by(Review.is_representative.desc(), Review.helpful_votes.desc())
                .limit(top_n)
            )
            .scalars()
            .all()
        )
        session.expunge_all()
    return list(reviews)


async def _call_r1(messages: list[dict]) -> dict:
    """调用 R1 进行 JSON 输出."""
    client = get_model_router()
    return await client.chat_json(
        messages=messages,
        model=settings.MODEL_R1,
        schema=r1_prompts.OUTPUT_SCHEMA,
        temperature=0.3,
    )


async def _call_qwen_fallback(messages: list[dict]) -> dict:
    """降级调用 qwen-max."""
    client = get_model_router()
    return await client.chat_json(
        messages=messages,
        model=settings.MODEL_LLM,
        schema=r1_prompts.OUTPUT_SCHEMA,
        temperature=0.3,
    )


def _attribute_one_pain_point(
    pain_point: PainPoint,
    reviews: list[Review],
    vision_tags: list[str] | None = None,
) -> dict[str, Any]:
    """对单个痛点做 R1 归因，失败时降级 qwen-max.

    Returns:
        {
            "root_cause": str,
            "evidence": list[dict],
            "improvement_measures": list[dict],
            "model_used": "deepseek-r1" | "qwen3.7-max",
            "latency_ms": int,
            "prompt_tokens": int | None,
            "completion_tokens": int | None,
            "fallback_reason": str | None,
        }
    """
    review_dicts = [_review_to_dict(r) for r in reviews]
    messages = r1_prompts.build_messages(
        label=pain_point.label,
        description=pain_point.description or "",
        reviews=review_dicts,
        vision_tags=vision_tags,
        top_n=len(review_dicts),
    )

    start = time.time()
    model_used = settings.MODEL_R1
    fallback_reason: str | None = None

    try:
        result = asyncio.run(_call_r1(messages))
        logger.info(
            "[s5_attribute] R1 归因成功 pain_point=%s", pain_point.id[:8]
        )
    except (LLMError, JSONParseError) as e:
        logger.warning(
            "[s5_attribute] R1 归因失败 pain_point=%s: %s，降级 qwen-max",
            pain_point.id[:8],
            e,
        )
        fallback_reason = str(e)
        model_used = settings.MODEL_LLM
        try:
            result = asyncio.run(_call_qwen_fallback(messages))
        except (LLMError, JSONParseError) as e2:
            logger.error(
                "[s5_attribute] qwen-max 降级也失败 pain_point=%s: %s",
                pain_point.id[:8],
                e2,
            )
            # 最终降级：用文本存储
            result = {
                "root_cause": f"（归因失败）{e2}",
                "evidence": [],
                "improvement_measures": [],
            }

    latency_ms = int((time.time() - start) * 1000)

    # 规范化字段
    root_cause = str(result.get("root_cause", ""))
    evidence = result.get("evidence", []) or []
    if not isinstance(evidence, list):
        evidence = []
    improvement_measures = result.get("improvement_measures", []) or []
    if not isinstance(improvement_measures, list):
        improvement_measures = []

    return {
        "root_cause": root_cause,
        "evidence": evidence,
        "improvement_measures": improvement_measures,
        "model_used": model_used,
        "latency_ms": latency_ms,
        "prompt_tokens": None,  # SDK 1.x chat_json 暂未回传 usage
        "completion_tokens": None,
        "fallback_reason": fallback_reason,
    }


def run_s5_attribute(project_id: str) -> AttributeStageResult:
    """执行 s5_attribute 阶段.

    Args:
        project_id: 项目 ID

    Returns:
        AttributeStageResult

    Raises:
        StageError: 项目不存在 / 无 pain_points 数据
    """
    logger.info("[s5_attribute] 开始 project_id=%s", project_id)
    result = AttributeStageResult()

    # 1. 校验项目
    with get_session() as session:
        project = session.get(Project, project_id)
        if project is None:
            raise StageError(
                "s5_attribute",
                f"项目不存在: {project_id}",
                code=1001,
                recoverable=False,
            )

        # 清空旧 attributions（支持重复执行）
        from sqlalchemy import delete

        session.execute(
            delete(Attribution).where(Attribution.project_id == project_id)
        )
        # 重置 pain_points.is_top5
        session.execute(
            update(PainPoint)
            .where(PainPoint.project_id == project_id)
            .values(is_top5=False)
        )
        session.commit()

    # 2. 选 Top 8 候选 + Top 5
    candidates, top5_list = _select_top5(project_id)
    result.candidates_count = len(candidates)
    result.top5_count = len(top5_list)

    if result.top5_count == 0:
        logger.warning(
            "[s5_attribute] 项目 %s 无适合推理的 Top 5 痛点", project_id
        )
        return result

    logger.info(
        "[s5_attribute] 候选 %d, Top 5 %d", result.candidates_count, result.top5_count
    )

    # 3. 标记 is_top5
    top5_ids = {p.id for p in top5_list}
    with get_session() as session:
        session.execute(
            update(PainPoint)
            .where(PainPoint.id.in_(top5_ids))
            .values(is_top5=True)
        )
        session.commit()

    # 4. 逐个调用 R1
    attributions_to_create: list[Attribution] = []

    for pp in top5_list:
        # 取代表性评论
        reviews = _fetch_representative_reviews(project_id, pp.cluster_id, top_n=10)
        if not reviews:
            logger.warning(
                "[s5_attribute] 痛点 %s (cluster=%d) 无代表性评论",
                pp.id[:8],
                pp.cluster_id,
            )
            reviews = []

        try:
            attr_data = _attribute_one_pain_point(pp, reviews)
            if attr_data["model_used"] == settings.MODEL_R1:
                result.r1_success += 1
            else:
                result.r1_failed += 1
                result.qwen_fallback_count += 1
        except Exception as e:
            logger.error(
                "[s5_attribute] 痛点 %s 归因异常: %s", pp.id[:8], e
            )
            result.r1_failed += 1
            result.qwen_fallback_count += 1
            attr_data = {
                "root_cause": f"（归因异常）{e}",
                "evidence": [],
                "improvement_measures": [],
                "model_used": settings.MODEL_LLM,
                "latency_ms": 0,
                "prompt_tokens": None,
                "completion_tokens": None,
                "fallback_reason": str(e),
            }

        # 构造 Attribution
        attr = Attribution(
            pain_point_id=pp.id,
            project_id=project_id,
            root_cause=attr_data["root_cause"],
            evidence=json.dumps(attr_data["evidence"], ensure_ascii=False),
            improvement_measures=json.dumps(
                attr_data["improvement_measures"], ensure_ascii=False
            )
            if attr_data["improvement_measures"]
            else None,
            model_used=attr_data["model_used"],
            prompt_tokens=attr_data["prompt_tokens"],
            completion_tokens=attr_data["completion_tokens"],
            latency_ms=attr_data["latency_ms"],
        )
        attributions_to_create.append(attr)

        result.by_pain_point[pp.id] = {
            "label": pp.label,
            "cluster_id": pp.cluster_id,
            "model_used": attr_data["model_used"],
            "root_cause_preview": attr_data["root_cause"][:80],
            "evidence_count": len(attr_data["evidence"]),
            "measures_count": len(attr_data["improvement_measures"]),
            "latency_ms": attr_data["latency_ms"],
            "fallback_reason": attr_data["fallback_reason"],
        }

    # 5. 写入 attributions 表
    try:
        with get_session() as session:
            for attr in attributions_to_create:
                session.add(attr)
            session.commit()
    except SQLAlchemyError as e:
        raise StageError(
            "s5_attribute",
            f"写入 attributions 失败: {e}",
            code=5001,
            cause=e,
            recoverable=False,
        ) from e

    logger.info(
        "[s5_attribute] 完成 top5=%d r1_success=%d r1_failed=%d fallback=%d",
        result.top5_count,
        result.r1_success,
        result.r1_failed,
        result.qwen_fallback_count,
    )
    return result


# ---------- 命令行入口 ----------
if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="s5_attribute: R1 根因归因")
    parser.add_argument("--project-id", required=True, help="项目 ID")
    args = parser.parse_args()

    try:
        r = run_s5_attribute(args.project_id)
        print(
            f"归因完成: 候选={r.candidates_count} top5={r.top5_count} "
            f"r1_success={r.r1_success} r1_failed={r.r1_failed} fallback={r.qwen_fallback_count}"
        )
        for pid, info in r.by_pain_point.items():
            print(
                f"  [{pid[:8]}] {info['label']} (cluster={info['cluster_id']}, "
                f"model={info['model_used']}, latency={info['latency_ms']}ms)"
            )
            print(f"    根因: {info['root_cause_preview']}")
    except StageError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)
