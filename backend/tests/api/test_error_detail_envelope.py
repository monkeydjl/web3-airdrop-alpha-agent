"""错误信封收口回归（2026-11-13 审查 P2-10）。

`http_exception_handler` 把非 dict 的 detail 统一降级为
`{"code": "HTTP_ERROR"}` —— 具体、可编程区分的错误码全部丢失
（10 处字符串 detail，前端只能靠 message 文案猜）。

契约：
1. routers 里不允许再有 `detail="<字符串>"`（静态守卫，f-string 同理丢码）；
2. 抽查端点行为：错误响应必须带语义化 code。
"""

from __future__ import annotations

import ast
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app

ROUTERS = Path(__file__).resolve().parents[2] / "app" / "routers" / "v1"


def _extract_detail_expr(call: ast.Call) -> ast.expr | None:
    for kw in call.keywords:
        if kw.arg == "detail":
            return kw.value
    if len(call.args) >= 2:
        return call.args[1]
    return None


def test_no_string_detail_in_routers() -> None:
    offenders: list[str] = []
    for path in sorted(ROUTERS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            is_http_exc = (isinstance(func, ast.Name) and func.id == "HTTPException") or (
                isinstance(func, ast.Attribute) and func.attr == "HTTPException"
            )
            if not is_http_exc:
                continue
            detail = _extract_detail_expr(node)
            if detail is None:
                offenders.append(f"{path.name}:{node.lineno} (missing detail)")
                continue
            if isinstance(detail, ast.Constant) and isinstance(detail.value, str):
                offenders.append(f"{path.name}:{node.lineno} (string literal detail)")
            elif isinstance(detail, ast.JoinedStr):
                offenders.append(f"{path.name}:{node.lineno} (f-string detail)")
            elif isinstance(detail, ast.BinOp):
                offenders.append(f"{path.name}:{node.lineno} (formatted string detail)")
            elif isinstance(detail, ast.Call) and isinstance(detail.func, ast.Name) and detail.func.id == "str":
                offenders.append(f"{path.name}:{node.lineno} (str(...) detail)")
            elif isinstance(detail, ast.Dict):
                keys = {k.value for k in detail.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
                if "code" not in keys:
                    offenders.append(f"{path.name}:{node.lineno} (dict detail missing 'code')")
    assert not offenders, (
        f"这些 HTTPException 未使用带语义化 code 的结构化 detail（错误码会降级为 HTTP_ERROR）：{offenders}。\n"
        '一律改成 detail={"code": "<语义化码>", "message": "..."}。'
    )


def test_validation_error_carries_semantic_code() -> None:
    app = create_app(db_override=lambda: None)
    client = TestClient(app)
    # 不带 ids 是 FastAPI 层 422（信封已是语义化码）；空 ids= 走路由内的 400 分支
    response = client.get("/api/v1/projects/compare?ids=")
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR", f"错误码仍是降级的 HTTP_ERROR：{body['error']}"


def test_not_found_error_carries_semantic_code() -> None:
    app = create_app(db_override=lambda: None)
    client = TestClient(app)
    response = client.delete("/api/v1/gas/alerts/rules/nonexistent-rule")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "NOT_FOUND", f"错误码仍是降级的 HTTP_ERROR：{body['error']}"
