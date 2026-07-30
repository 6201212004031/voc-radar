"""LLM 统一调用封装：qwen-max / R1 共用.

职责:
- 屏蔽 model_router 的细节，向上提供"业务语义"方法
- 封装 prompt 模板调用
- 提供 R1 vs qwen-max 对比调用的便捷方法（P1）

注意: prompt 模板本身在 app/pipeline/prompts/ 中管理，本模块只负责调用。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.core.exceptions import LLMError
from app.services.model_router import ModelRouterClient, get_model_router

logger = logging.getLogger(__name__)


@dataclass
class LLMCallResult:
    """LLM 调用结果（含元信息，便于成本追踪与对比实验）."""

    content: str
    """LLM 输出的文本内容"""

    model: str
    """实际使用的模型名"""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    latency_ms: int = 0
    raw_response: Any = None


class LLMService:
    """LLM 统一调用服务.

    提供 qwen-max / R1 的高层封装，记录 token 用量与延迟。
    """

    def __init__(self, client: ModelRouterClient | None = None) -> None:
        self.client = client or get_model_router()

    # ---------- qwen-max 调用 ----------
    async def qwen_chat(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.3,
        max_tokens: int | None = None,
        model: str | None = None,
    ) -> str:
        """调用 qwen3.7-max 进行对话.

        Args:
            prompt: user 消息内容
            system: 可选的 system 消息
            temperature: 采样温度
            max_tokens: 最大生成 token
            model: 模型名（默认 settings.MODEL_LLM）

        Returns:
            LLM 输出文本
        """
        messages = self._build_messages(prompt, system)
        return await self.client.chat(
            messages=messages,
            model=model or settings.MODEL_LLM,
            temperature=temperature,
            max_tokens=max_tokens,
        )  # type: ignore[return-value]

    async def qwen_json(
        self,
        prompt: str,
        system: str | None = None,
        schema: dict | None = None,
        temperature: float = 0.2,
        model: str | None = None,
    ) -> dict:
        """调用 qwen-max 并要求 JSON 输出.

        Returns:
            解析后的 dict
        """
        messages = self._build_messages(prompt, system)
        return await self.client.chat_json(
            messages=messages,
            model=model or settings.MODEL_LLM,
            schema=schema,
            temperature=temperature,
        )

    # ---------- R1 调用 ----------
    async def r1_chat(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> str:
        """调用 DeepSeek-R1 进行深度推理.

        R1 适合根因归因等需要深度推理的场景。
        超时/失败时由调用方决定是否降级到 qwen-max。

        Args:
            prompt: user 消息内容
            system: 可选 system 消息（建议包含推理约束规则）
            temperature: R1 推荐 0.3-0.5
            max_tokens: 最大生成 token（R1 推理链可能较长，建议 2048+）

        Returns:
            R1 输出文本
        """
        messages = self._build_messages(prompt, system)
        try:
            return await self.client.chat(  # type: ignore[return-value]
                messages=messages,
                model=settings.MODEL_R1,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except LLMError as e:
            logger.warning("R1 调用失败，由调用方决定降级: %s", e)
            raise

    async def r1_json(
        self,
        prompt: str,
        system: str | None = None,
        schema: dict | None = None,
        temperature: float = 0.3,
    ) -> dict:
        """R1 调用并要求 JSON 输出（容错解析）."""
        messages = self._build_messages(prompt, system)
        return await self.client.chat_json(
            messages=messages,
            model=settings.MODEL_R1,
            schema=schema,
            temperature=temperature,
        )

    # ---------- 对比实验（P1） ----------
    async def compare_attribution(
        self,
        prompt: str,
        system: str | None = None,
        schema: dict | None = None,
    ) -> dict[str, dict]:
        """同一 prompt 分别用 R1 和 qwen-max 归因，返回对比结果.

        P1：用于详情面板"对比视图" tab。

        Returns:
            {"r1": {...}, "qwen": {...}}
        """
        results: dict[str, dict] = {}

        # R1
        try:
            results["r1"] = await self.r1_json(prompt, system, schema)
        except LLMError as e:
            results["r1"] = {"error": str(e)}

        # qwen-max
        try:
            results["qwen"] = await self.qwen_json(prompt, system, schema)
        except LLMError as e:
            results["qwen"] = {"error": str(e)}

        return results

    # ---------- 工具 ----------
    @staticmethod
    def _build_messages(prompt: str, system: str | None) -> list[dict[str, str]]:
        """构造 OpenAI 消息列表."""
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return messages


# ---------- 全局单例 ----------
_llm_service: LLMService | None = None


def get_llm_service() -> LLMService:
    """获取全局 LLMService 单例."""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service
