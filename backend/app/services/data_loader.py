"""Kaggle 数据集加载 + 手动采集 JSON 解析.

职责:
- 读取 data/raw/ 下的 CSV / JSON / JSONL 文件
- 字段映射：将数据集原始列名映射到 Review 标准字段
- 支持单文件 + 多文件批量加载
- 返回标准化的 dict 列表（供 s1_ingest 入库）

不负责:
- 入库（由 s1_ingest 处理）
- 去重（由 s1_ingest 处理）
- 调用 LLM（无关）
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional

from app.core.config import settings
from app.core.exceptions import DatasetError
from app.utils.text import clean_text

logger = logging.getLogger(__name__)


# ---------- 字段映射表 ----------
# 业务字段 -> 数据集中可能的列名（按优先级）
FIELD_ALIASES: dict[str, list[str]] = {
    "asin": ["asin", "product_id", "parent_asin", "product_asin"],
    "rating": ["rating", "star", "stars", "overall", "score"],
    "body": ["text", "body", "review_text", "content", "review", "reviewBody"],
    "title": ["title", "review_title", "summary", "review_title"],
    "date": ["date", "review_date", "timestamp", "time", "reviewTime"],
    "verified_purchase": ["verified_purchase", "is_vp", "verified", "verified_purchase"],
    "helpful_votes": ["helpful_votes", "helpful", "helpfulness", "votes", "helpful_vote_count"],
    "variant": ["variant", "style", "color", "size", "variation"],
    "image_url": ["image_url", "images", "image", "image_urls"],
    "product_name": ["product_name", "product_title", "title_product"],
    "review_id": ["review_id", "id", "reviewID", "reviewer_id"],
    "reviewer_name": ["reviewer_name", "reviewer", "user_id", "reviewerName"],
}


@dataclass
class RawReview:
    """标准化后的原始评论（入库前的中间结构）."""

    asin: str
    rating: int
    body: str
    title: str = ""
    date: Optional[str] = None  # 原始字符串，由 s2 解析
    verified_purchase: Optional[bool] = None
    helpful_votes: int = 0
    variant: str = ""
    image_urls: list[str] = field(default_factory=list)
    product_name: str = ""
    review_id: str = ""  # 数据集自带的 id（用于去重）
    reviewer_name: str = ""
    raw: dict[str, Any] = field(default_factory=dict)  # 原始行数据备份

    def to_dict(self) -> dict[str, Any]:
        return {
            "asin": self.asin,
            "rating": self.rating,
            "body": self.body,
            "title": self.title,
            "date": self.date,
            "verified_purchase": self.verified_purchase,
            "helpful_votes": self.helpful_votes,
            "variant": self.variant,
            "image_urls": self.image_urls,
            "product_name": self.product_name,
            "review_id": self.review_id,
            "reviewer_name": self.reviewer_name,
            "raw": self.raw,
        }


# ---------- 主入口 ----------
class DataLoader:
    """数据集加载器."""

    def __init__(self, raw_dir: Path | None = None) -> None:
        self.raw_dir = raw_dir or settings.data_raw_dir

    # ---------- 文件级加载 ----------
    def load_dir(self, pattern: str = "*") -> list[RawReview]:
        """加载 raw_dir 下所有匹配文件.

        Args:
            pattern: 文件名 glob，默认 *（匹配所有）

        Returns:
            RawReview 列表

        Raises:
            DatasetError: 目录不存在或无文件
        """
        if not self.raw_dir.exists():
            raise DatasetError(f"数据目录不存在: {self.raw_dir}")

        files = sorted(
            f for f in self.raw_dir.glob(pattern) if f.suffix.lower() in {".csv", ".json", ".jsonl"}
        )
        # 排除 README 等
        files = [f for f in files if f.is_file() and not f.name.lower().startswith("readme")]

        if not files:
            raise DatasetError(
                f"未在 {self.raw_dir} 找到数据文件（支持 .csv/.json/.jsonl）。"
                "请将 Kaggle 数据集放到该目录。"
            )

        all_reviews: list[RawReview] = []
        for f in files:
            try:
                reviews = self.load_file(f)
                logger.info("加载文件 %s: %d 条评论", f.name, len(reviews))
                all_reviews.extend(reviews)
            except Exception as e:
                logger.error("加载文件 %s 失败: %s", f.name, e)
                # 单文件失败不中断整体加载
        return all_reviews

    def load_file(self, path: Path) -> list[RawReview]:
        """加载单个文件."""
        path = Path(path)
        suffix = path.suffix.lower()
        if suffix == ".csv":
            return self._load_csv(path)
        if suffix == ".json":
            return self._load_json(path)
        if suffix == ".jsonl":
            return self._load_jsonl(path)
        raise DatasetError(f"不支持的数据文件类型: {suffix}")

    # ---------- CSV ----------
    def _load_csv(self, path: Path) -> list[RawReview]:
        """加载 CSV 文件."""
        import pandas as pd

        try:
            df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8")
        except UnicodeDecodeError:
            df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        except Exception as e:
            raise DatasetError(f"CSV 读取失败 {path.name}: {e}", cause=e) from e

        # 字段映射
        col_map = self._build_column_map(list(df.columns))
        reviews: list[RawReview] = []
        for _, row in df.iterrows():
            review = self._row_to_review(row.to_dict(), col_map)
            if review:
                reviews.append(review)
        return reviews

    # ---------- JSON ----------
    def _load_json(self, path: Path) -> list[RawReview]:
        """加载 JSON 文件（数组或单对象）."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise DatasetError(f"JSON 解析失败 {path.name}: {e}", cause=e) from e
        except Exception as e:
            raise DatasetError(f"JSON 读取失败 {path.name}: {e}", cause=e) from e

        # 兼容多种结构
        if isinstance(data, dict):
            # 单条评论
            if "asin" in data or "rating" in data:
                data = [data]
            # 嵌套在 review 字段
            elif "reviews" in data and isinstance(data["reviews"], list):
                data = data["reviews"]
            elif "data" in data and isinstance(data["data"], list):
                data = data["data"]
            else:
                data = [data]
        if not isinstance(data, list):
            raise DatasetError(f"JSON 结构未识别 {path.name}: 期望数组或含 reviews/data 字段")

        col_map = self._build_column_map(list(data[0].keys()) if data else [])
        reviews: list[RawReview] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            review = self._row_to_review(item, col_map)
            if review:
                reviews.append(review)
        return reviews

    def _load_jsonl(self, path: Path) -> list[RawReview]:
        """加载 JSONL 文件（每行一个 JSON 对象）."""
        reviews: list[RawReview] = []
        col_map: dict[str, str] | None = None
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line_no, line in enumerate(f, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError as e:
                        logger.warning("JSONL 第 %d 行解析失败: %s", line_no, e)
                        continue
                    if not isinstance(item, dict):
                        continue
                    if col_map is None:
                        col_map = self._build_column_map(list(item.keys()))
                    review = self._row_to_review(item, col_map)
                    if review:
                        reviews.append(review)
        except Exception as e:
            raise DatasetError(f"JSONL 读取失败 {path.name}: {e}", cause=e) from e
        return reviews

    # ---------- 字段映射 ----------
    def _build_column_map(self, columns: list[str]) -> dict[str, str]:
        """构建 业务字段 -> 实际列名 的映射."""
        col_lower = {c.lower(): c for c in columns}
        col_set = set(columns)
        mapping: dict[str, str] = {}
        for biz_field, aliases in FIELD_ALIASES.items():
            # 1. 直接匹配（大小写不敏感）
            for alias in aliases:
                if alias.lower() in col_lower:
                    mapping[biz_field] = col_lower[alias.lower()]
                    break
            if biz_field in mapping:
                continue
            # 2. 原名匹配
            for alias in aliases:
                if alias in col_set:
                    mapping[biz_field] = alias
                    break
        return mapping

    def _row_to_review(
        self,
        row: dict[str, Any],
        col_map: dict[str, str],
    ) -> RawReview | None:
        """将一行原始数据转为 RawReview.

        必需字段缺失则返回 None。
        """
        def get(biz: str, default: Any = None) -> Any:
            col = col_map.get(biz)
            if not col:
                return default
            v = row.get(col, default)
            return v

        asin = str(get("asin", "")).strip()
        rating_raw = get("rating")
        body = clean_text(str(get("body", "")))

        if not asin:
            return None
        try:
            rating = int(float(rating_raw)) if rating_raw not in (None, "") else 0
        except (ValueError, TypeError):
            return None
        if not (1 <= rating <= 5):
            # 评分越界但保留（标 0 让 s2 过滤）
            pass
        if not body:
            # 空正文不可用
            return None

        # 可选字段
        title = clean_text(str(get("title", "")))
        date_raw = get("date")
        date_str = str(date_raw) if date_raw not in (None, "") else None

        # verified_purchase
        vp_raw = get("verified_purchase")
        if vp_raw in (None, ""):
            verified: Optional[bool] = None
        elif isinstance(vp_raw, bool):
            verified = vp_raw
        else:
            verified = str(vp_raw).strip().lower() in {"true", "1", "yes", "y", "verified"}

        # helpful_votes
        hv_raw = get("helpful_votes", 0)
        try:
            helpful_votes = int(float(hv_raw)) if hv_raw not in (None, "") else 0
        except (ValueError, TypeError):
            helpful_votes = 0

        # variant
        variant = str(get("variant", "")).strip()

        # image_urls
        image_urls = self._parse_image_urls(get("image_url"))

        # product_name
        product_name = str(get("product_name", "")).strip()

        # review_id
        review_id = str(get("review_id", "")).strip()

        # reviewer_name
        reviewer_name = str(get("reviewer_name", "")).strip()

        return RawReview(
            asin=asin,
            rating=rating,
            body=body,
            title=title,
            date=date_str,
            verified_purchase=verified,
            helpful_votes=max(0, helpful_votes),
            variant=variant,
            image_urls=image_urls,
            product_name=product_name,
            review_id=review_id,
            reviewer_name=reviewer_name,
            raw={k: v for k, v in row.items() if k in col_map.values()},
        )

    @staticmethod
    def _parse_image_urls(value: Any) -> list[str]:
        """解析 image_url 字段，兼容多种格式."""
        if not value:
            return []
        if isinstance(value, list):
            return [str(u) for u in value if u]
        if isinstance(value, str):
            v = value.strip()
            if not v:
                return []
            # JSON 数组字符串
            if v.startswith("["):
                try:
                    parsed = json.loads(v)
                    if isinstance(parsed, list):
                        return [str(u) for u in parsed if u]
                except json.JSONDecodeError:
                    pass
            # 逗号分隔
            if "," in v:
                return [u.strip() for u in v.split(",") if u.strip()]
            return [v]
        return []


# ---------- 便捷函数 ----------
def load_raw_reviews(raw_dir: Path | None = None) -> list[RawReview]:
    """便捷函数：从 data/raw/ 加载所有评论."""
    loader = DataLoader(raw_dir=raw_dir)
    return loader.load_dir()


def iter_raw_reviews(raw_dir: Path | None = None) -> Iterator[RawReview]:
    """迭代器模式（保留扩展位，当前未做流式）."""
    for r in load_raw_reviews(raw_dir):
        yield r
