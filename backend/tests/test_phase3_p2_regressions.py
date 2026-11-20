"""Phase 3 (P2-1 through P2-5) architecture, security, pool, HA, and CI regression tests."""

from __future__ import annotations

import ast
import io
import socket
import zipfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import openpyxl
import pytest
from fastapi.testclient import TestClient

from app.config import Settings, settings
from app.db import close_pg_pools, connection_scope, init_db

REPO_ROOT = Path(__file__).resolve().parents[2]


def _setup_isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str) -> Path:
    db_file = tmp_path / name
    monkeypatch.setattr(settings, "db_path", str(db_file))
    monkeypatch.setattr(settings, "database_url", None)
    monkeypatch.setattr(settings, "db_backend", "sqlite")
    init_db()
    return db_file


class TestP2SecurityHardening:
    """P2-1: Export formula neutralization, zip-bomb defense, vitals SSRF, config/redact/rate-limit/webhook/playbook."""

    def test_export_neutralizes_spreadsheet_formula_injection(self) -> None:
        from app.export import export_project_detail_to_excel, export_projects_to_csv, export_projects_to_excel

        projects = [
            {
                "id": "=CMD|' /C calc'!A0",
                "name": "+1+1",
                "url": "@SUM(1+1)",
                "sector": "-2+3",
                "stage": "testnet",
                "score": 88,
                "label": "FARM",
                "confidence": 0.9,
                "reason": ['=HYPERLINK("http://evil")'],
            }
        ]

        csv_out = export_projects_to_csv(projects)
        assert "'=CMD|' /C calc'!A0" in csv_out
        assert "'+1+1" in csv_out
        assert "'@SUM(1+1)" in csv_out
        assert "'-2+3" in csv_out

        xlsx_bytes = export_projects_to_excel(projects)
        wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes))
        ws = wb["Projects"]
        assert ws["A2"].value == "'=CMD|' /C calc'!A0"
        assert ws["B2"].value == "'+1+1"
        assert ws["C2"].value == "'@SUM(1+1)"
        assert ws["D2"].value == "'-2+3"
        assert ws["F2"].value == 88  # numeric values remain numeric

        detail_bytes = export_project_detail_to_excel(projects[0])
        wb2 = openpyxl.load_workbook(io.BytesIO(detail_bytes))
        assert wb2["评分原因"]["A2"].value == '\'=HYPERLINK("http://evil")'

    def test_import_rejects_xlsx_zip_bomb_and_excess_rows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app import import_utils

        # Build a tiny compressed zip whose single entry decompresses beyond patched threshold
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("xl/worksheets/sheet1.xml", "A" * 100_000)
        monkeypatch.setattr(import_utils, "MAX_XLSX_UNCOMPRESSED_BYTES", 10_000)
        with pytest.raises(ValueError, match="解压后体积超限"):
            import_utils.import_projects_from_excel(buf.getvalue())

        monkeypatch.setattr(import_utils, "MAX_IMPORT_ROWS", 3)
        csv_text = "name,sector\nA,DeFi\nB,DeFi\nC,DeFi\nD,DeFi\n"
        with pytest.raises(ValueError, match="行数超过上限"):
            import_utils.import_projects_from_csv(csv_text)

    @pytest.mark.asyncio
    async def test_vitals_fail_closed_nat64_and_streaming_get(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.services import vitals

        # 1. NAT64 prefix must be rejected even if addr.is_global were True
        with pytest.raises(vitals.BlockedTargetError):
            await vitals._reject_non_public_target(httpx.Request("HEAD", "http://[64:ff9b::7f00:1]/"))

        # 2. DNS failure (socket.gaierror) must fail-closed with BlockedTargetError
        async def _raise_gaierror(*args: Any, **kwargs: Any) -> Any:
            raise socket.gaierror("NXDOMAIN")

        loop = vitals.asyncio.get_running_loop()
        monkeypatch.setattr(loop, "getaddrinfo", _raise_gaierror)
        with pytest.raises(vitals.BlockedTargetError, match="dns_failed"):
            await vitals._reject_non_public_target(httpx.Request("HEAD", "https://nonexistent.invalid/"))

        # 3. 405 HEAD fallback uses streaming GET and passes trust_env=False
        captured_kwargs: dict[str, Any] = {}
        stream_called = False

        class _StreamResp:
            status_code = 200

            async def __aenter__(self) -> _StreamResp:
                return self

            async def __aexit__(self, *args: Any) -> None:
                return None

        class _MockClient:
            def __init__(self, **kwargs: Any) -> None:
                captured_kwargs.update(kwargs)

            async def __aenter__(self) -> _MockClient:
                return self

            async def __aexit__(self, *args: Any) -> None:
                return None

            async def head(self, url: str) -> Any:
                class _R:
                    status_code = 405

                return _R()

            def stream(self, method: str, url: str) -> _StreamResp:
                nonlocal stream_called
                stream_called = True
                assert method == "GET"
                return _StreamResp()

        with patch("httpx.AsyncClient", _MockClient):
            verdict, code = await vitals.probe_site("https://example.org")
        assert verdict == "ok" and code == 200
        assert stream_called is True
        assert captured_kwargs.get("trust_env") is False

    def test_production_config_enforces_secret_strength_and_debug_false(self) -> None:
        base = {
            "_env_file": None,
            "app_env": "production",
            "api_key": "a" * 32,
            "auth_token_secret": "b" * 48,
            "cors_origins": "https://app.example.com",
        }
        prod = Settings(**{**base, "debug": True})  # type: ignore[arg-type]
        assert prod.debug is False

        with pytest.raises(ValueError, match="AUTH_TOKEN_SECRET"):
            Settings(**{**base, "auth_token_secret": "too-short"})  # type: ignore[arg-type]

        with pytest.raises(ValueError, match="JWT_SECRET"):
            Settings(**{**base, "jwt_secret": "changeme"})  # type: ignore[arg-type]

    def test_redact_masks_auth_secrets_and_bot_webhook_urls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.utils.redact import redact

        monkeypatch.setattr(settings, "auth_token_secret", "super-secret-auth-token-999999")
        monkeypatch.setattr(settings, "jwt_secret", "super-secret-jwt-key-888888888")
        monkeypatch.setattr(settings, "postgres_password", "pg-secret-pass-7777777")
        monkeypatch.setattr(settings, "registration_bootstrap_token", "bootstrap-secret-666666")

        raw = (
            "auth=super-secret-auth-token-999999 jwt=super-secret-jwt-key-888888888 "
            "pg=pg-secret-pass-7777777 boot=bootstrap-secret-666666 "
            "tg=https://api.telegram.org/bot123456789:AAHfakeTokenXYZ12345/sendMessage "
            "dc=https://discord.com/api/webhooks/1234567890/AbCdEfGhIjKlMnOpQrSt"
        )
        out = redact(raw)
        for leaked in (
            "super-secret-auth-token-999999",
            "super-secret-jwt-key-888888888",
            "pg-secret-pass-7777777",
            "bootstrap-secret-666666",
            "AAHfakeTokenXYZ12345",
            "AbCdEfGhIjKlMnOpQrSt",
        ):
            assert leaked not in out
        assert "/bot123456789:***/sendMessage" in out

    def test_rate_limit_isolates_expensive_and_login_buckets(self) -> None:
        from app.rate_limit import RateLimitMiddleware, _auth_limits

        auth_rules = dict((p, (lim, win)) for p, lim, win in _auth_limits())
        assert "/api/v1/auth/login" in auth_rules

        mw = RateLimitMiddleware(app=lambda scope, receive, send: None)  # type: ignore[arg-type]
        # Record a /run hit in expensive window, then flood and prune general window
        assert mw._expensive_windows.check("1.2.3.4:/api/v1/run", 1, 3600.0, 100.0) is None
        for i in range(50):
            mw._windows.check(f"flood-{i}", 100, 60.0, 101.0)
        mw._windows.prune(102.0, 60.0, max_keys=5)
        # /run bucket in _expensive_windows must remain completely untouched
        retry = mw._expensive_windows.check("1.2.3.4:/api/v1/run", 1, 3600.0, 102.0)
        assert retry is not None and retry > 3500.0

    def test_webhook_rejects_oversized_payload_before_signature_check(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.main import create_app

        _setup_isolated_db(tmp_path, monkeypatch, "p2_webhook.db")
        monkeypatch.setattr(settings, "alchemy_webhook_signing_key", "test-signing-key-123456")
        monkeypatch.setattr(settings, "scheduler_enabled", False)
        monkeypatch.setattr(settings, "collection_scheduler_enabled", False)
        app = create_app()
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/webhook/alchemy",
                content=b"x" * (1024 * 1024 + 64),
                headers={"Content-Type": "application/json", "X-Alchemy-Signature": "deadbeef"},
            )
            assert resp.status_code == 413
            assert resp.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"

    def test_playbook_orchestrator_escapes_user_inputs_safely(self) -> None:
        from app.services.playbook_orchestrator import validate_and_generate_playbook_script

        payload = validate_and_generate_playbook_script(
            custom_title='Evil"); import os; os.system("id"); #',
            custom_steps=[
                {
                    "title": 'Inject"); import os; os.system("echo pwned"); #',
                    "action": "swap\nimport os; os.system('bad')",
                    "contract": "0x1234567890abcdef1234567890abcdef12345678",
                    "gas_usd": 1.2,
                }
            ],
        )
        assert payload["ok"] is True
        script = payload["executable_code"]
        # Generated script must be syntactically valid Python with no injected os.system call
        tree = ast.parse(script)
        calls = [
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        ]
        assert "system" not in calls


class TestP2PoolCompetitionHaAndSchema:
    """P2-2, P2-3, P2-4, P2-5: PG pooling, competition counting, schema 0016, HA rollback & scheduler."""

    def test_postgres_fallback_pool_reuses_and_rolls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app import db as db_mod

        created: list[Any] = []

        class _FakePgConn:
            def __init__(self) -> None:
                self.closed = False
                self.broken = False
                self.rollbacks = 0

            def rollback(self) -> None:
                self.rollbacks += 1

            def close(self) -> None:
                self.closed = True

        def _fake_connect(dsn: str, **kwargs: Any) -> _FakePgConn:
            c = _FakePgConn()
            created.append(c)
            return c

        import psycopg

        close_pg_pools()
        monkeypatch.setattr(settings, "app_env", "development")
        monkeypatch.setattr(settings, "database_url", "postgresql://u:p@localhost:5432/testpool")
        monkeypatch.setattr(psycopg, "connect", _fake_connect)

        try:
            c1 = db_mod._connect_postgres()
            assert len(created) == 1
            c1.close()
            assert created[0].rollbacks == 1
            assert created[0].closed is False

            # Second checkout reuses pooled connection rather than opening a second TCP connection
            c2 = db_mod._connect_postgres()
            assert len(created) == 1
            c2.close()
            assert created[0].rollbacks == 2
        finally:
            close_pg_pools()
        assert created[0].closed is True

    def test_canonical_sector_counts_excludes_hidden_backfill_and_batch_ids(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.repository import ProjectRepository

        _setup_isolated_db(tmp_path, monkeypatch, "p2_sector.db")
        with connection_scope() as conn:
            conn.execute(
                "INSERT INTO projects (id, name, sector, stage, score, label, confidence, source, hidden_reason) "
                "VALUES ('p-active', 'ActiveDex', 'Dexes', 'testnet', 80, 'FARM', 0.8, 'defillama', NULL)"
            )
            conn.execute(
                "INSERT INTO projects (id, name, sector, stage, score, label, confidence, source, hidden_reason) "
                "VALUES ('p-batch', 'BatchDex', 'DEX', 'testnet', 75, 'WATCH', 0.7, 'defillama', NULL)"
            )
            conn.execute(
                "INSERT INTO projects (id, name, sector, stage, score, label, confidence, source, hidden_reason) "
                "VALUES ('p-hidden', 'LaunchedDex', 'DEX', 'mainnet', 10, 'IGNORE', 0.9, 'defillama', 'token_launched')"
            )
            conn.execute(
                "INSERT INTO projects (id, name, sector, stage, score, label, confidence, source, hidden_reason) "
                "VALUES ('p-backfill', 'HistDex', 'DEX', 'mainnet', 90, 'FARM', 0.9, 'historical_backfill', NULL)"
            )
            conn.commit()

        repo = ProjectRepository()
        counts = repo.canonical_sector_counts(exclude_ids={"p-batch"}, active_only=True)
        # Only 'p-active' should be counted (excludes p-batch, p-hidden, and p-backfill)
        assert counts.get("DEX") == 1

    def test_init_db_consolidates_all_runtime_tables(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _setup_isolated_db(tmp_path, monkeypatch, "p2_schema.db")
        with connection_scope() as conn:
            rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            tables = {row["name"] for row in rows}
        for required in (
            "leader_election",
            "harvest_records",
            "faucet_claims",
            "gas_alert_rules",
            "team_studio_operators",
            "team_studio_tasks",
        ):
            assert required in tables

    def test_leader_election_rolls_back_when_lease_held_by_other(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.services.leader_election import LeaderElector

        _setup_isolated_db(tmp_path, monkeypatch, "p2_ha.db")
        elector_a = LeaderElector(instance_id="node-a", enabled=True, lease_ttl_seconds=60)
        assert elector_a.acquire_or_renew() is True

        # Track rollback calls on a borrowed connection when node-b loses election
        with connection_scope() as conn:
            rollback_calls = 0
            orig_rollback = conn.rollback

            def _counting_rollback() -> None:
                nonlocal rollback_calls
                rollback_calls += 1
                orig_rollback()

            monkeypatch.setattr(conn, "rollback", _counting_rollback)
            elector_b = LeaderElector(
                instance_id="node-b",
                enabled=True,
                lease_ttl_seconds=60,
                conn_factory=lambda: conn,
                owns_connections=False,
            )
            assert elector_b.acquire_or_renew() is False
            assert rollback_calls >= 1
            assert not conn._raw.in_transaction

    @pytest.mark.asyncio
    async def test_scheduler_repromotes_after_shutdown_and_locks_collection_and_persists_digest(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.collectors.registry import CollectorRegistry
        from app.inflight import claim_run, collect_key
        from app.scheduler import UnifiedScheduler

        _setup_isolated_db(tmp_path, monkeypatch, "p2_sched.db")
        monkeypatch.setattr(settings, "scheduler_enabled", True)
        monkeypatch.setattr(settings, "collection_scheduler_enabled", False)
        monkeypatch.setattr(settings, "archive_scheduler_enabled", False)
        monkeypatch.setattr(settings, "notify_enabled", False)
        monkeypatch.setattr(settings, "vitals_scheduler_enabled", False)
        monkeypatch.setattr(settings, "launch_review_scheduler_enabled", False)

        sched = UnifiedScheduler(registry=CollectorRegistry())
        sched.start()
        assert sched.scheduler.running is True
        first_inner = sched.scheduler
        sched.shutdown(wait=False)

        # Re-promotion must recreate the scheduler cleanly instead of failing on a stopped executor
        sched.start()
        assert sched.scheduler is not first_inner
        assert sched.scheduler.running is True
        sched.shutdown(wait=False)

        # Scheduled _run_collection respects in-flight collect_key lock
        class _DummyCollector:
            source_id = "dummy"
            called = False

            def is_enabled(self) -> bool:
                return True

            async def collect(self) -> Any:
                self.called = True
                raise AssertionError("should not run while collect_key is held")

        dummy = _DummyCollector()
        sched.registry._collectors["dummy"] = dummy  # type: ignore[assignment]
        with claim_run(collect_key("dummy")):
            await sched._run_collection("dummy")
        assert dummy.called is False

        # _run_alpha_digest_job persists digest snapshot to logs table
        with patch(
            "app.services.alpha_digest.generate_alpha_digest",
            return_value={"generated_at": "2026-11-20T00:00:00Z", "window_days": 7, "top_projects": [{"id": "p1"}]},
        ):
            await sched._run_alpha_digest_job()
        with connection_scope() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM logs WHERE agent_name = 'alpha_digest'").fetchone()
            assert int(row["n"]) >= 1

    def test_ci_workflows_and_makefile_hardening(self) -> None:
        ci_text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        sec_text = (REPO_ROOT / ".github" / "workflows" / "security.yml").read_text(encoding="utf-8")
        rel_text = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        mk_text = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")

        assert "postgres-smoke:" in ci_text
        assert "postgres:15-alpine" in ci_text
        assert "npm run lint" in ci_text
        assert "frontend-next/Dockerfile" in ci_text

        assert "aquasecurity/trivy-action@master" not in sec_text
        assert "aquasecurity/trivy-action@0.28.0" in sec_text
        assert "frontend-next/Dockerfile" in sec_text

        assert "frontend-next/Dockerfile" in rel_text

        assert "COMPOSE := docker compose" in mk_text
        assert "cd backend && $(PYTHON) -m alembic upgrade head" in mk_text
