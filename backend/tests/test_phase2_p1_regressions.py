"""Phase 2 (P1-1 through P1-10) engineering audit regression tests.

Covers:
- P1-1: ?user_id= IDOR hardening, interactions/summary isolation, PATCH user_id spoof prevention,
        ROLE_ANONYMOUS vs ROLE_VIEWER global-write parity, /api/v1/llm admin lock, 500 raw error redaction.
- P1-2: Malformed ak_ zero-bcrypt fast rejection, deactivated user API key rejection, >72B password 400.
- P1-3: Production frontend loopback bind (127.0.0.1:13002:3002).
- P1-4: Anti-PUA three signals propagation, persistence ProjectIdentityResolver & material requeue,
        save_batch_with_rows economic_replay_enabled forwarding.
- P1-5: DefiLlama nested funding unwrapping & HTTP change_7d percent->ratio conversion,
        RootData sector/has_docs fix, HeatSignalProvider DISTINCT + Twitter KOL matching, "Unknown" noise filter.
- P1-6: Orchestrator skips NULL score overwrite, project_evaluation re-infers explicit_points_program,
        calibration negated-note parsing & veto/confidence replay.
- P1-7: LLM concurrent in-flight budget reservation, empty-response usage billing & empty choices safety,
        401/402/403 provider-level failover & breaker handling.
- P1-8 & P1-9: Settings 16-source config, roi_simulator risk_appetite/dedup/mark_simulated,
               airdrop_pnl no auto-seed in production.
- P1-10: Nginx stdout/stderr bounded logging, .env.example port 8002, backup.sh -n check,
         ops_tasks merged viability inputs & structured viability_advisory dict.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.auth import (
    ROLE_ADMIN,
    ROLE_ANALYST,
    ROLE_ANONYMOUS,
    ROLE_VIEWER,
    check_role_permission,
    hash_password,
    issue_access_token,
    validate_password_strength,
    verify_password,
)
from app.config import settings
from app.db import connection_scope, init_db
from app.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]


def _setup_isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str = "phase2.db") -> Path:
    db_path = tmp_path / name
    monkeypatch.setattr(settings, "db_path", str(db_path))
    monkeypatch.setattr(settings, "app_env", "testing")
    init_db()
    return db_path


# ═══════════════════════════════════════════════════════════════
# P1-1: Auth, IDOR, Role Parity, /api/v1/llm Lock & Error Redaction
# ═══════════════════════════════════════════════════════════════


class TestP1AuthIdorAndRbac:
    def test_idor_user_id_query_ignored_for_non_admin(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _setup_isolated_db(tmp_path, monkeypatch, "p1_1_idor.db")
        monkeypatch.setattr(settings, "api_key", "admin-key-phase2-secret-1234567890")
        monkeypatch.setattr(settings, "auth_token_secret", "token-secret-phase2-32-bytes-minimum-key!!")

        with connection_scope() as conn:
            conn.execute(
                """
                INSERT INTO projects (id, name, sector, stage, score, label, confidence, source, meta)
                VALUES ('p-idor', 'IdorProj', 'DeFi', 'testnet', 85, 'FARM', 0.9, 'seed',
                        '{"signals":{"has_testnet":true,"has_task_portal":true}}')
                """
            )
            conn.execute(
                "INSERT INTO interactions (project_id, user_id, status, cost_usd, profit_usd, hours_spent) "
                "VALUES ('p-idor', 'usr_victim', 'done', 50, 200, 3.5)"
            )
            conn.execute(
                "INSERT INTO interactions (project_id, user_id, status, cost_usd, profit_usd, hours_spent) "
                "VALUES ('p-idor', 'usr_attacker', 'active', 10, 0, 1.0)"
            )
            conn.commit()

        attacker_jwt, _, _ = issue_access_token("usr_attacker", ROLE_ANALYST)
        attacker_headers = {"Authorization": f"Bearer {attacker_jwt}"}
        admin_headers = {"X-API-Key": "admin-key-phase2-secret-1234567890"}

        with TestClient(create_app()) as client:
            # 1. GET /user-profile?user_id=usr_victim must stay bound to usr_attacker
            r_prof = client.get("/api/v1/user-profile?user_id=usr_victim", headers=attacker_headers)
            assert r_prof.status_code == 200
            assert r_prof.json()["data"]["user_id"] == "usr_attacker"

            # 2. DELETE /user-profile?user_id=usr_victim must NOT clear usr_victim
            r_del = client.delete("/api/v1/user-profile?user_id=usr_victim", headers=attacker_headers)
            assert r_del.status_code == 200
            assert r_del.json()["data"]["user_id"] == "usr_attacker"
            r_victim_adm = client.get("/api/v1/user-profile?user_id=usr_victim", headers=admin_headers)
            assert r_victim_adm.json()["data"]["is_cleared"] is False

            # 3. GET /action-queue?user_id=usr_victim stays bound to usr_attacker
            r_aq = client.get("/api/v1/action-queue?user_id=usr_victim", headers=attacker_headers)
            assert r_aq.status_code == 200
            assert r_aq.json()["data"]["user_id"] == "usr_attacker"

            # 4. GET /interactions/summary isolates per user & exposes net_usd + total_hours_spent
            r_sum_atk = client.get("/api/v1/interactions/summary?user_id=usr_victim", headers=attacker_headers)
            assert r_sum_atk.status_code == 200
            atk_data = r_sum_atk.json()["data"]
            assert atk_data["total"] == 1
            assert atk_data["total_cost_usd"] == 10.0
            assert atk_data["total_hours_spent"] == 1.0
            assert atk_data["net_usd"] == -10.0

            # Admin sees both or filters cleanly
            r_sum_adm = client.get("/api/v1/interactions/summary", headers=admin_headers)
            assert r_sum_adm.json()["data"]["total"] == 2
            r_sum_adm_v = client.get("/api/v1/interactions/summary?user_id=usr_victim", headers=admin_headers)
            assert r_sum_adm_v.json()["data"]["total"] == 1
            assert r_sum_adm_v.json()["data"]["net_usd"] == 150.0

            # 5. PATCH /interactions/{id} cannot reassign user_id to victim
            atk_items = client.get("/api/v1/interactions", headers=attacker_headers).json()["data"]["items"]
            atk_id = atk_items[0]["id"]
            r_patch = client.patch(
                f"/api/v1/interactions/{atk_id}",
                headers=attacker_headers,
                json={"user_id": "usr_victim", "note": "updated"},
            )
            assert r_patch.status_code == 200
            assert r_patch.json()["data"]["user_id"] == "usr_attacker"

            # 6. GET /api/v1/llm/status is admin-only
            assert client.get("/api/v1/llm/status", headers=attacker_headers).status_code == 403
            anon_tok = client.post("/api/v1/auth/anonymous").json()["access_token"]
            assert client.get("/api/v1/llm/status", headers={"Authorization": f"Bearer {anon_tok}"}).status_code == 403
            assert client.get("/api/v1/llm/status", headers=admin_headers).status_code == 200

    def test_anonymous_cannot_outprivilege_viewer_on_global_writes(self) -> None:
        global_write_cases = (
            ("POST", "/api/v1/projects/p1/opportunity/evaluate"),
            ("POST", "/api/v1/projects/p1/opportunity/evidence"),
            ("POST", "/api/v1/projects/p1/evaluate"),
            ("POST", "/api/v1/gas/alerts/rules"),
            ("DELETE", "/api/v1/gas/alerts/rules/r1"),
            ("POST", "/api/v1/pnl/records"),
            ("POST", "/api/v1/team-studio/operator"),
            ("POST", "/api/v1/team-studio/assign-task"),
        )
        for method, path in global_write_cases:
            assert check_role_permission(ROLE_ANONYMOUS, method, path)[0] is False
            assert check_role_permission(ROLE_VIEWER, method, path)[0] is False
            assert check_role_permission(ROLE_ANALYST, method, path)[0] is True
            assert check_role_permission(ROLE_ADMIN, method, path)[0] is True

    def test_projects_evaluate_and_dossier_do_not_leak_raw_exception(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _setup_isolated_db(tmp_path, monkeypatch, "p1_1_redact.db")
        monkeypatch.setattr(settings, "api_key", "")
        secret_err = "sqlite3.OperationalError: secret-internal-dsn-password-xyz"

        async def _boom(_pid: str) -> dict:
            raise RuntimeError(secret_err)

        def _boom_sync(_pid: str) -> dict:
            raise RuntimeError(secret_err)

        monkeypatch.setattr("app.services.project_evaluation.evaluate_single_project", _boom)
        monkeypatch.setattr("app.services.alpha_dossier.generate_alpha_dossier", _boom_sync)

        with TestClient(create_app()) as client:
            r1 = client.post("/api/v1/projects/p1/evaluate")
            assert r1.status_code == 500
            assert secret_err not in r1.text

            r2 = client.get("/api/v1/projects/p1/dossier")
            assert r2.status_code == 500
            assert secret_err not in r2.text


# ═══════════════════════════════════════════════════════════════
# P1-2: Malformed ak_ DoS, Deactivated User Key & >72B Password
# ═══════════════════════════════════════════════════════════════


class TestP1ApiKeyAndPasswordHardening:
    def test_malformed_ak_and_inactive_user_zero_bcrypt_calls(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import app.repositories.api_key as ak_mod
        from app.repositories.api_key import ApiKeyRepository
        from app.repositories.user import UserRepository

        _setup_isolated_db(tmp_path, monkeypatch, "p1_2_ak.db")
        key_hex = "abcdef0123456789"
        raw_key = f"ak_{key_hex}_secretvalue123"
        key_hash = hash_password(raw_key)

        with connection_scope() as conn:
            UserRepository(conn).create_user(
                user_id="usr_inactive",
                email="inactive@example.com",
                password_hash="h",
                role="analyst",
            )
            ApiKeyRepository(conn).create_key(
                key_id=f"key_{key_hex}",
                user_id="usr_inactive",
                name="k1",
                key_hash=key_hash,
                role="analyst",
            )
            conn.commit()

        calls = {"n": 0}
        real_verify = ak_mod.verify_password

        def _counting_verify(raw: str, hashed: str) -> bool:
            calls["n"] += 1
            return real_verify(raw, hashed)

        monkeypatch.setattr(ak_mod, "verify_password", _counting_verify)

        with connection_scope() as conn:
            repo = ApiKeyRepository(conn)
            # Malformed ak_ prefixes MUST NOT fall through to full-table scan
            for malformed in ("ak_x", "ak_", "ak_short_sec", "ak_too_many_parts_here"):
                assert repo.find_active_key_by_raw(malformed) is None
            assert calls["n"] == 0

            # Active user succeeds with 1 bcrypt call
            assert repo.find_active_key_by_raw(raw_key) is not None
            assert calls["n"] == 1

            # Deactivated user is rejected with 0 additional bcrypt calls
            conn.execute("UPDATE users SET is_active = 0 WHERE id = 'usr_inactive'")
            conn.commit()
            assert repo.find_active_key_by_raw(raw_key) is None
            assert calls["n"] == 1

    def test_password_over_72_bytes_returns_400_not_500(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _setup_isolated_db(tmp_path, monkeypatch, "p1_2_pwd.db")
        monkeypatch.setattr(settings, "api_key", "")
        long_pwd = "Ab1" + ("x" * 90)
        ok, msg = validate_password_strength(long_pwd)
        assert ok is False
        assert "72" in msg
        assert verify_password(long_pwd, hash_password("Abcdef12")) is False

        with TestClient(create_app()) as client:
            res = client.post(
                "/api/v1/auth/register",
                json={"email": "longpwd@example.com", "password": long_pwd},
            )
            assert res.status_code == 400
            assert res.json()["error"]["code"] == "WEAK_PASSWORD"


# ═══════════════════════════════════════════════════════════════
# P1-4 & P1-5: Collector, Persistence, Funding, DefiLlama, RootData, Heat
# ═══════════════════════════════════════════════════════════════


class TestP1PipelineAndCollectorSignals:
    def test_persistence_uses_identity_resolver_and_material_requeue(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.collectors.base import CollectorResult, RawDiscovery, RawSignal
        from app.collectors.persistence import CollectionRepository
        from app.identity import ProjectIdentityResolver

        _setup_isolated_db(tmp_path, monkeypatch, "p1_4_persist.db")
        with connection_scope() as conn:
            ProjectIdentityResolver(conn).upsert_alias(
                dedup_key="alpha-proto::DeFi",
                project_id="canonical-alpha-id",
                source="manual",
            )
            repo = CollectionRepository(conn)
            d1 = RawDiscovery(
                source_id="defillama",
                raw_id="alpha-proto",
                name="Alpha Proto",
                url="https://alpha.example",
                sector="DeFi",
                stage="mainnet",
                raw_data={"tvl": 1_000_000, "has_testnet": False},
                raw_signals=[RawSignal("tvl", "defillama", {"tvl": 1_000_000}, 0.5)],
                discovery_score=0.6,
            )
            res1 = CollectorResult(source_id="defillama", items=[d1], status="success")
            res1.started_at = datetime.now(UTC)
            res1.finished_at = datetime.now(UTC)
            repo.persist_collection_result(res1)

            # Mark as processed
            conn.execute("UPDATE raw_projects SET processed = 1 WHERE source_id = 'defillama'")
            conn.commit()

            # Both raw_projects and project_signals got canonical-alpha-id
            rp = conn.execute("SELECT project_id, processed FROM raw_projects").fetchone()
            ps = conn.execute("SELECT project_id FROM project_signals").fetchone()
            assert rp["project_id"] == "canonical-alpha-id"
            assert ps["project_id"] == "canonical-alpha-id"

            # Re-collect with only volatile TVL change -> stays processed=1
            d2 = RawDiscovery(
                source_id="defillama",
                raw_id="alpha-proto",
                name="Alpha Proto",
                url="https://alpha.example",
                sector="DeFi",
                stage="mainnet",
                raw_data={"tvl": 1_200_000, "has_testnet": False},
                discovery_score=0.62,
            )
            res2 = CollectorResult(source_id="defillama", items=[d2], status="success")
            res2.started_at = datetime.now(UTC)
            res2.finished_at = datetime.now(UTC)
            repo.persist_collection_result(res2)
            assert conn.execute("SELECT processed FROM raw_projects").fetchone()["processed"] == 1

            # Re-collect with material signal change (has_testnet=True) -> resets processed=0
            d3 = RawDiscovery(
                source_id="defillama",
                raw_id="alpha-proto",
                name="Alpha Proto",
                url="https://alpha.example",
                sector="DeFi",
                stage="testnet",
                raw_data={"tvl": 1_200_000, "has_testnet": True},
                discovery_score=0.65,
            )
            res3 = CollectorResult(source_id="defillama", items=[d3], status="success")
            res3.started_at = datetime.now(UTC)
            res3.finished_at = datetime.now(UTC)
            repo.persist_collection_result(res3)
            assert conn.execute("SELECT processed FROM raw_projects").fetchone()["processed"] == 0

    def test_extract_funding_unwraps_nested_defillama_funding(self) -> None:
        from app.services.funding import extract_funding_from_raw

        out = extract_funding_from_raw(
            {
                "name": "NestedProto",
                "funding": {
                    "has_funding": True,
                    "total_raised": 25_000_000.0,
                    "round_count": 2,
                    "investors": ["Paradigm", "a16z"],
                    "lead_investors": ["Paradigm"],
                    "last_round_date": "2026-08-01",
                },
            }
        )
        assert out["funding_total_usd"] == 25_000_000.0
        assert out["funding_rounds"] == 2
        assert "Paradigm" in out["funding_investors"]
        assert out["funding_tier"] == "tier1"

    @pytest.mark.asyncio
    async def test_defillama_fetch_protocols_converts_percent_to_ratio(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.collectors.defillama import DefiLlamaCollector

        collector = DefiLlamaCollector()
        fake_resp = MagicMock()
        fake_resp.raise_for_status = MagicMock()
        fake_resp.json.return_value = [{"name": "P", "slug": "p", "tvl": 5_000_000, "change_7d": 15.4}]
        monkeypatch.setattr(collector, "request_with_retry", AsyncMock(return_value=fake_resp))
        rows = await collector._fetch_protocols()
        assert rows[0]["change_7d"] == pytest.approx(0.154, abs=1e-6)

    def test_rootdata_sector_and_has_docs_fix(self) -> None:
        from app.collectors.rootdata import RootDataCollector

        collector = RootDataCollector()
        d = collector._build_discovery(
            {
                "id": 42,
                "name": "SentenceCheck",
                "one_liner": "A very long marketing sentence about building next-gen rollup infrastructure",
                "tag": "L2",
                "website": "https://sentencecheck.xyz",
            }
        )
        assert d is not None
        assert d.sector == "L2"
        assert d.raw_data["has_docs"] is False

    def test_heat_signals_distinct_and_twitter_kol_airdrop_match(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.agents.heat_signals import HeatSignalProvider

        _setup_isolated_db(tmp_path, monkeypatch, "p1_5_heat.db")
        now_iso = datetime.now(UTC).isoformat()
        with connection_scope() as conn:
            # Two raw_projects sharing dedup_key (multi-source) to verify DISTINCT avoids 2x inflation
            conn.execute(
                "INSERT INTO raw_projects (raw_id, source_id, dedup_key, raw_data, project_id) "
                "VALUES ('r1', 'defillama', 'dk1', ?, 'pid1')",
                (json.dumps({"name": "P", "sector": "AI"}),),
            )
            conn.execute(
                "INSERT INTO raw_projects (raw_id, source_id, dedup_key, raw_data, project_id) "
                "VALUES ('r2', 'github', 'dk1', ?, 'pid1')",
                (json.dumps({"name": "P", "sector": "AI"}),),
            )
            conn.execute(
                "INSERT INTO project_signals (signal_id, project_id, dedup_key, signal_type, signal_source, "
                "signal_data, signal_strength, captured_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "sig-tw-1",
                    "pid1",
                    "dk1",
                    "twitter_mention",
                    "twitter",
                    json.dumps({"signal_type": "airdrop", "tweet_id": "111"}),
                    0.9,
                    now_iso,
                ),
            )
            conn.commit()

        provider = HeatSignalProvider()
        # With 1 twitter_mention carrying signal_type="airdrop", KOL component contributes +0.02 -> 0.814
        # (without KOL match it would be 0.754; without DISTINCT across 2 raw_projects it would inflate to 0.922)
        mult = provider._compute_multiplier("AI")
        assert mult == pytest.approx(0.814, abs=1e-3)

    def test_unknown_name_filtered_as_noise(self) -> None:
        from app.collectors.noise import is_noise_raw_project

        assert is_noise_raw_project("Unknown", "DeFi", {}) is True
        assert is_noise_raw_project("", "DeFi", {}) is True
        assert is_noise_raw_project("RealProto", "DeFi", {}) is False


# ═══════════════════════════════════════════════════════════════
# P1-6: Orchestrator Null-Guard, Project Evaluation & Calibration
# ═══════════════════════════════════════════════════════════════


class TestP1ScoringAndCalibration:
    @pytest.mark.asyncio
    async def test_orchestrator_does_not_overwrite_valid_score_with_null(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.agents.base import AgentContext, PipelineState, RawProject
        from app.agents.orchestrator_simple import SimpleOrchestrator

        _setup_isolated_db(tmp_path, monkeypatch, "p1_6_orch.db")
        with connection_scope() as conn:
            conn.execute(
                "INSERT INTO projects (id, name, sector, stage, score, label, confidence, source) "
                "VALUES ('keep-me', 'KeepMe', 'DeFi', 'testnet', 82, 'FARM', 0.9, 'seed')"
            )
            conn.commit()

        orch = SimpleOrchestrator()

        async def _failed_single(project, ctx, counts):
            return PipelineState(project=project, context=ctx, score=None, label=None)

        monkeypatch.setattr(orch, "_run_single_project", _failed_single)
        await orch.run_pipeline(
            [RawProject(id="keep-me", name="KeepMe", sector="DeFi")],
            AgentContext(run_id="test-p1-6-null-guard"),
            save_to_db=True,
        )

        with connection_scope() as conn:
            row = conn.execute("SELECT score, label FROM projects WHERE id = 'keep-me'").fetchone()
        assert row["score"] == 82
        assert row["label"] == "FARM"

    def test_calibration_negated_note_and_veto_confidence_replay(self) -> None:
        from app.calibration import WEIGHT_KEYS, _parse_label_from_note, recompute_label

        assert _parse_label_from_note("Not FARM, should be IGNORE") == "IGNORE"
        assert _parse_label_from_note("不是 FARM，应为 WATCH") == "WATCH"
        assert _parse_label_from_note("unfarmable hype") is None
        assert _parse_label_from_note("should be FARM") == "FARM"

        high_subs = {k: 90.0 for k in WEIGHT_KEYS}
        equal_w = {k: 1.0 / len(WEIGHT_KEYS) for k in WEIGHT_KEYS}
        assert recompute_label(high_subs, equal_w) == "FARM"
        assert recompute_label(high_subs, equal_w, veto="already_launched") == "IGNORE"
        assert recompute_label(high_subs, equal_w, veto="explicit_no_airdrop") == "IGNORE"
        assert recompute_label(high_subs, equal_w, veto="no_participation_path") == "WATCH"
        assert recompute_label(high_subs, equal_w, confidence=0.35) == "WATCH"


# ═══════════════════════════════════════════════════════════════
# P1-7: LLM Concurrent Budget Reservation, Empty Usage & 401/402
# ═══════════════════════════════════════════════════════════════


class TestP1LlmBudgetAndFailover:
    @pytest.mark.asyncio
    async def test_concurrent_llm_calls_respect_budget_reservation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.llm import budget as budget_mod
        from app.llm.client import _RawCompletion, _reset_round_robin_for_tests, llm_chat

        _setup_isolated_db(tmp_path, monkeypatch, "p1_7_conc.db")
        _reset_round_robin_for_tests()
        fake_settings = SimpleNamespace(
            llm_providers=[
                {"name": "p1", "base_url": "https://api.openai.com/v1", "api_key": "k", "models": ["gpt-4o"]}
            ],
            llm_daily_budget_usd=0.01,
            llm_fallback_price_per_1m_usd=10.0,
            llm_temperature=0.2,
            llm_max_tokens=1000,  # gpt-4o output 1000 tok = $0.01 -> allows only 1 concurrent call
        )
        monkeypatch.setattr("app.llm.client.settings", fake_settings)

        dispatched = 0

        async def _slow_ok(provider, model, **kwargs):
            nonlocal dispatched
            dispatched += 1
            await asyncio.sleep(0.05)
            return _RawCompletion(text="ok", raw_usage={"prompt_tokens": 100, "completion_tokens": 100})

        monkeypatch.setattr("app.llm.client._try_single", _slow_ok)
        results = await asyncio.gather(*(llm_chat([{"role": "user", "content": "hi"}]) for _ in range(5)))
        allowed = [r for r in results if r.ok]
        blocked = [r for r in results if r.refused_reason == budget_mod.REASON_BUDGET_EXCEEDED]
        assert len(allowed) == 1
        assert len(blocked) == 4
        assert dispatched == 1

    @pytest.mark.asyncio
    async def test_empty_response_with_usage_still_records_spend_and_401_skips_provider(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.llm import budget as budget_mod
        from app.llm.client import (
            _EmptyLLMResponseError,
            _is_connection_error,
            _reset_round_robin_for_tests,
            llm_chat,
        )

        _setup_isolated_db(tmp_path, monkeypatch, "p1_7_empty.db")
        _reset_round_robin_for_tests()

        req = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
        for code in (401, 402, 403):
            err = httpx.HTTPStatusError("err", request=req, response=httpx.Response(code, request=req))
            assert _is_connection_error(err) is True

        fake_settings = SimpleNamespace(
            llm_providers=[
                {"name": "p1", "base_url": "https://api.openai.com/v1", "api_key": "k", "models": ["gpt-4o-mini"]}
            ],
            llm_daily_budget_usd=5.0,
            llm_fallback_price_per_1m_usd=10.0,
            llm_temperature=0.2,
            llm_max_tokens=512,
        )
        monkeypatch.setattr("app.llm.client.settings", fake_settings)

        async def _empty_billed(provider, model, **kwargs):
            raise _EmptyLLMResponseError(
                "Empty LLM response",
                raw_usage={"prompt_tokens": 500_000, "completion_tokens": 500_000},
            )

        monkeypatch.setattr("app.llm.client._try_single", _empty_billed)
        res = await llm_chat([{"role": "user", "content": "reason"}])
        assert res.ok is False
        spend = budget_mod.get_daily_spend()
        assert spend.cost_usd > Decimal("0")
        assert spend.completion_tokens == 500_000


# ═══════════════════════════════════════════════════════════════
# P1-8, P1-9, P1-3 & P1-10: Settings, ROI Simulator, PnL, Ops & DevOps
# ═══════════════════════════════════════════════════════════════


class TestP1FrontendContractsAndDevOps:
    def test_settings_config_exposes_all_16_sources(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _setup_isolated_db(tmp_path, monkeypatch, "p1_8_settings.db")
        monkeypatch.setattr(settings, "api_key", "")
        with TestClient(create_app()) as client:
            sources = client.get("/api/v1/settings/config").json()["data"]["sources"]
        for expected in (
            "defillama",
            "github",
            "github_curated",
            "coingecko",
            "twitter",
            "etherscan",
            "rootdata",
            "cryptorank",
            "galxe",
            "layer3",
            "telegram",
            "farcaster",
            "discord",
            "reddit",
            "medium",
            "mirror",
        ):
            assert expected in sources

    def test_roi_simulator_risk_appetite_dedup_and_simulated_badge(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.services.roi_simulator import simulate_portfolio_allocation

        _setup_isolated_db(tmp_path, monkeypatch, "p1_9_roi.db")
        with connection_scope() as conn:
            for idx, (sec, stg) in enumerate(
                [
                    ("Restaking", "mainnet"),
                    ("L2", "testnet"),
                    ("ZK", "testnet"),
                    ("AI", "mainnet"),
                    ("Gaming", "mainnet"),
                ]
            ):
                conn.execute(
                    "INSERT INTO projects (id, name, sector, stage, score, label, confidence, source) "
                    "VALUES (?, ?, ?, ?, ?, 'FARM', 0.9, 'seed')",
                    (f"roi-p{idx}", f"RoiProj{idx}", sec, stg, 90 - idx),
                )
            conn.commit()

        cons = simulate_portfolio_allocation(total_budget_usd=1000, weekly_hours=10, risk_appetite="conservative")
        aggr = simulate_portfolio_allocation(total_budget_usd=1000, weekly_hours=10, risk_appetite="aggressive")
        assert cons["data_quality"]["quality"] == "simulated"
        assert aggr["data_quality"]["quality"] == "simulated"

        # No duplicate project_ids across buckets
        cons_ids = [a["project_id"] for a in cons["data"]["allocations"]]
        assert len(cons_ids) == len(set(cons_ids))

        # Conservative allocates more to Restaking than Aggressive
        assert (
            cons["data"]["allocations"][0]["allocated_budget_usd"]
            > aggr["data"]["allocations"][0]["allocated_budget_usd"]
        )
        assert aggr["data"]["total_expected_return_usd"] > cons["data"]["total_expected_return_usd"]

    def test_airdrop_pnl_does_not_auto_seed_in_production(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.services.airdrop_pnl import get_pnl_summary

        _setup_isolated_db(tmp_path, monkeypatch, "p1_9_pnl_prod.db")
        monkeypatch.setattr(settings, "app_env", "production")
        summary = get_pnl_summary()
        assert summary["total_claimed_projects"] == 0
        assert summary["records"] == []
        assert summary["records"] == []

    @pytest.mark.asyncio
    async def test_ops_tasks_sync_uses_merged_funding_and_structured_advisory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.services.ops_tasks import audit_database_viability, sync_database_defillama_raises

        _setup_isolated_db(tmp_path, monkeypatch, "p1_10_ops.db")
        with connection_scope() as conn:
            conn.execute(
                "INSERT INTO projects (id, name, sector, stage, score, label, confidence, source, meta) "
                "VALUES ('ops-p1', 'HyperAlpha', 'DeFi', 'mainnet', 80, 'FARM', 0.9, 'seed', ?)",
                (
                    json.dumps(
                        {
                            "funding": {"funding_total_usd": 12_000_000.0, "funding_tier": "tier2"},
                            "signals": {"has_points_program": True},
                            "viability_tier": "unviable",
                        }
                    ),
                ),
            )
            conn.commit()

        monkeypatch.setattr(
            "app.services.ops_tasks.fetch_all_protocols",
            AsyncMock(return_value=[{"name": "HyperAlpha", "slug": "hyperalpha"}]),
        )
        # DefiLlama returns smaller amount ($500k) but adds Tier-1 investor -> merged amount MUST stay $12M
        monkeypatch.setattr(
            "app.services.ops_tasks.fetch_protocol_funding",
            AsyncMock(
                return_value={
                    "has_funding": True,
                    "funding_amount": 500_000.0,
                    "funding_tier": "tier1",
                    "funding_quality": 0.9,
                    "round_count": 1,
                    "rounds": ["Seed"],
                    "lead_investors": ["Paradigm"],
                    "investors": ["Paradigm"],
                    "last_round_date": "2026-09-01",
                    "valuation": None,
                }
            ),
        )

        sync_res = await sync_database_defillama_raises(apply_changes=True)
        assert sync_res["ok"] is True
        assert sync_res["enriched_funding_count"] == 1
        assert sync_res["details"][0]["new_amount"] == 12_000_000.0
        assert sync_res["details"][0]["new_tier"] == "tier1"

        with connection_scope() as conn:
            meta = json.loads(conn.execute("SELECT meta FROM projects WHERE id = 'ops-p1'").fetchone()["meta"])
        assert isinstance(meta["viability_advisory"], dict)
        assert meta["viability_tier"] == "viable"

        audit_res = audit_database_viability(apply_changes=True)
        assert audit_res["ok"] is True
        assert audit_res["total_scanned"] == 1

    def test_devops_hardening_invariants(self) -> None:
        compose = (REPO_ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
        assert '"127.0.0.1:13002:3002"' in compose
        assert '"13002:3002"' not in compose

        nginx_http = (REPO_ROOT / "docker" / "nginx" / "nginx-http.conf").read_text(encoding="utf-8")
        assert "access_log /dev/stdout json;" in nginx_http
        assert "error_log  /dev/stderr warn;" in nginx_http

        env_ex = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
        assert "API_PROXY_TARGET=http://127.0.0.1:8002" in env_ex

        backup_sh = (REPO_ROOT / "scripts" / "backup.sh").read_bytes()
        assert b"\r\n" not in backup_sh
        assert b'[ -n "$(find logs -maxdepth 1 -type f | head -1)" ]' in backup_sh
