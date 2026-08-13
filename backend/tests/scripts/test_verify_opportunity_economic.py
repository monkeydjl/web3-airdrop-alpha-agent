"""Network-free tests for scripts/verify_opportunity_economic.py (Task 9)."""

from __future__ import annotations

import ast
import importlib.util
import io
import json
import socket
import sys
from contextlib import redirect_stdout, suppress
from datetime import UTC
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_opportunity_economic.py"
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "opportunity_economic"
BACKEND = Path(__file__).resolve().parents[2]

NETWORK_DENYLIST = frozenset(
    {
        "requests",
        "httpx",
        "aiohttp",
        "urllib.request",
        "urllib3",
    }
)

CANARY_SNIPPETS = (
    "CANARY_DL_API_KEY_TASK9_SYNTH_NEVER_LEAK",
    "CANARY_DL_TOKEN_TASK9_SYNTH_NEVER_LEAK",
    "CANARY_CG_API_KEY_TASK9_SYNTH_NEVER_LEAK",
    "CANARY_CG_TOKEN_TASK9_SYNTH_NEVER_LEAK",
    "CANARY_CR_API_KEY_TASK9_SYNTH_NEVER_LEAK",
    "CANARY_CR_TOKEN_TASK9_SYNTH_NEVER_LEAK",
)

EXPECTED_CASE_IDS = (
    "17.1.01",
    "17.1.02",
    "17.1.03",
    "17.1.04",
    "17.1.05",
    "17.1.06",
    "17.1.07",
    "17.1.08",
    "17.1.09",
    "17.1.10",
    "17.1.11",
    "17.1.12",
    "17.1.13",
    "17.1.14",
    "17.1.15",
    "17.1.16",
    "17.1.17",
    "17.1.18",
    "17.1.19",
    "17.1.20",
    "17.1.21",
    "17.1.22",
    "17.1.23",
    "17.1.24",
    "17.1.25",
    "17.1.26",
)

SECTION_17_2_ASSERTIONS = (
    "hash_framing_array_utf8_compact_lowercase",
    "provider_native_whitelist_strips_unknown_and_canary",
    "credentials_never_in_payload_hash_stdout",
    "missing_fields_not_filled_with_zero",
    "coingecko_cryptorank_same_independence_group_no_double_count",
    "mode_closed_set",
    "dedup_key_and_raw_id_preserved",
    "value_type_closed_set_and_specialized_types",
)


def _load_verifier():
    spec = importlib.util.spec_from_file_location("verify_opportunity_economic", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def verifier():
    return _load_verifier()


def _collect_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
            found.add(node.module)
    return found


def _assert_no_canaries(text: str) -> None:
    for canary in CANARY_SNIPPETS:
        assert canary not in text


def test_case_ids_frozen_exact_26_tuple(verifier) -> None:
    assert verifier.CASE_IDS == EXPECTED_CASE_IDS
    assert len(verifier.CASE_IDS) == 26
    assert len(set(verifier.CASE_IDS)) == 26


def test_run_verification_keyset_exact_case_ids(verifier) -> None:
    results = verifier.run_verification()
    assert set(results.keys()) == set(EXPECTED_CASE_IDS)
    assert len(results) == 26
    assert all(isinstance(v, bool) for v in results.values())


@pytest.mark.parametrize("case_id", EXPECTED_CASE_IDS)
def test_section_17_1_matrix_case_passes(verifier, case_id: str) -> None:
    results = verifier.run_verification()
    assert results[case_id] is True, f"case {case_id} failed"


def test_case_17_1_01_cross_utc_day_same_payload_two_history_rows(verifier) -> None:
    """Cross-UTC-day same payload must yield two distinct snapshot_ids via Writer."""
    results = verifier.run_verification()
    assert results["17.1.01"] is True
    # Independent production path: same payload hash, different run_id → different ids.
    from app.opportunity.economic_models import build_snapshot_id, payload_sha256
    from app.opportunity.economic_normalizers import canonical_provider_payload

    fixture = json.loads((FIXTURE_DIR / "defillama.json").read_text(encoding="utf-8"))
    raw = fixture["samples"]["happy"]
    raw_id = str(fixture["discovery"]["raw_id"])
    digest = payload_sha256(canonical_provider_payload("defillama", raw))
    day1 = build_snapshot_id(
        run_id="daily:2026-07-22:defillama",
        source_id="defillama",
        provider_entity_id=raw_id,
        payload_sha256_hex=digest,
    )
    day2 = build_snapshot_id(
        run_id="daily:2026-07-23:defillama",
        source_id="defillama",
        provider_entity_id=raw_id,
        payload_sha256_hex=digest,
    )
    assert day1 != day2
    assert len(day1) == 64 and day1 == day1.lower()
    assert verifier._case_17_1_01() is True


def test_case_17_1_02_same_run_duplicate_writer_no_row_growth(verifier) -> None:
    """Same-run Writer reprocess: zero row growth + production duplicate metric sample."""
    results = verifier.run_verification()
    assert results["17.1.02"] is True
    from app.metrics import OPPORTUNITY_ECONOMIC_SNAPSHOTS, metric_sample_value

    # Sample helper (not bare labels) must be the production verification surface.
    before = metric_sample_value(OPPORTUNITY_ECONOMIC_SNAPSHOTS, source="defillama", result="duplicate")
    assert verifier._case_17_1_02() is True
    after = metric_sample_value(OPPORTUNITY_ECONOMIC_SNAPSHOTS, source="defillama", result="duplicate")
    assert after - before == 1.0


def test_case_17_1_03_post_link_replay_zero_then_stable_evidence(verifier) -> None:
    """Orphan raw project_id → 0 Evidence; after projects row, stable evidence_id + no growth."""
    results = verifier.run_verification()
    assert results["17.1.03"] is True
    assert verifier._case_17_1_03() is True

    import sqlite3
    from datetime import datetime

    from app.collectors.base import CollectorResult
    from app.db import DbConnection, init_db
    from app.opportunity.economic_evidence import replay_economic_snapshots_for_project
    from app.opportunity.economic_models import build_evidence_id
    from app.opportunity.economic_repository import EconomicSnapshotRepository
    from app.opportunity.economic_writer import EconomicSnapshotWriter
    from app.opportunity.repository import OpportunityRepository

    observed = datetime(2026, 7, 22, 12, 0, 0, tzinfo=UTC)
    raw = sqlite3.connect(":memory:")
    raw.row_factory = sqlite3.Row
    conn = DbConnection(raw, kind="sqlite")
    init_db(conn)
    snap_repo = EconomicSnapshotRepository(conn)
    evid_repo = OpportunityRepository(conn)
    try:
        fixture = json.loads((FIXTURE_DIR / "defillama.json").read_text(encoding="utf-8"))
        meta = fixture["discovery"]
        item = verifier._make_discovery(
            source_id="defillama",
            raw_id=str(meta["raw_id"]) + "-test03",
            name=str(meta["name"]) + " T03",
            url=str(meta["url"]),
            raw_data=fixture["samples"]["happy"],
        )
        project_id = "proj-test-03-indep"
        writer = EconomicSnapshotWriter(snap_repo, now_factory=lambda: observed)
        result = CollectorResult(source_id="defillama", items=[item])
        result.finished_at = observed
        summary = writer.process(result, run_id="daily:2026-07-22:defillama", enabled=True)
        assert summary.snapshots_inserted == 1
        snapshot_id = summary.observations[0].snapshot_id
        verifier._seed_raw_project(
            conn,
            raw_id="raw-test-03",
            source_id="defillama",
            dedup_key=item.dedup_key,
            project_id=project_id,
        )
        assert snap_repo.find_linked_project_id("defillama", item.dedup_key) is None
        orphan = replay_economic_snapshots_for_project(project_id, conn=conn, enabled=True)
        assert orphan is not None
        assert orphan.emitted == 0
        assert orphan.unlinked >= 1
        assert raw.execute("SELECT COUNT(*) FROM opportunity_evidence").fetchone()[0] == 0

        verifier._seed_project(conn, project_id, name=str(meta["name"]))
        assert snap_repo.find_linked_project_id("defillama", item.dedup_key) == project_id
        linked = replay_economic_snapshots_for_project(project_id, conn=conn, enabled=True)
        assert linked is not None and linked.emitted >= 1
        rows = evid_repo.list_evidence(project_id)
        assert rows
        tvl = next(r for r in rows if r.factor_key == "tvl_usd")
        assert tvl.evidence_id == build_evidence_id(
            snapshot_id=snapshot_id, project_id=project_id, factor_key="tvl_usd"
        )
        count = len(rows)
        again = replay_economic_snapshots_for_project(project_id, conn=conn, enabled=True)
        assert again is not None and again.emitted == 0 and again.duplicates >= 1
        assert len(evid_repo.list_evidence(project_id)) == count
    finally:
        evid_repo.close()
        snap_repo.close()
        conn.close()


def test_case_17_1_04_unlinked_no_fuzzy_branch(verifier) -> None:
    """Same symbol without projects row stays unlinked; production SQL has no fuzzy branch."""
    results = verifier.run_verification()
    assert results["17.1.04"] is True
    assert verifier._case_17_1_04() is True

    import inspect
    import re

    from app.opportunity.economic_repository import EconomicSnapshotRepository

    source = inspect.getsource(EconomicSnapshotRepository.find_linked_project_id)
    sql_match = re.search(r'"""\s*(SELECT[\s\S]*?)\s*"""', source, flags=re.IGNORECASE)
    assert sql_match is not None
    sql_body = " ".join(sql_match.group(1).split()).lower()
    assert "inner join projects" in sql_body
    assert "rp.source_id = ?" in sql_body
    assert "rp.dedup_key = ?" in sql_body
    for banned in (" like ", "symbol", "p.name", "slug", "fuzzy", "similarity"):
        assert banned not in sql_body
    assert "nosymbol/name/slug/fuzzy" in re.sub(r"\s+", "", source.lower())

    # Runtime: orphan project_id + same display name elsewhere still unlinked.
    import sqlite3
    from datetime import datetime

    from app.collectors.base import CollectorResult
    from app.db import DbConnection, init_db
    from app.opportunity.economic_evidence import EconomicEvidenceEmitter
    from app.opportunity.economic_repository import EconomicSnapshotRepository
    from app.opportunity.economic_writer import EconomicSnapshotWriter
    from app.opportunity.repository import OpportunityRepository

    observed = datetime(2026, 7, 22, 12, 0, 0, tzinfo=UTC)
    raw = sqlite3.connect(":memory:")
    raw.row_factory = sqlite3.Row
    conn = DbConnection(raw, kind="sqlite")
    init_db(conn)
    snap_repo = EconomicSnapshotRepository(conn)
    evid_repo = OpportunityRepository(conn)
    try:
        fixture = json.loads((FIXTURE_DIR / "defillama.json").read_text(encoding="utf-8"))
        meta = fixture["discovery"]
        shared = str(meta["name"]) + " SameSymbol"
        item = verifier._make_discovery(
            source_id="defillama",
            raw_id=str(meta["raw_id"]) + "-test04",
            name=shared,
            url=str(meta["url"]),
            raw_data=fixture["samples"]["happy"],
        )
        writer = EconomicSnapshotWriter(snap_repo, now_factory=lambda: observed)
        result = CollectorResult(source_id="defillama", items=[item])
        result.finished_at = observed
        summary = writer.process(result, run_id="daily:2026-07-22:defillama", enabled=True)
        assert summary.snapshots_inserted == 1
        verifier._seed_project(conn, "proj-name-only-04", name=shared)
        verifier._seed_raw_project(
            conn,
            raw_id="raw-test-04",
            source_id="defillama",
            dedup_key=item.dedup_key,
            project_id="proj-missing-auth-04",
        )
        assert snap_repo.find_linked_project_id("defillama", item.dedup_key) is None
        emit = EconomicEvidenceEmitter(conn, snap_repo, evid_repo).emit(summary.observations[0], enabled=True)
        assert emit.unlinked == 1 and emit.emitted == 0
        assert raw.execute("SELECT COUNT(*) FROM opportunity_evidence").fetchone()[0] == 0
    finally:
        evid_repo.close()
        snap_repo.close()
        conn.close()


def test_case_17_1_05_two_day_price_resolver_latest_non_expired(verifier) -> None:
    """Two daily price_usd rows: latest non-expired wins; conflicted is False."""
    results = verifier.run_verification()
    assert results["17.1.05"] is True
    assert verifier._case_17_1_05() is True

    import sqlite3
    from datetime import datetime, timedelta

    from app.db import DbConnection, init_db
    from app.opportunity.economic_models import build_evidence_id
    from app.opportunity.economic_repository import EconomicSnapshotRepository
    from app.opportunity.economic_resolver import EconomicResolver
    from app.opportunity.models import EvidenceRecord

    now = datetime(2026, 7, 23, 13, 0, tzinfo=UTC)
    day1 = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
    day2 = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    expires = now + timedelta(hours=48)
    project_id = "proj-price-test-05"
    snap1 = "a" * 64
    snap2 = "b" * 64
    raw = sqlite3.connect(":memory:")
    raw.row_factory = sqlite3.Row
    conn = DbConnection(raw, kind="sqlite")
    init_db(conn)
    snap_repo = EconomicSnapshotRepository(conn)
    try:
        # Seed snapshot source map rows so provider ranking can resolve coingecko.
        from app.opportunity.economic_models import SCHEMA_VERSION, EconomicSnapshotRow

        for sid, run in ((snap1, "daily:2026-07-22:coingecko"), (snap2, "daily:2026-07-23:coingecko")):
            snap_repo.insert_if_absent(
                EconomicSnapshotRow(
                    snapshot_id=sid,
                    schema_version=SCHEMA_VERSION,
                    run_id=run,
                    source_id="coingecko",
                    dedup_key="coin:price-test-05",
                    provider_entity_id="coin-price-test-05",
                    payload_sha256="c" * 64,
                    payload_json={"current_price": 1.0},
                    source_url="https://api.coingecko.com/api/v3/coins/markets",
                    collected_at=day1 if sid == snap1 else day2,
                )
            )
        records = [
            EvidenceRecord(
                evidence_id=build_evidence_id(snapshot_id=snap1, project_id=project_id, factor_key="price_usd"),
                project_id=project_id,
                factor_key="price_usd",
                value="1.10000000",
                value_type="string",
                observation_type="observed",
                source_url="https://api.coingecko.com/api/v3/coins/markets",
                source_type="public_market_data",
                source_grade="C",
                observed_at=day1,
                effective_at=day1,
                expires_at=expires,
                verification_status="verified",
                independence_group="market-aggregators",
                raw_snapshot_ref=f"econ-snapshot:{snap1}",
            ),
            EvidenceRecord(
                evidence_id=build_evidence_id(snapshot_id=snap2, project_id=project_id, factor_key="price_usd"),
                project_id=project_id,
                factor_key="price_usd",
                value="2.50000000",
                value_type="string",
                observation_type="observed",
                source_url="https://api.coingecko.com/api/v3/coins/markets",
                source_type="public_market_data",
                source_grade="C",
                observed_at=day2,
                effective_at=day2,
                expires_at=expires,
                verification_status="verified",
                independence_group="market-aggregators",
                raw_snapshot_ref=f"econ-snapshot:{snap2}",
            ),
        ]
        projection = EconomicResolver(snap_repo).resolve(project_id, records, now=now)
        factor = projection.factors["price_usd"]
        assert factor.conflicted is False
        assert factor.value == "2.50000000"
        assert factor.evidence_id == build_evidence_id(snapshot_id=snap2, project_id=project_id, factor_key="price_usd")
        assert factor.value != "1.10000000"
    finally:
        snap_repo.close()
        conn.close()


def test_case_17_1_06_proxy_only_not_direct_available(verifier) -> None:
    """Proxy-only evidence + direct_available=False → PROXY_ONLY, never DIRECT_AVAILABLE."""
    results = verifier.run_verification()
    assert results["17.1.06"] is True
    assert verifier._case_17_1_06() is True

    import sqlite3
    from datetime import datetime, timedelta

    from app.db import DbConnection, init_db
    from app.opportunity.economic_models import SCHEMA_VERSION, EconomicSnapshotRow
    from app.opportunity.economic_repository import EconomicSnapshotRepository
    from app.opportunity.economic_resolver import project_economics_data
    from app.opportunity.models import EvidenceRecord
    from app.opportunity.repository import OpportunityRepository

    now = datetime(2026, 7, 22, 13, 0, tzinfo=UTC)
    collected = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
    project_id = "proj-proxy-test-06"
    snap_id = "d" * 64
    raw = sqlite3.connect(":memory:")
    raw.row_factory = sqlite3.Row
    conn = DbConnection(raw, kind="sqlite")
    init_db(conn)
    snap_repo = EconomicSnapshotRepository(conn)
    evid_repo = OpportunityRepository(conn)
    try:
        snap_repo.insert_if_absent(
            EconomicSnapshotRow(
                snapshot_id=snap_id,
                schema_version=SCHEMA_VERSION,
                run_id="daily:2026-07-22:defillama",
                source_id="defillama",
                dedup_key="protocol:proxy-test-06",
                provider_entity_id="proxy-test-06",
                payload_sha256="e" * 64,
                payload_json={"tvl": 1},
                source_url="https://defillama.com/protocol/x",
                collected_at=collected,
            )
        )
        evid_repo.add_economic_evidence_if_absent(
            EvidenceRecord(
                evidence_id="proxy-tvl-06",
                project_id=project_id,
                factor_key="tvl_usd",
                value="1000.00000000",
                value_type="string",
                observation_type="observed",
                source_url="https://defillama.com/protocol/x",
                source_type="public_aggregator",
                source_grade="C",
                observed_at=collected,
                effective_at=collected,
                expires_at=collected + timedelta(hours=48),
                verification_status="verified",
                independence_group="defillama-protocols",
                raw_snapshot_ref=f"econ-snapshot:{snap_id}",
            )
        )
        direct_available = False
        projection = project_economics_data(
            project_id,
            evidence_repository=evid_repo,
            snapshot_repository=snap_repo,
            direct_available=direct_available,
            now=now,
            enabled=True,
        )
        assert projection is not None
        assert direct_available is False
        assert projection.economics_data_mode == "PROXY_ONLY"
        assert projection.economics_data_mode != "DIRECT_AVAILABLE"
        assert projection.factors["tvl_usd"].value == "1000.00000000"
        upgraded = project_economics_data(
            project_id,
            evidence_repository=evid_repo,
            snapshot_repository=snap_repo,
            direct_available=True,
            now=now,
            enabled=True,
        )
        assert upgraded is not None
        assert upgraded.economics_data_mode == "DIRECT_AVAILABLE"
        assert upgraded.economics_data_mode != projection.economics_data_mode
    finally:
        evid_repo.close()
        snap_repo.close()
        conn.close()


def test_case_17_1_07_manual_direct_farm_not_downgraded(verifier) -> None:
    """Manual direct FARM stays FARM when economic projection/replay flags are closed."""
    results = verifier.run_verification()
    assert results["17.1.07"] is True
    assert verifier._case_17_1_07() is True

    from datetime import datetime
    from unittest.mock import MagicMock

    from app.opportunity.decision import decide
    from app.opportunity.economic_resolver import project_economics_data
    from app.opportunity.economics import calculate_economics
    from app.opportunity.models import (
        ConfidenceSet,
        DecisionStatus,
        MoneyRange,
        OpportunityInputs,
        ProbabilityRange,
        RiskLevel,
        RiskSet,
    )
    from app.opportunity.profile import DEFAULT_PROFILE

    now = datetime(2026, 7, 22, 12, 0, 0, tzinfo=UTC)
    inputs = OpportunityInputs(
        project_id="proj-farm-test-07",
        conditional_reward_usd=MoneyRange(low=80, base=160, high=400),
        hard_cost_usd=MoneyRange(low=5, base=8, high=10),
        capital_at_risk_usd=MoneyRange(low=0, base=0, high=0),
        expected_capital_loss_usd=MoneyRange(low=0, base=0, high=1),
        liquidity_cost_usd=MoneyRange(low=0, base=0, high=1),
        total_time_hours=MoneyRange(low=1, base=2, high=3),
        weekly_maintenance_hours=1.5,
        participation_open=True,
        task_path_known=True,
        authorization_exit_known=True,
        distribution_catalyst_3_6m=True,
        project_active=True,
        opportunity_timing="open",
        profile_fit="fit",
        integrity_blocked=False,
        safety_blocked=False,
        project_quality=70,
        project_failure_risk=RiskLevel.LOW,
        capital_security_risk=RiskLevel.LOW,
        official_multiwallet_policy="allowed",
        official_airdrop_evidence_count_a=1,
        confidence=ConfidenceSet(
            event=0.80,
            eligibility=0.75,
            reward=0.70,
            cost=0.80,
            risk=0.80,
            quality=0.75,
            overall=0.75,
        ),
        risks=RiskSet(
            capital_security=RiskLevel.LOW,
            eligibility=RiskLevel.LOW,
            project_failure=RiskLevel.LOW,
            reward_dilution=RiskLevel.MEDIUM,
            liquidity=RiskLevel.LOW,
        ),
    )
    event = ProbabilityRange(low=0.60, base=0.70, high=0.80)
    eligibility = ProbabilityRange(low=0.55, base=0.70, high=0.85)
    survival = ProbabilityRange(low=0.70, base=0.80, high=0.90)
    reward_probability = ProbabilityRange(low=0.25, base=0.39, high=0.61)
    economics = calculate_economics(
        reward_probability=reward_probability,
        conditional_reward=inputs.conditional_reward_usd,
        hard_cost=inputs.hard_cost_usd,
        capital_loss=inputs.expected_capital_loss_usd,
        liquidity_cost=inputs.liquidity_cost_usd,
        total_time_hours=inputs.total_time_hours,
    )
    before = decide(
        inputs=inputs,
        event=event,
        eligibility=eligibility,
        survival=survival,
        reward_probability=reward_probability,
        economics=economics,
        profile=DEFAULT_PROFILE,
        now=now,
    )
    assert before.public_label == "FARM"
    assert before.status == DecisionStatus.ACTIONABLE

    # Closed economic loop: project_economics_data must short-circuit with zero repo I/O.
    evidence_repo = MagicMock()
    snapshot_repo = MagicMock()
    closed = project_economics_data(
        "proj-farm-test-07",
        evidence_repository=evidence_repo,
        snapshot_repository=snapshot_repo,
        direct_available=True,
        now=now,
        enabled=False,
    )
    assert closed is None
    evidence_repo.list_evidence.assert_not_called()
    snapshot_repo.source_ids_by_snapshot_id.assert_not_called()

    after = decide(
        inputs=inputs,
        event=event,
        eligibility=eligibility,
        survival=survival,
        reward_probability=reward_probability,
        economics=economics,
        profile=DEFAULT_PROFILE,
        now=now,
    )
    assert after.public_label == "FARM"
    assert after.status == DecisionStatus.ACTIONABLE
    assert after.public_label == before.public_label
    assert after.status == before.status


def test_case_17_1_08_six_flags_default_false_canonical_bytes(verifier) -> None:
    """Six OPPORTUNITY_ECONOMIC flags default false; closed loop keeps baseline bytes."""
    results = verifier.run_verification()
    assert results["17.1.08"] is True
    assert verifier._case_17_1_08() is True

    from unittest.mock import MagicMock

    from app.config import Settings
    from app.opportunity.economic_integration import (
        economic_source_enabled,
        process_persisted_collection,
    )
    from app.opportunity.economic_models import canonical_json_bytes
    from app.opportunity.workflow import build_workflow_projection

    flag_names = verifier._ECONOMIC_FLAG_NAMES
    assert len(flag_names) == 6
    for name in flag_names:
        assert Settings.model_fields[name].default is False

    settings = Settings(_env_file=None)
    for name in flag_names:
        assert getattr(settings, name) is False
    for source_id in ("defillama", "coingecko", "cryptorank"):
        assert economic_source_enabled(source_id, settings) is False

    writer = MagicMock()
    emitter = MagicMock()
    from app.collectors.base import CollectorResult, RawDiscovery

    item = RawDiscovery(
        source_id="defillama",
        raw_id="raw-flags-test-08",
        name="Flags Test 08",
        url="https://example.invalid/flags-08",
        sector="DeFi",
        stage="mainnet",
        raw_data={
            "tvl": 1.0,
            "change_7d": 0.01,
            "change_7d_unit": "ratio",
            "chains": ["Ethereum"],
            "no_token_yet": True,
        },
    )
    result = CollectorResult(source_id="defillama", items=[item])
    result.finished_at = __import__("datetime").datetime(2026, 7, 22, 12, 0, tzinfo=__import__("datetime").timezone.utc)
    out = process_persisted_collection(
        result,
        run_id="daily:2026-07-22:defillama",
        writer=writer,
        emitter=emitter,
        settings_obj=settings,
    )
    assert out is None
    writer.process.assert_not_called()
    emitter.emit.assert_not_called()

    decision, decision_bytes, project_id = verifier._farm_decision_bundle()
    assert decision.public_label == "FARM"
    assert decision_bytes == canonical_json_bytes(decision.model_dump(mode="json"))
    from app.opportunity.models import EconomicsResult, MoneyRange, SignedMoneyRange

    economics = EconomicsResult(
        gross_reward=MoneyRange(low=50, base=100, high=200),
        net_reward=SignedMoneyRange(low=20, base=60, high=180),
        reward_to_cost_ratio=8.0,
        decision_value=48.0,
        capital_efficiency=4.8,
        time_efficiency=24.0,
    )
    wf_bytes = verifier._workflow_canonical_bytes(
        project_id=project_id,
        public_label=decision.public_label,
        status=decision.status,
        economics=economics,
    )
    assert b"economic_proxy" not in wf_bytes
    assert b"economics_data_mode" not in wf_bytes
    pure = build_workflow_projection(
        project={
            "id": project_id,
            "name": "Flags Closed Protocol",
            "score": 88,
            "label": decision.public_label,
            "reason": ["legacy baseline"],
            "url": "https://example.invalid/flags-closed",
            "stage": "mainnet",
        },
        assessment=None,
        evidence=(),
        participation_tasks=(),
        interactions=(),
        now=__import__("datetime").datetime(2026, 7, 22, 12, 0, tzinfo=__import__("datetime").timezone.utc),
    )
    pure_bytes = canonical_json_bytes(pure.model_dump(mode="json"))
    assert b"economic_proxy" not in pure_bytes


def test_case_17_1_09_sqlite_and_recording_pg_ddl_idempotent(verifier) -> None:
    """SQLite + RecordingPostgresConnection share economic DDL; init_db idempotent."""
    results = verifier.run_verification()
    assert results["17.1.09"] is True
    assert verifier._case_17_1_09() is True

    import sqlite3

    from app.db import DbConnection, init_db

    # Independent SQLite contract: columns + dedup CHECK + indexes after double init.
    raw = sqlite3.connect(":memory:")
    raw.row_factory = sqlite3.Row
    conn = DbConnection(raw, kind="sqlite")
    try:
        init_db(conn)
        init_db(conn)
        cols = [row["name"] for row in raw.execute("PRAGMA table_info(opportunity_economic_snapshots)")]
        assert cols == list(verifier._EXPECTED_ECONOMIC_SNAPSHOT_COLUMNS)
        table_sql = raw.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='opportunity_economic_snapshots'"
        ).fetchone()[0]
        assert "check(length(trim(dedup_key))>0)" in verifier._compact_sql(table_sql)
        index_names = {
            row[0]
            for row in raw.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='opportunity_economic_snapshots'"
            )
            if row[0]
        }
        for name in verifier._EXPECTED_ECONOMIC_SNAPSHOT_INDEXES:
            assert name in index_names
    finally:
        conn.close()

    # Independent PG recording path uses the same convention as test_db_init.
    events: list = []
    pg = verifier.RecordingPostgresConnection(events)
    init_db(pg)
    init_db(pg)
    sqls = [e[1] for e in events if e[0] == "execute"]
    all_sql = " ".join(" ".join(str(s).split()) for s in sqls)
    assert "CREATE TABLE IF NOT EXISTS opportunity_economic_snapshots" in all_sql
    assert "check(length(trim(dedup_key))>0)" in verifier._compact_sql(all_sql)
    for index_name in verifier._EXPECTED_ECONOMIC_SNAPSHOT_INDEXES:
        assert f"CREATE INDEX IF NOT EXISTS {index_name}" in all_sql


def test_case_17_1_10_frozen_raw_replay_schema_hash_mode_no_double_count(verifier) -> None:
    """Stage A: production-backed frozen replay must pass; not a hardcoded True."""
    results = verifier.run_verification()
    assert results["17.1.10"] is True
    # Independently fail if production schema/mode/independence contracts drift.
    from typing import get_args

    from app.opportunity.economic_models import SCHEMA_VERSION, EconomicsDataMode
    from app.opportunity.economic_normalizers import normalize_provider_payload

    assert SCHEMA_VERSION == "opportunity-economic-snapshot-v1"
    assert set(get_args(EconomicsDataMode)) == {
        "PROXY_ONLY",
        "DIRECT_AVAILABLE",
        "UNKNOWN",
    }
    observed = __import__("datetime").datetime(2026, 7, 22, 12, 0, 0, tzinfo=__import__("datetime").timezone.utc)
    expires = __import__("datetime").datetime(2026, 7, 24, 12, 0, 0, tzinfo=__import__("datetime").timezone.utc)
    cg = normalize_provider_payload(
        source_id="coingecko",
        raw_data={
            "market_cap": 1,
            "current_price": 1,
            "price_change_percentage_24h": 5.0,
        },
        source_url="https://api.coingecko.com/api/v3/coins/markets",
        observed_at=observed,
        expires_at=expires,
    )
    cr = normalize_provider_payload(
        source_id="cryptorank",
        raw_data={
            "market_cap": 1,
            "price": 1,
            "percent_change_24h": 10.0,
            "percent_change_7d": 20.0,
        },
        source_url="https://cryptorank.io/price/x",
        observed_at=observed,
        expires_at=expires,
    )
    assert {f.independence_group for f in cg} == {"market-aggregators"}
    assert {f.independence_group for f in cr} == {"market-aggregators"}


@pytest.mark.parametrize("assertion_id", SECTION_17_2_ASSERTIONS)
def test_section_17_2_parametrized(verifier, assertion_id: str) -> None:
    """§17.2 hung off case 17.1.10; each assertion independently fail-able."""
    checks = verifier.section_17_2_checks()
    assert assertion_id in checks
    assert checks[assertion_id] is True
    # Flip-resistance: a wrong production closed-set would fail mode/value checks.
    if assertion_id == "mode_closed_set":
        from typing import get_args

        from app.opportunity.economic_models import EconomicsDataMode

        assert set(get_args(EconomicsDataMode)) == {
            "PROXY_ONLY",
            "DIRECT_AVAILABLE",
            "UNKNOWN",
        }
    if assertion_id == "value_type_closed_set_and_specialized_types":
        from typing import get_args

        from app.opportunity.economic_models import ValueType

        assert set(get_args(ValueType)) == {"bool", "number", "string", "json"}


def test_case_17_1_11_empty_dedup_key_schema_invalid_no_snapshot(verifier) -> None:
    results = verifier.run_verification()
    assert results["17.1.11"] is True
    # Direct production path: blank dedup_key is schema_invalid with zero rows.
    assert verifier._case_17_1_11() is True


def test_case_17_1_12_coingecko_percentage_only(verifier) -> None:
    assert verifier.run_verification()["17.1.12"] is True
    from datetime import datetime
    from decimal import Decimal

    from app.opportunity.economic_normalizers import (
        canonical_provider_payload,
        normalize_provider_payload,
        normalize_ratio_string,
    )

    fixture = json.loads((FIXTURE_DIR / "coingecko.json").read_text(encoding="utf-8"))
    raw = fixture["samples"]["happy"]
    observed = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
    expires = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
    factors = {
        f.factor_key: f
        for f in normalize_provider_payload(
            source_id="coingecko",
            raw_data=raw,
            source_url="https://api.coingecko.com/api/v3/coins/markets",
            observed_at=observed,
            expires_at=expires,
        )
    }
    expected = normalize_ratio_string(raw["price_change_percentage_24h"], divisor=Decimal("100"))
    assert factors["price_change_24h_ratio"].value == expected
    assert "price_change_24h" not in canonical_provider_payload("coingecko", raw)


def test_case_17_1_13_cryptorank_percentages_div_100(verifier) -> None:
    assert verifier.run_verification()["17.1.13"] is True
    from datetime import datetime
    from decimal import Decimal

    from app.opportunity.economic_normalizers import (
        normalize_provider_payload,
        normalize_ratio_string,
    )

    fixture = json.loads((FIXTURE_DIR / "cryptorank.json").read_text(encoding="utf-8"))
    raw = fixture["samples"]["happy"]
    observed = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
    expires = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
    factors = {
        f.factor_key: f
        for f in normalize_provider_payload(
            source_id="cryptorank",
            raw_data=raw,
            source_url="https://cryptorank.io/price/x",
            observed_at=observed,
            expires_at=expires,
        )
    }
    assert factors["price_change_24h_ratio"].value == normalize_ratio_string(
        raw["percent_change_24h"], divisor=Decimal("100")
    )
    assert factors["price_change_7d_ratio"].value == normalize_ratio_string(
        raw["percent_change_7d"], divisor=Decimal("100")
    )


def test_case_17_1_14_defillama_unit_contract(verifier) -> None:
    assert verifier.run_verification()["17.1.14"] is True
    from app.opportunity.economic_normalizers import (
        DEFILLAMA_CHANGE_7D_PROVIDER_UNIT,
        EconomicNormalizationError,
        canonical_provider_payload,
    )

    fixture = json.loads((FIXTURE_DIR / "defillama.json").read_text(encoding="utf-8"))
    assert fixture["unit_contract"]["accepted_change_7d_unit"] == (DEFILLAMA_CHANGE_7D_PROVIDER_UNIT)
    ok = canonical_provider_payload("defillama", fixture["samples"]["happy"])
    assert ok["change_7d_unit"] == "ratio"
    with pytest.raises(EconomicNormalizationError):
        canonical_provider_payload("defillama", fixture["samples"]["invalid_unit"])
    with pytest.raises(EconomicNormalizationError):
        canonical_provider_payload("defillama", fixture["samples"]["missing_unit"])


def test_case_17_1_15_evidence_id_content_conflict_no_overwrite(verifier) -> None:
    """Conflicting content for same evidence_id raises and leaves original value intact."""
    results = verifier.run_verification()
    assert results["17.1.15"] is True
    assert verifier._case_17_1_15() is True

    import sqlite3
    from datetime import datetime, timedelta

    from app.db import DbConnection, init_db
    from app.opportunity.economic_models import build_evidence_id
    from app.opportunity.models import EvidenceRecord
    from app.opportunity.repository import (
        EconomicEvidenceContentConflict,
        OpportunityRepository,
    )

    now = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
    project_id = "proj-conflict-test-15"
    evidence_id = build_evidence_id(
        snapshot_id="snap-conflict-test-15",
        project_id=project_id,
        factor_key="tvl_usd",
    )
    raw = sqlite3.connect(":memory:")
    raw.row_factory = sqlite3.Row
    conn = DbConnection(raw, kind="sqlite")
    init_db(conn)
    evid_repo = OpportunityRepository(conn)
    try:
        first = EvidenceRecord(
            evidence_id=evidence_id,
            project_id=project_id,
            factor_key="tvl_usd",
            value="1000000.00000000",
            value_type="string",
            observation_type="observed",
            source_url="https://api.llama.fi/protocol/conflict-test-15",
            source_type="public_aggregator",
            source_grade="C",
            observed_at=now,
            effective_at=now,
            expires_at=now + timedelta(hours=48),
            verification_status="verified",
            independence_group="defillama-protocols",
            raw_snapshot_ref="econ-snapshot:snap-conflict-test-15",
        )
        stored, inserted = evid_repo.add_economic_evidence_if_absent(first)
        assert inserted is True
        assert stored.value == "1000000.00000000"
        conflicting = first.model_copy(update={"value": "9999999.00000000"})
        with pytest.raises(EconomicEvidenceContentConflict):
            evid_repo.add_economic_evidence_if_absent(conflicting)
        rows = [r for r in evid_repo.list_evidence(project_id) if r.evidence_id == evidence_id]
        assert len(rows) == 1
        assert rows[0].value == "1000000.00000000"
        assert rows[0].value != "9999999.00000000"
        assert raw.execute("SELECT COUNT(*) FROM opportunity_evidence").fetchone()[0] == 1
    finally:
        evid_repo.close()
        conn.close()


def test_case_17_1_16_specialized_normalizer_types(verifier) -> None:
    assert verifier.run_verification()["17.1.16"] is True
    from datetime import datetime

    from app.opportunity.economic_normalizers import normalize_provider_payload

    fixture = json.loads((FIXTURE_DIR / "defillama.json").read_text(encoding="utf-8"))
    observed = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
    expires = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
    factors = {
        f.factor_key: f
        for f in normalize_provider_payload(
            source_id="defillama",
            raw_data=fixture["samples"]["happy"],
            source_url="https://defillama.com/protocol/x",
            observed_at=observed,
            expires_at=expires,
        )
    }
    assert factors["tvl_usd"].value_type == "string"
    assert factors["tvl_usd"].unit == "usd"
    assert factors["tvl_change_7d_ratio"].unit == "ratio"
    assert factors["chains_json"].value_type == "json"
    assert list(factors["chains_json"].value) == sorted(factors["chains_json"].value)
    assert factors["token_unlisted_proxy"].value_type == "bool"


def test_case_17_1_17_gray_release_layered_flags(verifier) -> None:
    """Gray layers: snapshot-only; snapshot+evidence; all three — distinct production behavior."""
    results = verifier.run_verification()
    assert results["17.1.17"] is True
    assert verifier._case_17_1_17() is True

    import sqlite3
    from datetime import datetime

    from app.collectors.base import CollectorResult, RawDiscovery
    from app.db import DbConnection, init_db
    from app.metrics import OPPORTUNITY_ECONOMIC_EVIDENCE, metric_sample_value
    from app.opportunity.economic_evidence import EconomicEvidenceEmitter
    from app.opportunity.economic_integration import process_persisted_collection
    from app.opportunity.economic_repository import EconomicSnapshotRepository
    from app.opportunity.economic_resolver import project_economics_data
    from app.opportunity.economic_writer import EconomicSnapshotWriter
    from app.opportunity.repository import OpportunityRepository

    now = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
    fixture = json.loads((FIXTURE_DIR / "defillama.json").read_text(encoding="utf-8"))
    raw_data = fixture["samples"]["happy"]

    def _stack():
        raw = sqlite3.connect(":memory:")
        raw.row_factory = sqlite3.Row
        conn = DbConnection(raw, kind="sqlite")
        init_db(conn)
        snap = EconomicSnapshotRepository(conn)
        evid = OpportunityRepository(conn)
        return raw, conn, snap, evid

    def _item(name: str) -> RawDiscovery:
        return RawDiscovery(
            source_id="defillama",
            raw_id=f"raw-{name}",
            name=name,
            url="https://defillama.com/protocol/gray-test",
            sector="DeFi",
            stage="mainnet",
            raw_data=raw_data,
        )

    # Layer 1: snapshot only → rows, zero evidence, resolver None
    raw, conn, snap, evid = _stack()
    try:
        item = _item("Gray Layer One")
        conn.execute(
            "INSERT INTO projects (id, name, source) VALUES (?, ?, ?)",
            (item.project_id, item.name, "test"),
        )
        conn.execute(
            """INSERT INTO raw_projects
               (raw_id, source_id, dedup_key, raw_data, discovered_at, discovery_score, project_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("raw-l1", "defillama", item.dedup_key, "{}", now.isoformat(), 0.5, item.project_id),
        )
        conn.commit()
        settings = verifier._settings(
            opportunity_economic_snapshot_enabled=True,
            opportunity_economic_source_defillama_enabled=True,
            opportunity_economic_evidence_emit_enabled=False,
            opportunity_economic_resolver_enabled=False,
            defillama_enabled=True,
        )
        result = CollectorResult(source_id="defillama", items=[item])
        result.finished_at = now
        before_skip = metric_sample_value(OPPORTUNITY_ECONOMIC_EVIDENCE, source="defillama", result="skipped_flag_off")
        summary = process_persisted_collection(
            result,
            run_id="daily:2026-07-22:defillama",
            writer=EconomicSnapshotWriter(snap, now_factory=lambda: now),
            emitter=EconomicEvidenceEmitter(conn, snap, evid),
            settings_obj=settings,
        )
        assert summary is not None
        assert summary.snapshots_inserted >= 1
        assert raw.execute("SELECT COUNT(*) FROM opportunity_economic_snapshots").fetchone()[0] >= 1
        assert raw.execute("SELECT COUNT(*) FROM opportunity_evidence").fetchone()[0] == 0
        assert (
            metric_sample_value(OPPORTUNITY_ECONOMIC_EVIDENCE, source="defillama", result="skipped_flag_off")
            >= before_skip + 1
        )
        assert (
            project_economics_data(
                item.project_id,
                evidence_repository=evid,
                snapshot_repository=snap,
                direct_available=False,
                now=now,
                enabled=False,
            )
            is None
        )
    finally:
        evid.close()
        snap.close()
        conn.close()

    # Layer 2: snapshot+evidence → Evidence rows, resolver still None
    raw, conn, snap, evid = _stack()
    try:
        item = _item("Gray Layer Two")
        conn.execute(
            "INSERT INTO projects (id, name, source) VALUES (?, ?, ?)",
            (item.project_id, item.name, "test"),
        )
        conn.execute(
            """INSERT INTO raw_projects
               (raw_id, source_id, dedup_key, raw_data, discovered_at, discovery_score, project_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("raw-l2", "defillama", item.dedup_key, "{}", now.isoformat(), 0.5, item.project_id),
        )
        conn.commit()
        settings = verifier._settings(
            opportunity_economic_snapshot_enabled=True,
            opportunity_economic_source_defillama_enabled=True,
            opportunity_economic_evidence_emit_enabled=True,
            opportunity_economic_resolver_enabled=False,
            defillama_enabled=True,
        )
        result = CollectorResult(source_id="defillama", items=[item])
        result.finished_at = now
        summary = process_persisted_collection(
            result,
            run_id="daily:2026-07-22:defillama",
            writer=EconomicSnapshotWriter(snap, now_factory=lambda: now),
            emitter=EconomicEvidenceEmitter(conn, snap, evid),
            settings_obj=settings,
        )
        assert summary is not None
        assert raw.execute("SELECT COUNT(*) FROM opportunity_evidence").fetchone()[0] >= 1
        assert (
            project_economics_data(
                item.project_id,
                evidence_repository=evid,
                snapshot_repository=snap,
                direct_available=False,
                now=now,
                enabled=False,
            )
            is None
        )
    finally:
        evid.close()
        snap.close()
        conn.close()

    # Layer 3: all three → resolver projection non-None PROXY_ONLY
    raw, conn, snap, evid = _stack()
    try:
        item = _item("Gray Layer Three")
        conn.execute(
            "INSERT INTO projects (id, name, source) VALUES (?, ?, ?)",
            (item.project_id, item.name, "test"),
        )
        conn.execute(
            """INSERT INTO raw_projects
               (raw_id, source_id, dedup_key, raw_data, discovered_at, discovery_score, project_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("raw-l3", "defillama", item.dedup_key, "{}", now.isoformat(), 0.5, item.project_id),
        )
        conn.commit()
        settings = verifier._settings(
            opportunity_economic_snapshot_enabled=True,
            opportunity_economic_source_defillama_enabled=True,
            opportunity_economic_evidence_emit_enabled=True,
            opportunity_economic_resolver_enabled=True,
            defillama_enabled=True,
        )
        result = CollectorResult(source_id="defillama", items=[item])
        result.finished_at = now
        summary = process_persisted_collection(
            result,
            run_id="daily:2026-07-22:defillama",
            writer=EconomicSnapshotWriter(snap, now_factory=lambda: now),
            emitter=EconomicEvidenceEmitter(conn, snap, evid),
            settings_obj=settings,
        )
        assert summary is not None
        projection = project_economics_data(
            item.project_id,
            evidence_repository=evid,
            snapshot_repository=snap,
            direct_available=False,
            now=now,
            enabled=True,
        )
        assert projection is not None
        assert projection.economics_data_mode == "PROXY_ONLY"
        assert projection.factors
    finally:
        evid.close()
        snap.close()
        conn.close()


def test_case_17_1_18_source_and_provider_dual_true(verifier) -> None:
    """Source flag and provider-enabled must both be true; other combos write zero snapshots."""
    results = verifier.run_verification()
    assert results["17.1.18"] is True
    assert verifier._case_17_1_18() is True

    import sqlite3
    from datetime import datetime

    from app.collectors.base import CollectorResult, RawDiscovery
    from app.db import DbConnection, init_db
    from app.opportunity.economic_evidence import EconomicEvidenceEmitter
    from app.opportunity.economic_integration import (
        economic_source_enabled,
        process_persisted_collection,
    )
    from app.opportunity.economic_repository import EconomicSnapshotRepository
    from app.opportunity.economic_writer import EconomicSnapshotWriter
    from app.opportunity.repository import OpportunityRepository

    now = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
    fixture = json.loads((FIXTURE_DIR / "defillama.json").read_text(encoding="utf-8"))
    raw_data = fixture["samples"]["happy"]

    for source_flag, provider_flag in (
        (False, False),
        (False, True),
        (True, False),
        (True, True),
    ):
        raw = sqlite3.connect(":memory:")
        raw.row_factory = sqlite3.Row
        conn = DbConnection(raw, kind="sqlite")
        init_db(conn)
        snap = EconomicSnapshotRepository(conn)
        evid = OpportunityRepository(conn)
        try:
            item = RawDiscovery(
                source_id="defillama",
                raw_id=f"raw-dual-{int(source_flag)}{int(provider_flag)}",
                name=f"Dual {source_flag}{provider_flag}",
                url="https://defillama.com/protocol/dual",
                sector="DeFi",
                stage="mainnet",
                raw_data=raw_data,
            )
            settings = verifier._settings(
                opportunity_economic_snapshot_enabled=True,
                opportunity_economic_source_defillama_enabled=source_flag,
                defillama_enabled=provider_flag,
            )
            expected = source_flag and provider_flag
            assert economic_source_enabled("defillama", settings) is expected
            result = CollectorResult(source_id="defillama", items=[item])
            result.finished_at = now
            summary = process_persisted_collection(
                result,
                run_id="daily:2026-07-22:defillama",
                writer=EconomicSnapshotWriter(snap, now_factory=lambda: now),
                emitter=EconomicEvidenceEmitter(conn, snap, evid),
                settings_obj=settings,
            )
            snap_n = raw.execute("SELECT COUNT(*) FROM opportunity_economic_snapshots").fetchone()[0]
            if expected:
                assert summary is not None
                assert snap_n >= 1
            else:
                assert summary is None
                assert snap_n == 0
        finally:
            evid.close()
            snap.close()
            conn.close()


def test_case_17_1_19_raw_none_vs_actual_zero_legacy_local_fallback(verifier) -> None:
    assert verifier.run_verification()["17.1.19"] is True
    from app.collectors.coingecko import CoinGeckoCollector
    from app.collectors.defillama import DefiLlamaCollector

    dl = DefiLlamaCollector()
    d_none = dl._build_discovery(
        {
            "name": "N",
            "slug": "n",
            "category": "Lending",
            "tvl": None,
            "change_7d": None,
            "url": "https://n.example.com",
        }
    )
    d_zero = dl._build_discovery(
        {
            "name": "Z",
            "slug": "z",
            "category": "Lending",
            "tvl": 0,
            "change_7d": 0,
            "url": "https://z.example.com",
        }
    )
    assert d_none.raw_data["tvl"] is None
    assert d_zero.raw_data["tvl"] == 0
    assert d_none.raw_data["tvl"] != d_zero.raw_data["tvl"]
    tvl_sig = next(s for s in d_none.raw_signals if s.signal_type == "tvl")
    assert tvl_sig.signal_data["tvl"] == 0
    cg = CoinGeckoCollector()
    c_none = cg._build_discovery(
        {
            "id": "n",
            "symbol": "n",
            "name": "N",
            "image": "https://example.com/n.png",
            "market_cap_rank": None,
        }
    )
    assert c_none.raw_data.get("market_cap_rank") is None
    assert c_none.raw_signals[0].signal_data["market_cap_rank"] == 0


def test_case_17_1_20_payload_json_whitelist_omit_none_keep_zero_defi_unit_hash(
    verifier,
) -> None:
    assert verifier.run_verification()["17.1.20"] is True
    from app.opportunity.economic_models import payload_sha256
    from app.opportunity.economic_normalizers import (
        DEFILLAMA_CHANGE_7D_PROVIDER_UNIT,
        canonical_provider_payload,
    )

    fixture = json.loads((FIXTURE_DIR / "defillama.json").read_text(encoding="utf-8"))
    none_payload = canonical_provider_payload("defillama", fixture["samples"]["with_none"])
    zero_payload = canonical_provider_payload("defillama", fixture["samples"]["with_zero"])
    happy = canonical_provider_payload("defillama", fixture["samples"]["happy"])
    assert "tvl" not in none_payload
    assert zero_payload["tvl"] == 0
    assert happy["change_7d_unit"] == DEFILLAMA_CHANGE_7D_PROVIDER_UNIT
    assert "api_key" not in happy and "token" not in happy
    assert "unknown_noise_field" not in happy
    assert payload_sha256(happy) == payload_sha256(dict(happy))
    polluted = dict(happy)
    polluted["noise"] = 1
    assert payload_sha256(polluted) != payload_sha256(happy)


def test_case_17_1_21_manual_run_id_vs_daily_namespace(verifier) -> None:
    """manual:<uuid> exact form; daily UTC-date namespace; shapes isolated."""
    results = verifier.run_verification()
    assert results["17.1.21"] is True
    assert verifier._case_17_1_21() is True

    from datetime import datetime, timedelta, timezone
    from uuid import UUID

    from app.opportunity.economic_integration import daily_run_id, manual_run_id

    fixed = UUID("550e8400-e29b-41d4-a716-446655440000")
    assert manual_run_id(uuid_factory=lambda: fixed) == ("manual:550e8400-e29b-41d4-a716-446655440000")
    a = manual_run_id()
    b = manual_run_id()
    assert a.startswith("manual:") and b.startswith("manual:")
    assert a != b
    assert UUID(a[len("manual:") :])

    t1 = datetime(2026, 7, 22, 1, 0, tzinfo=UTC)
    t2 = datetime(2026, 7, 22, 23, 59, tzinfo=UTC)
    t3 = datetime(2026, 7, 23, 0, 0, tzinfo=UTC)
    assert daily_run_id("defillama", t1) == "daily:2026-07-22:defillama"
    assert daily_run_id("defillama", t2) == daily_run_id("defillama", t1)
    assert daily_run_id("defillama", t3) == "daily:2026-07-23:defillama"
    assert daily_run_id("defillama", t1) != daily_run_id("defillama", t3)
    offset = timezone(timedelta(hours=5))
    local = datetime(2026, 7, 23, 2, 0, tzinfo=offset)
    assert daily_run_id("defillama", local) == "daily:2026-07-22:defillama"
    daily = daily_run_id("defillama", t1)
    assert not daily.startswith("manual:")
    assert not a.startswith("daily:")
    assert a != daily
    assert manual_run_id(uuid_factory=lambda: fixed) != daily_run_id(str(fixed), t1)


def test_case_17_1_22_replay_enabled_false_zero_side_effects(verifier) -> None:
    """replay enabled=False: zero queries, rebuild, evidence writes, metric increments."""
    results = verifier.run_verification()
    assert results["17.1.22"] is True
    assert verifier._case_17_1_22() is True

    import sqlite3
    from datetime import datetime
    from unittest.mock import patch

    from app.db import DbConnection, init_db
    from app.metrics import (
        OPPORTUNITY_ECONOMIC_EVIDENCE,
        OPPORTUNITY_ECONOMIC_IDENTITY_RESOLUTION,
        metric_sample_value,
    )
    from app.opportunity import economic_evidence as evidence_mod
    from app.opportunity.economic_evidence import replay_economic_snapshots_for_project
    from app.opportunity.economic_repository import EconomicSnapshotRepository
    from app.opportunity.repository import OpportunityRepository

    now = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
    raw = sqlite3.connect(":memory:")
    raw.row_factory = sqlite3.Row
    conn = DbConnection(raw, kind="sqlite")
    init_db(conn)
    snap = EconomicSnapshotRepository(conn)
    evid = OpportunityRepository(conn)
    try:
        conn.execute(
            "INSERT INTO projects (id, name, source) VALUES (?, ?, ?)",
            ("proj-noop-22", "Noop", "test"),
        )
        conn.execute(
            """INSERT INTO raw_projects
               (raw_id, source_id, dedup_key, raw_data, discovered_at, discovery_score, project_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                "raw-noop-22",
                "defillama",
                "protocol:noop-22",
                "{}",
                now.isoformat(),
                0.5,
                "proj-noop-22",
            ),
        )
        conn.commit()
        before_ev = metric_sample_value(OPPORTUNITY_ECONOMIC_EVIDENCE, source="defillama", result="emitted")
        before_id = metric_sample_value(OPPORTUNITY_ECONOMIC_IDENTITY_RESOLUTION, source="defillama", result="linked")
        execute_calls: list[str] = []
        real_execute = conn.execute

        def tracking_execute(sql, params=None):
            execute_calls.append(" ".join(str(sql).split()).lower())
            if params is None:
                return real_execute(sql)
            return real_execute(sql, params)

        with (
            patch.object(
                EconomicSnapshotRepository,
                "list_by_identity",
                wraps=snap.list_by_identity,
            ) as list_spy,
            patch.object(
                evidence_mod,
                "observation_from_snapshot",
                wraps=evidence_mod.observation_from_snapshot,
            ) as recon_spy,
            patch.object(
                OpportunityRepository,
                "add_economic_evidence_if_absent",
                wraps=evid.add_economic_evidence_if_absent,
            ) as add_spy,
        ):
            conn.execute = tracking_execute  # type: ignore[method-assign]
            out = replay_economic_snapshots_for_project("proj-noop-22", conn=conn, enabled=False)
            conn.execute = real_execute  # type: ignore[method-assign]
            assert out is None
            assert list_spy.call_count == 0
            assert recon_spy.call_count == 0
            assert add_spy.call_count == 0
            assert not any("opportunity_economic_snapshots" in s for s in execute_calls)
            assert not any("raw_projects" in s for s in execute_calls)
        assert metric_sample_value(OPPORTUNITY_ECONOMIC_EVIDENCE, source="defillama", result="emitted") == before_ev
        assert (
            metric_sample_value(
                OPPORTUNITY_ECONOMIC_IDENTITY_RESOLUTION,
                source="defillama",
                result="linked",
            )
            == before_id
        )
        assert raw.execute("SELECT COUNT(*) FROM opportunity_evidence").fetchone()[0] == 0
    finally:
        evid.close()
        snap.close()
        conn.close()


def test_case_17_1_23_observation_from_snapshot_schema_hash_per_row_isolation(
    verifier,
) -> None:
    """schema_version + recomputed payload_sha256; bad row isolated; project not rolled back."""
    results = verifier.run_verification()
    assert results["17.1.23"] is True
    assert verifier._case_17_1_23() is True

    from datetime import datetime

    from app.opportunity.economic_models import (
        SCHEMA_VERSION,
        EconomicSnapshotRow,
        build_snapshot_id,
        payload_sha256,
    )
    from app.opportunity.economic_normalizers import canonical_provider_payload
    from app.opportunity.economic_writer import (
        EconomicReconstructionError,
        observation_from_snapshot,
    )

    fixture = json.loads((FIXTURE_DIR / "defillama.json").read_text(encoding="utf-8"))
    raw = fixture["samples"]["happy"]
    payload = canonical_provider_payload("defillama", raw)
    digest = payload_sha256(payload)
    observed = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
    good = EconomicSnapshotRow(
        snapshot_id=build_snapshot_id(
            run_id="daily:2026-07-22:defillama",
            source_id="defillama",
            provider_entity_id="entity-test-23",
            payload_sha256_hex=digest,
        ),
        schema_version=SCHEMA_VERSION,
        run_id="daily:2026-07-22:defillama",
        source_id="defillama",
        dedup_key="protocol:test-23",
        provider_entity_id="entity-test-23",
        payload_sha256=digest,
        payload_json=payload,
        source_url="https://defillama.com/protocol/test-23",
        collected_at=observed,
    )
    obs = observation_from_snapshot(good)
    assert obs.snapshot_id == good.snapshot_id
    assert payload_sha256(good.payload_json) == good.payload_sha256
    assert good.schema_version == SCHEMA_VERSION

    bad_schema = EconomicSnapshotRow.model_construct(
        snapshot_id="sid-bad-schema",
        schema_version="wrong-schema-v0",
        run_id="run",
        source_id="defillama",
        dedup_key="k",
        provider_entity_id="e",
        payload_sha256=digest,
        payload_json=payload,
        source_url="https://defillama.com/protocol/x",
        collected_at=observed,
    )
    with pytest.raises(EconomicReconstructionError):
        observation_from_snapshot(bad_schema)

    bad_hash = EconomicSnapshotRow(
        snapshot_id=build_snapshot_id(
            run_id="run",
            source_id="defillama",
            provider_entity_id="e-hash",
            payload_sha256_hex=digest,
        ),
        schema_version=SCHEMA_VERSION,
        run_id="run",
        source_id="defillama",
        dedup_key="k",
        provider_entity_id="e-hash",
        payload_sha256="0" * 64,
        payload_json=payload,
        source_url="https://defillama.com/protocol/x",
        collected_at=observed,
    )
    with pytest.raises(EconomicReconstructionError):
        observation_from_snapshot(bad_hash)


def test_case_17_1_24_internal_projection_no_workflow_v1_fields_four_layer(
    verifier,
) -> None:
    """Four layers independently: model, serializer, service, router — no economic leak."""
    results = verifier.run_verification()
    assert results["17.1.24"] is True
    assert verifier._case_17_1_24() is True

    import inspect

    from app.opportunity.workflow import OpportunityWorkflowProjection, build_workflow_projection
    from app.routers.v1 import opportunity as opportunity_router

    # Layer 1 — model
    field_names = tuple(OpportunityWorkflowProjection.model_fields.keys())
    assert field_names == verifier._BASELINE_WORKFLOW_FIELDS
    assert not (set(field_names) & verifier._FORBIDDEN_ECONOMIC_WORKFLOW_KEYS)
    assert "economic_proxy" not in field_names
    assert "economics_data_mode" not in field_names

    # Layer 2 — serializer
    pure = build_workflow_projection(
        project={
            "id": "proj-test-24",
            "name": "T24",
            "score": 1,
            "label": "WATCH",
            "url": "https://example.invalid/t24",
            "stage": "mainnet",
        },
        assessment=None,
        evidence=(),
        participation_tasks=(),
        interactions=(),
        now=__import__("datetime").datetime(2026, 7, 22, 12, 0, tzinfo=__import__("datetime").timezone.utc),
    )
    dump = pure.model_dump(mode="json")
    assert tuple(dump.keys()) == verifier._BASELINE_WORKFLOW_FIELDS
    assert "economic_proxy" not in dump
    assert "economics_data_mode" not in dump
    ser_bytes = (
        __import__("json").dumps(dump, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    assert b"economic_proxy" not in ser_bytes
    assert b"economics_data_mode" not in ser_bytes

    # Layer 4 — router source (no HTTP): model_dump path, no economic tokens
    router_source = inspect.getsource(opportunity_router.get_opportunity_workflow)
    assert (
        'projection.model_dump(mode="json")' in router_source or "projection.model_dump(mode='json')" in router_source
    )
    for token in (
        "economic_proxy",
        "economics_data_mode",
        "project_economics_data",
        "EconomicProxyProjection",
    ):
        assert token not in router_source
    module_source = Path(opportunity_router.__file__).read_text(encoding="utf-8")
    for token in (
        "economic_proxy",
        "economics_data_mode",
        "project_economics_data",
        "EconomicProxyProjection",
    ):
        assert token not in module_source


def test_case_17_1_25_metrics_sample_value_label_helper_not_bare_labels(verifier) -> None:
    """metric_sample_value / metric_label_sets prove deltas; bare labels is insufficient."""
    results = verifier.run_verification()
    assert results["17.1.25"] is True
    assert verifier._case_17_1_25() is True

    import inspect

    from app.metrics import (
        OPPORTUNITY_ECONOMIC_SNAPSHOTS,
        metric_label_sets,
        metric_sample_value,
        record_opportunity_economic_snapshot,
    )

    sig = inspect.signature(metric_sample_value)
    assert next(iter(sig.parameters)) == "metric"
    assert any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
    assert list(inspect.signature(metric_label_sets).parameters) == ["metric"]

    # Bare labels existence alone is not verification.
    child = OPPORTUNITY_ECONOMIC_SNAPSHOTS.labels(source="cryptorank", result="duplicate")
    assert child is not None

    before = metric_sample_value(OPPORTUNITY_ECONOMIC_SNAPSHOTS, source="cryptorank", result="duplicate")
    record_opportunity_economic_snapshot(source="cryptorank", result="duplicate")
    after = metric_sample_value(OPPORTUNITY_ECONOMIC_SNAPSHOTS, source="cryptorank", result="duplicate")
    assert after - before == 1.0

    label_sets = metric_label_sets(OPPORTUNITY_ECONOMIC_SNAPSHOTS)
    assert isinstance(label_sets, frozenset)
    assert label_sets
    found = False
    for label_set in label_sets:
        as_dict = dict(label_set)
        if as_dict.get("source") == "cryptorank" and as_dict.get("result") == "duplicate":
            found = True
        if "result" in as_dict:
            assert as_dict["result"] != "rejected_fuzzy_attempt"
    assert found is True


def test_case_17_1_26_connection_ownership_close_and_construct_process_isolation(
    verifier,
) -> None:
    """Borrowed conn never closed; process/emit + real construction isolation."""
    import inspect
    import sqlite3
    from datetime import datetime
    from unittest.mock import MagicMock
    from uuid import UUID

    from app.collectors.base import CollectorResult, RawDiscovery
    from app.db import DbConnection, init_db
    from app.opportunity.economic_evidence import EconomicEvidenceEmitter
    from app.opportunity.economic_integration import (
        daily_run_id,
        manual_run_id,
        process_persisted_collection,
    )
    from app.opportunity.economic_repository import EconomicSnapshotRepository
    from app.opportunity.economic_writer import EconomicSnapshotWriter
    from app.opportunity.repository import OpportunityRepository

    # Reject local boom_repo tautology; require production ownership stack injection.
    case_src = inspect.getsource(verifier._case_17_1_26)
    helper_src = inspect.getsource(verifier._prove_construction_failure_isolation)
    combined = case_src + helper_src
    assert "def boom_repo" not in combined
    assert "boom_repo(" not in combined
    assert "app.opportunity.economic_repository.EconomicSnapshotRepository" in helper_src
    assert "create_app" in helper_src and "lifespan_context" in helper_src
    assert "trigger_collection" in helper_src
    assert "_run_coro_sync" in helper_src
    assert "TestClient" not in combined
    assert "asyncio.run" not in combined

    results = verifier.run_verification()
    assert results["17.1.26"] is True
    assert verifier._case_17_1_26() is True

    main_src = (BACKEND / "app" / "main.py").read_text(encoding="utf-8")
    collections_src = (BACKEND / "app" / "routers" / "v1" / "collections.py").read_text(encoding="utf-8")
    assert "app_owns_conn = False" in main_src
    assert "app.economic_stack_construction_failed" in main_src
    assert "process_persisted_collection" in main_src
    assert "daily_run_id" in main_src
    assert "manual_run_id" in collections_src
    assert "collections.economic_failed" in collections_src
    assert ".close(" not in inspect.getsource(process_persisted_collection)

    raw = sqlite3.connect(":memory:")
    raw.row_factory = sqlite3.Row
    conn = DbConnection(raw, kind="sqlite")
    init_db(conn)
    close_calls = {"n": 0}
    real_close = conn.close

    def tracking_close() -> None:
        close_calls["n"] += 1
        real_close()

    conn.close = tracking_close  # type: ignore[method-assign]
    snap = EconomicSnapshotRepository(conn)
    evid = OpportunityRepository(conn)
    try:
        settings = verifier._settings(
            opportunity_economic_snapshot_enabled=True,
            opportunity_economic_source_defillama_enabled=True,
            opportunity_economic_evidence_emit_enabled=True,
            defillama_enabled=True,
        )
        now = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
        item = RawDiscovery(
            source_id="defillama",
            raw_id="raw-own-test-26",
            name="Own Test 26",
            url="https://defillama.com/protocol/own-26",
            sector="DeFi",
            stage="mainnet",
            raw_data={
                "tvl": 1.0,
                "change_7d": 0.01,
                "change_7d_unit": "ratio",
                "chains": ["Ethereum"],
                "no_token_yet": True,
            },
        )
        result = CollectorResult(source_id="defillama", items=[item])
        result.finished_at = now
        writer = EconomicSnapshotWriter(snap, now_factory=lambda: now)
        emitter = EconomicEvidenceEmitter(conn, snap, evid)
        summary = process_persisted_collection(
            result,
            run_id=daily_run_id("defillama", now),
            writer=writer,
            emitter=emitter,
            settings_obj=settings,
        )
        assert summary is not None
        assert summary.snapshots_inserted >= 1
        assert close_calls["n"] == 0
        snap.close()
        evid.close()
        assert close_calls["n"] == 0
        assert conn.execute("SELECT 1").fetchone()[0] == 1

        snap = EconomicSnapshotRepository(conn)
        evid = OpportunityRepository(conn)
        failing = MagicMock()
        failing.process.side_effect = RuntimeError("process boom")
        out = process_persisted_collection(
            result,
            run_id=manual_run_id(uuid_factory=lambda: UUID("550e8400-e29b-41d4-a716-446655440099")),
            writer=failing,
            emitter=EconomicEvidenceEmitter(conn, snap, evid),
            settings_obj=settings,
        )
        assert out is None
        failing.process.assert_called_once()
        assert close_calls["n"] == 0
        snap_n_before = int(raw.execute("SELECT COUNT(*) FROM opportunity_economic_snapshots").fetchone()[0])
        assert snap_n_before >= 1

        # Real production construction failure (scheduled + manual ownership stacks).
        assert verifier._prove_construction_failure_isolation(result) is True
        assert int(raw.execute("SELECT COUNT(*) FROM opportunity_economic_snapshots").fetchone()[0]) == snap_n_before
        assert close_calls["n"] == 0
    finally:
        with suppress(Exception):
            evid.close()
        with suppress(Exception):
            snap.close()
        if close_calls["n"] == 0:
            conn.close()


def test_ast_import_denylist_on_verifier_script() -> None:
    imports = _collect_imports(SCRIPT)
    for banned in NETWORK_DENYLIST:
        assert banned not in imports, f"banned import {banned} in verifier"
    # Direct socket client modules forbidden (stdlib socket import for sentinel ok? brief says
    # no socket clients/imports in verifier for networking — tests own the sentinel).
    assert "socket" not in imports


def test_socket_connect_sentinel_fails_if_outbound(verifier, monkeypatch) -> None:
    """If verification attempts outbound connect, case must fail via sentinel."""

    def _blocked(*_a, **_k):
        raise AssertionError("outbound socket connect attempted during verification")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", lambda *a, **k: 1)
    results = verifier.run_verification()
    assert set(results.keys()) == set(EXPECTED_CASE_IDS)
    assert all(results[cid] is True for cid in EXPECTED_CASE_IDS)


def test_main_success_exit_zero_and_status_26_of_26(verifier) -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = verifier.main([])
    out = buf.getvalue()
    assert code == 0
    assert "passed=26" in out
    assert "failed=0" in out
    assert "total=26" in out
    assert out.rstrip().endswith("RESULT: PASS")
    _assert_no_canaries(out)
    for path_frag in ("opportunity_economic", "fixtures", str(FIXTURE_DIR)):
        assert path_frag not in out


def test_main_missing_case_key_returns_1(verifier) -> None:
    full = {cid: True for cid in EXPECTED_CASE_IDS}
    del full["17.1.10"]

    def _partial():
        return full

    buf = io.StringIO()
    with patch.object(verifier, "run_verification", _partial), redirect_stdout(buf):
        code = verifier.main([])
    out = buf.getvalue()
    assert code == 1
    assert out.rstrip().endswith("RESULT: FAIL")
    _assert_no_canaries(out)


def test_main_false_case_returns_1(verifier) -> None:
    full = {cid: True for cid in EXPECTED_CASE_IDS}
    full["17.1.05"] = False

    buf = io.StringIO()
    with patch.object(verifier, "run_verification", lambda: full), redirect_stdout(buf):
        code = verifier.main([])
    out = buf.getvalue()
    assert code == 1
    assert "failed=" in out
    assert out.rstrip().endswith("RESULT: FAIL")
    _assert_no_canaries(out)


def test_main_extra_key_returns_1(verifier) -> None:
    full = {cid: True for cid in EXPECTED_CASE_IDS}
    full["17.1.99"] = True

    buf = io.StringIO()
    with patch.object(verifier, "run_verification", lambda: full), redirect_stdout(buf):
        code = verifier.main([])
    assert code == 1
    assert buf.getvalue().rstrip().endswith("RESULT: FAIL")


def test_main_hash_fixture_mismatch_returns_1(verifier) -> None:
    def _boom():
        raise verifier.VerificationContractError("hash_mismatch")

    buf = io.StringIO()
    with patch.object(verifier, "run_verification", _boom), redirect_stdout(buf):
        code = verifier.main([])
    out = buf.getvalue()
    assert code == 1
    assert "failure_type=VerificationContractError" in out or "failure_type=" in out
    assert out.rstrip().endswith("RESULT: FAIL")
    _assert_no_canaries(out)
    assert "payload" not in out.lower() or "failure_type=" in out


def test_main_exception_bounded_type_only(verifier) -> None:
    def _boom():
        raise RuntimeError(f"CANARY_DL_API_KEY_TASK9_SYNTH_NEVER_LEAK secret path={FIXTURE_DIR / 'defillama.json'}")

    buf = io.StringIO()
    with patch.object(verifier, "run_verification", _boom), redirect_stdout(buf):
        code = verifier.main([])
    out = buf.getvalue()
    assert code == 1
    assert "failure_type=RuntimeError" in out
    assert out.rstrip().endswith("RESULT: FAIL")
    _assert_no_canaries(out)
    assert "defillama.json" not in out
    assert str(FIXTURE_DIR) not in out


def test_fixtures_exist_with_none_zero_canaries() -> None:
    for name in ("defillama.json", "coingecko.json", "cryptorank.json"):
        path = FIXTURE_DIR / name
        assert path.is_file()
        text = path.read_text(encoding="utf-8")
        assert "null" in text  # JSON None
        assert '"with_zero"' in text or "with_zero" in text
        assert "CANARY_" in text
