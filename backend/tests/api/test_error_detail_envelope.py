"""错误信封收口回归（2026-11-13 审查 P2-10）。

`http_exception_handler` 把非 dict 的 detail 统一降级为
`{"code": "HTTP_ERROR"}` —— 具体、可编程区分的错误码全部丢失
（10 处字符串 detail，前端只能靠 message 文案猜）。

契约：
1. routers 里不允许再有 `detail="<字符串>"`（静态守卫，f-string 同理丢码）；
2. 抽查端点行为：错误响应必须带语义化 code。
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app

ROUTERS = Path(__file__).resolve().parents[2] / "app" / "routers" / "v1"


def test_no_string_detail_in_routers() -> None:
    offenders: list[str] = []
    for path in sorted(ROUTERS.glob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r'HTTPException\([^)]*detail="', line) or re.search(r'detail="[^"]*"\)', line):
                offenders.append(f"{path.name}:{lineno}")
    assert not offenders, (
        f"这些 HTTPException 用了字符串 detail（错误码降级为 HTTP_ERROR）：{offenders}。\n"
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
