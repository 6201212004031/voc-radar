"""VOC Radar 应用配置模块.

基于 Pydantic Settings 读取 .env，提供全局 settings 单例。
所有敏感信息（API Key、Base URL）仅通过环境变量注入，禁止硬编码。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# 后端根目录：backend/
BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """VOC Radar 全局配置.

    所有字段都从 .env 读取，未配置时使用合理默认值。
    """

    model_config = SettingsConfigDict(
        env_file=str(BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------- Model Router ----------
    MODEL_ROUTER_API_KEY: str = Field(
        default="",
        description="阿里云百炼 / Model Router API Key",
    )
    MODEL_ROUTER_BASE_URL: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        description="Model Router OpenAI 兼容 Base URL",
    )

    # ---------- 模型名称 ----------
    MODEL_EMBEDDING: str = Field(default="text-embedding-v4", description="向量化模型")
    MODEL_LLM: str = Field(default="qwen3.7-max", description="通用对话模型")
    MODEL_R1: str = Field(default="deepseek-r1", description="深度推理模型")
    MODEL_VISION: str = Field(default="qwen3-vl-plus", description="视觉理解模型")
    MODEL_FLASH: str = Field(default="qwen3.5-flash", description="轻量快速模型")

    # 根因归因主力模型。依据 Top5 全样本对比实验（data/reports/r1_vs_qwen_compare.md）：
    # 在根因归因任务上 qwen3.7-max 质量更高、快约 2.4 倍、更稳定，故默认使用它；
    # 高难度痛点可切换为 deepseek-r1，此时 qwen3.7-max 自动成为补充通道。
    ATTRIBUTION_MODEL: str = Field(
        default="qwen3.7-max",
        description="根因归因主力模型（可选 deepseek-r1 作为高难度补充通道）",
    )

    # ---------- 数据库 ----------
    DATABASE_URL: str = Field(
        default="sqlite:///./data/voc_radar.db",
        description="SQLite 数据库 URL",
    )

    # ---------- 聚类 ----------
    CLUSTER_K_MIN: int = Field(default=8, ge=2, description="K-Means 最小簇数")
    CLUSTER_K_MAX: int = Field(default=15, ge=2, description="K-Means 最大簇数")
    CLUSTER_BATCH_SIZE: int = Field(
        default=100, ge=1, description="聚类相关批处理大小"
    )
    CLUSTER_REPRESENTATIVE_TOP_N: int = Field(
        default=10, ge=1, description="每簇代表性评论 Top N"
    )
    CLUSTER_SILHOUETTE_FLOOR: float = Field(
        default=0.2,
        ge=0.0,
        le=1.0,
        description="silhouette 下限，低于此值降级到 k=10",
    )

    # ---------- Pipeline ----------
    TOP_N_FOR_R1: int = Field(default=5, ge=1, description="进入 R1 归因的痛点数")
    TOP_N_CANDIDATES: int = Field(
        default=8, ge=1, description="R1 候选数（按影响面取前 N）"
    )
    R1_MAX_RETRIES: int = Field(default=3, ge=0, description="R1 调用最大重试次数")
    LLM_TIMEOUT_SECONDS: int = Field(default=60, ge=1, description="LLM 调用超时秒数")
    COMMON_WEAKNESS_RATIO_THRESHOLD: float = Field(
        default=0.15,
        ge=0.0,
        le=1.0,
        description="共性弱点判定：竞品内占比阈值",
    )
    COMMON_WEAKNESS_COMPETITOR_MIN: int = Field(
        default=2,
        ge=1,
        description="共性弱点判定：至少多少个竞品共有",
    )

    # ---------- Embedding ----------
    EMBEDDING_BATCH_SIZE: int = Field(
        default=10, ge=1, le=10,
        description="embedding 批量调用每批条数（text-embedding-v4 单次上限为 10，"
                    "超出会报 InvalidParameter: batch size is invalid）"
    )
    EMBEDDING_CACHE_ENABLED: bool = Field(
        default=True, description="是否启用 embedding 缓存"
    )

    # ---------- 报告 ----------
    REPORT_OUTPUT_DIR: str = Field(
        default="./data/reports", description="报告输出目录"
    )

    # ---------- 日志 ----------
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", description="日志级别"
    )
    LOG_DIR: str = Field(default="./logs", description="日志目录")

    # ---------- 只读模式（公开演示部署用） ----------
    READ_ONLY: bool = Field(
        default=False,
        description="只读演示模式：为 true 时拒绝所有非 GET/HEAD/OPTIONS 请求，"
                    "仅开放浏览类接口（公开只读体验部署用，不暴露分析触发入口）",
    )

    # ---------- 派生属性 ----------
    @property
    def db_path(self) -> Path:
        """SQLite 数据库绝对路径.

        将 DATABASE_URL 中的相对路径解析为 backend/ 下的绝对路径。
        """
        # sqlite:///./data/voc_radar.db -> data/voc_radar.db
        url = self.DATABASE_URL
        if url.startswith("sqlite:///"):
            rel = url[len("sqlite:///") :]
            # 去掉前导 ./
            if rel.startswith("./"):
                rel = rel[2:]
            return (BACKEND_ROOT / rel).resolve()
        return BACKEND_ROOT / "data" / "voc_radar.db"

    @property
    def report_dir(self) -> Path:
        """报告输出绝对路径."""
        path = Path(self.REPORT_OUTPUT_DIR)
        if not path.is_absolute():
            path = BACKEND_ROOT / self.REPORT_OUTPUT_DIR
        return path.resolve()

    @property
    def log_dir(self) -> Path:
        """日志绝对路径."""
        path = Path(self.LOG_DIR)
        if not path.is_absolute():
            path = BACKEND_ROOT / self.LOG_DIR
        return path.resolve()

    @property
    def data_raw_dir(self) -> Path:
        """原始数据集目录: backend/data/raw/."""
        return BACKEND_ROOT / "data" / "raw"

    @property
    def data_processed_dir(self) -> Path:
        """预处理中间数据目录: backend/data/processed/."""
        return BACKEND_ROOT / "data" / "processed"

    # ---------- 校验 ----------
    @field_validator("CLUSTER_K_MAX")
    @classmethod
    def _k_max_ge_k_min(cls, v: int, info) -> int:
        k_min = info.data.get("CLUSTER_K_MIN", 8)
        if v < k_min:
            raise ValueError(
                f"CLUSTER_K_MAX({v}) 必须大于等于 CLUSTER_K_MIN({k_min})"
            )
        return v

    @field_validator("MODEL_ROUTER_API_KEY")
    @classmethod
    def _warn_empty_key(cls, v: str) -> str:
        if not v:
            # 不抛错，允许在没有 key 的情况下导入模块（如跑聚类测试）
            # 实际调用 LLM 时再检查
            pass
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """获取全局 Settings 单例（带 LRU 缓存）."""
    return Settings()


# 全局单例
settings = get_settings()


def ensure_dirs() -> None:
    """确保运行期所需目录存在（数据库、日志、报告、数据）."""
    for d in (
        settings.db_path.parent,
        settings.report_dir,
        settings.log_dir,
        settings.data_raw_dir,
        settings.data_processed_dir,
    ):
        d.mkdir(parents=True, exist_ok=True)
