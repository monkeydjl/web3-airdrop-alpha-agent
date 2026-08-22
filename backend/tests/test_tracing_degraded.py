"""`app/tracing.py` 的降级路径测试。

## 为什么专门测这个

OTel 的 7 个 `opentelemetry-*` 包是**可选依赖**（拆到 `requirements-otel.txt`），
本机与 CI 都没装。而 `app/tracing.py` 在全应用范围被调用（pipeline、每个 agent
都开 span），一旦它在缺包时抛异常，**整个应用起不来**。

此前这个模块**没有任何针对性测试**，两处 `except ImportError` 还挂着
`# pragma: no cover - deps always installed` 的注释 —— 那句话是不准确的
（依赖并非总是安装），已在本轮改为指向 `requirements-otel.txt`。

**准确的覆盖率数字**（实测，不是估计）：靠其它测试导入 `app.main` 带来的
间接覆盖是 **44%**，加上本文件后升到 **58%**。剩下的 42% 需要真装 OTel 才能
走到。所以不能说它"零覆盖"—— 它只是没有针对性测试，
关键的降级契约从来没被断言过。

这组测试锁住的正是"没装 OTel 时一切照常"这个契约。**装了 OTel 的正向路径
本机无法验证**（PyPI 不可达），如实记在 `CODE_REVIEW_REPORT.md` 的
「我无法验证的部分」里。
"""

from __future__ import annotations

import pytest

from app import tracing


def test_module_imports_without_otel_installed():
    """最基本的契约：缺包时模块本身必须能导入。"""
    assert hasattr(tracing, "tracer")
    assert hasattr(tracing, "setup_tracing")


def test_otel_unavailable_in_this_environment():
    """确认本测试确实跑在"未装 OTel"的环境下。

    若哪天 CI 装上了 OTel，这条会红 —— 那时应补正向路径测试，而不是删掉它。
    """
    assert tracing._OTEL_AVAILABLE is False, "本环境已安装 OTel，降级路径测试不再覆盖真实场景，请补正向测试"


def test_tracer_is_noop_when_unavailable():
    assert isinstance(tracing.tracer, tracing._NoOpTracer)


# ── no-op span 必须满足 OTel Span 的调用契约 ──────────────────


def test_noop_span_supports_context_manager():
    """agent 代码里到处是 `with tracer.start_as_current_span(...)`。"""
    with tracing.tracer.start_as_current_span("airdrop.pipeline.run") as span:
        assert isinstance(span, tracing._NoOpSpan)


def test_noop_span_accepts_attributes_and_status():
    """no-op span 必须默默吞掉所有调用，不能抛 AttributeError。"""
    with tracing.tracer.start_as_current_span("airdrop.agent.scorer") as span:
        span.set_attribute("run_id", "abc123")
        span.set_attribute("count", 42)
        span.record_exception(ValueError("boom"))
        span.set_status(object())
        assert span.is_recording() is False


def test_start_span_accepts_kwargs_like_real_tracer():
    """真实 Tracer 支持 `attributes=` 等关键字，shim 必须签名兼容。"""
    with tracing.tracer.start_as_current_span("x", attributes={"a": 1}, kind=None) as span:
        assert isinstance(span, tracing._NoOpSpan)


def test_nested_spans_do_not_interfere():
    with tracing.tracer.start_as_current_span("outer") as outer:
        with tracing.tracer.start_as_current_span("inner") as inner:
            inner.set_attribute("depth", 2)
        outer.set_attribute("depth", 1)


# ── 模块级函数在缺包时必须是安全的 no-op ─────────────────────


def test_setup_tracing_returns_false_when_disabled(monkeypatch):
    monkeypatch.setattr(tracing.settings, "otel_enabled", False)
    assert tracing.setup_tracing() is False


def test_setup_tracing_returns_false_when_enabled_but_deps_missing(monkeypatch):
    """**关键场景**：运维在生产打开了 OTEL_ENABLED，但镜像没装 OTel 包。

    此时必须是"记一条 warning 然后继续跑"，绝不能让应用启动失败。
    """
    monkeypatch.setattr(tracing.settings, "otel_enabled", True)
    monkeypatch.setattr(tracing, "_OTEL_AVAILABLE", False)
    assert tracing.setup_tracing() is False


def test_span_attribute_is_noop_without_otel():
    tracing.span_attribute("key", "value")  # 不抛异常即通过


def test_end_span_with_error_is_noop_without_otel():
    tracing.end_span_with_error(tracing._NoOpSpan(), ValueError("boom"))


def test_end_span_with_error_ignores_noop_span_even_if_otel_available(monkeypatch):
    """即使 OTel 可用，传进来的若是 no-op span 也必须跳过。

    否则会对 shim 调用 `record_exception` 之外的真实 API 而炸掉。
    """
    monkeypatch.setattr(tracing, "_OTEL_AVAILABLE", True)
    tracing.end_span_with_error(tracing._NoOpSpan(), ValueError("boom"))


def test_instrument_fastapi_app_is_noop_without_otel(monkeypatch):
    monkeypatch.setattr(tracing.settings, "otel_enabled", True)
    monkeypatch.setattr(tracing, "_OTEL_AVAILABLE", False)
    tracing.instrument_fastapi_app(object())  # 不抛异常即通过


def test_instrument_fastapi_app_skipped_when_disabled(monkeypatch):
    monkeypatch.setattr(tracing.settings, "otel_enabled", False)
    tracing.instrument_fastapi_app(object())


def test_internal_instrument_is_noop_without_otel(monkeypatch):
    monkeypatch.setattr(tracing, "_OTEL_AVAILABLE", False)
    tracing._instrument()


# ── 与文档/配置的一致性 ──────────────────────────────────────


@pytest.mark.parametrize("path", ["/health", "/metrics", "/version"])
def test_noisy_paths_excluded_from_tracing(path):
    """这三个路径既不该被 Prometheus 抓也不该被追踪（docs/OBSERVABILITY.md §4.2）。"""
    assert path in tracing._EXCLUDED_PATHS
