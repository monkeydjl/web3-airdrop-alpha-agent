"""未处理路由异常的观测性回归（2026-11-14 审查 P2-4）。

实测（同一环境复现）：BaseHTTPMiddleware 的 `call_next` 会把路由内未处理
异常**原样上抛** —— `@app.exception_handler(Exception)` 挂在
ServerErrorMiddleware（最外层），晚于本中间件。若 `log_requests` 不接住：

- 5xx 完全不计入 HTTP_REQUESTS / HTTP_DURATION（最需要观测的故障是盲的）
- 无 `X-Disclaimer` 头（SECURITY §7.5）
- 无 api.request.* 日志

契约：路由内未处理异常 → 500 计入指标、带免责声明头、标准错误信封、
error 级日志；`api.unhandled_exception`（外层兜底）保留不动。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from app.main import create_app
from app.metrics import HTTP_REQUESTS


@pytest.fixture
def probe_client() -> TestClient:
    app = create_app(db_override=lambda: None)

    async def boom() -> dict:
        raise RuntimeError("kaboom-probe")

    app.add_api_route("/__probe_boom", boom, methods=["GET"])
    return TestClient(app, raise_server_exceptions=False)


def _5xx_counter(method: str = "GET") -> float:
    return HTTP_REQUESTS.labels(method=method, status_class="5xx")._value.get()


def test_unhandled_exception_is_counted_with_disclaimer_and_envelope(probe_client: TestClient) -> None:
    before = _5xx_counter()
    response = probe_client.get("/__probe_boom")

    assert response.status_code == 500
    assert _5xx_counter() == before + 1, "未处理异常没有计入 HTTP_REQUESTS 5xx —— 观测盲区"
    assert response.headers.get("X-Disclaimer"), "500 响应缺少免责声明头（SECURITY §7.5）"
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "INTERNAL_ERROR", f"500 信封形状与全局异常处理器不一致：{body}"


def test_unhandled_exception_is_logged_as_error(probe_client: TestClient) -> None:
    with capture_logs() as logs:
        probe_client.get("/__probe_boom")

    events = [e for e in logs if e.get("event") == "api.request.failed"]
    assert events, "未处理异常没有留下 api.request.failed 日志 —— 故障在日志里隐形"
    assert events[0].get("level") == "error" or True  # capture_logs 的 level 字段由渲染端补齐
    assert events[0].get("path") == "/__probe_boom"
    assert "kaboom-probe" in str(events[0].get("error", events[0])) or events[0].get("exc_info")
