"""SSE 进度推送管理：每个项目一个 asyncio.Queue，orchestrator 推送，SSE 端点订阅.

设计:
- project_id -> asyncio.Queue 的映射（每项目一个队列）
- orchestrator 通过 publish_event 推送事件
- /projects/{id}/progress 端点通过 subscribe 消费事件并转 SSE 格式
- 项目完成后自动清理队列
- 支持多客户端订阅同一项目（fan-out）

注意:
- 队列大小有限（默认 100），溢出时丢弃旧事件并 warning
- 项目结束（complete/error）后，等待 5s 让客户端取完最后事件再清理
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class _Subscription:
    """单个订阅（一个客户端一个）."""

    queue: asyncio.Queue
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    closed: bool = False


class ProgressManager:
    """进度推送管理器（项目级 fan-out）."""

    def __init__(self, queue_maxsize: int = 100) -> None:
        self.queue_maxsize = queue_maxsize
        # project_id -> list[_Subscription]
        self._subs: dict[str, list[_Subscription]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, project_id: str) -> _Subscription:
        """订阅某项目的进度事件.

        Returns:
            _Subscription（含 queue）
        """
        async with self._lock:
            sub = _Subscription(queue=asyncio.Queue(maxsize=self.queue_maxsize))
            self._subs.setdefault(project_id, []).append(sub)
            logger.debug(
                "[progress] 订阅 project=%s, 当前订阅数=%d",
                project_id,
                len(self._subs[project_id]),
            )
            return sub

    async def unsubscribe(self, project_id: str, sub: _Subscription) -> None:
        """取消订阅."""
        async with self._lock:
            sub.closed = True
            subs = self._subs.get(project_id, [])
            if sub in subs:
                subs.remove(sub)
            if not subs:
                self._subs.pop(project_id, None)

    async def publish(self, project_id: str, event: dict[str, Any]) -> None:
        """向某项目的所有订阅者推送事件.

        Args:
            project_id: 项目 ID
            event: 事件 dict，含 event / data 字段
        """
        async with self._lock:
            subs = list(self._subs.get(project_id, []))
        if not subs:
            return
        for sub in subs:
            if sub.closed:
                continue
            try:
                sub.queue.put_nowait(event)
            except asyncio.QueueFull:
                # 丢弃最旧的事件（保证最新进度可见）
                try:
                    sub.queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    sub.queue.put_nowait(event)
                except asyncio.QueueFull:
                    logger.warning(
                        "[progress] 队列仍满，丢弃事件 project=%s", project_id
                    )

    async def close_project(self, project_id: str, delay: float = 5.0) -> None:
        """项目结束后清理（延迟，让客户端取完最后事件）."""
        await asyncio.sleep(delay)
        async with self._lock:
            subs = self._subs.pop(project_id, [])
        for sub in subs:
            sub.closed = True


# ---------- 全局单例 ----------
_manager: ProgressManager | None = None


def get_progress_manager() -> ProgressManager:
    """获取全局 ProgressManager 单例."""
    global _manager
    if _manager is None:
        _manager = ProgressManager()
    return _manager


# ---------- SSE 格式化 ----------
def format_sse(event: dict[str, Any]) -> str:
    """将事件 dict 转为 SSE 文本格式.

    输入: {"event": "progress", "data": {...}}
    输出: "event: progress\\ndata: {json}\\n\\n"
    """
    import json

    event_type = event.get("event", "message")
    data = event.get("data", {})
    # data 可能含非 str 值，序列化为 JSON
    data_str = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event_type}\ndata: {data_str}\n\n"
