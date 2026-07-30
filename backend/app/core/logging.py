"""统一日志配置.

格式: [时间] [级别] [模块] [request_id] 消息
输出: 控制台 + 文件（按天滚动）
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from app.core.config import settings

_FORMAT = (
    "[%(asctime)s] [%(levelname)s] [%(name)s] [%(request_id)s] %(message)s"
)
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_DEFAULT_REQUEST_ID = "-"


class _RequestIDFilter(logging.Filter):
    """为每条 LogRecord 注入默认 request_id 字段（若缺失）."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = _DEFAULT_REQUEST_ID  # type: ignore[attr-defined]
        return True


def _build_formatter() -> logging.Formatter:
    return logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT)


def setup_logging(level: str | None = None) -> None:
    """初始化全局日志.

    幂等：重复调用不会重复添加 handler。

    Args:
        level: 日志级别字符串，默认取 settings.LOG_LEVEL
    """
    root = logging.getLogger()
    if getattr(root, "_voc_radar_configured", False):
        # 已配置过，仅更新级别
        root.setLevel(level or settings.LOG_LEVEL)
        return

    root.setLevel(level or settings.LOG_LEVEL)

    formatter = _build_formatter()
    rid_filter = _RequestIDFilter()

    # 控制台 handler
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    console.addFilter(rid_filter)
    root.addHandler(console)

    # 文件 handler（按天滚动，保留 7 天）
    try:
        settings.log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.TimedRotatingFileHandler(
            filename=settings.log_dir / "app.log",
            when="midnight",
            backupCount=7,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(rid_filter)
        root.addHandler(file_handler)
    except OSError:
        # 日志目录不可写时仅用控制台
        root.warning("日志目录不可写，仅启用控制台输出: %s", settings.log_dir)

    # 调低第三方库噪音
    for noisy in ("httpx", "httpcore", "openai._base_client", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    root._voc_radar_configured = True  # type: ignore[attr-defined]


def get_logger(name: str) -> logging.Logger:
    """获取统一配置的 logger.

    Args:
        name: 模块名（建议传 __name__）

    Returns:
        logging.Logger 实例
    """
    # 首次获取时自动 setup（懒加载，避免导入即写文件）
    root = logging.getLogger()
    if not getattr(root, "_voc_radar_configured", False):
        setup_logging()
    return logging.getLogger(name)
