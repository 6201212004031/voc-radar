"""VOC Radar — 演示报告生成（mock）.

从 seed 数据聚合生成 Markdown 报告，写入 settings.report_dir/{project_id}.md，
使 /api/v1/projects/{id}/report 端点可用（pipeline 完成后本由 s7_report 生成）。

运行：
    cd backend
    /e/projects/voc-radar/.venv/Scripts/python.exe generate_report.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.config import settings  # noqa: E402
from app.models.database import get_session  # noqa: E402
from app.models.schemas import (  # noqa: E402
    Project,
    PainPoint,
    Attribution,
    Suggestion,
    ListingSuggestion,
    Review,
)

TREND = {"rising": "↗ 上升(恶化)", "falling": "↘ 下降(改善)", "stable": "→ 稳定"}


def main():
    with get_session() as s:
        p = s.query(Project).filter(Project.name.like("VOC Radar Demo%")).first()
        if not p:
            raise SystemExit("未找到 demo project，请先运行 seed_demo.py")
        pid = p.id
        pps = (
            s.query(PainPoint)
            .filter(PainPoint.project_id == pid)
            .order_by(PainPoint.rank_by_impact)
            .all()
        )
        pp_by_id = {pp.id: pp for pp in pps}
        attrs = {
            a.pain_point_id: a
            for a in s.query(Attribution).filter(Attribution.project_id == pid).all()
        }
        sugs = s.query(Suggestion).filter(Suggestion.project_id == pid).all()
        listings = (
            s.query(ListingSuggestion).filter(ListingSuggestion.project_id == pid).all()
        )
        neg = (
            s.query(Review)
            .filter(Review.project_id == pid, Review.is_negative.is_(True))
            .count()
        )

    md = []
    md.append(f"# VOC Radar 分析报告 · {p.name}")
    md.append("")
    md.append(
        f"> 品类：**{p.category}**  ｜  竞品数：{len(p.competitor_asin_list)}  ｜  "
        f"分析差评：{neg} 条  ｜  生成时间：{p.completed_at.strftime('%Y-%m-%d %H:%M') if p.completed_at else '-'}"
    )
    md.append("")

    # 一、痛点排名
    md.append("## 一、痛点排名（按影响面）")
    md.append("")
    md.append("| # | 痛点 | 影响面占比 | 平均星级 | 趋势 | 是否 Top5 归因 |")
    md.append("|---|------|-----------|---------|------|---------------|")
    for i, pp in enumerate(pps, 1):
        md.append(
            f"| {i} | {pp.label} | {pp.impact_ratio*100:.1f}% | {pp.avg_rating}★ | "
            f"{TREND.get(pp.trend,'-')} | {'⭐ 是' if pp.is_top5 else '否'} |"
        )
    md.append("")

    # 二、Top5 归因
    # 归因模型如实取自 attributions.model_used（主力由 settings.ATTRIBUTION_MODEL 决定，
    # 默认 qwen3.7-max；deepseek-r1 仅作高难度可选补充通道）
    top5_models = []
    for pp in pps:
        if pp.is_top5 and pp.id in attrs:
            m = attrs[pp.id].model_used
            if m and m not in top5_models:
                top5_models.append(m)
    if not top5_models:
        model_desc = settings.ATTRIBUTION_MODEL
    elif len(top5_models) == 1:
        model_desc = top5_models[0]
    else:
        model_desc = "主力 " + settings.ATTRIBUTION_MODEL
    md.append(f"## 二、Top5 痛点根因归因（{model_desc} · 证据驱动）")
    md.append("")
    for pp in pps:
        if pp.is_top5 and pp.id in attrs:
            a = attrs[pp.id]
            md.append(f"### {i_tag(pp, pps)} {pp.label}")
            md.append("")
            md.append(f"**根因**：{a.root_cause}")
            md.append("")
            md.append("**支撑证据（引用评论原文）**：")
            for e in a.evidence_list:
                md.append(f"- > \"{e.get('quote','')}\"  ——（{e.get('asin','')} · {e.get('rating','')}★）")
            md.append("")
            md.append("**改进措施**：")
            for m in a.measures_list:
                md.append(
                    f"- {m.get('measure','')}  （成本：{m.get('cost','-')} ／ 优先级：{m.get('priority','-')}）"
                )
            md.append("")

    # 三、改进优先级
    md.append("## 三、改进优先级清单")
    md.append("")
    md.append("| 痛点 | 类型 | 建议 | 成本 | 优先级 | 象限 |")
    md.append("|---|------|------|------|--------|------|")
    for su in sugs:
        label = pp_by_id.get(su.pain_point_id)
        label = label.label if label else su.pain_point_id[:8]
        md.append(
            f"| {label} | {su.type} | {su.content} | {su.cost or '-'} | "
            f"{su.priority or '-'} | {su.quadrant or '-'} |"
        )
    md.append("")

    # 四、Listing 卖点
    md.append("## 四、差异化卖点建议（竞品弱点 → 你的 Listing）")
    md.append("")
    for ls in listings:
        md.append(f"- **针对共性弱点**：{ls.competitor_weakness}")
        md.append(
            f"  - 建议卖点：{ls.suggested_selling_point}（字段：{ls.listing_field} · 优先级：{ls.priority}）"
        )
        md.append(f"  - 理由：{ls.rationale}")
    md.append("")

    content = "\n".join(md)
    settings.report_dir.mkdir(parents=True, exist_ok=True)
    out = settings.report_dir / f"{pid}.md"
    out.write_text(content, encoding="utf-8")
    print("✅ 报告已生成 ->", out)
    print("   字节数:", len(content.encode("utf-8")))


def i_tag(pp, pps):
    return str([i for i, x in enumerate(pps, 1) if x.id == pp.id][0])


if __name__ == "__main__":
    main()
