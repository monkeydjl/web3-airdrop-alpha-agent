"""Secret redaction helpers.

采集器把 httpx 异常字符串写入日志与 collection_logs，而 httpx 会把完整 URL
（含 query 中的 apikey）渲染进异常信息。此模块提供统一脱敏，避免密钥落盘/落日志。
"""

from __future__ import annotations

import re

from app.config import settings

# 常见密钥类配置名（settings 上的属性），值非空时纳入脱敏集合
_SECRET_ATTRS = (
    "etherscan_api_key",
    "cryptorank_api_key",
    "coingecko_api_key",
    "github_token",
    "twitter_bearer_token",
    "twitter_api_key",
    "rootdata_api_key",
    "galxe_api_key",
    "layer3_api_key",
    "alchemy_api_key",
    "dune_api_key",
    "openai_api_key",
    "llm_api_keys",
    "api_key",
    "database_url",
)

# query 中形如 apikey=xxx / api_key=xxx / token=xxx 的兜底脱敏
_QUERY_SECRET_RE = re.compile(r"(?i)([?&](?:api[_-]?key|apikey|token|access[_-]?token|key)=)[^&\s'\"]+")


def _known_secrets() -> list[str]:
    values: list[str] = []
    for attr in _SECRET_ATTRS:
        val = getattr(settings, attr, None)
        if isinstance(val, str) and len(val.strip()) >= 6:
            values.append(val.strip())
    # 长的先替换，避免子串先命中
    return sorted(set(values), key=len, reverse=True)


def _mask(text: str, secrets: list[str]) -> str:
    out = text
    for secret in secrets:
        out = out.replace(secret, "***")
    return _QUERY_SECRET_RE.sub(r"\1***", out)


def redact(text: str) -> str:
    """Return text with known secret values and secret-like query params masked."""
    if not text:
        return text
    return _mask(text, _known_secrets())


# 字段名匹配这些模式时，值一律替换为 ***REDACTED***（SECURITY.md §3.3）
_SECRET_KEY_RE = re.compile(r"(?i)(^|_)(api[_-]?key|apikey|token|bearer|authorization|password|secret|dsn)($|_)")


def _redact_value(key: str, value, secrets: list[str], depth: int = 0):
    """按字段名与取值递归脱敏（容器最多下探 4 层，防御环状/超深结构）。"""
    if _SECRET_KEY_RE.search(str(key)):
        return "***REDACTED***"
    if depth >= 4:
        return value
    if isinstance(value, str):
        return _mask(value, secrets)
    if isinstance(value, dict):
        return {k: _redact_value(str(k), v, secrets, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        masked = [_redact_value(key, v, secrets, depth + 1) for v in value]
        return type(value)(masked) if isinstance(value, tuple) else masked
    return value


def redact_processor(_logger, _method_name, event_dict):
    """structlog processor：按字段名脱敏，并对所有字符串值做已知密钥替换。

    SECURITY.md §3.3 要求"字段名匹配 `*_key|*_token|*_bearer|authorization|password`
    的值替换为 ***REDACTED***"，但此前全仓库没有任何 `structlog.configure()` 调用，
    这条规则从未生效。而代码里约 40 处 `logger.error(..., error=str(e))` 会把
    httpx/psycopg 的异常原文（含完整 URL 与 DSN）直接写进日志。

    必须**递归**处理容器：`logger.error("x", context={"api_key": ...})` 这种嵌套
    写法在只看顶层时会整个漏过去。
    """
    secrets = _known_secrets()  # 每条日志只算一次，不再每字段重算并排序
    for key, value in list(event_dict.items()):
        event_dict[key] = _redact_value(str(key), value, secrets)
    return event_dict


class _TeeWriter:
    """把同一行渲染结果同时转发到多个流（stdout + 日志文件）。

    structlog 的 WriteLogger 只依赖 write()/flush()，因此可用它把
    每条日志同时写入控制台与文件，两条路径共用同一条 processor 链（含脱敏）。
    """

    def __init__(self, *streams) -> None:
        self._streams = list(streams)

    def write(self, text: str) -> int:
        for stream in self._streams:
            stream.write(text)
        return len(text)

    def flush(self) -> None:
        for stream in self._streams:
            stream.flush()


def configure_logging() -> None:
    """安装脱敏 processor。幂等，可重复调用。

    当 settings.log_file 非空时追加文件输出（UTF-8 追加写，进程存活期间保持打开）：
    - 与 stdout 共用同一 processor 链，文件行同样经过脱敏，不会引入第二条渲染路径；
    - 落盘时强制 JSON 渲染——console 渲染带 ANSI 颜色与对齐补全，会污染文件行，
      且 JSON 行可直接被 Promtail/Loki 解析（按字段过滤）。
    """
    import sys
    from pathlib import Path

    import structlog

    from app.config import settings

    log_file = (getattr(settings, "log_file", "") or "").strip()

    # 落盘时强制 JSON；否则跟随 settings.log_format（json/console）
    renderer = (
        structlog.processors.JSONRenderer()
        if log_file or getattr(settings, "log_format", "console") == "json"
        else structlog.dev.ConsoleRenderer()
    )

    streams: list = [sys.stdout]
    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        streams.append(path.open("a", encoding="utf-8"))

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S"),
            structlog.processors.format_exc_info,
            # 必须排在 format_exc_info **之后**：traceback 是在那一步才被渲染成
            # 字符串塞进 event_dict 的。放在之前等于什么都没脱敏——而 exc_info=True
            # 的调用点恰恰是 httpx/psycopg 异常（含完整 URL 与 DSN）的主要来源。
            redact_processor,
            renderer,
        ],
        logger_factory=structlog.WriteLoggerFactory(file=_TeeWriter(*streams)),
        cache_logger_on_first_use=True,
    )
