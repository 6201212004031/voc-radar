"""时间工具：格式化、趋势计算."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional


def to_iso_utc(dt: datetime | None) -> str | None:
    """转 ISO 8601 UTC 字符串（如 2026-07-29T10:00:00Z）."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_date(s: str | None) -> datetime | None:
    """解析多种格式的日期字符串.

    支持:
    - ISO 8601: 2025-11-03T10:00:00Z
    - 日期: 2025-11-03
    - 美式: 11/03/2025
    - 英文: Nov 3, 2025 / November 3, 2025
    - Unix 时间戳（秒或毫秒）
    """
    if not s:
        return None
    s = str(s).strip()
    if not s:
        return None

    # Unix 时间戳
    if s.isdigit():
        ts = int(s)
        # 毫秒级（13 位）
        if len(s) >= 13:
            ts = ts / 1000
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (ValueError, OSError):
            pass

    # 尝试多种格式
    formats = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%d-%m-%Y",
        "%b %d, %Y",
        "%B %d, %Y",
        "%b %d %Y",
        "%B %d %Y",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue

    # 最后尝试 dateutil
    try:
        from dateutil import parser as _dateutil_parser

        dt = _dateutil_parser.parse(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def compute_trend(
    timestamps: list[datetime],
    window_days: int = 90,
) -> Literal["rising", "stable", "falling", "unknown"]:
    """根据评论时间分布计算趋势.

    将时间窗口分成前后两半，比较后半与前半的评论数：
    - 后半 > 前半 * 1.2 → rising
    - 后半 < 前半 * 0.8 → falling
    - 否则 stable
    - 样本不足 → unknown

    Args:
        timestamps: 评论时间列表
        window_days: 时间窗口（天），默认 90 天
    """
    if not timestamps or len(timestamps) < 6:
        return "unknown"

    # 过滤掉 None
    valid = [t for t in timestamps if t is not None]
    if len(valid) < 6:
        return "unknown"

    # 统一为 naive UTC datetime 用于计算
    valid_sorted = sorted(valid)
    latest = valid_sorted[-1]
    earliest_to_consider = latest.timestamp() - window_days * 86400
    in_window = [t for t in valid_sorted if t.timestamp() >= earliest_to_consider]
    if len(in_window) < 6:
        return "unknown"

    mid = len(in_window) // 2
    first_half = in_window[:mid]
    second_half = in_window[mid:]
    if not first_half or not second_half:
        return "unknown"

    # 按天聚合，避免单日突发
    first_count = len(first_half)
    second_count = len(second_half)

    if first_count == 0:
        return "rising" if second_count > 0 else "unknown"

    ratio = second_count / first_count
    if ratio > 1.2:
        return "rising"
    if ratio < 0.8:
        return "falling"
    return "stable"
