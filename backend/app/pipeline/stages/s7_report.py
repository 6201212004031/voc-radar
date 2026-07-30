"""Stage 7: 报告整合（Jinja2 渲染 Markdown）.

职责:
1. 从 DB 读取全部分析结果（项目/评论统计/pain_points/attributions/suggestions/listing_suggestions）
2. 用 Jinja2 模板渲染 Markdown 报告
3. 报告结构:
   - 概览（竞品数/评论数/痛点数/R1归因数）
   - 痛点排名表（label/影响面/星级/趋势）
   - Top 5 痛点根因归因（根因+证据+改进措施）
   - 改进优先级矩阵
   - 差异化卖点建议清单
4. 输出到 data/reports/{project_id}.md（幂等覆盖）

输入: project_id
输出: ReportStageResult（含文件路径与字符数）
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Template
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.exceptions import StageError
from app.core.logging import get_logger
from app.models.database import get_session
from app.models.schemas import (
    Attribution,
    ListingSuggestion,
    PainPoint,
    Project,
    Review,
    Suggestion,
)

logger = get_logger(__name__)


# ---------- Markdown 报告模板 ----------
REPORT_TEMPLATE = """# {{ project.name }} — 评论分析报告

> 生成时间: {{ generated_at }}
> 品类: {{ project.category }}
> 项目状态: {{ project.status }}

---

## 一、概览

| 指标 | 数值 |
|------|------|
| 竞品数 | {{ kpis.competitor_count }} |
| 评论总数 | {{ kpis.review_count }} |
| 差评数（rating≤3） | {{ kpis.negative_review_count }} |
| 痛点簇数 | {{ kpis.pain_point_count }} |
| R1 归因数（Top 5） | {{ kpis.r1_attribution_count }} |
| 共性弱点数 | {{ kpis.common_weakness_count }} |
| 改进建议数 | {{ kpis.suggestion_count }} |
| Listing 卖点建议数 | {{ kpis.listing_suggestion_count }} |

{% if kpis.competitor_asins %}
**竞品 ASIN**: {{ kpis.competitor_asins | join(", ") }}
{% endif %}

---

## 二、痛点排名（按影响面排序）

| 排名 | 痛点标签 | 影响面 | 评论数 | 平均星级 | 趋势 | 共性弱点 | 适合推理 |
|------|---------|--------|--------|----------|------|----------|----------|
{% for pp in pain_points %}| {{ pp.rank_by_impact }} | {{ pp.label }} | {{ "%.1f" | format(pp.impact_ratio * 100) }}% | {{ pp.review_count }} | {{ "%.1f" | format(pp.avg_rating) if pp.avg_rating else "-" }} | {{ pp.trend or "-" }} | {{ "是" if pp.is_common_weakness else "否" }} | {{ "是" if pp.suitable_for_reasoning else "否" }} |
{% endfor %}

---

## 三、Top 5 痛点根因归因

{% for item in top5_details %}
### {{ loop.index }}. {{ item.pain_point.label }}

**影响面**: {{ "%.1f" | format(item.pain_point.impact_ratio * 100) }}% ({{ item.pain_point.review_count }} 条评论) | **平均星级**: {{ "%.1f" | format(item.pain_point.avg_rating) if item.pain_point.avg_rating else "-" }} | **趋势**: {{ item.pain_point.trend or "未知" }}

#### 根因
{{ item.attribution.root_cause }}

#### 证据
{% for ev in item.attribution.evidence_list %}
- **[{{ ev.review_id[:12] if ev.review_id else "?" }}]** "{{ ev.quote }}"
  - {{ ev.explanation }}
{% endfor %}

#### 改进措施
{% for m in item.attribution.measures_list %}
- {{ m.measure }} (成本: {{ m.cost }}, 优先级: {{ m.priority }})
{% endfor %}

**归因模型**: {{ item.attribution.model_used }} | 耗时: {{ item.attribution.latency_ms }}ms

---

{% endfor %}

## 四、改进优先级矩阵

| 象限 | 含义 | 痛点 |
|------|------|------|
| 快赢 (quick_win) | 高影响 + 易解决 | {% for pp in quadrants.quick_win %}{{ pp.label }}{% if not loop.last %}, {% endif %}{% endfor %} |
| 战略 (strategic) | 高影响 + 难解决 | {% for pp in quadrants.strategic %}{{ pp.label }}{% if not loop.last %}, {% endif %}{% endfor %} |
| 填充 (filler) | 低影响 + 易解决 | {% for pp in quadrants.filler %}{{ pp.label }}{% if not loop.last %}, {% endif %}{% endfor %} |
| 费力不讨好 (thankless) | 低影响 + 难解决 | {% for pp in quadrants.thankless %}{{ pp.label }}{% if not loop.last %}, {% endif %}{% endfor %} |

---

## 五、改进建议清单

{% for sug in all_suggestions %}
- **[{{ sug.priority | upper }}]** {{ sug.content }}
  - 痛点: {{ sug.pain_point_label }} | 成本: {{ sug.cost }} | 象限: {{ sug.quadrant }}
{% endfor %}

---

## 六、差异化 Listing 卖点建议

{% for ls in listing_suggestions %}
- **[{{ ls.priority | upper }}] {{ ls.competitor_weakness }}**
  - 建议卖点: {{ ls.suggested_selling_point }}
  - 字段: {{ ls.listing_field }}
  {% if ls.rationale %}  - 理由: {{ ls.rationale }}
  {% endif %}
{% endfor %}

---

## 七、附：聚类质量指标

- 聚类簇数 k = {{ cluster_k }}
- Silhouette 分数 = {{ "%.4f" | format(silhouette_score) if silhouette_score else "-" }}
{% if fell_back %}- ⚠️ 触发降级: {{ fallback_reason }}
{% endif %}

---

*本报告由 VOC Radar 评论雷达自动生成。R1 归因结果为 AI 辅助参考，最终决策请结合卖家自身判断。*
"""


@dataclass
class ReportStageResult:
    """s7 报告阶段结果."""

    report_path: str = ""
    """报告文件绝对路径"""

    char_count: int = 0
    """报告字符数"""

    pain_point_count: int = 0
    """报告包含的痛点数"""

    top5_count: int = 0
    """报告包含的 Top 5 归因数"""

    def to_dict(self) -> dict:
        return {
            "report_path": self.report_path,
            "char_count": self.char_count,
            "pain_point_count": self.pain_point_count,
            "top5_count": self.top5_count,
        }


def _gather_report_data(project_id: str) -> dict[str, Any]:
    """从 DB 汇总报告数据."""
    with get_session() as session:
        project = session.get(Project, project_id)
        if project is None:
            raise StageError(
                "s7_report",
                f"项目不存在: {project_id}",
                code=1001,
                recoverable=False,
            )

        # 评论统计
        review_count = session.execute(
            select(func.count(Review.id)).where(Review.project_id == project_id)
        ).scalar() or 0
        negative_count = session.execute(
            select(func.count(Review.id))
            .where(Review.project_id == project_id)
            .where(Review.is_negative.is_(True))
        ).scalar() or 0

        # 痛点
        pain_points = (
            session.execute(
                select(PainPoint)
                .where(PainPoint.project_id == project_id)
                .order_by(PainPoint.rank_by_impact.asc())
            )
            .scalars()
            .all()
        )

        # Top 5 归因（含 attribution）
        top5_with_attr = (
            session.execute(
                select(PainPoint, Attribution)
                .join(Attribution, Attribution.pain_point_id == PainPoint.id)
                .where(PainPoint.project_id == project_id)
                .where(PainPoint.is_top5.is_(True))
                .order_by(PainPoint.rank_by_impact.asc())
            )
            .all()
        )

        # 所有改进建议
        suggestions = (
            session.execute(
                select(Suggestion)
                .where(Suggestion.project_id == project_id)
                .order_by(Suggestion.priority.desc())
            )
            .scalars()
            .all()
        )

        # Listing 建议
        listing_suggestions = (
            session.execute(
                select(ListingSuggestion)
                .where(ListingSuggestion.project_id == project_id)
                .order_by(ListingSuggestion.priority.desc())
            )
            .scalars()
            .all()
        )

        # 竞品 ASIN 列表
        competitor_asins = project.competitor_asin_list

        # detach
        session.expunge_all()

    # 构造 KPI
    r1_count = len(top5_with_attr)
    common_weakness_count = sum(1 for p in pain_points if p.is_common_weakness)
    kpis = {
        "competitor_count": len(competitor_asins),
        "review_count": int(review_count),
        "negative_review_count": int(negative_count),
        "pain_point_count": len(pain_points),
        "r1_attribution_count": r1_count,
        "common_weakness_count": common_weakness_count,
        "suggestion_count": len(suggestions),
        "listing_suggestion_count": len(listing_suggestions),
        "competitor_asins": competitor_asins,
    }

    # Top 5 详情
    top5_details = []
    for pp, attr in top5_with_attr:
        top5_details.append({"pain_point": pp, "attribution": attr})

    # 四象限分组（按 suggestion 的 quadrant 字段，取每个痛点的第一条 suggestion 的象限）
    quadrants: dict[str, list[PainPoint]] = {
        "quick_win": [],
        "strategic": [],
        "filler": [],
        "thankless": [],
    }
    sug_by_pp: dict[str, Suggestion] = {}
    for sug in suggestions:
        if sug.pain_point_id not in sug_by_pp:
            sug_by_pp[sug.pain_point_id] = sug
    for pp in pain_points:
        sug = sug_by_pp.get(pp.id)
        if sug and sug.quadrant in quadrants:
            quadrants[sug.quadrant].append(pp)

    # 改进建议清单（含 pain_point label）
    all_suggestions = []
    pp_label_map = {p.id: p.label for p in pain_points}
    for sug in suggestions:
        all_suggestions.append(
            {
                "content": sug.content,
                "cost": sug.cost or "medium",
                "priority": sug.priority or "medium",
                "quadrant": sug.quadrant or "strategic",
                "pain_point_label": pp_label_map.get(sug.pain_point_id, "?"),
            }
        )

    # 聚类质量（从 project.config 取，s3 写入）
    cluster_info = project.config.get("cluster_info", {}) if project.config else {}
    cluster_k = cluster_info.get("k", 0)
    silhouette_score = cluster_info.get("silhouette_score", 0.0)
    fell_back = cluster_info.get("fell_back", False)
    fallback_reason = cluster_info.get("fallback_reason", "")

    return {
        "project": project,
        "kpis": kpis,
        "pain_points": pain_points,
        "top5_details": top5_details,
        "quadrants": quadrants,
        "all_suggestions": all_suggestions,
        "listing_suggestions": listing_suggestions,
        "cluster_k": cluster_k,
        "silhouette_score": silhouette_score,
        "fell_back": fell_back,
        "fallback_reason": fallback_reason,
    }


def render_report(data: dict[str, Any]) -> str:
    """渲染 Markdown 报告."""
    template = Template(REPORT_TEMPLATE, trim_blocks=True, lstrip_blocks=True)
    return template.render(
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        **data,
    )


def run_s7_report(project_id: str) -> ReportStageResult:
    """执行 s7_report 阶段.

    Args:
        project_id: 项目 ID

    Returns:
        ReportStageResult

    Raises:
        StageError: 项目不存在或渲染失败
    """
    logger.info("[s7_report] 开始 project_id=%s", project_id)
    result = ReportStageResult()

    try:
        data = _gather_report_data(project_id)
    except StageError:
        raise
    except Exception as e:
        raise StageError(
            "s7_report",
            f"汇总报告数据失败: {e}",
            code=5001,
            cause=e,
            recoverable=False,
        ) from e

    result.pain_point_count = len(data["pain_points"])
    result.top5_count = len(data["top5_details"])

    try:
        markdown = render_report(data)
    except Exception as e:
        raise StageError(
            "s7_report",
            f"渲染 Markdown 失败: {e}",
            code=5001,
            cause=e,
            recoverable=False,
        ) from e

    result.char_count = len(markdown)

    # 写入文件（幂等覆盖）
    try:
        report_dir = settings.report_dir
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"{project_id}.md"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(markdown)
        result.report_path = str(report_path)
    except OSError as e:
        raise StageError(
            "s7_report",
            f"写入报告文件失败: {e}",
            code=5001,
            cause=e,
            recoverable=False,
        ) from e

    logger.info(
        "[s7_report] 完成 path=%s chars=%d pain_points=%d top5=%d",
        result.report_path,
        result.char_count,
        result.pain_point_count,
        result.top5_count,
    )
    return result


# ---------- 命令行入口 ----------
if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="s7_report: Markdown 报告生成")
    parser.add_argument("--project-id", required=True, help="项目 ID")
    args = parser.parse_args()

    try:
        r = run_s7_report(args.project_id)
        print(
            f"报告生成完成: {r.report_path} ({r.char_count} 字符, "
            f"痛点 {r.pain_point_count} 个, Top5 归因 {r.top5_count} 个)"
        )
    except StageError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)
