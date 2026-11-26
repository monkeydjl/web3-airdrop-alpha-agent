"""response_model 覆盖率守卫（2026-11-13 审查 P2-10 收口）。

FastAPI 会从返回注解自动推导 response_model —— 全仓 173 个操作里只有
个位数缺口。契约：**每个操作**要么有 response_model（OpenAPI 200 带
schema），要么在 `RESPONSE_MODEL_EXEMPT` 里带一句理由（文件/文本下载等
非 JSON 响应）。

没有 response_model 的操作在 OpenAPI 里是空 schema —— 客户端无法生成
类型化调用代码，"contracts 可推导"就断了。豁免必须显式登记并写理由：
**豁免的粒度就是文档缺口的大小。**
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app

# (path, method) → 理由。只允许非 JSON 响应登记；JSON 端点缺 response_model
# 请直接补模型，而不是往这张表里加行。
RESPONSE_MODEL_EXEMPT: dict[tuple[str, str], str] = {
    ("/metrics", "get"): "Prometheus 文本暴露格式，不是 JSON。",
    ("/api/v1/export/projects", "get"): "xlsx/csv 二进制下载。",
    ("/api/v1/export/project/{project_id}", "get"): "xlsx/csv 二进制下载。",
    ("/api/v1/export/template", "get"): "导入模板文件下载。",
    ("/api/v1/calendar/export.ics", "get"): "iCalendar (.ics) 文本下载。",
}


def test_every_operation_has_response_model_or_registered_exemption() -> None:
    app = create_app(db_override=lambda: None)
    client = TestClient(app)
    spec = client.get("/openapi.json").json()

    offenders: list[str] = []
    total = 0
    for path, item in spec["paths"].items():
        for method, op in item.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            total += 1
            if (path, method) in RESPONSE_MODEL_EXEMPT:
                continue
            # schema 可能挂在任一 2xx 键下（status_code=201 的路由在 "201"）
            schemas = [
                (resp.get("content") or {}).get("application/json", {}).get("schema") or {}
                for code, resp in (op.get("responses") or {}).items()
                if code.startswith("2")
            ]
            if not any(schemas):
                offenders.append(f"{method.upper()} {path}")

    assert not offenders, (
        f"{len(offenders)}/{total} 个操作没有 response_model（OpenAPI 200 空 schema）："
        f"{sorted(offenders)}。\n"
        "JSON 端点请补 response_model；文件/文本下载在 RESPONSE_MODEL_EXEMPT 登记并写理由。"
    )
