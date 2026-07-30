"""API 公共响应模型与工具.

统一响应格式:
{
  "code": 0,
  "message": "ok",
  "data": {...} | null,
  "request_id": "uuid"
}
"""
from __future__ import annotations

import uuid
from typing import Any, Generic, Optional, TypeVar

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """统一响应模型."""

    code: int = Field(default=0, description="业务错误码，0 表示成功")
    message: str = Field(default="ok", description="人类可读消息")
    data: Optional[T] = None
    request_id: str = Field(default="", description="请求 ID")


class PageVO(BaseModel, Generic[T]):
    """分页响应."""

    items: list[T]
    total: int
    page: int
    size: int
    pages: int


def success(data: Any = None, message: str = "ok", request_id: str | None = None) -> dict:
    """构造成功响应 dict."""
    return {
        "code": 0,
        "message": message,
        "data": data,
        "request_id": request_id or _gen_request_id(),
    }


def error(
    code: int,
    message: str,
    *,
    data: Any = None,
    request_id: str | None = None,
    status_code: int = 400,
) -> JSONResponse:
    """构造失败响应（HTTPException 替代）."""
    return JSONResponse(
        status_code=status_code,
        content={
            "code": code,
            "message": message,
            "data": data,
            "request_id": request_id or _gen_request_id(),
        },
    )


def _gen_request_id() -> str:
    return str(uuid.uuid4())


def get_request_id(request: Request) -> str:
    """从 Request 中获取或生成 request_id."""
    rid = request.headers.get("X-Request-ID")
    if rid:
        return rid
    return _gen_request_id()
