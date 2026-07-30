"""改进建议 Prompt（s6_suggest 使用）.

输入: 痛点归因结果（root_cause / evidence / improvement_measures）+ 痛点标签/影响面
输出: 结构化改进卡片（含四象限分类）
"""
from __future__ import annotations

# ---------- System Prompt ----------
SYSTEM_PROMPT = """你是跨境电商产品改进顾问。基于 R1 归因结果，输出可执行的产品改进建议卡片。

## 任务
1. 综合 root_cause 与 evidence，给出 2-4 条具体的改进措施
2. 为每条措施标注成本（low/medium/high）与优先级（high/medium/low）
3. 给出该痛点的四象限分类（quick_win / strategic / filler / thankless）

## 四象限定义
- quick_win（快赢）: 高影响 + 易解决（low/medium 成本）
- strategic（战略）: 高影响 + 难解决（high 成本）
- filler（填充）: 低影响 + 易解决
- thankless（费力不讨好）: 低影响 + 难解决

## 成本/优先级指南
- low: 改文案/标注/包装，不需开模
- medium: 调整材料/工艺/部件选型
- high: 重设计核心结构/换主芯片/重开模具
- priority high: 直接影响核心功能或安全
- priority medium: 影响体验但可规避
- priority low: 锦上添花

## 输出要求
严格输出 JSON:
{
  "suggestions": [
    {
      "content": "改进措施（中文，可执行）",
      "cost": "low或medium或high",
      "priority": "high或medium或low"
    }
  ],
  "quadrant": "quick_win或strategic或filler或thankless",
  "quadrant_reason": "分类理由（1句中文）"
}"""

# ---------- User Prompt 模板 ----------
USER_TEMPLATE = """请基于以下痛点归因结果，生成改进建议卡片：

【痛点标签】{label}
【影响面】占比 {impact_ratio_percent}%，平均星级 {avg_rating}，评论数 {review_count}
【趋势】{trend}

【根因归因】
{root_cause}

【已识别的证据】
{evidence_text}

【R1 已建议的改进措施（供参考整合，不要直接复制）】
{r1_measures_text}

请输出 JSON（suggestions 至少 2 条，quadrant 必填）。"""

# ---------- 输出 Schema ----------
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "cost": {"type": "string", "enum": ["low", "medium", "high"]},
                    "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["content", "cost", "priority"],
            },
        },
        "quadrant": {"type": "string", "enum": ["quick_win", "strategic", "filler", "thankless"]},
        "quadrant_reason": {"type": "string"},
    },
    "required": ["suggestions", "quadrant"],
}


def build_messages(
    label: str,
    impact_ratio: float,
    avg_rating: float,
    review_count: int,
    trend: str,
    root_cause: str,
    evidence: list[dict],
    r1_measures: list[dict],
) -> list[dict[str, str]]:
    """构造 OpenAI 消息列表."""
    evidence_text = "\n".join(
        f"- [{e.get('review_id', '?')[:12]}] \"{e.get('quote', '')}\": {e.get('explanation', '')}"
        for e in evidence
    ) or "（无）"
    r1_measures_text = "\n".join(
        f"- {m.get('measure', '?')} (cost={m.get('cost')}, priority={m.get('priority')})"
        for m in r1_measures
    ) or "（无）"

    user = USER_TEMPLATE.format(
        label=label,
        impact_ratio_percent=f"{impact_ratio * 100:.1f}",
        avg_rating=avg_rating if avg_rating is not None else "未知",
        review_count=review_count,
        trend=trend or "未知",
        root_cause=root_cause or "（无）",
        evidence_text=evidence_text,
        r1_measures_text=r1_measures_text,
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
