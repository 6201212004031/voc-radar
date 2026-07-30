"""R1 根因归因 Prompt（s5_attribute 使用）.

关键约束（必须出现在 system prompt）:
1. 所有结论必须引用评论原文作为证据
2. 不编造评论中未出现的数据
3. 信息不足时明确说明"无法确认"

输入:
- 痛点标签 + 描述
- 代表性评论 Top 10
- [可选] 图片缺陷识别结果

输出 JSON:
{
  "root_cause": "根因结论（中文）",
  "evidence": [
    {"review_id": "...", "quote": "评论原文片段", "explanation": "该证据如何支撑根因"}
  ],
  "improvement_measures": [
    {"measure": "改进措施", "cost": "low|medium|high", "priority": "high|medium|low"}
  ]
}
"""
from __future__ import annotations

# ---------- System Prompt ----------
SYSTEM_PROMPT = """你是产品根因分析专家。基于用户评论做根因归因。

## 核心规则（必须严格遵守）
1. 所有结论必须引用评论原文作为证据，不得编造评论中未出现的数据
2. 若评论信息不足以确认某项根因，必须明确说明"无法确认"，不得臆测
3. 证据 quote 字段必须是评论原文的逐字引用（保留英文原文），不得改写
4. 改进措施必须基于已确认的根因，不得脱离证据泛泛而谈

## 输出要求
严格输出 JSON，不要任何额外文本。结构如下:
{
  "root_cause": "根因结论（中文，1-3句，必须能从 evidence 推导出来）",
  "evidence": [
    {
      "review_id": "评论ID",
      "quote": "评论原文片段（逐字引用，保留原文语言）",
      "explanation": "该证据如何支撑根因（中文，1句）"
    }
  ],
  "improvement_measures": [
    {
      "measure": "改进措施（中文，可执行）",
      "cost": "low或medium或high",
      "priority": "high或medium或low"
    }
  ]
}

## 成本标注指南
- low: 改动文案/规格标注/包装说明等不需重新开模的改动
- medium: 调整材料/工艺/部件选型，需要供应商配合但不动核心架构
- high: 重新设计核心结构/更换主芯片/重开模具

## 优先级指南
- high: 直接影响核心功能或安全（如续航、连接、电池安全）
- medium: 影响体验但可规避（如佩戴舒适度、操作复杂度）
- low: 锦上添花（如外观细节、配件丰富度）"""

# ---------- User Prompt 模板 ----------
USER_TEMPLATE = """请对以下痛点进行根因归因分析：

【痛点标签】{label}
【痛点描述】{description}

【代表性评论（Top {top_n}）】
{reviews_text}
{vision_section}
请输出 JSON（root_cause / evidence / improvement_measures 三字段均必填，evidence 至少 2 条）。"""


USER_TEMPLATE_WITH_VISION = """
【图片缺陷识别结果】
{vision_tags}
"""

# ---------- 输出 Schema ----------
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "root_cause": {"type": "string", "description": "根因结论"},
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "review_id": {"type": "string"},
                    "quote": {"type": "string", "description": "评论原文逐字引用"},
                    "explanation": {"type": "string"},
                },
                "required": ["review_id", "quote", "explanation"],
            },
        },
        "improvement_measures": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "measure": {"type": "string"},
                    "cost": {"type": "string", "enum": ["low", "medium", "high"]},
                    "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["measure", "cost", "priority"],
            },
        },
    },
    "required": ["root_cause", "evidence", "improvement_measures"],
}


def format_reviews(reviews: list[dict]) -> str:
    """格式化评论列表（含 review_id 便于 R1 引用）."""
    lines = []
    for i, r in enumerate(reviews, start=1):
        rid = r.get("review_id", f"R{i}")
        # 取短 id 便于 LLM 引用
        short_id = rid[:12] if len(rid) > 12 else rid
        rating = r.get("rating", "?")
        title = r.get("title", "")
        body = r.get("body", "")
        votes = r.get("helpful_votes", 0)
        title_part = f" | 标题: {title}" if title else ""
        lines.append(
            f"[{short_id}] ⭐{rating}{title_part} | 👍{votes}\n   正文: {body}"
        )
    return "\n\n".join(lines)


def build_messages(
    label: str,
    description: str,
    reviews: list[dict],
    vision_tags: list[str] | None = None,
    top_n: int = 10,
) -> list[dict[str, str]]:
    """构造 OpenAI 消息列表.

    Args:
        label: 痛点标签
        description: 痛点描述
        reviews: 代表性评论列表（含 review_id/rating/title/body/helpful_votes）
        vision_tags: 可选的图片缺陷识别标签
        top_n: 实际使用的评论数

    Returns:
        [{"role":"system",...}, {"role":"user",...}]
    """
    reviews_text = format_reviews(reviews)
    vision_section = ""
    if vision_tags:
        vision_section = USER_TEMPLATE_WITH_VISION.format(
            vision_tags="\n".join(f"- {t}" for t in vision_tags)
        )
    user = USER_TEMPLATE.format(
        label=label,
        description=description or "（无描述）",
        top_n=top_n,
        reviews_text=reviews_text,
        vision_section=vision_section,
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
