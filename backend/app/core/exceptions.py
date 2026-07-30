"""自定义异常 + 业务错误码.

错误处理约定：
- API 路由层: HTTPException + 全局异常处理器，统一返回 {code, message, request_id}
- Pipeline 编排层: StageError，捕获后决定是否降级
- 服务层: LLMError / EmbeddingError / ClusterError，由调用方决定重试或降级
- 工具层: JSONParseError，尝试容错解析；失败则上抛

业务错误码表：
- 0    = 成功
- 1001 = 项目不存在
- 1002 = 项目状态非法
- 2001 = 数据集缺失
- 2002 = 数据预处理失败
- 3001 = 向量化失败
- 3002 = 聚类失败
- 4001 = LLM 调用失败（超时/限流/网络）
- 4002 = LLM JSON 输出解析失败
- 5001 = 报告渲染失败
"""
from __future__ import annotations

from typing import Any


# ---------- 错误码常量 ----------
class ErrorCode:
    SUCCESS = 0
    PROJECT_NOT_FOUND = 1001
    PROJECT_STATUS_INVALID = 1002
    DATASET_MISSING = 2001
    PREPROCESS_FAILED = 2002
    EMBEDDING_FAILED = 3001
    CLUSTER_FAILED = 3002
    LLM_CALL_FAILED = 4001
    LLM_JSON_PARSE_FAILED = 4002
    REPORT_RENDER_FAILED = 5001


# ---------- 基类 ----------
class VOCRadarError(Exception):
    """VOC Radar 业务异常基类.

    Attributes:
        code: 业务错误码
        message: 人类可读消息
        cause: 原始异常（可选）
    """

    code: int = ErrorCode.PREPROCESS_FAILED

    def __init__(self, message: str, *, code: int | None = None, cause: Exception | None = None):
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        self.cause = cause

    def __str__(self) -> str:
        if self.cause:
            return f"{self.message} (cause: {self.cause!r})"
        return self.message


# ---------- 数据层 ----------
class DatasetError(VOCRadarError):
    """数据集相关错误（缺失/格式非法）."""
    code = ErrorCode.DATASET_MISSING


class PreprocessError(VOCRadarError):
    """预处理阶段错误."""
    code = ErrorCode.PREPROCESS_FAILED


# ---------- 模型层 ----------
class LLMError(VOCRadarError):
    """LLM 调用失败（超时/限流/网络/响应非法）."""
    code = ErrorCode.LLM_CALL_FAILED


class EmbeddingError(VOCRadarError):
    """向量化失败."""
    code = ErrorCode.EMBEDDING_FAILED


class ClusterError(VOCRadarError):
    """聚类失败."""
    code = ErrorCode.CLUSTER_FAILED


class JSONParseError(VOCRadarError):
    """LLM JSON 输出解析失败."""
    code = ErrorCode.LLM_JSON_PARSE_FAILED


# ---------- Pipeline 层 ----------
class StageError(VOCRadarError):
    """Pipeline 阶段错误.

    Attributes:
        stage: 阶段名（如 s3_cluster）
        recoverable: 是否可降级继续后续阶段
    """

    def __init__(
        self,
        stage: str,
        message: str,
        *,
        code: int | None = None,
        cause: Exception | None = None,
        recoverable: bool = False,
    ):
        super().__init__(f"[{stage}] {message}", code=code, cause=cause)
        self.stage = stage
        self.recoverable = recoverable


# ---------- API 层 ----------
class APIError(VOCRadarError):
    """API 层错误（转换为 HTTPException）."""

    def __init__(
        self,
        message: str,
        *,
        code: int,
        status_code: int = 400,
        details: Any = None,
    ):
        super().__init__(message, code=code)
        self.status_code = status_code
        self.details = details


class ProjectNotFoundError(APIError):
    def __init__(self, project_id: str):
        super().__init__(
            f"项目不存在: {project_id}",
            code=ErrorCode.PROJECT_NOT_FOUND,
            status_code=404,
        )


class ProjectStatusError(APIError):
    def __init__(self, message: str):
        super().__init__(
            message,
            code=ErrorCode.PROJECT_STATUS_INVALID,
            status_code=409,
        )
