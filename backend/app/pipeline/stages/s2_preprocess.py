"""Stage 2: 评论预处理.

职责:
- 过滤非 VP（Verified Purchase）评论：可选，默认保留 VP；非 VP 标记但仍入库
- 元数据提取/规范化：date 解析、helpful_votes 数值化、image_urls 解析
- is_negative 标记：rating <= 3 视为差评
- is_suspicious 标记（P1 简化版：仅标记模板化短评）

注意:
- 评论入库后不可变原则：仅修改分析字段（is_negative, is_vp, has_image, image_urls, is_suspicious）
- 元数据规范化（date 解析）也允许（s1 写入的是原始字符串解析结果，这里二次校验）

输入: project_id
输出: PreprocessResult 统计
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import func, select, update

from app.core.exceptions import StageError
from app.core.logging import get_logger
from app.models.database import get_session
from app.models.schemas import Project, Review
from app.utils.text import clean_text
from app.utils.time import parse_date

logger = get_logger(__name__)


# 简单的刷评模板特征（P1 简化版）
_SUSPICIOUS_PATTERNS = [
    re.compile(r"^(great|good|excellent|amazing|awesome|perfect)\s*(product|item|buy|value)!?\.?$", re.IGNORECASE),
    re.compile(r"^(I love it|Highly recommend|Five stars|Five star)\.?$", re.IGNORECASE),
    re.compile(r"^(符合描述|物美价廉|强烈推荐|五星好评)\s*[!。.]?$"),
]
_SUSPICIOUS_MIN_LEN = 5
_SUSPICIOUS_MAX_LEN = 30  # 短评更可疑


@dataclass
class PreprocessResult:
    """s2 预处理结果."""

    total: int = 0
    """处理总数"""

    marked_negative: int = 0
    """标记为差评（rating<=3）的条数"""

    marked_vp: int = 0
    """VP 评论数"""

    non_vp: int = 0
    """非 VP 评论数"""

    has_image: int = 0
    """带图评论数"""

    suspicious: int = 0
    """疑似刷评数（P1 简化标记）"""

    date_parsed: int = 0
    """成功解析 date 的条数"""

    date_failed: int = 0
    """date 解析失败的条数"""

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "marked_negative": self.marked_negative,
            "marked_vp": self.marked_vp,
            "non_vp": self.non_vp,
            "has_image": self.has_image,
            "suspicious": self.suspicious,
            "date_parsed": self.date_parsed,
            "date_failed": self.date_failed,
        }


def _is_suspicious(body: str, title: str = "") -> bool:
    """P1 简化刷评初判.

    规则（任一满足即标记）:
    - 正文长度 < _SUSPICIOUS_MIN_LEN
    - 正文长度 <= _SUSPICIOUS_MAX_LEN 且匹配模板
    - 标题与正文完全相同且较短
    """
    body = (body or "").strip()
    title = (title or "").strip()
    if not body:
        return False
    if len(body) < _SUSPICIOUS_MIN_LEN:
        return True
    if len(body) <= _SUSPICIOUS_MAX_LEN:
        for pat in _SUSPICIOUS_PATTERNS:
            if pat.match(body):
                return True
    if title and title == body and len(body) <= _SUSPICIOUS_MAX_LEN:
        return True
    return False


def run_s2_preprocess(
    project_id: str,
    *,
    drop_non_vp: bool = False,
    suspicious_check: bool = True,
) -> PreprocessResult:
    """执行 s2_preprocess 阶段.

    Args:
        project_id: 项目 ID
        drop_non_vp: 是否删除非 VP 评论（默认 False，仅标记）
        suspicious_check: 是否执行刷评初判（P1，默认 True）

    Returns:
        PreprocessResult 统计

    Raises:
        StageError: 项目不存在或预处理失败
    """
    logger.info("[s2_preprocess] 开始 project_id=%s", project_id)

    result = PreprocessResult()

    with get_session() as session:
        # 1. 校验项目
        project = session.get(Project, project_id)
        if project is None:
            raise StageError(
                "s2_preprocess",
                f"项目不存在: {project_id}",
                code=1001,
                recoverable=False,
            )

        # 2. 拉取该项目的所有评论
        reviews = (
            session.execute(
                select(Review).where(Review.project_id == project_id)
            )
            .scalars()
            .all()
        )
        result.total = len(reviews)
        if result.total == 0:
            logger.warning("[s2_preprocess] 项目 %s 无评论可处理", project_id)
            return result

        # 3. 逐条规范化元数据 + 标记
        to_delete: list[Review] = []
        for r in reviews:
            # date 解析（s1 已解析过，这里二次校验）
            if r.date is None and r.raw_json:
                # 从 raw_json 中找原始 date 字符串
                try:
                    raw = json.loads(r.raw_json)
                    date_raw = (
                        raw.get("date")
                        or raw.get("review_date")
                        or raw.get("timestamp")
                        or raw.get("time")
                    )
                    if date_raw:
                        parsed = parse_date(str(date_raw))
                        if parsed:
                            r.date = parsed
                            result.date_parsed += 1
                        else:
                            result.date_failed += 1
                    else:
                        result.date_failed += 1
                except json.JSONDecodeError:
                    result.date_failed += 1
            elif r.date is not None:
                result.date_parsed += 1

            # is_vp 标记（s1 已设置，这里仅统计）
            if r.is_vp:
                result.marked_vp += 1
            else:
                result.non_vp += 1

            # has_image 统计
            if r.has_image:
                result.has_image += 1

            # is_negative 标记（rating <= 3）
            r.is_negative = (r.rating is not None) and (r.rating <= 3)
            if r.is_negative:
                result.marked_negative += 1

            # is_suspicious 标记（P1 简化）
            if suspicious_check:
                was_suspicious = r.is_suspicious
                r.is_suspicious = _is_suspicious(r.body or "", r.title or "")
                if r.is_suspicious and not was_suspicious:
                    result.suspicious += 1
            else:
                r.is_suspicious = False

            # 清洗 title / body（去除多余空白，保留原文意图）
            if r.title:
                r.title = clean_text(r.title) or None
            if r.body:
                r.body = clean_text(r.body)

            # 非 VP 删除（可选）
            if drop_non_vp and not r.is_vp:
                to_delete.append(r)

        # 4. 执行删除
        for r in to_delete:
            session.delete(r)

        session.commit()

    logger.info(
        "[s2_preprocess] 完成 total=%d negative=%d vp=%d non_vp=%d "
        "has_image=%d suspicious=%d date_parsed=%d date_failed=%d",
        result.total,
        result.marked_negative,
        result.marked_vp,
        result.non_vp,
        result.has_image,
        result.suspicious,
        result.date_parsed,
        result.date_failed,
    )
    if to_delete:
        logger.info("[s2_preprocess] 删除非 VP 评论 %d 条", len(to_delete))

    return result


# ---------- 命令行入口 ----------
if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="s2_preprocess: 评论预处理")
    parser.add_argument("--project-id", required=True, help="项目 ID")
    parser.add_argument("--drop-non-vp", action="store_true", help="删除非 VP 评论")
    parser.add_argument("--no-suspicious-check", action="store_true", help="跳过刷评初判")
    args = parser.parse_args()

    try:
        r = run_s2_preprocess(
            args.project_id,
            drop_non_vp=args.drop_non_vp,
            suspicious_check=not args.no_suspicious_check,
        )
        print(
            f"预处理完成: total={r.total} negative={r.marked_negative} "
            f"vp={r.marked_vp} non_vp={r.non_vp} suspicious={r.suspicious}"
        )
    except StageError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)
