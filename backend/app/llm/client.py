"""LLM client with multi-provider / multi-model failover.

故障转移策略：
1. 接口1连不上（ConnectError / TimeoutException） → 切换接口2
2. 模型1调用失败（400 / 404 / "model not found"） → 切换模型2
3. 所有组合都失败 → 返回 None（调用方回退到 rule-based）

使用方式：
    from app.llm.client import llm_chat
    text = await llm_chat(messages=[...], temperature=0.3, max_tokens=512)
    if text is None:
        # 回退到规则引擎
        ...

配置（.env，每个接口一组编号变量）：
    # 接口 1
    LLM_BASEURL_1=https://api.openai.com/v1
    LLM_API_KEY_1=sk-xxx
    LLM_MODELS_1_1=gpt-4o-mini
    LLM_MODELS_1_2=gpt-4o

    # 接口 2
    LLM_BASEURL_2=https://api.deepseek.com/v1
    LLM_API_KEY_2=sk-yyy
    LLM_MODELS_2_1=deepseek-chat
    LLM_MODELS_2_2=deepseek-reasoner

    # 单接口（向后兼容，未配置编号接口时生效）
    OPENAI_API_KEY=sk-xxx
    OPENAI_BASE_URL=https://api.openai.com/v1
    LLM_MODEL=gpt-4o-mini
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog

from app.config import settings

logger = structlog.get_logger(__name__)

# 默认请求超时（秒）
_DEFAULT_TIMEOUT = 45.0
# 连接超时（秒）— 连不上就快速切换到下一个接口
_CONNECT_TIMEOUT = 10.0


@dataclass
class LLMProvider:
    """单个 LLM 接口配置（含该接口专属的模型列表）。"""

    base_url: str
    api_key: str
    name: str = "provider"
    models: list[str] = field(default_factory=list)


@dataclass
class LLMAttempt:
    """单次尝试的结果记录。"""

    provider: str
    model: str
    success: bool
    error: str = ""
    elapsed_ms: float = 0.0


@dataclass
class LLMResult:
    """LLM 调用结果（含故障转移轨迹）。"""

    text: str | None
    provider_used: str | None
    model_used: str | None
    attempts: list[LLMAttempt] = field(default_factory=list)
    prompt_version: str | None = None  # E3 (§5.4.9): 记录使用的 prompt 版本

    @property
    def ok(self) -> bool:
        return self.text is not None


def _get_providers() -> list[LLMProvider]:
    """从 settings 解析 provider 列表（每个 provider 自带模型列表）。"""
    return [
        LLMProvider(
            base_url=p["base_url"],
            api_key=p["api_key"],
            name=p["name"],
            models=p.get("models", []),
        )
        for p in settings.llm_providers
    ]


def _is_connection_error(exc: Exception) -> bool:
    """是否为连接级错误（应切换接口）。"""
    if isinstance(exc, (httpx.ConnectError, httpx.TimeoutException)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        # 5xx / 429 视为接口侧问题
        return exc.response.status_code >= 500 or exc.response.status_code == 429
    return False


def _is_model_error(exc: Exception) -> bool:
    """是否为模型级错误（应切换模型，而非切换接口）。"""
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        body = exc.response.text.lower()
        # 400 / 404 / 422 通常意味着模型名错误或不支持
        if status in (400, 404, 422):
            return True
        if "model" in body and ("not found" in body or "invalid" in body or "deprecat" in body):
            return True
    return False


def _build_combinations(providers: list[LLMProvider]) -> list[tuple[LLMProvider, str]]:
    """生成 (provider, model) 尝试组合列表。

    每个接口有自己专属的模型列表，按顺序遍历：
    provider1+model1 → provider1+model2 → provider2+model1 → provider2+model2
    """
    combos: list[tuple[LLMProvider, str]] = []
    for provider in providers:
        for model in provider.models:
            combos.append((provider, model))
    return combos


async def _try_single(
    provider: LLMProvider,
    model: str,
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int,
    timeout: float | None,
) -> str:
    """尝试单个 provider + model 组合。成功返回文本，失败抛异常。"""
    url = provider.base_url.rstrip("/") + "/chat/completions"
    body: dict[str, Any] = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": messages,
    }

    timeout_cfg = httpx.Timeout(
        timeout or _DEFAULT_TIMEOUT,
        connect=_CONNECT_TIMEOUT,
    )

    async with httpx.AsyncClient(timeout=timeout_cfg) as client:
        resp = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {provider.api_key}",
                "Content-Type": "application/json",
            },
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content")
        if not content or not str(content).strip():
            raise ValueError("Empty LLM response")
        return str(content).strip()


async def llm_chat(
    messages: list[dict[str, str]],
    temperature: float | None = None,
    max_tokens: int | None = None,
    timeout: float | None = None,
    prompt_version: str | None = None,
) -> LLMResult:
    """带故障转移的 LLM 调用。

    Args:
        messages: OpenAI 格式的消息列表
        temperature: 采样温度（默认使用 settings.llm_temperature）
        max_tokens: 最大 token 数（默认使用 settings.llm_max_tokens）
        timeout: 请求超时（秒，默认 45s，连接超时 10s）
        prompt_version: 当前使用的 prompt 版本标识（E3 §5.4.9，可选）

    Returns:
        LLMResult，包含文本和故障转移轨迹
    """
    providers = _get_providers()

    if not providers:
        logger.warning("llm.no_providers_configured")
        return LLMResult(text=None, provider_used=None, model_used=None, prompt_version=prompt_version)

    # 检查是否所有 provider 都没有配置模型
    has_models = any(p.models for p in providers)
    if not has_models:
        logger.warning("llm.no_models_configured")
        return LLMResult(text=None, provider_used=None, model_used=None, prompt_version=prompt_version)

    temp = temperature if temperature is not None else settings.llm_temperature
    tokens = max_tokens if max_tokens is not None else settings.llm_max_tokens

    combinations = _build_combinations(providers)
    attempts: list[LLMAttempt] = []

    for provider, model in combinations:
        attempt = LLMAttempt(
            provider=provider.name,
            model=model,
            success=False,
        )
        start = time.monotonic()

        try:
            text = await _try_single(
                provider=provider,
                model=model,
                messages=messages,
                temperature=temp,
                max_tokens=tokens,
                timeout=timeout,
            )
            attempt.success = True
            attempt.elapsed_ms = (time.monotonic() - start) * 1000
            attempts.append(attempt)

            logger.info(
                "llm.success",
                provider=provider.name,
                model=model,
                elapsed_ms=round(attempt.elapsed_ms, 1),
                attempt_count=len(attempts),
                prompt_version=prompt_version,
            )

            return LLMResult(
                text=text,
                provider_used=provider.name,
                model_used=model,
                attempts=attempts,
                prompt_version=prompt_version,
            )

        except Exception as exc:
            attempt.elapsed_ms = (time.monotonic() - start) * 1000
            attempt.error = str(exc)[:200]
            attempts.append(attempt)

            is_conn = _is_connection_error(exc)
            is_model = _is_model_error(exc)

            logger.warning(
                "llm.attempt_failed",
                provider=provider.name,
                model=model,
                error_type="connection" if is_conn else "model" if is_model else "other",
                error=attempt.error,
                elapsed_ms=round(attempt.elapsed_ms, 1),
                will_retry=len(attempts) < len(combinations),
            )

            # 连接错误：跳过当前 provider 剩余模型，直接切到下一个 provider
            if is_conn:
                remaining = [
                    c for c in combinations[len(attempts):]
                    if c[0] != provider
                ]
                combinations = combinations[:len(attempts)] + remaining
                continue

            # 模型错误或其他错误：继续尝试下一个组合
            continue

    logger.error(
        "llm.all_providers_failed",
        attempts=len(attempts),
        providers_tried=list({a.provider for a in attempts}),
        models_tried=list({a.model for a in attempts}),
    )

    return LLMResult(
        text=None,
        provider_used=None,
        model_used=None,
        attempts=attempts,
        prompt_version=prompt_version,
    )


async def llm_chat_simple(
    messages: list[dict[str, str]],
    temperature: float | None = None,
    max_tokens: int | None = None,
    timeout: float | None = None,
    prompt_version: str | None = None,
) -> str | None:
    """简化版：直接返回文本或 None。

    适用于不关心故障转移轨迹的调用方。
    """
    result = await llm_chat(
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        prompt_version=prompt_version,
    )
    return result.text
