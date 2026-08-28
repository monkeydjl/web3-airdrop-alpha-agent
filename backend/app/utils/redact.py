"""Secret redaction helpers.

采集器把 httpx 异常字符串写入日志与 collection_logs，而 httpx 会把完整 URL
（含 query 中的 apikey）渲染进异常信息。此模块提供统一脱敏，避免密钥落盘/落日志。
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Mapping, MutableMapping
from pathlib import Path
from typing import Any

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


def _redact_value(key: str, value: Any, secrets: list[str], depth: int = 0) -> Any:
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


def redact_processor(
    _logger: Any, _method_name: str, event_dict: MutableMapping[str, Any]
) -> Mapping[str, Any]:
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

    def __init__(self, *streams: Any) -> None:
        self._streams = list(streams)

    def write(self, text: str) -> int:
        for stream in self._streams:
            stream.write(text)
        return len(text)

    def flush(self) -> None:
        for stream in self._streams:
            stream.flush()


# structlog 的 filtering bound logger 只认小写级别名；`warn` 是 `warning` 的别名。
_LEVEL_ALIASES = {"warn": "warning", "fatal": "critical"}
_VALID_LEVELS = ("debug", "info", "warning", "error", "critical")

# 上一次 configure_logging() 打开的日志文件句柄。
#
# 这个模块级引用不是"缓存优化"，是修一个真实的句柄泄漏：configure_logging()
# 的文档说它幂等可重复调用，但每次调用都会 open() 一个新的日志文件，
# 旧句柄既没关闭也没被引用 —— 只能等 GC 回收，届时 CPython 抛
# ResourceWarning（CI 用 `-W error::ResourceWarning`，直接变成失败）。
#
# 生产里它只被调一次，所以影响有限；但测试与任何"改完配置重新装一次日志"
# 的场景都会稳定泄漏。重新配置前显式关掉上一个，是唯一干净的做法。
_open_log_file: Any | None = None


class _RotatingLogStream:
    """按大小轮转的日志写入流。

    ## 为什么不用 `logging.handlers.RotatingFileHandler`

    structlog 在这里走的是 `WriteLoggerFactory`，它要的是一个有
    `write()`/`flush()` 的对象，而不是 stdlib `logging` 的 handler ——
    两者不是同一条管道。硬把 stdlib handler 接进来，就要把整条
    structlog processor 链（含脱敏）搬到 stdlib 的 formatter 里去，
    等于新增第二条渲染路径。**日志渲染路径每多一条，脱敏就多一处可能漏掉的地方。**
    所以这里只补"按大小换文件"这一件事，其余照旧走原来的链。

    ## 为什么必须有

    `log_file` 此前是无上限追加写：实测 `logs/backend.log` 6 天 3.97 MB
    （约 240 MB/年），代码无轮转、compose 无 `max-size`、宿主无 logrotate。
    磁盘写满的真实后果不是"日志丢了"，是**数据库写入开始失败** ——
    DB 和日志在同一块盘上。

    ## 轮转失败时**不能**让写日志抛异常

    轮转是在 `write()` 里做的，而 `write()` 挂掉会让**每一条日志调用**
    都抛异常，进而打断正在处理的业务请求。
    一个为了保护磁盘而存在的机制，绝不该成为线上故障的来源。
    所以轮转异常被吞掉并降级为"继续往当前文件写"：
    磁盘满是慢性问题，请求 500 是即时问题。
    """

    def __init__(self, path: Path, max_bytes: int, backup_count: int) -> None:
        self._path = path
        self._max_bytes = max(0, int(max_bytes))
        self._backup_count = max(0, int(backup_count))
        self._handle = path.open("a", encoding="utf-8")
        # 用已有文件大小做起点，而不是从 0 数：进程重启后如果从 0 开始计，
        # 一个已经 900 MB 的文件会被认为"还没到 10 MiB"，永远不轮转。
        try:
            self._size = path.stat().st_size
        except OSError:
            self._size = 0

    @property
    def _rotation_enabled(self) -> bool:
        return self._max_bytes > 0 and self._backup_count > 0

    def write(self, text: str) -> int:
        encoded_len = len(text.encode("utf-8"))
        if self._rotation_enabled and self._size + encoded_len > self._max_bytes:
            self._rotate()
        self._handle.write(text)
        self._size += encoded_len
        return len(text)

    def flush(self) -> None:
        self._handle.flush()

    def close(self) -> None:
        with contextlib.suppress(OSError):
            self._handle.close()

    def _rotate(self) -> None:
        """把当前文件挪到 `.1`，历史依次后移，最旧的丢弃。"""
        try:
            self._handle.flush()
            self._handle.close()
            # 从最旧往最新挪，否则会自己覆盖自己
            for index in range(self._backup_count - 1, 0, -1):
                source = self._path.with_name(f"{self._path.name}.{index}")
                target = self._path.with_name(f"{self._path.name}.{index + 1}")
                if source.exists():
                    target.unlink(missing_ok=True)
                    source.rename(target)
            first = self._path.with_name(f"{self._path.name}.1")
            first.unlink(missing_ok=True)
            self._path.rename(first)
            self._handle = self._path.open("a", encoding="utf-8")
            self._size = 0
        except OSError:
            # 轮转失败不能把异常抛给日志调用方（见类 docstring）。
            # 尽力重新打开当前文件继续写；连这一步都失败就只能放弃文件输出。
            with contextlib.suppress(OSError):
                self._handle = self._path.open("a", encoding="utf-8")
                self._size = 0


def _resolve_log_level() -> int:
    """把 settings.log_level 解析成 structlog 的数值级别。

    非法值（拼错、留空）**不静默降级成 DEBUG** —— 那会让生产环境突然开始打印
    全部 debug 日志（含 fetcher 细节），是"配置写错反而放开了输出"的经典陷阱。
    这里退回 INFO，与 `Settings.log_level` 的默认值一致。
    """
    import logging

    raw = (getattr(settings, "log_level", "") or "").strip().lower()
    name = _LEVEL_ALIASES.get(raw, raw)
    if name not in _VALID_LEVELS:
        name = "info"
    return int(getattr(logging, name.upper()))


def _close_previous_log_file() -> None:
    """关闭上一次配置留下的日志文件句柄（若有）。

    关闭失败不能让整个日志配置流程崩掉 —— 日志系统装不上比一个悬空句柄严重得多。
    """
    global _open_log_file
    if _open_log_file is None:
        return
    try:
        _open_log_file.close()
    except OSError:
        pass
    finally:
        _open_log_file = None


def configure_logging() -> None:
    """安装脱敏 processor 与级别过滤。幂等，可重复调用。

    当 settings.log_file 非空时追加文件输出（UTF-8 追加写，进程存活期间保持打开）：
    - 与 stdout 共用同一 processor 链，文件行同样经过脱敏，不会引入第二条渲染路径；
    - 落盘时强制 JSON 渲染——console 渲染带 ANSI 颜色与对齐补全，会污染文件行，
      且 JSON 行可直接被 Promtail/Loki 解析（按字段过滤）。
    - 按 `LOG_MAX_BYTES` / `LOG_BACKUP_COUNT` 轮转（见 `_RotatingLogStream`）。
      此前是**无上限追加**：实测 6 天 3.97 MB，代码无轮转、compose 无 `max-size`、
      宿主无 logrotate —— 三层都没有。写满盘会让数据库写入一起失败。

    `wrapper_class` 必须显式传 filtering bound logger：`settings.log_level` 此前
    **只传给了 uvicorn**（`main.py` 的 `uvicorn.run(log_level=...)`），
    应用自身的 structlog 调用完全不看它 —— 于是 `LOG_LEVEL=WARNING` 下 12 处
    `logger.debug`（fetcher 缓存命中、限流等待、rootdata 逐条失败）照样全量输出。
    一个"设了但不生效"的级别开关比没有开关更糟：运维以为已经压掉了噪音。
    """
    import sys

    import structlog

    from app.config import settings

    global _open_log_file

    log_file = (getattr(settings, "log_file", "") or "").strip()

    # 落盘时强制 JSON；否则跟随 settings.log_format（json/console）
    renderer = (
        structlog.processors.JSONRenderer()
        if log_file or getattr(settings, "log_format", "console") == "json"
        else structlog.dev.ConsoleRenderer()
    )

    # 重新配置前先释放上一次的句柄，否则每次调用都泄漏一个打开的文件。
    _close_previous_log_file()

    streams: list[Any] = [sys.stdout]
    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        _open_log_file = _RotatingLogStream(
            path,
            max_bytes=int(getattr(settings, "log_max_bytes", 0) or 0),
            backup_count=int(getattr(settings, "log_backup_count", 0) or 0),
        )
        streams.append(_open_log_file)

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
        # WriteLoggerFactory 的类型标注要求完整 TextIO，但运行时只用 write()/flush()
        # （见 _TeeWriter docstring）。这里是结构化鸭子类型与标注的落差，非真实缺陷。
        logger_factory=structlog.WriteLoggerFactory(
            file=_TeeWriter(*streams),  # type: ignore[arg-type]
        ),
        wrapper_class=structlog.make_filtering_bound_logger(_resolve_log_level()),
        cache_logger_on_first_use=True,
    )
