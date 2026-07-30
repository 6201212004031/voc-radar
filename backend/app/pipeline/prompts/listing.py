"""Listing 卖点建议 Prompt（s6_suggest 使用）.

输入: 竞品共性弱点列表（is_common_weakness=true 的痛点）
输出: Listing 卖点建议（标题/五点描述/A+内容/图片）
"""
from __future__ import annotations

# ---------- System Prompt ----------
SYSTEM_PROMPT = """你是亚马逊 Listing 优化专家。基于竞品共性弱点，输出差异化卖点建议。

## 任务
1. 分析给定的竞品共性弱点（≥2 个竞品都有的痛点）
2. 针对每个共性弱点，提出卖家 Listing 应强调的差异化卖点
3. 指明该卖点应放在 Listing 的哪个字段（title/bullet_point/a_plus_content/image）
4. 标注优先级（high/medium/low）

## Listing 字段指南
- title: 标题，适合放核心参数（如"50H Playtime"）—— 字数有限，仅放最强卖点
- bullet_point: 五点描述，适合放具体差异化点 —— 每点聚焦一个卖点
- a_plus_content: A+ 内容，适合讲故事/对比图/使用场景 —— 信息密度高
- image: 图片，适合视觉化卖点（如续航对比图、防水测试图）

## 优先级指南
- high: 直接对应 Top 3 共性弱点，差异化价值最大
- medium: 对应中等影响共性弱点，强化整体卖点
- low: 锦上添花，资源充裕时再做

## 输出要求
严格输出 JSON:
{
  "listing_suggestions": [
    {
      "competitor_weakness": "竞品共性弱点描述（中文）",
      "suggested_selling_point": "建议卖点（中文，具体可执行）",
      "listing_field": "title或bullet_point或a_plus_content或image",
      "priority": "high或medium或low",
      "rationale": "建议理由（1句中文，说明为什么这个卖点在这个字段）"
    }
  ]
}"""

# ---------- User Prompt 模板 ----------
USER_TEMPLATE = """请基于以下竞品共性弱点，生成 Listing 差异化卖点建议：

【共性弱点列表】
{weaknesses_text}

【品类】{category}

请输出 JSON（listing_suggestions 至少 2 条，每个共性弱点至少对应 1 条建议）。"""

# ---------- 输出 Schema ----------
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "listing_suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "competitor_weakness": {"type": "string"},
                    "suggested_selling_point": {"type": "string"},
                    "listing_field": {
                        "type": "string",
                        "enum": ["title", "bullet_point", "a_plus_content", "image"],
                    },
                    "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                    "rationale": {"type": "string"},
                },
                "required": [
                    "competitor_weakness",
                    "suggested_selling_point",
                    "listing_field",
                    "priority",
                ],
            },
        }
    },
    "required": ["listing_suggestions"],
}


def build_messages(
    weaknesses: list[dict],
    category: str = "",
) -> list[dict[str, str]]:
    """构造 OpenAI 消息列表.

    Args:
        weaknesses: 共性弱点列表，每条含 label/description/impact_ratio/competitor_breakdown
        category: 品类关键词

    Returns:
        消息列表
    """
    lines = []
    for i, w in enumerate(weaknesses, start=1):
        label = w.get("label", "?")
        desc = w.get("description", "")
        ratio = w.get("impact_ratio", 0)
        breakdown = w.get("competitor_breakdown", [])
        breakdown_text = ""
        if breakdown:
            parts = []
            for b in breakdown:
                asin = b.get("asin", "?")
                pr = b.get("pain_ratio", 0)
                parts.append(f"{asin}({pr * 100:.0f}%)")
            breakdown_text = " | 竞品分布: " + ", ".join(parts)
        lines.append(
            f"{i}. {label}（影响面 {ratio * 100:.1f}%）{breakdown_text}\n   {desc}"
        )
    weaknesses_text = "\n\n".join(lines) if lines else "（无）"

    user = USER_TEMPLATE.format(
        weaknesses_text=weaknesses_text,
        category=category or "未指定",
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
