"""Model Router 客户端封装（OpenAI 兼容格式）.

所有模型调用统一走本模块，禁止在 stage / service 中直接 import openai。
提供三个核心方法：
- embed(texts)          批量向量化
- chat(messages)        通用对话调用（qwen-max / R1 共用）
- chat_json(messages)   要求 JSON 输出的对话调用（含解析容错）
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, AsyncIterator, Optional

from openai import AsyncOpenAI, APIError, APITimeoutError, RateLimitError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings
from app.core.exceptions import EmbeddingError, LLMError, JSONParseError
from app.utils.json_helpers import extract_json_block, parse_llm_json

logger = logging.getLogger(__name__)


# ---------- 重试装饰器 ----------
def _retry_on_llm_error(retries: int):
    """LLM 调用重试装饰器（指数退避 1s/2s/4s）."""
    return retry(
        retry=retry_if_exception_type((APITimeoutError, RateLimitError, ConnectionError)),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        stop=stop_after_attempt(retries),
        reraise=True,
    )


class ModelRouterClient:
    """Model Router 统一客户端（OpenAI 兼容格式）.

    通过 .env 配置 api_key 与 base_url，方便切换个人百炼 / 比赛 Model Router。
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.MODEL_ROUTER_API_KEY
        self.base_url = (
            base_url if base_url is not None else settings.MODEL_ROUTER_BASE_URL
        )
        self.timeout = timeout if timeout is not None else float(settings.LLM_TIMEOUT_SECONDS)

        if not self.api_key:
            logger.warning(
                "MODEL_ROUTER_API_KEY 未配置，LLM 调用将失败。"
                "请在 backend/.env 中设置。"
            )

        self.client = AsyncOpenAI(
            api_key=self.api_key or "missing-key",
            base_url=self.base_url,
            timeout=self.timeout,
            max_retries=0,  # 由本类的 tenacity 重试控制
        )

    # ---------- embed ----------
    async def embed(
        self,
        texts: list[str],
        model: str | None = None,
        batch_size: int | None = None,
    ) -> list[list[float]]:
        """批量向量化.

        Args:
            texts: 文本列表
            model: 向量化模型名，默认取 settings.MODEL_EMBEDDING
            batch_size: 每批最大条数，默认取 settings.EMBEDDING_BATCH_SIZE

        Returns:
            与 texts 等长的向量列表（每条是一个 float 列表）

        Raises:
            EmbeddingError: 调用失败
        """
        if not texts:
            return []

        model = model or settings.MODEL_EMBEDDING
        batch_size = batch_size or settings.EMBEDDING_BATCH_SIZE

        results: list[list[float]] = []
        total = len(texts)
        for i in range(0, total, batch_size):
            batch = texts[i : i + batch_size]
            try:
                response = await self._embed_batch(batch, model)
                results.extend(response)
                logger.debug(
                    "embed batch %d-%d/%d ok (model=%s)",
                    i,
                    i + len(batch),
                    total,
                    model,
                )
            except Exception as e:
                logger.error("embed batch 失败 (%d-%d): %s", i, i + len(batch), e)
                raise EmbeddingError(
                    f"向量化失败 batch[{i}:{i + len(batch)}]: {e}",
                    cause=e,
                ) from e
        return results

    async def _embed_batch(self, texts: list[str], model: str) -> list[list[float]]:
        """单批调用 embedding API."""
        # 某些 OpenAI 兼容端点用 input 而不是 inputs
        # openai SDK 1.x 接口: client.embeddings.create(model=, input=[])
        resp = await self.client.embeddings.create(model=model, input=texts)
        # 按 index 排序保证顺序
        sorted_data = sorted(resp.data, key=lambda d: d.index)
        return [d.embedding for d in sorted_data]

    # ---------- chat ----------
    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int | None = None,
        response_format: dict | None = None,
        stream: bool = False,
    ) -> str | AsyncIterator:
        """通用对话调用（qwen-max / R1 共用）.

        Args:
            messages: OpenAI 消息列表 [{"role":"system","content":"..."}, ...]
            model: 模型名，默认 settings.MODEL_LLM
            temperature: 采样温度
            max_tokens: 最大生成 token 数
            response_format: OpenAI response_format（如 {"type": "json_object"}）
            stream: 是否流式

        Returns:
            非流式: 字符串内容
            流式: AsyncIterator，逐 chunk 输出 delta.content

        Raises:
            LLMError: 调用失败
        """
        model = model or settings.MODEL_LLM
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if response_format is not None:
            kwargs["response_format"] = response_format
        if stream:
            kwargs["stream"] = True

        try:
            start = time.time()
            if stream:
                return self._stream_chat(kwargs)

            response = await self._chat_call(kwargs, model)
            content = response.choices[0].message.content or ""
            latency_ms = int((time.time() - start) * 1000)

            # 记录 token 用量
            usage = getattr(response, "usage", None)
            prompt_t = getattr(usage, "prompt_tokens", None) if usage else None
            completion_t = getattr(usage, "completion_tokens", None) if usage else None
            logger.info(
                "LLM chat ok model=%s latency_ms=%d prompt_tokens=%s completion_tokens=%s",
                model,
                latency_ms,
                prompt_t,
                completion_t,
            )
            return content
        except Exception as e:
            logger.error("LLM chat 失败 model=%s: %s", model, e)
            raise LLMError(f"LLM 调用失败 model={model}: {e}", cause=e) from e

    async def _stream_chat(self, kwargs: dict[str, Any]) -> AsyncIterator:
        """流式输出."""
        try:
            stream = await self.client.chat.completions.create(**kwargs)
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            raise LLMError(f"LLM 流式调用失败: {e}", cause=e) from e

    @_retry_on_llm_error(settings.R1_MAX_RETRIES)
    async def _chat_call(self, kwargs: dict[str, Any], model: str):
        """带重试的非流式 chat 调用."""
        try:
            return await self.client.chat.completions.create(**kwargs)
        except (APITimeoutError, RateLimitError, ConnectionError) as e:
            # 由 tenacity 重试
            logger.warning("LLM 调用失败（重试中）model=%s: %s", model, e)
            raise
        except APIError as e:
            raise LLMError(f"LLM API 错误 model={model}: {e}", cause=e) from e

    @_retry_on_llm_error(settings.R1_MAX_RETRIES)
    async def _embed_call(self, *args, **kwargs):
        """带重试的 embedding 调用（保留扩展位）."""
        return await self.client.embeddings.create(*args, **kwargs)

    # ---------- chat_json ----------
    async def chat_json(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        schema: dict | None = None,
        temperature: float = 0.2,
    ) -> dict:
        """要求 JSON 输出的对话调用（含解析容错）.

        Args:
            messages: 消息列表（建议在 system prompt 中明确要求输出 JSON）
            model: 模型名
            schema: 期望 JSON schema（仅用于 prompt 提示，部分模型支持原生 schema）
            temperature: 采样温度（默认 0.2，JSON 输出宜低）

        Returns:
            解析后的 dict

        Raises:
            JSONParseError: JSON 解析失败（含容错尝试后仍失败）
            LLMError: 调用本身失败
        """
        # 在 system 中追加 JSON 指令
        if schema:
            schema_hint = (
                "\n\n请严格按照以下 JSON Schema 输出（仅输出 JSON，无其他文本）:\n"
                + json.dumps(schema, ensure_ascii=False, indent=2)
            )
            messages = list(messages)
            if messages and messages[0].get("role") == "system":
                messages[0] = {
                    "role": "system",
                    "content": messages[0]["content"] + schema_hint,
                }
            else:
                messages.insert(0, {"role": "system", "content": schema_hint})

        # 显式要求 JSON 输出（部分 OpenAI 兼容端点支持）
        try:
            content = await self.chat(
                messages=messages,
                model=model,
                temperature=temperature,
                response_format={"type": "json_object"},
            )
        except LLMError:
            # response_format 不被支持时降级
            content = await self.chat(
                messages=messages,
                model=model,
                temperature=temperature,
            )

        if not content or not isinstance(content, str):
            raise JSONParseError("LLM 返回空内容，无法解析 JSON")

        try:
            return parse_llm_json(content)
        except JSONParseError:
            logger.warning("JSON 容错解析失败，原始内容前 500 字: %s", content[:500])
            raise


# ---------- 全局单例 ----------
_model_router: ModelRouterClient | None = None


def get_model_router() -> ModelRouterClient:
    """获取全局 ModelRouterClient 单例."""
    global _model_router
    if _model_router is None:
        _model_router = ModelRouterClient()
    return _model_router


def reset_model_router() -> None:
    """重置单例（测试用）."""
    global _model_router
    _model_router = None


# 模块级单例（按架构文档约定）
model_router = get_model_router()
