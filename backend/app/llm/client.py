"""LLM client：多接口多模型**自动轮询** + provider 感知的故障转移（ADR-016）。

## 两件不同的事

**选择（轮询）**决定每次调用**从哪个组合开始**：

    请求 1 → provider-1 / model-1
    请求 2 → provider-1 / model-2
    请求 3 → provider-2 / model-1
    ...    → 一轮走完回到 provider-1 / model-1

**故障转移**决定**这一次调用里遇到失败怎么走**：

| 错误 | 行为 |
| --- | --- |
| timeout / connect / 5xx / 429 | 整个接口不可用，跳过它的剩余模型 |
| 400 / 404 / 422 / model not found | 只跳过当前模型，同接口下一个模型继续 |
| 预算拒绝 / 账本不可用 | 立即返回，**一个字节都不发** |
| 输出泄漏检测命中 | 立即返回，不重试其它组合（内容问题，换接口大概率同样内容） |
| 全部组合失败 | 返回 `text=None`，调用方降级规则引擎（ADR-001） |

轮询之前是固定顺序：每次都从第一个组合开始，成功后不记位置。于是配了
6 个接口也只有第 1 个在承担流量，其余是冷备 —— 免费额度型接口会单点耗尽。

## 使用方式

    from app.llm.client import llm_chat
    result = await llm_chat(messages=[...], temperature=0.3, max_tokens=512)
    if result.text is None:
        ...  # 回退到规则引擎

## 配置（.env，每个接口一组编号变量）

    # 接口 1
    OPENAI_BASE_URL_1=https://api.openai.com/v1
    OPENAI_API_KEY_1=<key>
    OPENAI_MODEL_1_1=gpt-4o-mini
    OPENAI_MODEL_1_2=gpt-4o

    # 接口 2
    OPENAI_BASE_URL_2=https://api.deepseek.com/v1
    OPENAI_API_KEY_2=<key>
    OPENAI_MODEL_2_1=deepseek-chat

旧编号格式 `LLM_BASEURL_N` / `LLM_API_KEY_N` / `LLM_MODELS_N_M` 在弃用窗口内
仍支持；新旧同时存在时**新格式优先**并打 warning。都没配则回退单接口
`OPENAI_API_KEY` / `OPENAI_BASE_URL` / `LLM_MODEL`。
解析与有效性校验在 `app/config.py::llm_providers`。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import httpx
import structlog

from app import metrics
from app.config import settings
from app.llm import budget as budget_mod
from app.llm import pricing
from app.utils.domain_allowlist import assert_url_allowed
from app.utils.redact import detect_secret_leak

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
class LLMUsage:
    """单次成功调用的 token 用量与估算成本。

    `estimated=True` 表示接口**没有返回 `usage` 字段**，token 数是按字符估的。
    这件事必须能被区分出来：OpenAI 兼容接口不保证返回 usage，
    而"缺 usage 就当 0 token"等于静默关掉预算。
    """

    prompt_tokens: int
    completion_tokens: int
    cost_usd: Decimal
    basis: str
    estimated: bool


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
    # 成功时的用量与成本；失败或被预算拦下时为 None
    usage: LLMUsage | None = None
    # 被预算拦下时的原因（`budget.REASON_*`）。正常调用为 None。
    # 调用方要区分"LLM 试过但失败了"和"LLM 根本没被允许调用" ——
    # 两者都返回 text=None，但前者该重试/告警，后者是预期行为。
    refused_reason: str | None = None
    # 输出泄漏（SECURITY §10.5）：text 被检测到含密钥值/密钥 pattern 而丢弃。
    # text 为 None 但 leak_detected=True，与 refused_reason / 接口全挂都不同。
    leak_detected: bool = False

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
    """生成 (provider, model) 组合的**规范顺序**。

    每个接口有自己专属的模型列表，按声明顺序展开：
    provider1+model1 → provider1+model2 → provider2+model1 → provider2+model2

    这只是**候选集合的规范序**，不是某次调用的尝试顺序 ——
    后者由 `_next_start_index()` 旋转出来（ADR-016 §3）。
    """
    combos: list[tuple[LLMProvider, str]] = []
    for provider in providers:
        for model in provider.models:
            combos.append((provider, model))
    return combos


# ── 组合级 round-robin 指针（ADR-016 §3）──────────────────────────
#
# 进程内单调计数器。**每个 uvicorn worker 各持一个**，所以多 worker /
# 多实例下不保证全局严格均衡，只保证进程内均衡；重启后从头开始。
# 这只影响流量分布，不影响 failover 正确性与预算正确性 —— 预算是全局
# 单账本（`llm/budget.py`），与选哪个组合无关。
#
# 要跨节点严格轮询就得用 Redis/DB 原子计数器，那意味着"选一个模型"先做
# 一次网络往返：为均衡付出可用性代价，而 LLM 本身只是可选增强层。
_rr_counter = 0
_rr_lock: asyncio.Lock | None = None


def _get_rr_lock() -> asyncio.Lock:
    """惰性创建锁。

    模块顶层建锁会让它绑到导入时那个 event loop 上。测试里每个 async 用例
    是一个新 loop，一个绑错 loop 的锁会在 `await acquire()` 上抛
    "attached to a different loop" —— 而那与被测逻辑毫无关系。
    """
    global _rr_lock
    if _rr_lock is None:
        _rr_lock = asyncio.Lock()
    return _rr_lock


async def _next_start_index(total: int) -> int:
    """取本次调用的起始组合下标，并把指针推进一格。

    **指针在调用开始时推进，与成功/失败无关。** 若只在成功后推进，一个
    持续失败的组合会被每次调用都当作起点重试 —— 那等于把轮询退化回固定
    顺序，还额外付出全部失败组合的超时。

    加锁是因为 `llm_chat` 会被并发调用（`LLM_SEMAPHORE_SIZE` 默认 5）。
    读改写虽然在单个 await 之间不会被打断，但显式加锁让"两个并发调用不会
    拿到同一个起点"不依赖于对字节码原子性的假设。
    """
    global _rr_counter
    if total <= 0:
        return 0
    async with _get_rr_lock():
        start = _rr_counter % total
        _rr_counter = (_rr_counter + 1) % total
    return start


def _rotate(
    combos: list[tuple[LLMProvider, str]],
    start: int,
) -> list[tuple[LLMProvider, str]]:
    """把组合列表旋转到以 `start` 开头。

    旋转而不是截断：**全部组合仍然都会被尝试**，只是顺序轮换。
    截断会让"轮到最后一个组合时只剩它自己可试"，failover 深度随请求
    序号变化 —— 那是把可用性做成了掷骰子。
    """
    if not combos:
        return []
    idx = start % len(combos)
    return combos[idx:] + combos[:idx]


def _reset_round_robin_for_tests() -> None:
    """把指针复位到 0。**仅供测试使用。**

    轮询是跨调用的进程内状态，用例之间不隔离的话，「第 1 次调用应该命中
    provider-1」这类断言会取决于同文件里前面跑了几个用例 —— 一个结论
    取决于执行顺序的断言不是断言。
    """
    global _rr_counter
    _rr_counter = 0


@dataclass
class _RawCompletion:
    """`_try_single` 的返回值：文本 + 接口自报的 usage（可能缺失）。

    为什么用 dataclass 而不是 `tuple[str, dict]`：调用方会写
    `text, usage = await _try_single(...)`，而如果某个 mock 仍返回裸字符串，
    元组解包会把 `"ab"` 拆成 `text="a"`, `usage="b"` —— **静默地错**。
    换成 dataclass，同样的错误会在 `.text` 上立刻 AttributeError。
    """

    text: str
    raw_usage: dict[str, Any] | None


def _extract_usage(
    *,
    model: str,
    raw_usage: dict[str, Any] | None,
    messages: list[dict[str, str]],
    completion_text: str,
) -> LLMUsage:
    """把接口返回的 usage（或缺失）折算成 token 数与成本。

    OpenAI 兼容接口**不保证**返回 `usage`：流式响应、部分中转、
    部分自建推理服务都可能省略。缺失时按字符估算并标记 `estimated=True` ——
    **"缺 usage 就当 0 token"等于静默关掉预算**，而现象是"预算怎么都不触发"。
    """
    prompt_tokens = 0
    completion_tokens = 0
    if isinstance(raw_usage, dict):
        try:
            prompt_tokens = int(raw_usage.get("prompt_tokens") or 0)
            completion_tokens = int(raw_usage.get("completion_tokens") or 0)
        except (TypeError, ValueError):
            prompt_tokens = completion_tokens = 0

    estimated = prompt_tokens <= 0 and completion_tokens <= 0
    if estimated:
        prompt_chars = sum(len(str(m.get("content") or "")) for m in messages)
        prompt_tokens, completion_tokens = pricing.estimate_tokens_from_text(
            prompt_chars=prompt_chars,
            completion_chars=len(completion_text),
        )

    cost, basis = pricing.estimate_cost_usd(
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        fallback_price_per_1m_usd=float(getattr(settings, "llm_fallback_price_per_1m_usd", 10.0)),
        tokens_were_estimated=estimated,
    )
    return LLMUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=cost,
        basis=basis,
        estimated=estimated,
    )


async def _try_single(
    provider: LLMProvider,
    model: str,
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int,
    timeout: float | None,
) -> _RawCompletion:
    """尝试单个 provider + model 组合。成功返回文本与 usage，失败抛异常。"""
    url = provider.base_url.rstrip("/") + "/chat/completions"
    # 域名白名单（SECURITY §10.2）：provider 域名已由 allowed_domains() 动态放行，
    # 这里防御的是 url 拼接 bug 把请求带到表外域名。表外直接 fail-closed。
    assert_url_allowed(url)
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
        raw_usage = data.get("usage")
        return _RawCompletion(
            text=str(content).strip(),
            raw_usage=raw_usage if isinstance(raw_usage, dict) else None,
        )


async def llm_chat(
    messages: list[dict[str, str]],
    temperature: float | None = None,
    max_tokens: int | None = None,
    timeout: float | None = None,
    prompt_version: str | None = None,
) -> LLMResult:
    """带故障转移与日预算拦截的 LLM 调用。

    调用顺序上，**预算检查在任何网络请求之前** —— 这是"拦截"和"事后记账"
    的区别所在。预算耗尽时直接返回 `refused_reason`，一个字节都不发出去。

    Args:
        messages: OpenAI 格式的消息列表
        temperature: 采样温度（默认使用 settings.llm_temperature）
        max_tokens: 最大 token 数（默认使用 settings.llm_max_tokens）
        timeout: 请求超时（秒，默认 45s，连接超时 10s）
        prompt_version: 当前使用的 prompt 版本标识（E3 §5.4.9，可选）

    Returns:
        LLMResult，包含文本、故障转移轨迹、用量成本，或被拒原因
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

    # ── 日预算闸门 ──────────────────────────────────────────────
    # 放在故障转移循环之外：预算是"今天还能不能花钱"，与试哪个接口无关。
    # 放在循环里会让一次超预算的调用把每个组合都试一遍再各自拒绝。
    decision = budget_mod.check_budget(budget_usd=float(settings.llm_daily_budget_usd))
    metrics.set_llm_budget_state(
        budget_usd=float(decision.budget_usd),
        spent_today_usd=float(decision.spent_usd),
    )
    if not decision.allowed:
        metrics.record_llm_budget_block(reason=decision.reason)
        logger.warning(
            "llm.refused_by_budget",
            reason=decision.reason,
            budget_usd=float(decision.budget_usd),
            spent_usd=float(decision.spent_usd),
        )
        return LLMResult(
            text=None,
            provider_used=None,
            model_used=None,
            prompt_version=prompt_version,
            refused_reason=decision.reason,
        )

    temp = temperature if temperature is not None else settings.llm_temperature
    tokens = max_tokens if max_tokens is not None else settings.llm_max_tokens

    # ── 组合级轮询（ADR-016 §3）─────────────────────────────────
    # 起点每次调用推进一格，遍历顺序是从该起点开始的**旋转序列**。
    # 全部组合仍会被试到，failover 深度不随请求序号变化。
    canonical = _build_combinations(providers)
    start_index = await _next_start_index(len(canonical))
    combinations = _rotate(canonical, start_index)
    attempts: list[LLMAttempt] = []
    if combinations:
        first_provider, first_model = combinations[0]
        logger.debug(
            "llm.round_robin_selected",
            start_index=start_index,
            candidate_count=len(combinations),
            provider=first_provider.name,
            model=first_model,
        )

    # 连接级失败的 provider 名。命中后跳过它的剩余模型 ——
    # 接口连不上是**接口的问题**，换一个模型名再连同一个地址不会有别的结果，
    # 只会再付一个连接超时（默认 10s）。owner 的配置是 6 接口 × 2~3 模型，
    # 一个挂掉的接口不跳过就要空等 20~30s。
    #
    # ⚠️ 这里刻意用 set 而不是原来那种「重建 combinations 列表」的写法：
    # `for x in combinations` 在进入循环时就取好了迭代器，之后把
    # `combinations` 这个**名字**指向新列表**完全不影响正在进行的迭代** ——
    # 原实现的 provider 跳过其实是死代码，一直在逐个模型重试挂掉的接口。
    # 它没被测出来是因为既有用例里每个 provider 只配了 1 个模型，
    # 「跳过剩余模型」和「没有剩余模型」看起来一样。
    failed_providers: set[str] = set()

    for combo_index, (provider, model) in enumerate(combinations):
        if provider.name in failed_providers:
            continue

        attempt = LLMAttempt(
            provider=provider.name,
            model=model,
            success=False,
        )
        start = time.monotonic()

        try:
            completion = await _try_single(
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
            metrics.record_llm_attempt(model=model, ok=True, duration_seconds=attempt.elapsed_ms / 1000)

            usage = _extract_usage(
                model=model,
                raw_usage=completion.raw_usage,
                messages=messages,
                completion_text=completion.text,
            )
            metrics.record_llm_cost(
                model=model,
                basis=usage.basis,
                cost_usd=float(usage.cost_usd),
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
            )
            # 记账失败不影响返回值：钱已经花了，丢掉结果是纯亏损。
            # 但要让"少记了多少次"可被观测 —— 未记账的花费永远不计入预算。
            if not budget_mod.record_spend(
                cost_usd=usage.cost_usd,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
            ):
                metrics.record_llm_spend_record_failure()

            # ── 输出泄漏过滤（SECURITY §10.5）────────────────────────
            # 成本在前面的 record_spend 已记账（钱已花，不能因丢弃而漏记，否则
            # 预算静默失效）。命中则丢弃结果：text=None + leak_detected=True，
            # 调用方据此回退规则引擎。不重试下一个组合 —— 泄漏是内容问题，
            # 换接口/模型大概率吐出同样的内容，且丢弃应是 fail-closed。
            leak_category = detect_secret_leak(completion.text)
            if leak_category is not None:
                metrics.record_llm_leak_detected()
                logger.error(
                    "llm.secret_leak_detected",
                    provider=provider.name,
                    model=model,
                    prompt_version=prompt_version,
                    pattern=leak_category,
                )
                return LLMResult(
                    text=None,
                    provider_used=provider.name,
                    model_used=model,
                    attempts=attempts,
                    prompt_version=prompt_version,
                    usage=usage,
                    leak_detected=True,
                )

            logger.info(
                "llm.success",
                provider=provider.name,
                model=model,
                elapsed_ms=round(attempt.elapsed_ms, 1),
                attempt_count=len(attempts),
                prompt_version=prompt_version,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                cost_usd=float(usage.cost_usd),
                cost_basis=usage.basis,
            )

            return LLMResult(
                text=completion.text,
                provider_used=provider.name,
                model_used=model,
                attempts=attempts,
                prompt_version=prompt_version,
                usage=usage,
            )

        except Exception as exc:
            attempt.elapsed_ms = (time.monotonic() - start) * 1000
            attempt.error = str(exc)[:200]
            attempts.append(attempt)
            metrics.record_llm_attempt(model=model, ok=False, duration_seconds=attempt.elapsed_ms / 1000)

            is_conn = _is_connection_error(exc)
            is_model = _is_model_error(exc)

            # will_retry 必须算「本次失败之后**真的还会被尝试**的组合」，
            # 不能用 `len(attempts) < len(combinations)`：
            #   1. 跳过的组合不进 attempts，计数与下标脱钩；
            #   2. 连接失败会让本 provider 剩余模型全部作废，
            #      拿总数比较只会朝「还有兜底」的方向错报。
            # 这个字段是排查降级时第一眼看的东西 —— 报 True 却直接返回
            # None，会把排查引向「重试为什么没生效」这个不存在的问题。
            skipped = failed_providers | ({provider.name} if is_conn else set())
            will_retry = any(p.name not in skipped for p, _ in combinations[combo_index + 1 :])

            logger.warning(
                "llm.attempt_failed",
                provider=provider.name,
                model=model,
                error_type="connection" if is_conn else "model" if is_model else "other",
                error=attempt.error,
                elapsed_ms=round(attempt.elapsed_ms, 1),
                will_retry=will_retry,
            )

            # 连接错误（timeout / connect / 5xx / 429）：整个接口不可用，
            # 跳过它的剩余模型，直接进下一个 provider。
            if is_conn:
                failed_providers.add(provider.name)
                continue

            # 模型错误或其他错误：只跳过当前模型，同接口下一个模型继续
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
