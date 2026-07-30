"""Stage 6: 改进建议生成 + Listing 卖点建议.

职责:
1. 对每个有归因的痛点（is_top5=true 且有 attribution）:
   - qwen-max 整合归因结果 → 生成改进建议卡片
   - 写入 suggestions 表（type='product_improvement'）
   - 同时更新 pain_points 的 quadrant 信息（写入第一条 suggestion 的 quadrant）
2. 分析共性弱点（is_common_weakness=true 的痛点）:
   - qwen-max 生成 Listing 卖点建议
   - 写入 listing_suggestions 表

四象限分类:
- quick_win: 高影响 + 易解决
- strategic: 高影响 + 难解决
- filler: 低影响 + 易解决
- thankless: 低影响 + 难解决

输入: project_id
输出: SuggestStageResult 统计
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.exceptions import LLMError, JSONParseError, StageError
from app.core.logging import get_logger
from app.models.database import get_session
from app.models.schemas import (
    Attribution,
    ListingSuggestion,
    PainPoint,
    Project,
    Suggestion,
)
from app.pipeline.prompts import listing as listing_prompts
from app.pipeline.prompts import suggestions as suggestions_prompts
from app.services.model_router import get_model_router

logger = get_logger(__name__)


@dataclass
class SuggestStageResult:
    """s6 建议阶段结果."""

    top5_pain_point_count: int = 0
    """有归因的 Top 5 痛点数"""

    suggestions_generated: int = 0
    """生成的改进建议条数"""

    common_weakness_count: int = 0
    """共性弱点数"""

    listing_suggestions_generated: int = 0
    """Listing 卖点建议条数"""

    failed: int = 0
    """失败次数"""

    by_pain_point: dict[str, dict[str, Any]] = field(default_factory=dict)
    """每个痛点的建议摘要"""

    def to_dict(self) -> dict:
        return {
            "top5_pain_point_count": self.top5_pain_point_count,
            "suggestions_generated": self.suggestions_generated,
            "common_weakness_count": self.common_weakness_count,
            "listing_suggestions_generated": self.listing_suggestions_generated,
            "failed": self.failed,
            "by_pain_point": self.by_pain_point,
        }


async def _call_qwen_json(messages: list[dict], schema: dict) -> dict:
    """调用 qwen-max JSON 输出."""
    client = get_model_router()
    return await client.chat_json(
        messages=messages,
        model=settings.MODEL_LLM,
        schema=schema,
        temperature=0.3,
    )


def _generate_suggestions_for_pain_point(
    pp: PainPoint, attribution: Attribution
) -> dict[str, Any]:
    """为单个痛点生成改进建议.

    Returns:
        {"suggestions": [{content,cost,priority}], "quadrant": str, "quadrant_reason": str}
    """
    # 解析归因数据
    evidence = attribution.evidence_list
    measures = attribution.measures_list

    messages = suggestions_prompts.build_messages(
        label=pp.label,
        impact_ratio=pp.impact_ratio,
        avg_rating=pp.avg_rating if pp.avg_rating is not None else 0.0,
        review_count=pp.review_count,
        trend=pp.trend or "unknown",
        root_cause=attribution.root_cause,
        evidence=evidence,
        r1_measures=measures,
    )

    try:
        result = asyncio.run(_call_qwen_json(messages, suggestions_prompts.OUTPUT_SCHEMA))
        return {
            "suggestions": result.get("suggestions", []) or [],
            "quadrant": result.get("quadrant", "strategic"),
            "quadrant_reason": result.get("quadrant_reason", ""),
        }
    except (LLMError, JSONParseError) as e:
        logger.warning(
            "[s6_suggest] 痛点 %s 建议生成失败: %s", pp.id[:8], e
        )
        return {
            "suggestions": [],
            "quadrant": "strategic",
            "quadrant_reason": f"（生成失败）{e}",
        }


def _generate_listing_suggestions(
    weaknesses: list[PainPoint], category: str
) -> list[dict[str, Any]]:
    """为共性弱点生成 Listing 卖点建议."""
    if not weaknesses:
        return []

    # 构造 prompt 输入
    weakness_dicts = []
    for pp in weaknesses:
        weakness_dicts.append(
            {
                "label": pp.label,
                "description": pp.description or "",
                "impact_ratio": pp.impact_ratio,
                "competitor_breakdown": pp.competitor_breakdown_dict,
            }
        )

    messages = listing_prompts.build_messages(weakness_dicts, category=category)
    try:
        result = asyncio.run(_call_qwen_json(messages, listing_prompts.OUTPUT_SCHEMA))
        return result.get("listing_suggestions", []) or []
    except (LLMError, JSONParseError) as e:
        logger.warning("[s6_suggest] Listing 卖点生成失败: %s", e)
        return []


def run_s6_suggest(project_id: str) -> SuggestStageResult:
    """执行 s6_suggest 阶段.

    Args:
        project_id: 项目 ID

    Returns:
        SuggestStageResult

    Raises:
        StageError: 项目不存在
    """
    logger.info("[s6_suggest] 开始 project_id=%s", project_id)
    result = SuggestStageResult()

    # 1. 校验项目
    with get_session() as session:
        project = session.get(Project, project_id)
        if project is None:
            raise StageError(
                "s6_suggest",
                f"项目不存在: {project_id}",
                code=1001,
                recoverable=False,
            )
        category = project.category

        # 清空旧 suggestions + listing_suggestions（支持重复执行）
        session.execute(
            delete(Suggestion).where(Suggestion.project_id == project_id)
        )
        session.execute(
            delete(ListingSuggestion).where(ListingSuggestion.project_id == project_id)
        )
        session.commit()

    # 2. 拉取有归因的 Top 5 痛点
    with get_session() as session:
        pairs = (
            session.execute(
                select(PainPoint, Attribution)
                .join(Attribution, Attribution.pain_point_id == PainPoint.id)
                .where(PainPoint.project_id == project_id)
                .where(PainPoint.is_top5.is_(True))
                .order_by(PainPoint.rank_by_impact.asc())
            )
            .all()
        )
        # detach
        session.expunge_all()

    result.top5_pain_point_count = len(pairs)
    if result.top5_pain_point_count == 0:
        logger.warning(
            "[s6_suggest] 项目 %s 无有归因的 Top 5 痛点", project_id
        )

    # 3. 逐个痛点生成改进建议
    suggestions_to_create: list[Suggestion] = []
    pp_quadrant_updates: dict[str, str] = {}  # pain_point_id -> quadrant

    for pp, attr in pairs:
        sug_data = _generate_suggestions_for_pain_point(pp, attr)
        sug_list = sug_data.get("suggestions", [])
        quadrant = sug_data.get("quadrant", "strategic")
        quadrant_reason = sug_data.get("quadrant_reason", "")

        if not sug_list:
            result.failed += 1
            result.by_pain_point[pp.id] = {
                "label": pp.label,
                "suggestions_count": 0,
                "quadrant": quadrant,
                "quadrant_reason": quadrant_reason,
            }
            continue

        for sug in sug_list:
            content = str(sug.get("content", "")).strip()
            if not content:
                continue
            cost = str(sug.get("cost", "medium")).lower()
            if cost not in {"low", "medium", "high"}:
                cost = "medium"
            priority = str(sug.get("priority", "medium")).lower()
            if priority not in {"high", "medium", "low"}:
                priority = "medium"

            suggestions_to_create.append(
                Suggestion(
                    pain_point_id=pp.id,
                    project_id=project_id,
                    type="product_improvement",
                    content=content,
                    cost=cost,
                    priority=priority,
                    quadrant=quadrant,
                )
            )
            result.suggestions_generated += 1

        pp_quadrant_updates[pp.id] = quadrant
        result.by_pain_point[pp.id] = {
            "label": pp.label,
            "suggestions_count": len(sug_list),
            "quadrant": quadrant,
            "quadrant_reason": quadrant_reason,
        }

    # 4. 拉取共性弱点
    with get_session() as session:
        weaknesses = (
            session.execute(
                select(PainPoint)
                .where(PainPoint.project_id == project_id)
                .where(PainPoint.is_common_weakness.is_(True))
                .order_by(PainPoint.rank_by_impact.asc())
            )
            .scalars()
            .all()
        )
        session.expunge_all()

    result.common_weakness_count = len(weaknesses)

    # 5. 生成 Listing 卖点建议
    listing_suggestions_to_create: list[ListingSuggestion] = []
    if weaknesses:
        listing_data = _generate_listing_suggestions(list(weaknesses), category)
        for ls in listing_data:
            weakness = str(ls.get("competitor_weakness", "")).strip()
            selling_point = str(ls.get("suggested_selling_point", "")).strip()
            if not weakness or not selling_point:
                continue
            listing_field = str(ls.get("listing_field", "bullet_point")).lower()
            if listing_field not in {"title", "bullet_point", "a_plus_content", "image"}:
                listing_field = "bullet_point"
            priority = str(ls.get("priority", "medium")).lower()
            if priority not in {"high", "medium", "low"}:
                priority = "medium"

            listing_suggestions_to_create.append(
                ListingSuggestion(
                    project_id=project_id,
                    competitor_weakness=weakness,
                    suggested_selling_point=selling_point,
                    listing_field=listing_field,
                    priority=priority,
                    rationale=str(ls.get("rationale", "")) or None,
                )
            )
            result.listing_suggestions_generated += 1

    # 6. 写入数据库
    try:
        with get_session() as session:
            for sug in suggestions_to_create:
                session.add(sug)
            for ls in listing_suggestions_to_create:
                session.add(ls)
            session.commit()
    except SQLAlchemyError as e:
        raise StageError(
            "s6_suggest",
            f"写入建议失败: {e}",
            code=5001,
            cause=e,
            recoverable=False,
        ) from e

    logger.info(
        "[s6_suggest] 完成 top5=%d suggestions=%d common_weakness=%d listing=%d",
        result.top5_pain_point_count,
        result.suggestions_generated,
        result.common_weakness_count,
        result.listing_suggestions_generated,
    )
    return result


# ---------- 命令行入口 ----------
if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="s6_suggest: 改进建议生成")
    parser.add_argument("--project-id", required=True, help="项目 ID")
    args = parser.parse_args()

    try:
        r = run_s6_suggest(args.project_id)
        print(
            f"建议生成完成: top5={r.top5_pain_point_count} "
            f"suggestions={r.suggestions_generated} listing={r.listing_suggestions_generated}"
        )
        for pid, info in r.by_pain_point.items():
            print(
                f"  [{pid[:8]}] {info['label']} → {info['suggestions_count']} 条建议 "
                f"(quadrant={info['quadrant']})"
            )
    except StageError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)
