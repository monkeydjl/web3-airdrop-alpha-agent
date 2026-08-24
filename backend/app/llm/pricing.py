"""LLM 调用成本估算。

这个模块存在的唯一理由：**没有成本数字，预算就无法拦截。**
`LLM_DAILY_BUDGET_USD` 此前只被两个只读接口读出来展示，因为全仓根本没有
任何地方在算一次调用花了多少钱 —— 没有累计，就无从超限。

## 三个"静默变成零"的陷阱

估算成本的代码有一个特有的失效方式：**算错会被发现，算成 0 不会。**
成本永远是 0，日累计就永远是 0，预算永远不超，于是拦截逻辑虽然写了、
测了、跑着，实际效果和没写一样 —— 而且比没写更坏，因为文档会说它在保护你。

三个会导致成本静默为 0 的地方，这里逐个堵掉：

1. **未知模型**。价格表不可能覆盖所有模型（新模型每周都有，还有自建/中转
   接口用任意模型名）。如果表里查不到就返回 0，那么"换一个模型名"就等于
   "关掉预算"。所以未知模型走 `LLM_FALLBACK_PRICE_PER_1M_USD` 兜底价，
   且该兜底价故意定得偏高：**宁可高估导致提前熔断，也不要低估导致不熔断。**
   高估的后果是少花钱、看到一条明确的超预算日志；低估的后果是账单。

2. **接口不返回 `usage`**。OpenAI 兼容接口**不保证**返回 `usage` 字段
   （流式响应、部分中转、部分自建推理服务都可能省略）。缺 `usage` 就当
   0 token，同样等于关掉预算。所以缺失时按字符数估算 token，
   并把这次记账标记成 `estimated`，让运维能在指标里看到有多少比例是估的。

3. **价格单位**。各家定价页写的是 "per 1M tokens" 或 "per 1K tokens"，
   差 1000 倍。这里统一只用 **per 1M**，并且函数签名里带上单位名
   （`per_1m`），不留"这个数字是哪个单位"的猜测空间。

## 为什么用 Decimal

成本是钱。`0.1 + 0.2 != 0.3` 在浮点里是真的，而预算判断是一个
"是否 >= 阈值"的比较 —— 累加几万次浮点误差之后，`>=` 的结果就不可信了。
所有金额计算在 Decimal 域内做，只在上报指标时转成 float。

落库那一层还要再防一次：账本里存**纳美元整数**（见 `budget.py`），
因为累加发生在 SQL 的 UPSERT 里，Python 的 Decimal 管不住那个加号。

## 价格表的准确性边界（重要）

下表是**手工维护的近似价格**，不是从任何 API 实时拉取的。它一定会过时。
它的用途是"够准地估出一个能触发熔断的量级"，**不是**做账单核对。
真实账单以各家控制台为准。
"""

from __future__ import annotations

from decimal import Decimal

# 每 1M token 的美元单价：模型名 → (输入价, 输出价)
#
# 匹配方式是**前缀匹配**（见 `_lookup`），因为真实模型名常带日期/版本后缀
# （`gpt-4o-mini-2024-07-18`）。前缀匹配让这类变体自动落到正确档位，
# 而不是掉进兜底价。
#
# 价格取自 2026-08 各家公开定价页，四舍五入到便于阅读的量级。
_PRICES_PER_1M: dict[str, tuple[str, str]] = {
    # OpenAI
    "gpt-4o-mini": ("0.15", "0.60"),
    "gpt-4o": ("2.50", "10.00"),
    "gpt-4.1-mini": ("0.40", "1.60"),
    "gpt-4.1": ("2.00", "8.00"),
    "gpt-4-turbo": ("10.00", "30.00"),
    "gpt-4": ("30.00", "60.00"),
    "gpt-3.5-turbo": ("0.50", "1.50"),
    "o1-mini": ("1.10", "4.40"),
    "o1": ("15.00", "60.00"),
    # DeepSeek
    "deepseek-reasoner": ("0.55", "2.19"),
    "deepseek-chat": ("0.27", "1.10"),
    "deepseek-v": ("0.27", "1.10"),
    # Anthropic（经 OpenAI 兼容网关时也会用这些名字）
    "claude-3-5-haiku": ("0.80", "4.00"),
    "claude-3-haiku": ("0.25", "1.25"),
    "claude-3-5-sonnet": ("3.00", "15.00"),
    "claude-3-7-sonnet": ("3.00", "15.00"),
    "claude-sonnet-4": ("3.00", "15.00"),
    "claude-3-opus": ("15.00", "75.00"),
    # 其它常见中转模型
    "qwen": ("0.40", "1.20"),
    "glm-4": ("0.60", "0.60"),
    "moonshot": ("2.00", "2.00"),
    "gemini-1.5-flash": ("0.075", "0.30"),
    "gemini-1.5-pro": ("1.25", "5.00"),
    "gemini-2": ("0.30", "1.20"),
    "llama-3": ("0.20", "0.20"),
    "mistral": ("0.25", "0.25"),
}

# 记账依据（闭合词表）。这三个值会进 Prometheus 标签，必须是有限集合 ——
# 不能拼模型名进去，那会让标签基数随模型数量爆炸。
BASIS_TABLE = "table"  # 命中价格表，且接口返回了真实 usage
BASIS_FALLBACK_PRICE = "fallback_price"  # 未知模型，用兜底单价
BASIS_ESTIMATED_TOKENS = "estimated_tokens"  # 接口没返回 usage，按字符估的 token
COST_BASES: frozenset[str] = frozenset({BASIS_TABLE, BASIS_FALLBACK_PRICE, BASIS_ESTIMATED_TOKENS})

# 缺 usage 时按字符数估 token 的除数。
# 英文约 4 字符/token，中文约 1.5 字符/token；本项目 prompt 以中文为主，
# 取 2 是**偏保守**（估出的 token 偏多 → 成本偏高 → 提前熔断）。
# 同样的取向：宁可高估。
_CHARS_PER_TOKEN = Decimal("2")


def _lookup(model: str) -> tuple[Decimal, Decimal] | None:
    """按最长前缀匹配价格表。命中返回 (输入价, 输出价)，未命中返回 None。

    用最长前缀而不是任意 `in`：`gpt-4` 是 `gpt-4o` 的前缀，
    按最长匹配才能让 `gpt-4o-mini-2024-07-18` 落到 `gpt-4o-mini`（0.15）
    而不是 `gpt-4`（30.00）—— 差 200 倍。
    """
    name = (model or "").strip().lower()
    if not name:
        return None
    best: str | None = None
    for key in _PRICES_PER_1M:
        if name.startswith(key) and (best is None or len(key) > len(best)):
            best = key
    if best is None:
        return None
    raw_in, raw_out = _PRICES_PER_1M[best]
    return Decimal(raw_in), Decimal(raw_out)


def is_known_model(model: str) -> bool:
    """模型是否在价格表里（供门禁与诊断接口使用）。"""
    return _lookup(model) is not None


def estimate_tokens_from_text(*, prompt_chars: int, completion_chars: int) -> tuple[int, int]:
    """接口没返回 usage 时，按字符数估算 token 数。

    返回 (prompt_tokens, completion_tokens)，两者都**至少为 1**：
    真实发生过的一次调用不可能是 0 token，返回 0 会让这次调用免费，
    也就回到了"静默变成零"。
    """
    prompt_tokens = int(max(Decimal(1), Decimal(max(prompt_chars, 0)) / _CHARS_PER_TOKEN))
    completion_tokens = int(max(Decimal(1), Decimal(max(completion_chars, 0)) / _CHARS_PER_TOKEN))
    return prompt_tokens, completion_tokens


def estimate_cost_usd(
    *,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    fallback_price_per_1m_usd: float,
    tokens_were_estimated: bool = False,
) -> tuple[Decimal, str]:
    """估算单次调用成本（美元）与记账依据。

    Args:
        model: 模型名（可带日期/版本后缀）
        prompt_tokens / completion_tokens: token 数
        fallback_price_per_1m_usd: 未知模型的兜底单价（输入与输出同价）
        tokens_were_estimated: token 数是否是按字符估的（接口未返回 usage）

    Returns:
        (成本 Decimal, 记账依据)。依据取 `COST_BASES` 之一：
        token 是估的就报 `estimated_tokens`（这是最需要被看见的情况），
        否则未知模型报 `fallback_price`，都不是则报 `table`。
    """
    priced = _lookup(model)
    if priced is None:
        # 兜底价也要防"配成 0 就等于关掉预算"：负数与 0 一律按一个明确的
        # 非零下限处理。这里不抛异常 —— 成本估算不该成为 LLM 调用失败的原因。
        fallback = Decimal(str(max(float(fallback_price_per_1m_usd), 0.0)))
        if fallback <= 0:
            fallback = Decimal("1")
        price_in = price_out = fallback
        basis = BASIS_FALLBACK_PRICE
    else:
        price_in, price_out = priced
        basis = BASIS_TABLE

    # token 是估出来的，这件事比"用了兜底价"更值得暴露：
    # 它意味着我们连输入都不确定，而不只是单价不确定。
    if tokens_were_estimated:
        basis = BASIS_ESTIMATED_TOKENS

    million = Decimal("1000000")
    cost = (Decimal(max(prompt_tokens, 0)) * price_in + Decimal(max(completion_tokens, 0)) * price_out) / million
    return cost, basis
