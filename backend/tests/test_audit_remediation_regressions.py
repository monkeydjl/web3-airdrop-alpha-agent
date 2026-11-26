"""全栈审计修复回归测试套件（覆盖 P1-1..P1-4 与 P2 关键修复项）。"""

from __future__ import annotations

import socket
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.agents.base import AgentContext, PipelineState, RawProject
from app.agents.scorer import ScorerAgent
from app.config import settings
from app.db import init_db
from app.main import create_app
from app.rate_limit import _auth_limits
from app.repository import ProjectRepository
from app.routers.v1.projects import _reason_to_zh
from app.services.vitals import BlockedTargetError, _PinnedPublicIPBackend


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_file = tmp_path / "audit_remediation.db"
    monkeypatch.setattr(settings, "db_path", str(db_file))
    monkeypatch.setattr(settings, "db_backend", "sqlite")
    init_db()
    return db_file


class TestImportDeterministicIdentity:
    """P1-1: 批量导入不得再使用 import-001 硬编码序号覆写历史项目。"""

    def test_successive_imports_do_not_overwrite_previous_batches(self) -> None:
        with TestClient(create_app()) as client:
            csv_batch_1 = "项目名称,赛道,有测试网\nAlphaChain,L2,true\n"
            r1 = client.post(
                "/api/v1/import/projects",
                files={"file": ("batch1.csv", csv_batch_1.encode("utf-8"), "text/csv")},
            )
            assert r1.status_code == 200

            csv_batch_2 = "项目名称,赛道,有测试网\nBetaDex,DeFi,true\n"
            r2 = client.post(
                "/api/v1/import/projects",
                files={"file": ("batch2.csv", csv_batch_2.encode("utf-8"), "text/csv")},
            )
            assert r2.status_code == 200

            repo = ProjectRepository()
            rows, total = repo.list_projects(page=1, page_size=50, include_hidden=True)
            names = {row["name"]: row["id"] for row in rows}
            assert total >= 2
            assert "AlphaChain" in names
            assert "BetaDex" in names
            assert not str(names["AlphaChain"]).startswith("import-")
            assert names["AlphaChain"] != names["BetaDex"]

            # 再次导入同名同赛道项目应幂等复用同一确定性 ID
            r3 = client.post(
                "/api/v1/import/projects",
                files={"file": ("batch3.csv", csv_batch_1.encode("utf-8"), "text/csv")},
            )
            assert r3.status_code == 200
            rows_after, _ = repo.list_projects(page=1, page_size=50, include_hidden=True)
            names_after = {row["name"]: row["id"] for row in rows_after}
            assert names_after["AlphaChain"] == names["AlphaChain"]


class TestProjectUserScopeIsolation:
    """P1-3: 详情页与列表页必须按当前用户隔离 skipped / watchlisted 状态。"""

    def test_detail_and_list_isolate_watchlist_and_skip_per_user(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        admin_key = "k" * 36
        monkeypatch.setattr(settings, "api_key", admin_key)
        monkeypatch.setattr(settings, "auth_token_secret", "s" * 36)

        repo = ProjectRepository()
        repo.save(
            PipelineState(
                project=RawProject(
                    id="proj-iso-1",
                    name="IsoLayer",
                    url="https://isolayer.example",
                    sector="L2",
                    stage="testnet",
                    source="defillama",
                    has_testnet=True,
                    no_token_yet=True,
                ),
                context=AgentContext(run_id="r-iso"),
                score=78,
                label="FARM",
                confidence=0.85,
                reason=["strong airdrop signal"],
            )
        )

        with TestClient(create_app()) as client:
            tok_a = client.post("/api/v1/auth/anonymous").json()["access_token"]
            tok_b = client.post("/api/v1/auth/anonymous").json()["access_token"]
            headers_a = {"Authorization": f"Bearer {tok_a}"}
            headers_b = {"Authorization": f"Bearer {tok_b}"}

            assert client.post("/api/v1/watchlist/proj-iso-1", json={}, headers=headers_a).status_code in (
                200,
                201,
            )
            assert client.post("/api/v1/projects/proj-iso-1/skip", json={}, headers=headers_a).status_code == 200

            detail_a = client.get("/api/v1/projects/proj-iso-1", headers=headers_a).json()["data"]["project"]
            detail_b = client.get("/api/v1/projects/proj-iso-1", headers=headers_b).json()["data"]["project"]
            assert detail_a["watchlisted"] is True
            assert detail_a["skipped"] is True
            assert detail_b["watchlisted"] is False
            assert detail_b["skipped"] is False

            list_a = client.get("/api/v1/projects", headers=headers_a).json()["data"]["projects"]
            list_b = client.get("/api/v1/projects", headers=headers_b).json()["data"]["projects"]
            item_a = next(p for p in list_a if p["id"] == "proj-iso-1")
            item_b = next(p for p in list_b if p["id"] == "proj-iso-1")
            assert item_a["watchlisted"] is True
            assert item_a["skipped"] is True
            assert item_b["watchlisted"] is False
            assert item_b["skipped"] is False


class TestAuthLogoutAndAiGuards:
    """P1-4 & P2-1b: 匿名登出拦截、跨用户会话吊销防护、ai-brief force 锁与限流桶。"""

    def test_anonymous_cannot_logout_and_user_cannot_revoke_other_users_refresh_token(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "api_key", "a" * 36)
        monkeypatch.setattr(settings, "auth_token_secret", "b" * 36)

        with TestClient(create_app()) as client:
            anon = client.post("/api/v1/auth/anonymous").json()["access_token"]
            anon_headers = {"Authorization": f"Bearer {anon}"}

            assert client.post("/api/v1/auth/logout", json={}, headers=anon_headers).status_code == 401
            assert client.post("/api/v1/auth/logout/all", headers=anon_headers).status_code == 401

            reg_a = client.post(
                "/api/v1/auth/register",
                json={"email": "alice@example.com", "password": "Password123"},
            ).json()
            reg_b = client.post(
                "/api/v1/auth/register",
                json={"email": "bob@example.com", "password": "Password123"},
            ).json()

            # Alice 尝试在登出时传入 Bob 的 refresh_token —— 不得吊销 Bob 的会话
            res_logout = client.post(
                "/api/v1/auth/logout",
                json={"refresh_token": reg_b["refresh_token"]},
                headers={"Authorization": f"Bearer {reg_a['access_token']}"},
            )
            assert res_logout.status_code == 200

            bob_refresh = client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": reg_b["refresh_token"]},
            )
            assert bob_refresh.status_code == 200
            assert bob_refresh.json()["access_token"]

    def test_ai_brief_force_requires_global_mutation_privilege(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        admin_key = "m" * 36
        monkeypatch.setattr(settings, "api_key", admin_key)
        monkeypatch.setattr(settings, "auth_token_secret", "n" * 36)
        monkeypatch.setattr(settings, "enable_llm_enhancement", False)

        ProjectRepository().save(
            PipelineState(
                project=RawProject(
                    id="proj-brief-1",
                    name="BriefGuard",
                    url="https://brief.example",
                    sector="DeFi",
                    stage="testnet",
                    source="defillama",
                    has_testnet=True,
                    no_token_yet=True,
                ),
                context=AgentContext(run_id="r-brief"),
                score=72,
                label="FARM",
                confidence=0.8,
                reason=["strong airdrop signal"],
            )
        )

        with TestClient(create_app()) as client:
            anon = client.post("/api/v1/auth/anonymous").json()["access_token"]
            anon_headers = {"Authorization": f"Bearer {anon}"}

            # force=false 允许匿名触发首次生成并读缓存
            ok_resp = client.post(
                "/api/v1/projects/proj-brief-1/ai-brief",
                json={"force": False},
                headers=anon_headers,
            )
            assert ok_resp.status_code == 200

            # force=true 拒绝匿名覆写全局简报缓存
            forbidden_resp = client.post(
                "/api/v1/projects/proj-brief-1/ai-brief",
                json={"force": True},
                headers=anon_headers,
            )
            assert forbidden_resp.status_code == 403
            assert forbidden_resp.json()["error"]["code"] == "FORBIDDEN"

            # 管理员携带 X-API-Key 允许 force=true 强制刷新
            admin_resp = client.post(
                "/api/v1/projects/proj-brief-1/ai-brief",
                json={"force": True},
                headers={"X-API-Key": admin_key},
            )
            assert admin_resp.status_code == 200

    def test_register_and_llm_endpoints_have_dedicated_rate_limits(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        auth_prefixes = {prefix for prefix, _, _ in _auth_limits()}
        assert "/api/v1/auth/register" in auth_prefixes

        monkeypatch.setattr(settings, "rate_limit_enabled", True)
        monkeypatch.setattr(settings, "rate_limit_requests", 500)
        monkeypatch.setattr(
            "app.rate_limit._llm_pattern_limits",
            lambda: (
                (
                    "llm_project_ai",
                    __import__("re").compile(r"^/api/v1/projects/[^/]+/ai-(?:brief|chat)(?:/|$)"),
                    2,
                    3600,
                ),
            ),
        )

        with TestClient(create_app()) as client:
            payload = {"messages": [{"role": "user", "content": "该项目风险如何？"}]}
            r1 = client.post("/api/v1/projects/nonexistent/ai-chat", json=payload)
            r2 = client.post("/api/v1/projects/nonexistent/ai-chat", json=payload)
            r3 = client.post("/api/v1/projects/nonexistent/ai-chat", json=payload)
            assert r1.status_code == 404
            assert r2.status_code == 404
            assert r3.status_code == 429
            assert r3.json()["error"]["code"] == "RATE_LIMITED"


class TestVitalsPinningAndScorerDynamicConfig:
    """P2-1a & P2-4: DNS 重绑定公网 IP 钉死、动态权重热读取与理由中文化。"""

    @pytest.mark.asyncio
    async def test_pinned_backend_connects_to_validated_ip_and_blocks_rebind(self) -> None:
        inner = MagicMock()
        stream_sentinel = object()
        inner.connect_tcp = AsyncMock(return_value=stream_sentinel)
        backend = _PinnedPublicIPBackend(inner)

        fake_public = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
        with patch("asyncio.base_events.BaseEventLoop.getaddrinfo", new_callable=AsyncMock, return_value=fake_public):
            got = await backend.connect_tcp("ok.example", 443, timeout=5.0)
        assert got is stream_sentinel
        # 传给底层 socket 的必须是已校验的 IP 字面量，绝非再次触发 DNS 解析的原始域名
        assert inner.connect_tcp.await_args.args[0] == "93.184.216.34"

        fake_rebind = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 80))]
        with (
            patch("asyncio.base_events.BaseEventLoop.getaddrinfo", new_callable=AsyncMock, return_value=fake_rebind),
            pytest.raises(BlockedTargetError),
        ):
            await backend.connect_tcp("rebind.example", 80, timeout=5.0)

    @pytest.mark.asyncio
    async def test_scorer_reads_weights_and_version_dynamically(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "weight_version", "v9.9-live")
        scorer = ScorerAgent()
        state = PipelineState(
            project=RawProject(
                id="p-dyn",
                name="DynWeight",
                sector="L2",
                stage="testnet",
                source="defillama",
                has_testnet=True,
                no_token_yet=True,
            ),
            context=AgentContext(run_id="r-dyn"),
        )
        scored = await scorer.run(state)
        assert scored.weight_version == "v9.9-live"

    def test_eligibility_monitor_reason_translates_to_chinese(self) -> None:
        raw = "no verified participation path; monitor for a testnet, points, or task portal"
        zh = _reason_to_zh(raw)
        assert zh != raw
        assert "交互路径" in zh


class TestAdminAuditLogPipeline:
    """管理员写操作安全审计链路（audit_logs 生产写入、脱敏与 GET /api/v1/ops/audit-logs）。"""

    def test_admin_mutation_records_redacted_audit_log_and_blocks_anonymous_query(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_file = tmp_path / "audit_pipeline.db"
        monkeypatch.setattr(settings, "db_path", str(db_file))
        monkeypatch.setattr(settings, "api_key", "super-secret-admin-key-999")
        init_db()

        app = create_app()
        with TestClient(app) as client:
            r_anon_issue = client.post("/api/v1/auth/anonymous")
            assert r_anon_issue.status_code == 200
            anon_token = r_anon_issue.json()["access_token"]

            # 1. 匿名用户不可访问 /api/v1/ops/audit-logs，且被拒写操作不产生成功审计记录
            r_anon_get = client.get(
                "/api/v1/ops/audit-logs",
                headers={"Authorization": f"Bearer {anon_token}"},
            )
            assert r_anon_get.status_code == 403

            r_anon_mut = client.post(
                "/api/v1/ops/audit-viability",
                json={"apply_changes": False},
                headers={"Authorization": f"Bearer {anon_token}"},
            )
            assert r_anon_mut.status_code == 403

            # 2. 管理员执行写操作自动落库，且 query 参数中的敏感凭据被强制脱敏
            r_admin_mut = client.post(
                "/api/v1/ops/audit-viability?api_key=super-secret-admin-key-999",
                json={"apply_changes": False},
                headers={"X-API-Key": "super-secret-admin-key-999"},
            )
            assert r_admin_mut.status_code == 200

            r_logs = client.get(
                "/api/v1/ops/audit-logs",
                params={"action": "POST /api/v1/ops/audit-viability", "limit": 10},
                headers={"X-API-Key": "super-secret-admin-key-999"},
            )
            assert r_logs.status_code == 200
            body = r_logs.json()
            assert body["ok"] is True
            assert body["data"]["total"] == 1
            entry = body["data"]["items"][0]
            assert entry["action"] == "POST /api/v1/ops/audit-viability"
            assert entry["user"] == "admin"
            assert "super-secret-admin-key-999" not in (entry["detail"] or "")
            assert "***" in (entry["detail"] or "")
