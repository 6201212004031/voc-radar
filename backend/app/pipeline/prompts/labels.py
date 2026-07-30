"""痛点标签生成 Prompt（s4_label 使用）.

输入: 某个簇内的代表性评论 Top 10
输出 JSON:
  {
    "label": "痛点简短标签（≤8字，中文）",
    "description": "痛点简述（1-2句）",
    "suitable_for_reasoning": true/false,
    "reasoning_reason": "不适合推理时的理由（可选）"
  }

suitable_for_reasoning=false 的情况:
- 纯事实型（"太贵了""太重了"）—— 无需深度推理
- 简单偏好型（"颜色不喜欢"）—— 主观且无根因可挖
"""
from __future__ import annotations

# ---------- System Prompt ----------
SYSTEM_PROMPT = """你是跨境电商产品评论分析专家，擅长从 Amazon 评论中提炼痛点。

你的任务:
1. 阅读给定的一组评论（同一痛点簇的代表性评论）
2. 提炼一个简短中文标签（≤8字，描述痛点本质，如"续航差""连接不稳定""佩戴不适"）
3. 用 1-2 句话简述该痛点的具体表现
4. 判断该痛点是否适合深度推理（R1 根因归因）

适合深度推理（suitable_for_reasoning=true）的痛点特征:
- 体验型问题（涉及使用场景、环境触发）
- 涉及技术原理（电池化学、信号干扰、材料老化）
- 多因素交织（需要分析根因链路）
- 用户描述具体（有场景、有现象、有对比）

不适合深度推理（suitable_for_reasoning=false）的情况:
- 纯事实��（"太贵了""太重了""体积大"）—— 直接归因到成本/规格
- 简单偏好型（"颜色不喜欢""外观丑"）—— 主观且无根因可挖
- 评价模糊（评论本身信息量不足以推理）

输出要求:
- 严格输出 JSON，不要任何额外文本
- 标签用中文，简短有力
- description 用中文，描述具体现象
- 若 suitable_for_reasoning=false，必须给出 reasoning_reason 说明理由"""

# ---------- User Prompt 模板 ----------
USER_TEMPLATE = """请分析以下评论簇的痛点（这些评论来自同一聚类簇）：

【评论列表】
{reviews_text}

请输出 JSON:
{{
  "label": "痛点简短标签（≤8字中文）",
  "description": "痛点简述（1-2句中文，描述具体现象）",
  "suitable_for_reasoning": true或false,
  "reasoning_reason": "若 false，给出理由；若 true，此字段留空字符串"
}}"""

# ---------- 输出 Schema（用于提示与校验） ----------
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "description": "痛点标签，≤8字中文"},
        "description": {"type": "string", "description": "痛点简述"},
        "suitable_for_reasoning": {"type": "boolean"},
        "reasoning_reason": {"type": "string", "description": "不适合推理时的理由"},
    },
    "required": ["label", "description", "suitable_for_reasoning"],
}


def format_reviews(reviews: list[dict]) -> str:
    """格式化评论列表为 prompt 输入.

    Args:
        reviews: 评论 dict 列表，每条含 review_id/rating/title/body/helpful_votes

    Returns:
        格式化后的字符串
    """
    lines = []
    for i, r in enumerate(reviews, start=1):
        rating = r.get("rating", "?")
        title = r.get("title", "")
        body = r.get("body", "")
        votes = r.get("helpful_votes", 0)
        title_part = f" | 标题: {title}" if title else ""
        lines.append(
            f"{i}. ⭐{rating}{title_part} | 👍{votes}\n   正文: {body}"
        )
    return "\n\n".join(lines)


def build_messages(reviews: list[dict]) -> list[dict[str, str]]:
    """构造 OpenAI 消息列表.

    Args:
        reviews: 代表性评论列表

    Returns:
        [{"role":"system",...}, {"role":"user",...}]
    """
    reviews_text = format_reviews(reviews)
    user = USER_TEMPLATE.format(reviews_text=reviews_text)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
