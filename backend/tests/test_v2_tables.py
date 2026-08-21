"""Tests for V2 new tables migration + repository methods (E1).

Covers:
- Migration 0002: creates all 8 new tables + missing feedback indexes
- init_db: new tables exist after fresh init
- Repository CRUD for all 8 tables
- Schema consistency: table columns match §5.4 DDL

Reference:
- V2_TASKS.md E1
- DATABASE_DDL.md §2.4–§2.12
- ENGINEERING_ROADMAP.md §5.4
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from app.db import init_db
from app.repositories.v2 import (
    AuditLogRepository,
    DedupKeysRepository,
    LLMEvalRepository,
    MetricsRepository,
    NarrativesRepository,
    ProjectHistoryRepository,
    PromptVersionsRepository,
    QuarantineRepository,
)

# ── Fixtures ────────────────────────────────────


def _make_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


@pytest.fixture
def conn():
    c = _make_conn()
    try:
        yield c
    finally:
        c.close()


# ── Table existence tests ──────────────────────


@pytest.mark.parametrize(
    "table_name",
    [
        "quarantine",
        "project_history",
        "audit_logs",
        "llm_eval_changelog",
        "metrics",
        "narratives",
        "dedup_keys",
        "prompt_versions",
    ],
)
def test_table_exists_after_init_db(conn, table_name):
    """All V2 tables are created by init_db()."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    assert row is not None, f"Table '{table_name}' not found after init_db()"


@pytest.mark.parametrize(
    "index_name",
    [
        "idx_quarantine_status",
        "idx_quarantine_reason",
        "idx_quarantine_created",
        "idx_project_history_project",
        "idx_project_history_run",
        "idx_project_history_created",
        "idx_audit_action",
        "idx_audit_user",
        "idx_audit_created",
        "idx_llm_eval_date",
        "idx_metrics_run_id",
        "idx_metrics_name",
        "idx_metrics_timestamp",
        "idx_narratives_stage",
        "idx_dedup_key",
        "idx_dedup_project",
        "idx_prompt_agent",
        "idx_prompt_version",
        "idx_feedback_signal",
        "idx_feedback_created",
    ],
)
def test_index_exists_after_init_db(conn, index_name):
    """All V2 indexes are created by init_db()."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
        (index_name,),
    ).fetchone()
    assert row is not None, f"Index '{index_name}' not found after init_db()"


# ── Schema column tests ─────────────────────────


def test_quarantine_columns(conn):
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(quarantine)")}
    expected = {"id", "project_id", "raw_data", "failure_reason", "severity", "status", "resolved_at", "created_at"}
    assert expected.issubset(cols), f"Missing columns: {expected - cols}"


def test_project_history_columns(conn):
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(project_history)")}
    expected = {"id", "project_id", "run_id", "score", "label", "stage", "weight_version", "snapshot", "created_at"}
    assert expected.issubset(cols)


def test_audit_logs_columns(conn):
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(audit_logs)")}
    expected = {"id", "action", "user", "detail", "ip", "created_at"}
    assert expected.issubset(cols)


def test_narratives_columns(conn):
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(narratives)")}
    expected = {"sector", "aliases", "base_heat", "stage", "momentum", "updated_at"}
    assert expected.issubset(cols)


def test_prompt_versions_columns(conn):
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(prompt_versions)")}
    expected = {"id", "agent_name", "prompt_key", "version", "content", "is_default", "created_by", "created_at"}
    assert expected.issubset(cols)


# ── AuditLogRepository tests ────────────────────


class TestAuditLogRepository:
    def test_insert_and_query(self, conn):
        repo = AuditLogRepository(conn)
        log_id = repo.insert(action="run", user="admin", detail="POST /run", ip="127.0.0.1")
        assert log_id > 0

        logs = repo.query(action="run")
        assert len(logs) == 1
        assert logs[0]["action"] == "run"
        assert logs[0]["user"] == "admin"
        assert logs[0]["detail"] == "POST /run"
        assert logs[0]["ip"] == "127.0.0.1"

    def test_query_by_user(self, conn):
        repo = AuditLogRepository(conn)
        repo.insert(action="run", user="admin")
        repo.insert(action="re-score", user="analyst")
        repo.insert(action="run", user="analyst")

        logs = repo.query(user="analyst")
        assert len(logs) == 2
        assert all(log["user"] == "analyst" for log in logs)

    def test_query_all(self, conn):
        repo = AuditLogRepository(conn)
        repo.insert(action="run", user="admin")
        repo.insert(action="config_change", user="admin")

        logs = repo.query()
        assert len(logs) == 2


# ── MetricsRepository tests ─────────────────────


class TestMetricsRepository:
    def test_insert_and_query_by_run(self, conn):
        repo = MetricsRepository(conn)
        repo.insert(run_id="run-1", metric_name="completeness", metric_value=0.95)
        repo.insert(run_id="run-1", metric_name="timeliness", metric_value=0.80)
        repo.insert(run_id="run-2", metric_name="completeness", metric_value=0.90)

        metrics = repo.query_by_run("run-1")
        assert len(metrics) == 2
        names = {m["metric_name"] for m in metrics}
        assert {"completeness", "timeliness"} == names

    def test_query_by_name(self, conn):
        repo = MetricsRepository(conn)
        repo.insert(run_id="run-1", metric_name="completeness", metric_value=0.95)
        repo.insert(run_id="run-2", metric_name="completeness", metric_value=0.90)

        metrics = repo.query_by_name("completeness")
        assert len(metrics) == 2

    def test_detail_json(self, conn):
        repo = MetricsRepository(conn)
        detail = json.dumps({"tables_checked": 5, "nulls_found": 2})
        repo.insert(run_id="run-1", metric_name="completeness", metric_value=0.95, detail=detail)

        metrics = repo.query_by_run("run-1")
        assert json.loads(metrics[0]["detail"])["tables_checked"] == 5


# ── LLMEvalRepository tests ─────────────────────


class TestLLMEvalRepository:
    def test_insert_and_get_latest(self, conn):
        repo = LLMEvalRepository(conn)
        repo.insert(
            eval_date="2026-01-01",
            sample_count=100,
            rule_accuracy=0.75,
            llm_accuracy=0.82,
            llm_cost_usd=12.50,
            decision="keep_llm",
        )
        repo.insert(
            eval_date="2026-02-01",
            sample_count=150,
            rule_accuracy=0.78,
            llm_accuracy=0.85,
            llm_cost_usd=15.00,
            decision="keep_llm",
        )

        latest = repo.get_latest()
        assert latest is not None
        assert latest["eval_date"] == "2026-02-01"
        assert latest["llm_accuracy"] == 0.85

    def test_list_all(self, conn):
        repo = LLMEvalRepository(conn)
        repo.insert(
            eval_date="2026-01-01",
            sample_count=100,
            rule_accuracy=0.75,
            llm_accuracy=0.82,
            llm_cost_usd=12.50,
            decision="keep_llm",
        )

        all_evals = repo.list_all()
        assert len(all_evals) == 1


# ── QuarantineRepository tests ──────────────────


class TestQuarantineRepository:
    def test_insert_and_query_pending(self, conn):
        repo = QuarantineRepository(conn)
        repo.insert(
            raw_data=json.dumps({"name": "Bad Project"}),
            failure_reason="schema_violation",
        )
        pending = repo.query_pending()
        assert len(pending) == 1
        assert pending[0]["status"] == "pending"
        assert pending[0]["failure_reason"] == "schema_violation"

    def test_resolve(self, conn):
        repo = QuarantineRepository(conn)
        qid = repo.insert(
            raw_data="{}",
            failure_reason="business_rule_violation",
        )
        assert repo.resolve(qid) is True

        pending = repo.query_pending()
        assert len(pending) == 0

    def test_resolve_already_resolved(self, conn):
        repo = QuarantineRepository(conn)
        qid = repo.insert(raw_data="{}", failure_reason="dedup_conflict")
        assert repo.resolve(qid) is True
        # Second resolve should fail (status != 'pending')
        assert repo.resolve(qid) is False

    def test_query_by_reason(self, conn):
        repo = QuarantineRepository(conn)
        repo.insert(raw_data="{}", failure_reason="schema_violation")
        repo.insert(raw_data="{}", failure_reason="dedup_conflict")
        repo.insert(raw_data="{}", failure_reason="schema_violation")

        results = repo.query_by_reason("schema_violation")
        assert len(results) == 2


# ── ProjectHistoryRepository tests ──────────────


class TestProjectHistoryRepository:
    def test_insert_and_query_by_project(self, conn):
        repo = ProjectHistoryRepository(conn)
        repo.insert(
            project_id="proj-1",
            run_id="run-1",
            score=75,
            label="FARM",
            stage="testnet",
            weight_version="v1.2",
            snapshot=json.dumps({"score": 75}),
        )
        repo.insert(
            project_id="proj-1",
            run_id="run-2",
            score=80,
            label="FARM",
            stage="mainnet",
            weight_version="v1.3",
            snapshot=json.dumps({"score": 80}),
        )

        history = repo.query_by_project("proj-1")
        assert len(history) == 2
        # Latest first (DESC)
        assert history[0]["run_id"] == "run-2"
        assert history[0]["score"] == 80

    def test_query_by_run(self, conn):
        repo = ProjectHistoryRepository(conn)
        repo.insert(
            project_id="proj-1",
            run_id="run-1",
            snapshot=json.dumps({}),
        )
        repo.insert(
            project_id="proj-2",
            run_id="run-1",
            snapshot=json.dumps({}),
        )

        history = repo.query_by_run("run-1")
        assert len(history) == 2


# ── NarrativesRepository tests ──────────────────


class TestNarrativesRepository:
    def test_upsert_and_get(self, conn):
        repo = NarrativesRepository(conn)
        repo.upsert(
            sector="DeFi",
            aliases=["defi", "decentralized_finance"],
            base_heat=0.8,
            stage="growth",
            momentum=1.2,
        )

        narrative = repo.get("DeFi")
        assert narrative is not None
        assert narrative["base_heat"] == 0.8
        assert narrative["stage"] == "growth"
        aliases = json.loads(narrative["aliases"])
        assert "defi" in aliases

    def test_upsert_update_existing(self, conn):
        repo = NarrativesRepository(conn)
        repo.upsert(sector="ZK", base_heat=0.7, stage="early")
        repo.upsert(sector="ZK", base_heat=0.9, stage="growth")

        narrative = repo.get("ZK")
        assert narrative["base_heat"] == 0.9
        assert narrative["stage"] == "growth"

    def test_list_all(self, conn):
        repo = NarrativesRepository(conn)
        repo.upsert(sector="DeFi", base_heat=0.8)
        repo.upsert(sector="ZK", base_heat=0.7)
        repo.upsert(sector="Bridge", base_heat=0.6)

        all_narratives = repo.list_all()
        assert len(all_narratives) == 3

    def test_delete(self, conn):
        repo = NarrativesRepository(conn)
        repo.upsert(sector="Gaming", base_heat=0.5)
        assert repo.delete("Gaming") is True
        assert repo.get("Gaming") is None
        assert repo.delete("Gaming") is False


# ── DedupKeysRepository tests ───────────────────


class TestDedupKeysRepository:
    def test_upsert_and_lookup(self, conn):
        repo = DedupKeysRepository(conn)
        repo.upsert(
            dedup_key="nova-l2::L2",
            project_id="proj-001",
            name_raw="Nova L2",
            sector_raw="L2",
        )

        result = repo.lookup("nova-l2::L2")
        assert result is not None
        assert result["project_id"] == "proj-001"
        assert result["name_raw"] == "Nova L2"

    def test_upsert_conflict_updates(self, conn):
        repo = DedupKeysRepository(conn)
        repo.upsert(
            dedup_key="scroll::ZK",
            project_id="proj-old",
            name_raw="Scroll",
            sector_raw="ZK",
        )
        repo.upsert(
            dedup_key="scroll::ZK",
            project_id="proj-new",
            name_raw="Scroll zkEVM",
            sector_raw="ZK",
        )

        result = repo.lookup("scroll::ZK")
        assert result["project_id"] == "proj-new"
        assert result["name_raw"] == "Scroll zkEVM"

    def test_query_by_project(self, conn):
        repo = DedupKeysRepository(conn)
        repo.upsert(dedup_key="k1::S1", project_id="proj-1", name_raw="A", sector_raw="S1")
        repo.upsert(dedup_key="k2::S2", project_id="proj-1", name_raw="B", sector_raw="S2")
        repo.upsert(dedup_key="k3::S3", project_id="proj-2", name_raw="C", sector_raw="S3")

        results = repo.query_by_project("proj-1")
        assert len(results) == 2


# ── PromptVersionsRepository tests ──────────────


class TestPromptVersionsRepository:
    def test_insert_and_get_version(self, conn):
        repo = PromptVersionsRepository(conn)
        repo.insert(
            agent_name="narrative",
            prompt_key="system_prompt",
            version="v1.0",
            content="You are a narrative analyst.",
            created_by="admin",
        )

        result = repo.get_version("narrative", "v1.0")
        assert result is not None
        assert result["content"] == "You are a narrative analyst."
        assert result["is_default"] == 0

    def test_insert_with_default(self, conn):
        repo = PromptVersionsRepository(conn)
        repo.insert(
            agent_name="narrative",
            prompt_key="system_prompt",
            version="v1.0",
            content="v1 content",
            created_by="admin",
            is_default=True,
        )

        default = repo.get_default("narrative", "system_prompt")
        assert default is not None
        assert default["version"] == "v1.0"

    def test_set_default_clears_others(self, conn):
        repo = PromptVersionsRepository(conn)
        repo.insert(
            agent_name="scorer",
            prompt_key="prompt",
            version="v1",
            content="c1",
            created_by="admin",
            is_default=True,
        )
        id2 = repo.insert(
            agent_name="scorer",
            prompt_key="prompt",
            version="v2",
            content="c2",
            created_by="admin",
        )

        # Before: v1 is default
        default = repo.get_default("scorer", "prompt")
        assert default["version"] == "v1"

        # Switch default to v2
        assert repo.set_default(id2) is True

        # After: v2 is default, v1 is not
        default = repo.get_default("scorer", "prompt")
        assert default["version"] == "v2"

    def test_list_by_agent(self, conn):
        repo = PromptVersionsRepository(conn)
        repo.insert(
            agent_name="narrative",
            prompt_key="p1",
            version="v1",
            content="c1",
            created_by="admin",
        )
        repo.insert(
            agent_name="narrative",
            prompt_key="p2",
            version="v2",
            content="c2",
            created_by="admin",
        )
        repo.insert(
            agent_name="scorer",
            prompt_key="p1",
            version="v1",
            content="c3",
            created_by="admin",
        )

        narrative_prompts = repo.list_by_agent("narrative")
        assert len(narrative_prompts) == 2

    def test_get_default_none_when_not_set(self, conn):
        repo = PromptVersionsRepository(conn)
        result = repo.get_default("nonexistent", "prompt")
        assert result is None
