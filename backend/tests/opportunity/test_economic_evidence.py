"""Task 5: EconomicEvidenceEmitter + replay_economic_snapshots_for_project contracts."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

from app.db import DbConnection, init_db
from app.metrics import (
    OPPORTUNITY_ECONOMIC_EVIDENCE,
    OPPORTUNITY_ECONOMIC_IDENTITY_RESOLUTION,
    metric_sample_value,
)
from app.opportunity.economic_models import (
    SCHEMA_VERSION,
    EconomicSnapshotRow,
    NormalizedFactor,
    NormalizedObservation,
    build_evidence_id,
    build_snapshot_id,
    payload_sha256,
)
from app.opportunity.economic_repository import EconomicSnapshotRepository
from app.opportunity.repository import OpportunityRepository

NOW = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
EXPIRES = NOW + timedelta(hours=48)


def _sqlite_stack():
    raw = sqlite3.connect(":memory:")
    raw.row_factory = sqlite3.Row
    conn = DbConnection(raw, kind="sqlite")
    init_db(conn)
    snap_repo = EconomicSnapshotRepository(conn)
    evid_repo = OpportunityRepository(conn)
    return raw, conn, snap_repo, evid_repo


def _seed_project(conn: Any, project_id: str) -> None:
    conn.execute(
        "INSERT INTO projects (id, name, source) VALUES (?, ?, ?)",
        (project_id, "Example", "test"),
    )
    conn.commit()


def _seed_raw(
    conn: Any,
    *,
    raw_id: str,
    source_id: str,
    dedup_key: str,
    project_id: str | None,
) -> None:
    conn.execute(
        """
        INSERT INTO raw_projects (
            raw_id, source_id, dedup_key, raw_data, discovered_at, discovery_score, project_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (raw_id, source_id, dedup_key, "{}", NOW.isoformat(), 0.5, project_id),
    )
    conn.commit()


def _factor(
    *,
    factor_key: str,
    value: Any,
    value_type: str,
    source_id: str = "defillama",
    source_url: str = "https://api.llama.fi/protocol/example",
) -> NormalizedFactor:
    meta = {
        "defillama": ("public_aggregator", "defillama-protocols"),
        "coingecko": ("public_market_data", "market-aggregators"),
        "cryptorank": ("public_market_data", "market-aggregators"),
    }[source_id]
    return NormalizedFactor(
        factor_key=factor_key,
        value=value,
        value_type=value_type,  # type: ignore[arg-type]
        unit=None,
        source_type=meta[0],
        source_grade="C",
        verification_status="verified",
        independence_group=meta[1],
        source_url=source_url,
        observed_at=NOW,
        expires_at=EXPIRES,
    )


def _observation(
    *,
    source_id: str = "defillama",
    dedup_key: str = "protocol:example",
    snapshot_id: str = "snap-1",
    factors: tuple[NormalizedFactor, ...] | None = None,
) -> NormalizedObservation:
    if factors is None:
        factors = (
            _factor(factor_key="tvl_usd", value="1000000.00000000", value_type="string"),
            _factor(
                factor_key="tvl_change_7d_ratio",
                value="0.05000000",
                value_type="string",
            ),
            _factor(factor_key="chains_json", value=["ethereum"], value_type="json"),
            _factor(factor_key="token_unlisted_proxy", value=True, value_type="bool"),
        )
    return NormalizedObservation(
        snapshot_id=snapshot_id,
        source_id=source_id,
        dedup_key=dedup_key,
        provider_entity_id="entity-1",
        factors=factors,
        collected_at=NOW,
        source_url="https://api.llama.fi/protocol/example",
    )


def _metric(metric, *, source: str, result: str) -> float:
    return metric_sample_value(metric, source=source, result=result)


def test_economic_evidence_emitter_factors_whitelist_ref_id_flag_metrics() -> None:
    from app.opportunity.economic_evidence import (
        EconomicEvidenceEmitter,
        EconomicEvidenceSummary,
    )

    raw, conn, snap_repo, evid_repo = _sqlite_stack()
    try:
        emitter = EconomicEvidenceEmitter(conn, snap_repo, evid_repo)

        # enabled=False → skipped_flag_off, zero Evidence writes
        before_ev = _metric(OPPORTUNITY_ECONOMIC_EVIDENCE, source="defillama", result="skipped_flag_off")
        summary_off = emitter.emit(_observation(), enabled=False)
        assert isinstance(summary_off, EconomicEvidenceSummary)
        assert summary_off.skipped_flag_off == 1
        assert summary_off.emitted == 0
        assert summary_off.duplicates == 0
        assert summary_off.unlinked == 0
        assert summary_off.conflicts == 0
        assert raw.execute("SELECT COUNT(*) FROM opportunity_evidence").fetchone()[0] == 0
        assert _metric(OPPORTUNITY_ECONOMIC_EVIDENCE, source="defillama", result="skipped_flag_off") == before_ev + 1

        # unlinked: no dual-condition identity → zero Evidence, snapshot retained concept
        before_unlinked = _metric(OPPORTUNITY_ECONOMIC_IDENTITY_RESOLUTION, source="defillama", result="unlinked")
        before_skip_proj = _metric(OPPORTUNITY_ECONOMIC_EVIDENCE, source="defillama", result="skipped_no_project")
        summary_unlinked = emitter.emit(_observation(dedup_key="protocol:nolink"), enabled=True)
        assert summary_unlinked.unlinked == 1
        assert summary_unlinked.emitted == 0
        assert raw.execute("SELECT COUNT(*) FROM opportunity_evidence").fetchone()[0] == 0
        assert (
            _metric(OPPORTUNITY_ECONOMIC_IDENTITY_RESOLUTION, source="defillama", result="unlinked")
            == before_unlinked + 1
        )
        assert (
            _metric(OPPORTUNITY_ECONOMIC_EVIDENCE, source="defillama", result="skipped_no_project")
            == before_skip_proj + 1
        )

        # linked path: seed identity + emit closed factor set
        _seed_project(conn, "proj-1")
        _seed_raw(
            conn,
            raw_id="raw-1",
            source_id="defillama",
            dedup_key="protocol:example",
            project_id="proj-1",
        )
        before_linked = _metric(OPPORTUNITY_ECONOMIC_IDENTITY_RESOLUTION, source="defillama", result="linked")
        before_emitted = _metric(OPPORTUNITY_ECONOMIC_EVIDENCE, source="defillama", result="emitted")
        obs = _observation(snapshot_id="snap-dl-1")
        # Inject a non-whitelisted factor that must be ignored
        bad_factor = _factor(factor_key="not_a_factor", value="x", value_type="string")
        obs = obs.model_copy(update={"factors": (*obs.factors, bad_factor)})
        summary = emitter.emit(obs, enabled=True)
        assert summary.emitted == 4  # closed DL set only
        assert summary.duplicates == 0
        assert summary.unlinked == 0
        assert summary.conflicts == 0
        assert (
            _metric(OPPORTUNITY_ECONOMIC_IDENTITY_RESOLUTION, source="defillama", result="linked") == before_linked + 1
        )
        assert _metric(OPPORTUNITY_ECONOMIC_EVIDENCE, source="defillama", result="emitted") == before_emitted + 4

        rows = evid_repo.list_evidence("proj-1")
        assert len(rows) == 4
        by_key = {r.factor_key: r for r in rows}
        assert set(by_key) == {
            "tvl_usd",
            "tvl_change_7d_ratio",
            "chains_json",
            "token_unlisted_proxy",
        }
        for key, record in by_key.items():
            assert record.source_grade == "C"
            assert record.verification_status == "verified"
            assert record.observation_type == "observed"
            assert record.effective_at == NOW
            assert record.expires_at == EXPIRES
            assert record.source_type == "public_aggregator"
            assert record.independence_group == "defillama-protocols"
            assert record.raw_snapshot_ref == "econ-snapshot:snap-dl-1"
            assert record.project_id == "proj-1"
            expected_id = build_evidence_id(snapshot_id="snap-dl-1", project_id="proj-1", factor_key=key)
            assert record.evidence_id == expected_id
            assert len(record.evidence_id) == 64
            assert all(c in "0123456789abcdef" for c in record.evidence_id)

        value_types = {
            "tvl_usd": "string",
            "tvl_change_7d_ratio": "string",
            "chains_json": "json",
            "token_unlisted_proxy": "bool",
        }
        for key, vt in value_types.items():
            assert by_key[key].value_type == vt

        # duplicate emit → duplicates metric, no overwrite / no new rows
        before_dup = _metric(OPPORTUNITY_ECONOMIC_EVIDENCE, source="defillama", result="duplicate")
        summary_dup = emitter.emit(_observation(snapshot_id="snap-dl-1"), enabled=True)
        assert summary_dup.duplicates == 4
        assert summary_dup.emitted == 0
        assert raw.execute("SELECT COUNT(*) FROM opportunity_evidence").fetchone()[0] == 4
        assert _metric(OPPORTUNITY_ECONOMIC_EVIDENCE, source="defillama", result="duplicate") == before_dup + 4

        # content conflict: same evidence_id different content → conflicts++
        from app.opportunity.models import EvidenceRecord

        conflict_id = build_evidence_id(snapshot_id="snap-conflict", project_id="proj-1", factor_key="tvl_usd")
        first = EvidenceRecord(
            evidence_id=conflict_id,
            project_id="proj-1",
            factor_key="tvl_usd",
            value="1.00000000",
            value_type="string",
            observation_type="observed",
            source_url="https://api.llama.fi/protocol/example",
            source_type="public_aggregator",
            source_grade="C",
            observed_at=NOW,
            effective_at=NOW,
            expires_at=EXPIRES,
            verification_status="verified",
            independence_group="defillama-protocols",
            raw_snapshot_ref="econ-snapshot:snap-conflict",
        )
        evid_repo.add_economic_evidence_if_absent(first)
        # Force conflict via direct second insert path through emit by pre-seeding
        # different content under same id is exercised by repository; emitter maps
        # EconomicEvidenceContentConflict → conflicts + content_conflict metric.
        before_cc = _metric(OPPORTUNITY_ECONOMIC_EVIDENCE, source="defillama", result="content_conflict")
        # Build observation that would emit same evidence_id with different value
        # by using same snapshot/project/factor but different factor value; evidence_id
        # is derived from snapshot+project+factor only — so conflict needs pre-seeded
        # row with same id but different body. Use snap-conflict observation.
        conflict_obs = _observation(
            snapshot_id="snap-conflict",
            factors=(_factor(factor_key="tvl_usd", value="999.00000000", value_type="string"),),
        )
        summary_cc = emitter.emit(conflict_obs, enabled=True)
        assert summary_cc.conflicts == 1
        assert _metric(OPPORTUNITY_ECONOMIC_EVIDENCE, source="defillama", result="content_conflict") == before_cc + 1
        # row content never overwritten
        stored = next(r for r in evid_repo.list_evidence("proj-1") if r.evidence_id == conflict_id)
        assert stored.value == "1.00000000"

        # CG whitelist subset (market_cap/price/volume/circulating/rank/24h)
        _seed_raw(
            conn,
            raw_id="raw-cg",
            source_id="coingecko",
            dedup_key="coin:example",
            project_id="proj-1",
        )
        cg_factors = (
            _factor(
                factor_key="market_cap_usd",
                value="1.00000000",
                value_type="string",
                source_id="coingecko",
                source_url="https://api.coingecko.com/api/v3/coins/example",
            ),
            _factor(
                factor_key="price_usd",
                value="2.00000000",
                value_type="string",
                source_id="coingecko",
                source_url="https://api.coingecko.com/api/v3/coins/example",
            ),
            _factor(
                factor_key="volume_24h_usd",
                value="3.00000000",
                value_type="string",
                source_id="coingecko",
                source_url="https://api.coingecko.com/api/v3/coins/example",
            ),
            _factor(
                factor_key="circulating_supply",
                value="4.00000000",
                value_type="string",
                source_id="coingecko",
                source_url="https://api.coingecko.com/api/v3/coins/example",
            ),
            _factor(
                factor_key="market_rank",
                value=5,
                value_type="number",
                source_id="coingecko",
                source_url="https://api.coingecko.com/api/v3/coins/example",
            ),
            _factor(
                factor_key="price_change_24h_ratio",
                value="0.01000000",
                value_type="string",
                source_id="coingecko",
                source_url="https://api.coingecko.com/api/v3/coins/example",
            ),
            # not on CG whitelist
            _factor(
                factor_key="price_change_7d_ratio",
                value="0.02000000",
                value_type="string",
                source_id="coingecko",
                source_url="https://api.coingecko.com/api/v3/coins/example",
            ),
            _factor(
                factor_key="total_supply",
                value="6.00000000",
                value_type="string",
                source_id="coingecko",
                source_url="https://api.coingecko.com/api/v3/coins/example",
            ),
        )
        cg_obs = NormalizedObservation(
            snapshot_id="snap-cg-1",
            source_id="coingecko",
            dedup_key="coin:example",
            provider_entity_id="cg-1",
            factors=cg_factors,
            collected_at=NOW,
            source_url="https://api.coingecko.com/api/v3/coins/example",
        )
        cg_summary = emitter.emit(cg_obs, enabled=True)
        assert cg_summary.emitted == 6
        cg_rows = [r for r in evid_repo.list_evidence("proj-1") if r.raw_snapshot_ref == "econ-snapshot:snap-cg-1"]
        assert {r.factor_key for r in cg_rows} == {
            "market_cap_usd",
            "price_usd",
            "volume_24h_usd",
            "circulating_supply",
            "market_rank",
            "price_change_24h_ratio",
        }
        assert all(r.source_type == "public_market_data" for r in cg_rows)
        assert all(r.independence_group == "market-aggregators" for r in cg_rows)
        assert all(r.value_type == "number" if r.factor_key == "market_rank" else True for r in cg_rows)

        # CR whitelist: market_cap/price/volume/circulating/total/rank/24h/7d
        _seed_raw(
            conn,
            raw_id="raw-cr",
            source_id="cryptorank",
            dedup_key="coin:example-cr",
            project_id="proj-1",
        )
        cr_url = "https://api.cryptorank.io/v1/currencies/example"
        cr_factors = (
            _factor(
                factor_key="market_cap_usd",
                value="10.00000000",
                value_type="string",
                source_id="cryptorank",
                source_url=cr_url,
            ),
            _factor(
                factor_key="price_usd",
                value="11.00000000",
                value_type="string",
                source_id="cryptorank",
                source_url=cr_url,
            ),
            _factor(
                factor_key="volume_24h_usd",
                value="12.00000000",
                value_type="string",
                source_id="cryptorank",
                source_url=cr_url,
            ),
            _factor(
                factor_key="circulating_supply",
                value="13.00000000",
                value_type="string",
                source_id="cryptorank",
                source_url=cr_url,
            ),
            _factor(
                factor_key="total_supply",
                value="14.00000000",
                value_type="string",
                source_id="cryptorank",
                source_url=cr_url,
            ),
            _factor(
                factor_key="market_rank",
                value=15,
                value_type="number",
                source_id="cryptorank",
                source_url=cr_url,
            ),
            _factor(
                factor_key="price_change_24h_ratio",
                value="0.03000000",
                value_type="string",
                source_id="cryptorank",
                source_url=cr_url,
            ),
            _factor(
                factor_key="price_change_7d_ratio",
                value="0.04000000",
                value_type="string",
                source_id="cryptorank",
                source_url=cr_url,
            ),
            # not on CR whitelist (DL-only)
            _factor(
                factor_key="tvl_usd",
                value="99.00000000",
                value_type="string",
                source_id="cryptorank",
                source_url=cr_url,
            ),
            _factor(
                factor_key="chains_json",
                value=["eth"],
                value_type="json",
                source_id="cryptorank",
                source_url=cr_url,
            ),
        )
        cr_obs = NormalizedObservation(
            snapshot_id="snap-cr-1",
            source_id="cryptorank",
            dedup_key="coin:example-cr",
            provider_entity_id="cr-1",
            factors=cr_factors,
            collected_at=NOW,
            source_url=cr_url,
        )
        cr_summary = emitter.emit(cr_obs, enabled=True)
        assert cr_summary.emitted == 8
        cr_rows = [r for r in evid_repo.list_evidence("proj-1") if r.raw_snapshot_ref == "econ-snapshot:snap-cr-1"]
        assert {r.factor_key for r in cr_rows} == {
            "market_cap_usd",
            "price_usd",
            "volume_24h_usd",
            "circulating_supply",
            "total_supply",
            "market_rank",
            "price_change_24h_ratio",
            "price_change_7d_ratio",
        }
        assert all(r.source_type == "public_market_data" for r in cr_rows)
        assert all(r.independence_group == "market-aggregators" for r in cr_rows)
        assert all(r.value_type == "number" if r.factor_key == "market_rank" else True for r in cr_rows)
        assert "tvl_usd" not in {r.factor_key for r in cr_rows}
    finally:
        snap_repo.close()
        evid_repo.close()
        conn.close()


def test_replay_economic_snapshots_for_project_enabled_false_is_immediate_noop() -> None:
    from app.opportunity import economic_evidence as mod
    from app.opportunity.economic_evidence import replay_economic_snapshots_for_project

    raw, conn, snap_repo, evid_repo = _sqlite_stack()
    try:
        _seed_project(conn, "proj-replay")
        _seed_raw(
            conn,
            raw_id="raw-replay",
            source_id="defillama",
            dedup_key="protocol:replay",
            project_id="proj-replay",
        )

        before_ev = {
            result: _metric(OPPORTUNITY_ECONOMIC_EVIDENCE, source="defillama", result=result)
            for result in (
                "emitted",
                "skipped_no_project",
                "duplicate",
                "skipped_flag_off",
                "content_conflict",
            )
        }
        before_id = {
            result: _metric(OPPORTUNITY_ECONOMIC_IDENTITY_RESOLUTION, source="defillama", result=result)
            for result in ("linked", "unlinked")
        }

        with (
            patch.object(
                EconomicSnapshotRepository,
                "list_by_identity",
                wraps=snap_repo.list_by_identity,
            ) as list_spy,
            patch.object(
                mod,
                "observation_from_snapshot",
                wraps=mod.observation_from_snapshot,
            ) as recon_spy,
            patch.object(
                OpportunityRepository,
                "add_economic_evidence_if_absent",
                wraps=evid_repo.add_economic_evidence_if_absent,
            ) as add_spy,
        ):
            # Spy on conn.execute for snapshot-related SELECTs via wrapping
            execute_calls: list[str] = []
            real_execute = conn.execute

            def tracking_execute(sql, params=None):
                execute_calls.append(" ".join(str(sql).split()).lower())
                if params is None:
                    return real_execute(sql)
                return real_execute(sql, params)

            conn.execute = tracking_execute  # type: ignore[method-assign]

            result = replay_economic_snapshots_for_project(
                "proj-replay",
                conn=conn,
                enabled=False,
            )

            assert result is None
            assert list_spy.call_count == 0
            assert recon_spy.call_count == 0
            assert add_spy.call_count == 0
            # zero snapshot / raw identity queries
            assert not any("opportunity_economic_snapshots" in s for s in execute_calls)
            assert not any("raw_projects" in s for s in execute_calls)

        for result_name, before in before_ev.items():
            assert _metric(OPPORTUNITY_ECONOMIC_EVIDENCE, source="defillama", result=result_name) == before
        for result_name, before in before_id.items():
            assert (
                _metric(
                    OPPORTUNITY_ECONOMIC_IDENTITY_RESOLUTION,
                    source="defillama",
                    result=result_name,
                )
                == before
            )
        assert raw.execute("SELECT COUNT(*) FROM opportunity_evidence").fetchone()[0] == 0
    finally:
        snap_repo.close()
        evid_repo.close()
        conn.close()


def test_replay_reconstructs_and_emits_with_row_isolation() -> None:
    from app.opportunity.economic_evidence import (
        EconomicEvidenceSummary,
        replay_economic_snapshots_for_project,
    )

    raw, conn, snap_repo, evid_repo = _sqlite_stack()
    try:
        _seed_project(conn, "proj-iso")
        _seed_raw(
            conn,
            raw_id="raw-iso",
            source_id="defillama",
            dedup_key="protocol:iso",
            project_id="proj-iso",
        )

        good_payload = {
            "tvl": 1_000_000,
            "change_7d": 0.05,
            "change_7d_unit": "ratio",
            "chains": ["ethereum"],
            "no_token_yet": True,
        }
        good_digest = payload_sha256(good_payload)
        good_id = build_snapshot_id(
            run_id="run-good",
            source_id="defillama",
            provider_entity_id="ent-good",
            payload_sha256_hex=good_digest,
        )
        good = EconomicSnapshotRow(
            snapshot_id=good_id,
            schema_version=SCHEMA_VERSION,
            run_id="run-good",
            source_id="defillama",
            dedup_key="protocol:iso",
            provider_entity_id="ent-good",
            payload_sha256=good_digest,
            payload_json=good_payload,
            source_url="https://api.llama.fi/protocol/example",
            collected_at=NOW,
        )
        # Bad snapshot: schema_version ok but payload hash will fail reconstruction
        bad_payload = {"tvl": 1}
        bad = EconomicSnapshotRow(
            snapshot_id="bad-snap-id-not-hash-based-but-ok",
            schema_version=SCHEMA_VERSION,
            run_id="run-bad",
            source_id="defillama",
            dedup_key="protocol:iso",
            provider_entity_id="ent-bad",
            payload_sha256="0" * 64,
            payload_json=bad_payload,
            source_url="https://api.llama.fi/protocol/example",
            collected_at=NOW,
        )
        snap_repo.insert_if_absent(good)
        # insert bad via direct SQL to skip model if needed — model allows any payload
        snap_repo.insert_if_absent(bad)

        summary = replay_economic_snapshots_for_project(
            "proj-iso",
            conn=conn,
            enabled=True,
        )
        assert isinstance(summary, EconomicEvidenceSummary)
        # Good row still emitted despite bad row reconstruction failure
        assert summary.emitted >= 1
        count = raw.execute("SELECT COUNT(*) FROM opportunity_evidence").fetchone()[0]
        assert count >= 1
        # Snapshots unchanged (2 rows)
        assert raw.execute("SELECT COUNT(*) FROM opportunity_economic_snapshots").fetchone()[0] == 2
        # No HTTP — module must not import/use requests; smoke via no network side effects
    finally:
        snap_repo.close()
        evid_repo.close()
        conn.close()
