"""文本工具：清洗、截断、Token 估算."""
from __future__ import annotations

import re
from typing import Optional


# 简单的 token 估算系数（英文 ~4 字符/token，中文 ~1.5 字符/token）
# 仅用于预估，精确估算请用 tiktoken
_CHAR_PER_TOKEN_EN = 4.0
_CHAR_PER_TOKEN_ZH = 1.5


def clean_text(text: str | None) -> str:
    """清洗文本.

    - None → 空字符串
    - 去除多余空白
    - 去除控制字符
    """
    if not text:
        return ""
    # 去控制字符（保留换行）
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    # 连续空白合并为单个空格（保留换行）
    text = re.sub(r"[ \t]+", " ", text)
    # 去除行尾空白
    text = re.sub(r"\s+\n", "\n", text)
    return text.strip()


def truncate(text: str, max_chars: int = 4000, suffix: str = "...") -> str:
    """按字符数截断（保守估计 token 限制）.

    Args:
        text: 原文本
        max_chars: 最大字符数
        suffix: 截断时追加的后缀
    """
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + suffix


def estimate_tokens(text: str) -> int:
    """粗略估算 token 数.

    按中英文混合估算，仅用于预判上下文长度，不精确。
    """
    if not text:
        return 0
    # 统计中文字符数（含全角标点）
    zh_count = len(re.findall(r"[\u4e00-\u9fff]", text))
    en_count = len(text) - zh_count
    return max(1, int(zh_count / _CHAR_PER_TOKEN_ZH + en_count / _CHAR_PER_TOKEN_EN))


def combine_review_text(title: str | None, body: str | None) -> str:
    """组合评论标题 + 正文为统一文本（用于向量化 / LLM 输入）."""
    title = clean_text(title)
    body = clean_text(body)
    if title and body:
        return f"{title}. {body}"
    return title or body


def extract_quote(text: str, max_chars: int = 200) -> str:
    """从长文本中提取一段引用（用于证据展示）.

    优先取开头部分。
    """
    return truncate(text, max_chars, suffix="...")
