"""SQLAlchemy ORM 模型.

6 张表（严格对齐架构文档第三章）：
- projects        分析项目
- reviews         评论
- pain_points     痛点簇
- attributions    R1 根因归因
- suggestions     改进建议
- listing_suggestions  Listing 卖点建议

关系:
  projects 1───* reviews
  projects 1───* pain_points
  pain_points 1───1 attributions   （仅 Top 5 痛点有归因）
  pain_points 1───* suggestions
  projects 1───* listing_suggestions
"""
from __future__ import annotations

import enum
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Float,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.database import Base


# ---------- 工具函数 ----------
def _now() -> datetime:
    """UTC 当前时间."""
    return datetime.now(timezone.utc)


def _uuid() -> str:
    """UUID v4 字符串."""
    return str(uuid.uuid4())


# ---------- 枚举（仅用于代码内校验，DB 仍存 TEXT） ----------
class ProjectStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class PipelineStage(str, enum.Enum):
    S1_INGEST = "s1_ingest"
    S2_PREPROCESS = "s2_preprocess"
    S3_CLUSTER = "s3_cluster"
    S4_LABEL = "s4_label"
    S5_ATTRIBUTE = "s5_attribute"
    S6_SUGGEST = "s6_suggest"
    S7_REPORT = "s7_report"


class TrendType(str, enum.Enum):
    RISING = "rising"
    STABLE = "stable"
    FALLING = "falling"
    UNKNOWN = "unknown"


class SuggestionType(str, enum.Enum):
    PRODUCT_IMPROVEMENT = "product_improvement"
    LISTING_OPTIMIZATION = "listing_optimization"


class CostLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PriorityLevel(str, enum.Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class QuadrantType(str, enum.Enum):
    QUICK_WIN = "quick_win"
    STRATEGIC = "strategic"
    FILLER = "filler"
    THANKLESS = "thankless"


class ListingField(str, enum.Enum):
    TITLE = "title"
    BULLET_POINT = "bullet_point"
    A_PLUS_CONTENT = "a_plus_content"
    IMAGE = "image"


# ---------- ORM 模型 ----------
class Project(Base):
    """分析项目."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(255), nullable=False)
    competitor_asins: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )  # JSON 数组
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ProjectStatus.PENDING.value
    )
    current_stage: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    progress: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    config_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_now, onupdate=_now
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # 关系
    reviews: Mapped[list["Review"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    pain_points: Mapped[list["PainPoint"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    listing_suggestions: Mapped[list["ListingSuggestion"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    # ---------- 便捷访问器 ----------
    @property
    def competitor_asin_list(self) -> list[str]:
        """解析 competitor_asins JSON 为列表."""
        if not self.competitor_asins:
            return []
        try:
            data = json.loads(self.competitor_asins)
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []

    @competitor_asin_list.setter
    def competitor_asin_list(self, value: list[str]) -> None:
        self.competitor_asins = json.dumps(value, ensure_ascii=False) if value else None

    @property
    def config(self) -> dict[str, Any]:
        """解析 config_json."""
        if not self.config_json:
            return {}
        try:
            data = json.loads(self.config_json)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}

    @config.setter
    def config(self, value: dict[str, Any]) -> None:
        self.config_json = json.dumps(value, ensure_ascii=False) if value else None

    def __repr__(self) -> str:
        return f"<Project {self.id[:8]} {self.name!r} status={self.status}>"


class Review(Base):
    """评论."""

    __tablename__ = "reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    asin: Mapped[str] = mapped_column(String(32), nullable=False)
    product_name: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    variant: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    helpful_votes: Mapped[int] = mapped_column(Integer, default=0)
    is_vp: Mapped[bool] = mapped_column(Boolean, default=True)
    has_image: Mapped[bool] = mapped_column(Boolean, default=False)
    image_urls: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON 数组
    is_negative: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    cluster_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_representative: Mapped[bool] = mapped_column(Boolean, default=False)
    is_suspicious: Mapped[bool] = mapped_column(Boolean, default=False)
    raw_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)

    # 关系
    project: Mapped["Project"] = relationship(back_populates="reviews")

    # 索引（按架构文档 3.1.2）
    __table_args__ = (
        Index("idx_reviews_project_asin", "project_id", "asin"),
        Index("idx_reviews_project_negative", "project_id", "is_negative"),
        Index("idx_reviews_cluster", "cluster_id"),
        Index("idx_reviews_project_helpful", "project_id", "helpful_votes"),
    )

    # ---------- 便捷访问器 ----------
    @property
    def image_url_list(self) -> list[str]:
        if not self.image_urls:
            return []
        try:
            data = json.loads(self.image_urls)
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []

    @image_url_list.setter
    def image_url_list(self, value: list[str]) -> None:
        self.image_urls = json.dumps(value, ensure_ascii=False) if value else None

    @property
    def raw(self) -> dict[str, Any]:
        if not self.raw_json:
            return {}
        try:
            data = json.loads(self.raw_json)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}

    @raw.setter
    def raw(self, value: dict[str, Any]) -> None:
        self.raw_json = json.dumps(value, ensure_ascii=False) if value else None

    def __repr__(self) -> str:
        return (
            f"<Review {self.id[:8]} asin={self.asin} rating={self.rating} "
            f"cluster={self.cluster_id}>"
        )


class PainPoint(Base):
    """痛点簇."""

    __tablename__ = "pain_points"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    cluster_id: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    review_count: Mapped[int] = mapped_column(Integer, nullable=False)
    impact_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    avg_rating: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    trend: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    is_common_weakness: Mapped[bool] = mapped_column(Boolean, default=False)
    suitable_for_reasoning: Mapped[bool] = mapped_column(Boolean, default=True)
    reasoning_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rank_by_impact: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_top5: Mapped[bool] = mapped_column(Boolean, default=False)
    competitor_breakdown: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )  # JSON
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)

    # 关系
    project: Mapped["Project"] = relationship(back_populates="pain_points")
    attribution: Mapped[Optional["Attribution"]] = relationship(
        back_populates="pain_point",
        cascade="all, delete-orphan",
        uselist=False,
    )
    suggestions: Mapped[list["Suggestion"]] = relationship(
        back_populates="pain_point", cascade="all, delete-orphan"
    )

    # 索引（按架构文档 3.1.3）
    __table_args__ = (
        Index("idx_painpoints_project_rank", "project_id", "rank_by_impact"),
        Index("idx_painpoints_project_top5", "project_id", "is_top5"),
    )

    # ---------- 便捷访问器 ----------
    @property
    def competitor_breakdown_dict(self) -> list[dict[str, Any]]:
        if not self.competitor_breakdown:
            return []
        try:
            data = json.loads(self.competitor_breakdown)
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []

    @competitor_breakdown_dict.setter
    def competitor_breakdown_dict(self, value: list[dict[str, Any]]) -> None:
        self.competitor_breakdown = (
            json.dumps(value, ensure_ascii=False) if value else None
        )

    def __repr__(self) -> str:
        return (
            f"<PainPoint {self.id[:8]} cluster={self.cluster_id} "
            f"label={self.label!r} impact={self.impact_ratio:.2f}>"
        )


class Attribution(Base):
    """R1 根因归因（与 pain_points 一对一）."""

    __tablename__ = "attributions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    pain_point_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("pain_points.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    root_cause: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)  # JSON 数组
    improvement_measures: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )  # JSON 数组
    model_used: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)

    # 关系
    pain_point: Mapped["PainPoint"] = relationship(back_populates="attribution")

    # ---------- 便捷访问器 ----------
    @property
    def evidence_list(self) -> list[dict[str, Any]]:
        if not self.evidence:
            return []
        try:
            data = json.loads(self.evidence)
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []

    @evidence_list.setter
    def evidence_list(self, value: list[dict[str, Any]]) -> None:
        self.evidence = json.dumps(value, ensure_ascii=False) if value else "[]"

    @property
    def measures_list(self) -> list[dict[str, Any]]:
        if not self.improvement_measures:
            return []
        try:
            data = json.loads(self.improvement_measures)
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []

    @measures_list.setter
    def measures_list(self, value: list[dict[str, Any]]) -> None:
        self.improvement_measures = (
            json.dumps(value, ensure_ascii=False) if value else None
        )

    def __repr__(self) -> str:
        return f"<Attribution {self.id[:8]} model={self.model_used}>"


class Suggestion(Base):
    """改进建议."""

    __tablename__ = "suggestions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    pain_point_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("pain_points.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    cost: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    priority: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    quadrant: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)

    # 关系
    pain_point: Mapped["PainPoint"] = relationship(back_populates="suggestions")

    def __repr__(self) -> str:
        return f"<Suggestion {self.id[:8]} type={self.type} priority={self.priority}>"


class ListingSuggestion(Base):
    """Listing 卖点建议."""

    __tablename__ = "listing_suggestions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    competitor_weakness: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_selling_point: Mapped[str] = mapped_column(Text, nullable=False)
    listing_field: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    priority: Mapped[str] = mapped_column(String(16), nullable=False)
    rationale: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)

    # 关系
    project: Mapped["Project"] = relationship(back_populates="listing_suggestions")

    def __repr__(self) -> str:
        return f"<ListingSuggestion {self.id[:8]} priority={self.priority}>"
