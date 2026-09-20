"""收益台账（F3，ACTION_LOOP_DESIGN §4）测试：录入 / 隔离 / 聚合。

三个重点：

1. **身份隔离的正反断言都要有**。只验证"自己的能看到"是半个断言 ——
   真正要钉住的是"别人的看不到"。user_id 来自 token，请求体自报被忽略。
2. **汇总数值必须与手工核算一致**。`/roi/summary` 是给人看最终赚赔的，
   聚合写错（比如漏了 GROUP BY 的某个 project）不会报错，只会静默算错。
3. **边界不能编**。零成本时 `roi_ratio` 必须是 null：返回 0 会被读成
   "没赚没赔"，返回 inf 会污染任何下游聚合。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import get_connection, init_db
from app.main import create_app

ADMIN_HEADERS = {"X-API-Key": "test-admin-key-roi-00000000001"}


@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / "test.db"
    prev_db_path = settings.db_path
    settings.db_path = str(db_path)
    init_db()
    app = create_app(db_override=lambda: None)
    yield TestClient(app)
    settings.db_path = prev_db_path


@pytest.fixture
def authed(client):
    """开启鉴权 + 两个项目，返回 (client, token_a, token_b)。"""
    prev_key = settings.api_key
    settings.api_key = ADMIN_HEADERS["X-API-Key"]
    try:
        _seed_projects()
        tokens = []
        for _ in range(2):
            r = client.post("/api/v1/auth/anonymous")
            assert r.status_code == 200
            tokens.append(r.json()["access_token"])
        yield client, tokens[0], tokens[1]
    finally:
        settings.api_key = prev_key


def _seed_projects() -> None:
    """手工 INSERT 两个项目 —— 走 /run 会触发完整评分，这里只需要 id 存在。"""
    from datetime import UTC, datetime

    with get_connection() as conn:
        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        for pid, name in (("proj-1", "Alpha"), ("proj-2", "Beta")):
            conn.execute(
                "INSERT INTO projects (id, name, score, label, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (pid, name, 70, "FARM", now, now),
            )
        conn.commit()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _entry(client, token, project_id="proj-1", **overrides):
    body = {"kind": "gas", "amount_usd": 10.0}
    body.update(overrides)
    return client.post(f"/api/v1/projects/{project_id}/roi/entries", json=body, headers=_auth(token))


def _outcome(client, token, project_id="proj-1", **overrides):
    body = {"event": "airdrop_received", "amount_usd": 100.0}
    body.update(overrides)
    return client.post(f"/api/v1/projects/{project_id}/roi/outcomes", json=body, headers=_auth(token))


class TestRecordEntry:
    def test_record_money_and_hours(self, authed):
        client, token_a, _ = authed
        r = _entry(client, token_a, kind="time", amount_usd=12.5, hours=3.0, note="测试网交互")
        assert r.status_code == 200
        assert r.json()["data"]["project_id"] == "proj-1"

        detail = client.get("/api/v1/projects/proj-1/roi", headers=_auth(token_a)).json()["data"]
        entry = detail["entries"][0]
        assert entry["kind"] == "time"
        assert entry["amount_usd"] == 12.5
        assert entry["hours"] == 3.0

    def test_hours_only_is_allowed(self, authed):
        """时间投入没有金额也要能记 —— 早期参与的主要成本就是时间。"""
        client, token_a, _ = authed
        assert _entry(client, token_a, kind="time", amount_usd=None, hours=5.0).status_code == 200

    def test_both_amounts_empty_is_rejected(self, authed):
        """两个量纲都空的行对台账没有贡献，直接 422 而不是存一行空账。"""
        client, token_a, _ = authed
        r = _entry(client, token_a, kind="gas", amount_usd=None)
        assert r.status_code == 422
        # 全局 HTTPException 处理器把 detail 包成 {"ok": false, "error": {...}}，
        # 不是 FastAPI 默认的 {"detail": ...} —— 断言要照真实 envelope 写。
        assert r.json()["error"]["code"] == "MISSING_AMOUNT"

    def test_negative_amount_is_rejected(self, authed):
        client, token_a, _ = authed
        assert _entry(client, token_a, amount_usd=-1.0).status_code == 422

    def test_unknown_project_is_404(self, authed):
        client, token_a, _ = authed
        r = _entry(client, token_a, project_id="proj-nope")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "NOT_FOUND"


class TestRecordOutcome:
    def test_record_airdrop_received(self, authed):
        client, token_a, _ = authed
        r = _outcome(client, token_a, amount_usd=480.0, tokens=120.0, tx_hash="0xabc")
        assert r.status_code == 200

        detail = client.get("/api/v1/projects/proj-1/roi", headers=_auth(token_a)).json()["data"]
        outcome = detail["outcomes"][0]
        assert outcome["event"] == "airdrop_received"
        assert outcome["source"] == "manual"
        assert outcome["tx_hash"] == "0xabc"

    @pytest.mark.parametrize("event", ["token_launched", "airdrop_missed", "campaign_ended"])
    def test_all_outcome_events_accepted(self, authed, event):
        client, token_a, _ = authed
        assert _outcome(client, token_a, event=event).status_code == 200

    def test_unknown_event_is_rejected(self, authed):
        client, token_a, _ = authed
        assert _outcome(client, token_a, event="moon").status_code == 422

    def test_backtest_source_is_stored(self, authed):
        """回测样本必须标得出来 —— 校准靠它分桶，混进 live 会污染统计。"""
        client, token_a, _ = authed
        assert _outcome(client, token_a, source="backtest").status_code == 200
        detail = client.get("/api/v1/projects/proj-1/roi", headers=_auth(token_a)).json()["data"]
        assert detail["outcomes"][0]["source"] == "backtest"


class TestIdentityIsolation:
    def test_other_user_sees_nothing(self, authed):
        client, token_a, token_b = authed
        _entry(client, token_a, amount_usd=10.0)
        _outcome(client, token_a, amount_usd=100.0)

        # 反断言：token_b 看不到 a 的任何一条
        detail_b = client.get("/api/v1/projects/proj-1/roi", headers=_auth(token_b)).json()["data"]
        assert detail_b["entries"] == []
        assert detail_b["outcomes"] == []
        assert detail_b["subtotal"]["cost_usd"] == 0

        # 正断言：token_a 看得到
        detail_a = client.get("/api/v1/projects/proj-1/roi", headers=_auth(token_a)).json()["data"]
        assert len(detail_a["entries"]) == 1
        assert len(detail_a["outcomes"]) == 1

    def test_request_body_user_id_is_ignored(self, authed):
        """自报 user_id 不得改变归属 —— 否则任何人能往别人账上写。"""
        client, token_a, token_b = authed
        r = client.post(
            "/api/v1/projects/proj-1/roi/entries",
            json={"kind": "gas", "amount_usd": 10.0, "user_id": "anon-spoofed"},
            headers=_auth(token_a),
        )
        assert r.status_code == 200

        # 记录落在 token_a 名下，而不是 "anon-spoofed"
        assert client.get("/api/v1/projects/proj-1/roi", headers=_auth(token_a)).json()["data"]["entries"]
        assert not client.get("/api/v1/projects/proj-1/roi", headers=_auth(token_b)).json()["data"]["entries"]

    def test_cannot_delete_others_entry(self, authed):
        client, token_a, token_b = authed
        entry_id = _entry(client, token_a).json()["data"]["entry_id"]
        r = client.delete(f"/api/v1/roi/entries/{entry_id}", headers=_auth(token_b))
        assert r.status_code == 404

        # 记录还在
        assert _entry(client, token_a).status_code == 200
        assert len(client.get("/api/v1/projects/proj-1/roi", headers=_auth(token_a)).json()["data"]["entries"]) == 2

    def test_cannot_delete_others_outcome(self, authed):
        client, token_a, token_b = authed
        outcome_id = _outcome(client, token_a).json()["data"]["outcome_id"]
        assert client.delete(f"/api/v1/roi/outcomes/{outcome_id}", headers=_auth(token_b)).status_code == 404

    def test_delete_own_entry(self, authed):
        client, token_a, _ = authed
        entry_id = _entry(client, token_a).json()["data"]["entry_id"]
        assert client.delete(f"/api/v1/roi/entries/{entry_id}", headers=_auth(token_a)).status_code == 200
        assert client.get("/api/v1/projects/proj-1/roi", headers=_auth(token_a)).json()["data"]["entries"] == []


class TestSummaryAggregation:
    def test_subtotal_matches_manual_calculation(self, authed):
        client, token_a, _ = authed
        _entry(client, token_a, kind="gas", amount_usd=10.0)
        _entry(client, token_a, kind="time", amount_usd=None, hours=4.0)
        _entry(client, token_a, kind="infra", amount_usd=5.0)
        _outcome(client, token_a, amount_usd=60.0, tokens=30.0)

        sub = client.get("/api/v1/projects/proj-1/roi", headers=_auth(token_a)).json()["data"]["subtotal"]
        # 手工核算：投入 10 + 5 = 15；时间 4h；产出 60；净 45；ROI = 45/15 = 3
        assert sub["cost_usd"] == pytest.approx(15.0)
        assert sub["hours"] == pytest.approx(4.0)
        assert sub["returned_usd"] == pytest.approx(60.0)
        assert sub["tokens"] == pytest.approx(30.0)
        assert sub["net_usd"] == pytest.approx(45.0)
        assert sub["roi_ratio"] == pytest.approx(3.0)

    def test_summary_aggregates_across_projects(self, authed):
        """两个项目的账必须各自归各自 —— 漏 GROUP BY 会让数字静默算错。"""
        client, token_a, _ = authed
        _entry(client, token_a, project_id="proj-1", amount_usd=10.0)
        _outcome(client, token_a, project_id="proj-1", amount_usd=100.0)
        _entry(client, token_a, project_id="proj-2", amount_usd=20.0)
        _outcome(client, token_a, project_id="proj-2", amount_usd=10.0)

        data = client.get("/api/v1/roi/summary", headers=_auth(token_a)).json()["data"]
        totals = data["totals"]
        assert totals["cost_usd"] == pytest.approx(30.0)
        assert totals["returned_usd"] == pytest.approx(110.0)
        assert totals["net_usd"] == pytest.approx(80.0)
        assert totals["project_count"] == 2

        by_project = {item["project_id"]: item for item in data["items"]}
        assert by_project["proj-1"]["net_usd"] == pytest.approx(90.0)
        assert by_project["proj-2"]["net_usd"] == pytest.approx(-10.0)

    def test_summary_is_isolated_per_user(self, authed):
        client, token_a, token_b = authed
        _entry(client, token_a, amount_usd=10.0)
        assert client.get("/api/v1/roi/summary", headers=_auth(token_b)).json()["data"]["totals"]["cost_usd"] == 0

    def test_roi_ratio_is_null_when_cost_is_zero(self, authed):
        """零成本时 ROI 无定义 —— 必须是 null，不能是 0（读成没赚没赔）或 inf。"""
        client, token_a, _ = authed
        _outcome(client, token_a, amount_usd=100.0)

        sub = client.get("/api/v1/projects/proj-1/roi", headers=_auth(token_a)).json()["data"]["subtotal"]
        assert sub["cost_usd"] == 0
        assert sub["roi_ratio"] is None

    def test_empty_ledger_is_all_zero(self, authed):
        client, token_a, _ = authed
        data = client.get("/api/v1/roi/summary", headers=_auth(token_a)).json()["data"]
        assert data["totals"]["cost_usd"] == 0
        assert data["totals"]["project_count"] == 0
        assert data["items"] == []
