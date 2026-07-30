"""LLM JSON 输出解析（容错）.

LLM 输出 JSON 经常带 markdown code fence、前后多余文本、单引号、尾随逗号等。
本模块提供多层容错解析，最大概率还原出 dict / list。
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.core.exceptions import JSONParseError


# ---------- 主入口 ----------
def parse_llm_json(content: str) -> dict:
    """解析 LLM 输出的 JSON 字符串（容错）.

    解析顺序:
    1. 去除 markdown code fence 后直接 json.loads
    2. 提取第一个 {...} 块再解析
    3. 单引号转双引号、去除尾随逗号
    4. 仍失败则抛 JSONParseError

    Args:
        content: LLM 原始输出

    Returns:
        解析后的 dict

    Raises:
        JSONParseError: 所有容错尝试均失败
    """
    if not content or not content.strip():
        raise JSONParseError("LLM 输出为空，无法解析 JSON")

    text = content.strip()

    # Step 1: 去 markdown code fence
    cleaned = _strip_code_fence(text)

    # Step 2: 直接解析
    try:
        result = json.loads(cleaned)
        if isinstance(result, dict):
            return result
        if isinstance(result, list) and result and isinstance(result[0], dict):
            # 偶尔模型输出数组而非对象，取第一个
            return result[0]
    except json.JSONDecodeError:
        pass

    # Step 3: 提取 {...} 块
    block = extract_json_block(cleaned)
    if block:
        try:
            result = json.loads(block)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    # Step 4: 单引号 / 尾随逗号 / Python 字面量风格
    fixed = _fix_common_issues(cleaned)
    try:
        result = json.loads(fixed)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Step 5: 提取块后再 fix
    if block:
        fixed_block = _fix_common_issues(block)
        try:
            result = json.loads(fixed_block)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    raise JSONParseError(
        f"JSON 解析失败，原始内容前 300 字: {content[:300]}",
    )


# ---------- 辅助 ----------
def _strip_code_fence(text: str) -> str:
    """去除 markdown ```json ... ``` code fence."""
    # ```json\n...\n``` or ```\n...\n```
    pattern = r"^```(?:json|JSON)?\s*\n(.*?)\n```\s*$"
    match = re.match(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # 行首单 ``` 开头，行尾单 ``` 结尾
    if text.startswith("```") and text.endswith("```"):
        # 去掉首行 ``` 可能含 json 标识
        lines = text.splitlines()
        if len(lines) >= 2:
            inner = "\n".join(lines[1:-1])
            return inner.strip()
    return text


def extract_json_block(text: str) -> str | None:
    """从文本中提取第一个完整的 {...} 块.

    用栈匹配大括号，处理嵌套。

    Returns:
        提取到的 JSON 字符串；找不到返回 None
    """
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _fix_common_issues(text: str) -> str:
    """修复常见的 JSON 格式问题.

    - 单引号 → 双引号（仅在 key/value 边界，粗略处理）
    - 去除尾随逗号
    - 处理 None/True/False → null/true/false
    """
    # 单引号 → 双引号（粗略，不区分字符串内容）
    # 仅在 : 或 { 或 [ 或 , 后面跟 ' 的情况视为字符串开始
    fixed = re.sub(r"(?<=[:\[{,])\s*'", '"', text)
    fixed = re.sub(r"'\s*(?=[,\]\}:])", '"', fixed)

    # 尾随逗号
    fixed = re.sub(r",\s*([}\]])", r"\1", fixed)

    # Python 风格字面量
    fixed = re.sub(r"\bNone\b", "null", fixed)
    fixed = re.sub(r"\bTrue\b", "true", fixed)
    fixed = re.sub(r"\bFalse\b", "false", fixed)

    return fixed
