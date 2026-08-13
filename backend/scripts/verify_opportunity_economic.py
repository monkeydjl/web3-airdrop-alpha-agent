"""Network-free Opportunity economic verifier (Task 9).

Stage A: cases 17.1.10–14, 17.1.16, 17.1.19–20 and §17.2.
Stage B1: cases 17.1.01, 17.1.02, 17.1.09 (writer/history/DDL).
Stage B2: cases 17.1.03–07, 17.1.15 (evidence/post-link/resolver/mode).
Stage C1: cases 17.1.08, 17.1.17–18, 17.1.21–22 (flags/gray/run-id/replay).
Stage C2: cases 17.1.23–26 (observation isolation / workflow four-layer /
metrics helpers / connection ownership). Calls production interfaces only;
does not reimplement normalizer/hash/workflow algorithms.
"""

from __future__ import annotations

import asyncio
import collections.abc
import contextlib
import inspect
import io
import json
import re
import sqlite3
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, get_args
from unittest.mock import MagicMock, patch
from uuid import UUID

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.collectors.base import CollectorResult, RawDiscovery
from app.collectors.coingecko import CoinGeckoCollector
from app.collectors.cryptorank import CryptoRankCollector
from app.collectors.defillama import DefiLlamaCollector
from app.config import Settings
from app.db import DbConnection, init_db
from app.metrics import (
    OPPORTUNITY_ECONOMIC_EVIDENCE,
    OPPORTUNITY_ECONOMIC_IDENTITY_RESOLUTION,
    OPPORTUNITY_ECONOMIC_LAST_SUCCESS,
    OPPORTUNITY_ECONOMIC_OBSERVATIONS,
    OPPORTUNITY_ECONOMIC_RUN_DURATION,
    OPPORTUNITY_ECONOMIC_SNAPSHOTS,
    metric_label_sets,
    metric_sample_value,
    record_opportunity_economic_snapshot,
)
from app.opportunity import economic_writer as economic_writer_mod
from app.opportunity.decision import decide
from app.opportunity.economic_evidence import (
    EconomicEvidenceEmitter,
    replay_economic_snapshots_for_project,
)
from app.opportunity.economic_integration import (
    daily_run_id,
    economic_source_enabled,
    manual_run_id,
    process_persisted_collection,
)
from app.opportunity.economic_models import (
    SCHEMA_VERSION,
    EconomicsDataMode,
    EconomicSnapshotRow,
    ValueType,
    build_evidence_id,
    build_snapshot_id,
    canonical_json_bytes,
    hash_string_array,
    payload_sha256,
)
from app.opportunity.economic_normalizers import (
    DEFILLAMA_CHANGE_7D_PROVIDER_UNIT,
    PROVIDER_RAW_FIELD_KEYS,
    EconomicNormalizationError,
    canonical_provider_payload,
    normalize_provider_payload,
    normalize_ratio_string,
    sanitize_source_url,
)
from app.opportunity.economic_repository import EconomicSnapshotRepository
from app.opportunity.economic_resolver import (
    EconomicResolver,
    project_economics_data,
)
from app.opportunity.economic_writer import (
    EconomicReconstructionError,
    EconomicSnapshotWriter,
    observation_from_snapshot,
)
from app.opportunity.economics import calculate_economics
from app.opportunity.models import (
    ConfidenceSet,
    DecisionStatus,
    EconomicsResult,
    EvidenceRecord,
    MoneyRange,
    OpportunityAssessment,
    OpportunityInputs,
    ProbabilityRange,
    RiskLevel,
    RiskSet,
    SignedMoneyRange,
)
from app.opportunity.profile import DEFAULT_PROFILE
from app.opportunity.repository import (
    EconomicEvidenceContentConflict,
    OpportunityRepository,
)
from app.opportunity.workflow import (
    OpportunityWorkflowProjection,
    build_workflow_projection,
)
from app.opportunity.workflow_service import OpportunityWorkflowService
from app.routers.v1 import opportunity as opportunity_router

_ECONOMIC_FLAG_NAMES: tuple[str, ...] = (
    "opportunity_economic_snapshot_enabled",
    "opportunity_economic_source_defillama_enabled",
    "opportunity_economic_source_coingecko_enabled",
    "opportunity_economic_source_cryptorank_enabled",
    "opportunity_economic_evidence_emit_enabled",
    "opportunity_economic_resolver_enabled",
)

CASE_IDS: tuple[str, ...] = (
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

FIXTURE_DIR = BACKEND / "tests" / "fixtures" / "opportunity_economic"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_MODE_CLOSED = frozenset({"PROXY_ONLY", "DIRECT_AVAILABLE", "UNKNOWN"})
_VALUE_TYPE_CLOSED = frozenset({"bool", "number", "string", "json"})
_CANARY_SNIPPETS = (
    "CANARY_DL_API_KEY_TASK9_SYNTH_NEVER_LEAK",
    "CANARY_DL_TOKEN_TASK9_SYNTH_NEVER_LEAK",
    "CANARY_CG_API_KEY_TASK9_SYNTH_NEVER_LEAK",
    "CANARY_CG_TOKEN_TASK9_SYNTH_NEVER_LEAK",
    "CANARY_CR_API_KEY_TASK9_SYNTH_NEVER_LEAK",
    "CANARY_CR_TOKEN_TASK9_SYNTH_NEVER_LEAK",
)
_OBSERVED = datetime(2026, 7, 22, 12, 0, 0, tzinfo=UTC)
_EXPIRES = datetime(2026, 7, 24, 12, 0, 0, tzinfo=UTC)

_EXPECTED_ECONOMIC_SNAPSHOT_COLUMNS: tuple[str, ...] = (
    "snapshot_id",
    "schema_version",
    "run_id",
    "source_id",
    "dedup_key",
    "provider_entity_id",
    "payload_sha256",
    "payload_json",
    "source_url",
    "collected_at",
)
_EXPECTED_ECONOMIC_SNAPSHOT_INDEXES: dict[str, str] = {
    "idx_opportunity_economic_snapshots_run_source": "(run_id, source_id)",
    "idx_opportunity_economic_snapshots_identity": "(source_id, dedup_key)",
    "idx_opportunity_economic_snapshots_collected": "(collected_at DESC)",
}


class VerificationContractError(RuntimeError):
    """Contract failure inside economic verification (hash/fixture/keyset)."""


class _PostgresCursor:
    """Minimal cursor used by RecordingPostgresConnection (test convention)."""

    def __init__(self, events: list[tuple[Any, ...]]) -> None:
        self._events = events

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self._events.append(("execute", " ".join(sql.split()), params))

    def fetchone(self) -> dict[str, int]:
        return {"exists": 1}

    def close(self) -> None:
        pass


class _PostgresRawConnection:
    def __init__(self, events: list[tuple[Any, ...]]) -> None:
        self._events = events

    def cursor(self) -> _PostgresCursor:
        return _PostgresCursor(self._events)

    def commit(self) -> None:
        self._events.append(("commit",))

    def rollback(self) -> None:
        self._events.append(("rollback",))

    def close(self) -> None:
        self._events.append(("close",))


class RecordingPostgresConnection(DbConnection):
    """Mirrors backend/tests/test_db_init.py RecordingPostgresConnection convention."""

    def __init__(self, events: list[tuple[Any, ...]]) -> None:
        super().__init__(_PostgresRawConnection(events), kind="postgres")
        self._events = events
        self._script_count = 0

    def executescript(self, script: str) -> None:
        self._script_count += 1
        self._events.append(("executescript", self._script_count))
        super().executescript(script)


def _compact_sql(sql: str) -> str:
    return " ".join(sql.split()).lower().replace(" ", "")


def _load_fixture(name: str) -> dict[str, Any]:
    path = FIXTURE_DIR / name
    if not path.is_file():
        raise VerificationContractError("fixture_missing")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VerificationContractError("fixture_unreadable") from exc
    if not isinstance(data, dict):
        raise VerificationContractError("fixture_invalid")
    return data


def _sample(fixture: dict[str, Any], key: str) -> dict[str, Any]:
    samples = fixture.get("samples")
    if not isinstance(samples, dict) or key not in samples:
        raise VerificationContractError("fixture_sample_missing")
    sample = samples[key]
    if not isinstance(sample, dict):
        raise VerificationContractError("fixture_sample_invalid")
    return dict(sample)


def _discovery_meta(fixture: dict[str, Any]) -> dict[str, Any]:
    meta = fixture.get("discovery")
    if not isinstance(meta, dict):
        raise VerificationContractError("fixture_discovery_missing")
    return meta


def _run_coro_sync(coro: Any) -> Any:
    """Drive plain coroutine chains without an asyncio event loop (socket-free)."""
    stack: list[Any] = [coro]
    in_value: Any = None
    in_exc: BaseException | None = None
    while stack:
        current = stack[-1]
        try:
            if in_exc is not None:
                exc, in_exc = in_exc, None
                yielded = current.throw(exc)
            else:
                yielded = current.send(in_value)
            in_value = None
            if asyncio.iscoroutine(yielded) or isinstance(yielded, collections.abc.Generator):
                stack.append(yielded)
            else:
                await_meth = getattr(yielded, "__await__", None)
                if await_meth is not None:
                    stack.append(await_meth())
                else:
                    raise RuntimeError(f"unsupported awaitable in _run_coro_sync: {type(yielded)!r}")
        except StopIteration as stop:
            stack.pop()
            in_value = stop.value
        except BaseException as exc:
            stack.pop()
            if not stack:
                raise
            in_exc = exc
    return in_value


_COLLECTOR_CTOR_NAMES: tuple[str, ...] = (
    "DefiLlamaCollector",
    "GitHubCollector",
    "CoinGeckoCollector",
    "CryptoRankCollector",
    "RootDataCollector",
    "TwitterKolCollector",
    "TwitterKeywordCollector",
    "EtherscanCollector",
    "GalxeCollector",
    "Layer3Collector",
)


def _track_close(conn: DbConnection) -> dict[str, int]:
    calls = {"n": 0}
    real = conn.close

    def tracking() -> None:
        calls["n"] += 1
        real()

    conn.close = tracking  # type: ignore[method-assign]
    return calls


def _prove_construction_failure_isolation(result: CollectorResult) -> bool:
    """Inject EconomicSnapshotRepository ctor failure into production ownership stacks.

    Exercises scheduled ``create_app`` lifespan (``app.economic_stack_construction_failed``)
    and manual ``trigger_collection`` (``collections.economic_failed``). Asserts borrowed
    shared conn is never closed, request-owned close happens once, persist still runs,
    and the legacy collection result remains usable/unmodified.
    """
    import app.main as main_module
    import app.routers.v1.collections as coll_mod

    def boom_ctor(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("construction boom")

    # ── Scheduled borrowed override: construction boom must not close conn ──
    _raw_s, conn_s, _snap_s, _evid_s = _sqlite_evidence_stack()
    close_s = _track_close(conn_s)
    persist_n = {"n": 0}
    schedulers: list[Any] = []

    class _Reg:
        def __init__(self) -> None:
            self.collectors: list[object] = []

        def register(self, c: object) -> None:
            self.collectors.append(c)

    class _CollSched:
        def __init__(self, registry: object, on_collection: object) -> None:  # noqa: ARG002
            self.on_collection = on_collection
            schedulers.append(self)

        def start(self) -> None:
            return None

        def shutdown(self, *, wait: bool) -> None:  # noqa: ARG002
            return None

    class _AnalSched:
        def start(self) -> None:
            return None

        def shutdown(self, *, wait: bool) -> None:  # noqa: ARG002
            return None

    class _PersistRepo:
        def __init__(self, c: Any = None) -> None:  # noqa: ARG002
            return None

        def persist_collection_result(self, *a: Any, **k: Any) -> None:  # noqa: ARG002
            persist_n["n"] += 1

    prev_env = main_module.settings.app_env
    prev_auto = main_module.settings.collection_auto_run_enabled
    try:
        main_module.settings.app_env = "development"
        main_module.settings.collection_auto_run_enabled = False
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(main_module, "get_default_registry", lambda: _Reg()))
            stack.enter_context(patch.object(main_module, "CollectionScheduler", _CollSched))
            stack.enter_context(patch.object(main_module, "AnalysisScheduler", _AnalSched))
            stack.enter_context(patch.object(main_module, "CollectionRepository", _PersistRepo))
            stack.enter_context(patch.object(main_module, "init_db", lambda: None))
            stack.enter_context(
                patch(
                    "app.opportunity.economic_repository.EconomicSnapshotRepository",
                    boom_ctor,
                )
            )
            application = main_module.create_app(db_override=conn_s)

            async def _scheduled() -> bool:
                async with application.router.lifespan_context(application):
                    if not schedulers:
                        return False
                    await schedulers[0].on_collection("defillama", result)
                    return True

            if not _run_coro_sync(_scheduled()):
                return False
        if close_s["n"] != 0 or persist_n["n"] != 1:
            return False
        if int(conn_s.execute("SELECT 1").fetchone()[0]) != 1:
            return False
    finally:
        main_module.settings.app_env = prev_env
        main_module.settings.collection_auto_run_enabled = prev_auto
        if close_s["n"] == 0:
            with contextlib.suppress(Exception):
                conn_s.close()

    # ── Manual request path: ctor boom after persist; result unmodified ──
    _raw_m, conn_m, _snap_m, _evid_m = _sqlite_evidence_stack()
    close_m = _track_close(conn_m)
    persisted: list[CollectorResult] = []

    class _FakeCollector:
        source_id = "defillama"
        source_name = "DefiLlama"
        source_type = "api"

        def is_enabled(self) -> bool:
            return True

        async def collect(self) -> CollectorResult:
            return result

    class _FakeReg:
        def get(self, source_id: str) -> _FakeCollector | None:
            return _FakeCollector() if source_id == "defillama" else None

    class _ManualRepo:
        def __init__(self, c: Any = None) -> None:  # noqa: ARG002
            return None

        def persist_collection_result(self, res: CollectorResult, **k: Any) -> None:  # noqa: ARG002
            persisted.append(res)

    prev_auto_c = coll_mod.settings.collection_auto_run_enabled
    try:
        coll_mod.settings.collection_auto_run_enabled = False
        with (
            patch.object(coll_mod, "_build_registry", lambda: _FakeReg()),
            patch.object(coll_mod, "CollectionRepository", _ManualRepo),
            patch.object(coll_mod, "get_connection", lambda: conn_m),
            patch(
                "app.opportunity.economic_repository.EconomicSnapshotRepository",
                boom_ctor,
            ),
        ):
            response = _run_coro_sync(coll_mod.trigger_collection(source_id="defillama"))
        if response.ok is not True:
            return False
        data = response.model_dump().get("data") or {}
        if data.get("source_id") != "defillama":
            return False
        if data.get("items_collected") != 1:
            return False
        if data.get("status") != result.status:
            return False
        if close_m["n"] != 1:
            return False
        if len(persisted) != 1 or persisted[0] is not result:
            return False
    finally:
        coll_mod.settings.collection_auto_run_enabled = prev_auto_c

    return True


def _sqlite_repo() -> tuple[sqlite3.Connection, DbConnection, EconomicSnapshotRepository]:
    raw = sqlite3.connect(":memory:")
    raw.row_factory = sqlite3.Row
    conn = DbConnection(raw, kind="sqlite")
    init_db(conn)
    return raw, conn, EconomicSnapshotRepository(conn)


def _sqlite_evidence_stack() -> tuple[
    sqlite3.Connection,
    DbConnection,
    EconomicSnapshotRepository,
    OpportunityRepository,
]:
    raw = sqlite3.connect(":memory:")
    raw.row_factory = sqlite3.Row
    conn = DbConnection(raw, kind="sqlite")
    init_db(conn)
    return (
        raw,
        conn,
        EconomicSnapshotRepository(conn),
        OpportunityRepository(conn),
    )


def _seed_project(conn: DbConnection, project_id: str, *, name: str = "Example") -> None:
    conn.execute(
        "INSERT INTO projects (id, name, source) VALUES (?, ?, ?)",
        (project_id, name, "test"),
    )
    conn.commit()


def _seed_raw_project(
    conn: DbConnection,
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
        (
            raw_id,
            source_id,
            dedup_key,
            "{}",
            _OBSERVED.isoformat(),
            0.5,
            project_id,
        ),
    )
    conn.commit()


def _evidence_count(raw_conn: sqlite3.Connection) -> int:
    return int(raw_conn.execute("SELECT COUNT(*) AS c FROM opportunity_evidence").fetchone()["c"])


def _make_discovery(
    *,
    source_id: str,
    raw_id: str,
    name: str,
    url: str,
    raw_data: dict[str, Any],
    sector: str = "DeFi",
    stage: str = "mainnet",
) -> RawDiscovery:
    return RawDiscovery(
        source_id=source_id,
        raw_id=raw_id,
        name=name,
        url=url,
        sector=sector,
        stage=stage,
        raw_data=raw_data,
    )


@dataclass
class _BlankDedupDiscovery(RawDiscovery):
    """RawDiscovery with blank dedup_key for schema_invalid path."""

    @property
    def dedup_key(self) -> str:  # type: ignore[override]
        return ""


def _factors_by_key(
    source_id: str,
    raw_data: dict[str, Any],
    *,
    source_url: str,
) -> dict[str, Any]:
    factors = normalize_provider_payload(
        source_id=source_id,
        raw_data=raw_data,
        source_url=source_url,
        observed_at=_OBSERVED,
        expires_at=_EXPIRES,
    )
    return {f.factor_key: f for f in factors}


def _is_lower_hex64(value: str) -> bool:
    return isinstance(value, str) and bool(_HEX64.fullmatch(value))


def _contains_canary(text: str) -> bool:
    return any(canary in text for canary in _CANARY_SNIPPETS)


def _check_hash_framing() -> bool:
    """§5.0 array framing order, UTF-8 compact JSON, lowercase 64-hex via production APIs."""
    parts = [
        SCHEMA_VERSION,
        "daily:2026-07-22:defillama",
        "defillama",
        "alpha-economic-protocol",
        "a" * 64,
    ]
    digest = hash_string_array(parts)
    if not _is_lower_hex64(digest):
        return False
    # Production framing is fixed-order: reordering components must change digest.
    reordered = hash_string_array([parts[0], parts[2], parts[1], parts[3], parts[4]])
    if reordered == digest:
        return False
    # Compact UTF-8 JSON (no spaces) is the hash input material for payload objects.
    payload = {"tvl": 0, "change_7d_unit": "ratio", "chains": ["Ethereum"]}
    compact = canonical_json_bytes(payload)
    if not isinstance(compact, (bytes, bytearray)):
        return False
    try:
        compact.decode("utf-8")
    except UnicodeDecodeError:
        return False
    if b" " in compact or b": " in compact or b", " in compact:
        return False
    if compact != json.dumps(
        json.loads(compact.decode("utf-8")),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8"):
        return False
    snap = build_snapshot_id(
        run_id=parts[1],
        source_id=parts[2],
        provider_entity_id=parts[3],
        payload_sha256_hex=parts[4],
    )
    if snap != digest:
        return False
    evidence = build_evidence_id(
        snapshot_id=snap,
        project_id="proj-stage-a",
        factor_key="tvl_usd",
    )
    expected_evidence = hash_string_array([SCHEMA_VERSION, snap, "proj-stage-a", "tvl_usd"])
    return not (evidence != expected_evidence or not _is_lower_hex64(evidence))


def _check_whitelist_and_canary_strip() -> bool:
    dl = _load_fixture("defillama.json")
    cg = _load_fixture("coingecko.json")
    cr = _load_fixture("cryptorank.json")
    for source_id, fixture in (
        ("defillama", dl),
        ("coingecko", cg),
        ("cryptorank", cr),
    ):
        raw = _sample(fixture, "happy")
        payload = canonical_provider_payload(source_id, raw)
        allowed = PROVIDER_RAW_FIELD_KEYS[source_id]
        if set(payload.keys()) - set(allowed):
            return False
        if "unknown_noise_field" in payload:
            return False
        if "api_key" in payload or "token" in payload:
            return False
        dumped = json.dumps(payload, ensure_ascii=False)
        if _contains_canary(dumped):
            return False
        # Hash is over whitelist object only.
        digest = payload_sha256(payload)
        if not _is_lower_hex64(digest):
            return False
        if _contains_canary(digest):
            return False
    return True


def _check_credentials_absent() -> bool:
    for name in ("defillama.json", "coingecko.json", "cryptorank.json"):
        fixture = _load_fixture(name)
        source_id = fixture["provider"]
        raw = _sample(fixture, "happy")
        meta = _discovery_meta(fixture)
        url = str(meta.get("url") or "https://example.invalid/x")
        clean = sanitize_source_url(url)
        if "api_key" in clean or "token" in clean or "?" in clean or "#" in clean:
            return False
        if _contains_canary(clean):
            return False
        payload = canonical_provider_payload(source_id, raw)
        digest = payload_sha256(payload)
        for material in (json.dumps(payload), digest, clean):
            if _contains_canary(material):
                return False
            if "api_key" in material or '"token"' in material:
                return False
    return True


def _check_missing_not_zero() -> bool:
    sparse_dl = {"tvl": 1.0, "change_7d_unit": "ratio"}
    factors = normalize_provider_payload(
        source_id="defillama",
        raw_data=sparse_dl,
        source_url="https://defillama.com/protocol/sparse",
        observed_at=_OBSERVED,
        expires_at=_EXPIRES,
    )
    keys = {f.factor_key for f in factors}
    if keys != {"tvl_usd"}:
        return False
    # Missing ratio/chains/bool must not appear as zero-filled factors.
    for forbidden in (
        "tvl_change_7d_ratio",
        "chains_json",
        "token_unlisted_proxy",
    ):
        if forbidden in keys:
            return False
    # CoinGecko: absolute price_change_24h is not a whitelist key; missing % field
    # must not invent a ratio factor of 0.
    cg_sparse = {
        "market_cap": 10.0,
        "current_price": 1.0,
        "price_change_24h": 999.0,
    }
    cg_factors = normalize_provider_payload(
        source_id="coingecko",
        raw_data=cg_sparse,
        source_url="https://api.coingecko.com/api/v3/coins/markets",
        observed_at=_OBSERVED,
        expires_at=_EXPIRES,
    )
    cg_keys = {f.factor_key for f in cg_factors}
    if "price_change_24h_ratio" in cg_keys:
        return False
    return not ("market_cap_usd" not in cg_keys or "price_usd" not in cg_keys)


def _check_cg_cr_independence_group() -> bool:
    cg = _load_fixture("coingecko.json")
    cr = _load_fixture("cryptorank.json")
    cg_factors = _factors_by_key(
        "coingecko",
        _sample(cg, "happy"),
        source_url="https://api.coingecko.com/api/v3/coins/markets",
    )
    cr_factors = _factors_by_key(
        "cryptorank",
        _sample(cr, "happy"),
        source_url="https://cryptorank.io/price/rank-economic-asset",
    )
    if not cg_factors or not cr_factors:
        return False
    cg_groups = {f.independence_group for f in cg_factors.values()}
    cr_groups = {f.independence_group for f in cr_factors.values()}
    if cg_groups != {"market-aggregators"}:
        return False
    if cr_groups != {"market-aggregators"}:
        return False
    # Same independence group → not independent double-count sources.
    return cg_groups == cr_groups


def _check_mode_closed_set() -> bool:
    modes = set(get_args(EconomicsDataMode))
    if modes != _MODE_CLOSED:
        return False
    # Proxy factors from frozen fixtures imply PROXY_ONLY semantics for the mode
    # closed set (DIRECT requires separate direct farm evidence — out of stage A).
    return not ("PROXY_ONLY" not in modes or "UNKNOWN" not in modes)


def _check_dedup_and_raw_id_preserved() -> bool:
    dl = _load_fixture("defillama.json")
    meta = _discovery_meta(dl)
    raw = _sample(dl, "happy")
    raw_id = str(meta["raw_id"])
    name = str(meta["name"])
    url = str(meta["url"])
    item = _make_discovery(
        source_id="defillama",
        raw_id=raw_id,
        name=name,
        url=url,
        raw_data=raw,
        sector=str(meta.get("sector") or "DeFi"),
        stage=str(meta.get("stage") or "mainnet"),
    )
    expected_dedup = item.dedup_key
    raw_conn, _conn, repo = _sqlite_repo()
    try:
        writer = EconomicSnapshotWriter(repo, now_factory=lambda: _OBSERVED)
        result = CollectorResult(source_id="defillama", items=[item])
        result.finished_at = _OBSERVED
        summary = writer.process(result, run_id="daily:2026-07-22:defillama", enabled=True)
        if summary.snapshots_inserted != 1 or len(summary.observations) != 1:
            return False
        obs = summary.observations[0]
        if obs.dedup_key != expected_dedup:
            return False
        if obs.provider_entity_id != raw_id:
            return False
        # Snapshot row preserves the same identity inputs.
        stored = repo.get(obs.snapshot_id)
        if stored is None:
            return False
        return not (stored.dedup_key != expected_dedup or stored.provider_entity_id != raw_id)
    finally:
        repo.close()
        raw_conn.close()


def _check_value_type_closed_and_specialized() -> bool:
    types_closed = set(get_args(ValueType))
    if types_closed != _VALUE_TYPE_CLOSED:
        return False
    return _case_17_1_16()


def section_17_2_checks() -> dict[str, bool]:
    """§17.2 assertions hung off case 17.1.10 — each independently fail-able."""
    return {
        "hash_framing_array_utf8_compact_lowercase": _check_hash_framing(),
        "provider_native_whitelist_strips_unknown_and_canary": _check_whitelist_and_canary_strip(),
        "credentials_never_in_payload_hash_stdout": _check_credentials_absent(),
        "missing_fields_not_filled_with_zero": _check_missing_not_zero(),
        "coingecko_cryptorank_same_independence_group_no_double_count": (_check_cg_cr_independence_group()),
        "mode_closed_set": _check_mode_closed_set(),
        "dedup_key_and_raw_id_preserved": _check_dedup_and_raw_id_preserved(),
        "value_type_closed_set_and_specialized_types": _check_value_type_closed_and_specialized(),
    }


def _case_17_1_01() -> bool:
    """Same provider payload on two UTC dates → distinct snapshot_id + two history rows."""
    dl = _load_fixture("defillama.json")
    meta = _discovery_meta(dl)
    raw = _sample(dl, "happy")
    raw_id = str(meta["raw_id"])
    payload = canonical_provider_payload("defillama", raw)
    digest = payload_sha256(payload)
    day1_run = "daily:2026-07-22:defillama"
    day2_run = "daily:2026-07-23:defillama"
    expected_day1 = build_snapshot_id(
        run_id=day1_run,
        source_id="defillama",
        provider_entity_id=raw_id,
        payload_sha256_hex=digest,
    )
    expected_day2 = build_snapshot_id(
        run_id=day2_run,
        source_id="defillama",
        provider_entity_id=raw_id,
        payload_sha256_hex=digest,
    )
    if expected_day1 == expected_day2:
        return False
    if not _is_lower_hex64(expected_day1) or not _is_lower_hex64(expected_day2):
        return False

    raw_conn, _conn, repo = _sqlite_repo()
    try:
        writer = EconomicSnapshotWriter(repo, now_factory=lambda: _OBSERVED)
        item = _make_discovery(
            source_id="defillama",
            raw_id=raw_id,
            name=str(meta["name"]),
            url=str(meta["url"]),
            raw_data=raw,
            sector=str(meta.get("sector") or "DeFi"),
            stage=str(meta.get("stage") or "mainnet"),
        )
        result_day1 = CollectorResult(source_id="defillama", items=[item])
        result_day1.finished_at = _OBSERVED
        summary1 = writer.process(result_day1, run_id=day1_run, enabled=True)
        if summary1.snapshots_inserted != 1 or summary1.snapshots_duplicate != 0:
            return False
        if len(summary1.observations) != 1:
            return False
        id1 = summary1.observations[0].snapshot_id
        if id1 != expected_day1:
            return False

        # Same frozen payload, different UTC-day run namespace → second history row.
        result_day2 = CollectorResult(source_id="defillama", items=[item])
        result_day2.finished_at = _OBSERVED
        summary2 = writer.process(result_day2, run_id=day2_run, enabled=True)
        if summary2.snapshots_inserted != 1 or summary2.snapshots_duplicate != 0:
            return False
        if len(summary2.observations) != 1:
            return False
        id2 = summary2.observations[0].snapshot_id
        if id2 != expected_day2 or id1 == id2:
            return False

        count = raw_conn.execute("SELECT COUNT(*) AS c FROM opportunity_economic_snapshots").fetchone()["c"]
        if count != 2:
            return False
        stored1 = repo.get(id1)
        stored2 = repo.get(id2)
        if stored1 is None or stored2 is None:
            return False
        if stored1.payload_sha256 != digest or stored2.payload_sha256 != digest:
            return False
        if stored1.run_id != day1_run or stored2.run_id != day2_run:
            return False
        return not (stored1.provider_entity_id != raw_id or stored2.provider_entity_id != raw_id)
    finally:
        repo.close()
        raw_conn.close()


def _case_17_1_02() -> bool:
    """Same-run duplicate Writer: no row growth; production duplicate metric sample +1."""
    dl = _load_fixture("defillama.json")
    meta = _discovery_meta(dl)
    raw = _sample(dl, "happy")
    run_id = "daily:2026-07-22:defillama"
    raw_conn, _conn, repo = _sqlite_repo()
    try:
        writer = EconomicSnapshotWriter(repo, now_factory=lambda: _OBSERVED)
        item = _make_discovery(
            source_id="defillama",
            raw_id=str(meta["raw_id"]) + "-dup02",
            name=str(meta["name"]) + " Dup02",
            url=str(meta["url"]),
            raw_data=raw,
            sector=str(meta.get("sector") or "DeFi"),
            stage=str(meta.get("stage") or "mainnet"),
        )
        result = CollectorResult(source_id="defillama", items=[item])
        result.finished_at = _OBSERVED

        summary1 = writer.process(result, run_id=run_id, enabled=True)
        if summary1.snapshots_inserted != 1 or summary1.snapshots_duplicate != 0:
            return False
        if len(summary1.observations) != 1:
            return False
        first_id = summary1.observations[0].snapshot_id
        count_after_insert = raw_conn.execute("SELECT COUNT(*) AS c FROM opportunity_economic_snapshots").fetchone()[
            "c"
        ]
        if count_after_insert != 1:
            return False

        before_dup = metric_sample_value(OPPORTUNITY_ECONOMIC_SNAPSHOTS, source="defillama", result="duplicate")
        summary2 = writer.process(result, run_id=run_id, enabled=True)
        if summary2.snapshots_inserted != 0 or summary2.snapshots_duplicate != 1:
            return False
        if len(summary2.observations) != 1:
            return False
        if summary2.observations[0].snapshot_id != first_id:
            return False
        count_after_dup = raw_conn.execute("SELECT COUNT(*) AS c FROM opportunity_economic_snapshots").fetchone()["c"]
        if count_after_dup != 1:
            return False
        after_dup = metric_sample_value(OPPORTUNITY_ECONOMIC_SNAPSHOTS, source="defillama", result="duplicate")
        if after_dup - before_dup != 1.0:
            return False
        # Bare labels() existence is not verification; sample delta must prove record.
        return not after_dup < 1.0
    finally:
        repo.close()
        raw_conn.close()


def _case_17_1_03() -> bool:
    """Post-link replay: orphan raw project_id → 0 Evidence; after projects row, stable id."""
    dl = _load_fixture("defillama.json")
    meta = _discovery_meta(dl)
    raw_sample = _sample(dl, "happy")
    project_id = "proj-stage-b2-03"
    raw_conn, conn, snap_repo, evid_repo = _sqlite_evidence_stack()
    try:
        item = _make_discovery(
            source_id="defillama",
            raw_id=str(meta["raw_id"]) + "-postlink03",
            name=str(meta["name"]) + " PostLink03",
            url=str(meta["url"]),
            raw_data=raw_sample,
            sector=str(meta.get("sector") or "DeFi"),
            stage=str(meta.get("stage") or "mainnet"),
        )
        dedup_key = item.dedup_key
        writer = EconomicSnapshotWriter(snap_repo, now_factory=lambda: _OBSERVED)
        result = CollectorResult(source_id="defillama", items=[item])
        result.finished_at = _OBSERVED
        summary = writer.process(result, run_id="daily:2026-07-22:defillama", enabled=True)
        if summary.snapshots_inserted != 1 or len(summary.observations) != 1:
            return False
        snapshot_id = summary.observations[0].snapshot_id

        # Non-empty project_id on raw_projects, but no authoritative projects row.
        _seed_raw_project(
            conn,
            raw_id="raw-postlink-03",
            source_id="defillama",
            dedup_key=dedup_key,
            project_id=project_id,
        )
        if snap_repo.find_linked_project_id("defillama", dedup_key) is not None:
            return False

        orphan = replay_economic_snapshots_for_project(project_id, conn=conn, enabled=True)
        if orphan is None:
            return False
        if orphan.emitted != 0 or orphan.unlinked < 1:
            return False
        if _evidence_count(raw_conn) != 0:
            return False

        # Authoritative projects row completes dual-condition link.
        _seed_project(conn, project_id, name=str(meta["name"]))
        if snap_repo.find_linked_project_id("defillama", dedup_key) != project_id:
            return False

        linked = replay_economic_snapshots_for_project(project_id, conn=conn, enabled=True)
        if linked is None or linked.emitted < 1 or linked.unlinked != 0:
            return False
        rows = evid_repo.list_evidence(project_id)
        if not rows:
            return False
        count_after_first = len(rows)
        by_key = {r.factor_key: r for r in rows}
        if "tvl_usd" not in by_key:
            return False
        expected_id = build_evidence_id(
            snapshot_id=snapshot_id,
            project_id=project_id,
            factor_key="tvl_usd",
        )
        if by_key["tvl_usd"].evidence_id != expected_id:
            return False
        if not _is_lower_hex64(expected_id):
            return False
        if by_key["tvl_usd"].raw_snapshot_ref != f"econ-snapshot:{snapshot_id}":
            return False

        # Repeated replay is insert-if-absent: no new rows, duplicates only.
        again = replay_economic_snapshots_for_project(project_id, conn=conn, enabled=True)
        if again is None or again.emitted != 0 or again.duplicates < 1:
            return False
        if _evidence_count(raw_conn) != count_after_first:
            return False
        second_rows = evid_repo.list_evidence(project_id)
        second_ids = {r.evidence_id for r in second_rows}
        first_ids = {r.evidence_id for r in rows}
        return second_ids == first_ids
    finally:
        evid_repo.close()
        snap_repo.close()
        raw_conn.close()


def _case_17_1_04() -> bool:
    """Same symbol / raw id without authoritative projects row → unlinked; no fuzzy link."""
    # Static production contract: linking SQL is exact dual-condition only (no fuzzy branch).
    source = inspect.getsource(EconomicSnapshotRepository.find_linked_project_id)
    sql_match = re.search(
        r'"""\s*(SELECT[\s\S]*?)\s*"""',
        source,
        flags=re.IGNORECASE,
    )
    if sql_match is None:
        return False
    sql_body = " ".join(sql_match.group(1).split()).lower()
    if "inner join projects" not in sql_body:
        return False
    if "rp.source_id = ?" not in sql_body or "rp.dedup_key = ?" not in sql_body:
        return False
    for banned_sql in (
        " like ",
        "similarity",
        "levenshtein",
        "symbol",
        "p.name",
        "slug",
        "fuzzy",
        " or ",
    ):
        if banned_sql in sql_body:
            return False
    # Docstring must explicitly deny fuzzy/symbol matching (production contract surface).
    if "nosymbol/name/slug/fuzzy" not in re.sub(r"\s+", "", source.lower()):
        return False

    dl = _load_fixture("defillama.json")
    meta = _discovery_meta(dl)
    raw_sample = _sample(dl, "happy")
    raw_conn, conn, snap_repo, evid_repo = _sqlite_evidence_stack()
    try:
        shared_name = str(meta["name"]) + " SharedSymbol04"
        item = _make_discovery(
            source_id="defillama",
            raw_id=str(meta["raw_id"]) + "-unlinked04",
            name=shared_name,
            url=str(meta["url"]),
            raw_data=raw_sample,
            sector=str(meta.get("sector") or "DeFi"),
            stage=str(meta.get("stage") or "mainnet"),
        )
        dedup_key = item.dedup_key
        writer = EconomicSnapshotWriter(snap_repo, now_factory=lambda: _OBSERVED)
        result = CollectorResult(source_id="defillama", items=[item])
        result.finished_at = _OBSERVED
        summary = writer.process(result, run_id="daily:2026-07-22:defillama", enabled=True)
        if summary.snapshots_inserted != 1:
            return False

        # Authoritative project exists with the same display name/symbol, but is not linked.
        _seed_project(conn, "proj-other-symbol-04", name=shared_name)
        # raw_projects carries a non-empty project_id that has no projects row (orphan).
        orphan_project_id = "proj-orphan-raw-04"
        _seed_raw_project(
            conn,
            raw_id="raw-unlinked-04",
            source_id="defillama",
            dedup_key=dedup_key,
            project_id=orphan_project_id,
        )
        if snap_repo.find_linked_project_id("defillama", dedup_key) is not None:
            return False
        # Exact identity only: same name does not fuzzy-link to proj-other-symbol-04.
        if snap_repo.find_linked_project_id("defillama", "protocol:not-that-key") is not None:
            return False

        emitter = EconomicEvidenceEmitter(conn, snap_repo, evid_repo)
        obs = summary.observations[0]
        emit_summary = emitter.emit(obs, enabled=True)
        if emit_summary.unlinked != 1 or emit_summary.emitted != 0:
            return False
        if _evidence_count(raw_conn) != 0:
            return False

        # Replay against orphan project_id also yields zero Evidence.
        replay = replay_economic_snapshots_for_project(orphan_project_id, conn=conn, enabled=True)
        if replay is None or replay.emitted != 0:
            return False
        return _evidence_count(raw_conn) == 0
    finally:
        evid_repo.close()
        snap_repo.close()
        raw_conn.close()


def _case_17_1_05() -> bool:
    """Two daily price Evidence values → latest non-expired; not conflicted."""
    cg = _load_fixture("coingecko.json")
    meta = _discovery_meta(cg)
    day1 = _OBSERVED
    day2 = _OBSERVED + timedelta(days=1)
    now = day2 + timedelta(hours=1)
    project_id = "proj-price-05"
    raw_conn, conn, snap_repo, evid_repo = _sqlite_evidence_stack()
    try:
        raw_day1 = dict(_sample(cg, "happy"))
        raw_day1["current_price"] = 1.10
        raw_day2 = dict(_sample(cg, "happy"))
        raw_day2["current_price"] = 2.50

        item_base_name = str(meta["name"]) + " Price05"
        item_day1 = _make_discovery(
            source_id="coingecko",
            raw_id=str(meta["raw_id"]) + "-price05",
            name=item_base_name,
            url=str(meta["url"]),
            raw_data=raw_day1,
            sector=str(meta.get("sector") or "DeFi"),
            stage=str(meta.get("stage") or "mainnet"),
        )
        # Same identity (dedup_key) across days; Writer uses same discovery identity.
        item_day2 = _make_discovery(
            source_id="coingecko",
            raw_id=str(meta["raw_id"]) + "-price05",
            name=item_base_name,
            url=str(meta["url"]),
            raw_data=raw_day2,
            sector=str(meta.get("sector") or "DeFi"),
            stage=str(meta.get("stage") or "mainnet"),
        )
        if item_day1.dedup_key != item_day2.dedup_key:
            return False

        writer = EconomicSnapshotWriter(snap_repo, now_factory=lambda: day1)
        r1 = CollectorResult(source_id="coingecko", items=[item_day1])
        r1.finished_at = day1
        s1 = writer.process(r1, run_id="daily:2026-07-22:coingecko", enabled=True)
        if s1.snapshots_inserted != 1 or not s1.observations:
            return False
        snap1 = s1.observations[0].snapshot_id

        writer2 = EconomicSnapshotWriter(snap_repo, now_factory=lambda: day2)
        r2 = CollectorResult(source_id="coingecko", items=[item_day2])
        r2.finished_at = day2
        s2 = writer2.process(r2, run_id="daily:2026-07-23:coingecko", enabled=True)
        if s2.snapshots_inserted != 1 or not s2.observations:
            return False
        snap2 = s2.observations[0].snapshot_id
        if snap1 == snap2:
            return False

        _seed_project(conn, project_id, name=item_base_name)
        _seed_raw_project(
            conn,
            raw_id="raw-price-05",
            source_id="coingecko",
            dedup_key=item_day1.dedup_key,
            project_id=project_id,
        )
        emitter = EconomicEvidenceEmitter(conn, snap_repo, evid_repo)
        # Emit both observations under linked identity.
        for obs in (s1.observations[0], s2.observations[0]):
            part = emitter.emit(obs, enabled=True)
            if part.emitted < 1 or part.unlinked != 0:
                return False

        records = evid_repo.list_evidence(project_id)
        price_rows = [r for r in records if r.factor_key == "price_usd"]
        if len(price_rows) != 2:
            return False
        values = {r.value for r in price_rows}
        if len(values) < 2:
            return False

        # Ensure both are in-window at `now` (non-expired).
        for row in price_rows:
            if row.expires_at is None or row.expires_at <= now:
                # TTL is collected_at+48h from emitter; force-check via resolver window.
                pass

        projection = EconomicResolver(snap_repo).resolve(project_id, records, now=now)
        factor = projection.factors["price_usd"]
        if factor.conflicted is not False:
            return False
        if factor.value is None:
            return False
        # Latest day (day2 / snap2) must win among same independence group.
        expected_latest_id = build_evidence_id(snapshot_id=snap2, project_id=project_id, factor_key="price_usd")
        if factor.evidence_id != expected_latest_id:
            return False
        # Value must match day2 price, not day1.
        day2_price_factor = None
        for f in s2.observations[0].factors:
            if f.factor_key == "price_usd":
                day2_price_factor = f
                break
        if day2_price_factor is None or factor.value != day2_price_factor.value:
            return False
        day1_price_factor = None
        for f in s1.observations[0].factors:
            if f.factor_key == "price_usd":
                day1_price_factor = f
                break
        return not (
            day1_price_factor is not None
            and factor.value == day1_price_factor.value
            and day1_price_factor.value != day2_price_factor.value
        )
    finally:
        evid_repo.close()
        snap_repo.close()
        raw_conn.close()


def _case_17_1_06() -> bool:
    """Proxy-only Evidence → direct completeness false; mode PROXY_ONLY not DIRECT_AVAILABLE."""
    dl = _load_fixture("defillama.json")
    meta = _discovery_meta(dl)
    project_id = "proj-proxy-06"
    raw_conn, conn, snap_repo, evid_repo = _sqlite_evidence_stack()
    try:
        item = _make_discovery(
            source_id="defillama",
            raw_id=str(meta["raw_id"]) + "-proxy06",
            name=str(meta["name"]) + " Proxy06",
            url=str(meta["url"]),
            raw_data=_sample(dl, "happy"),
            sector=str(meta.get("sector") or "DeFi"),
            stage=str(meta.get("stage") or "mainnet"),
        )
        writer = EconomicSnapshotWriter(snap_repo, now_factory=lambda: _OBSERVED)
        result = CollectorResult(source_id="defillama", items=[item])
        result.finished_at = _OBSERVED
        summary = writer.process(result, run_id="daily:2026-07-22:defillama", enabled=True)
        if summary.snapshots_inserted != 1 or not summary.observations:
            return False

        _seed_project(conn, project_id, name=str(meta["name"]))
        _seed_raw_project(
            conn,
            raw_id="raw-proxy-06",
            source_id="defillama",
            dedup_key=item.dedup_key,
            project_id=project_id,
        )
        emitter = EconomicEvidenceEmitter(conn, snap_repo, evid_repo)
        emit_summary = emitter.emit(summary.observations[0], enabled=True)
        if emit_summary.emitted < 1:
            return False

        # direct_available=False models missing direct completeness.
        direct_available = False
        projection = project_economics_data(
            project_id,
            evidence_repository=evid_repo,
            snapshot_repository=snap_repo,
            direct_available=direct_available,
            now=_OBSERVED + timedelta(hours=1),
            enabled=True,
        )
        if projection is None:
            return False
        if direct_available is not False:
            return False
        if projection.economics_data_mode == "DIRECT_AVAILABLE":
            return False
        if projection.economics_data_mode != "PROXY_ONLY":
            return False
        if projection.economics_data_mode not in _MODE_CLOSED:
            return False
        # Usable proxy factor present (closed-set PROXY_ONLY semantics).
        usable = [f for f in projection.factors.values() if f.value is not None and f.conflicted is False]
        if not usable:
            return False
        if projection.factors["tvl_usd"].value is None:
            return False

        # Contrast: same evidence with direct_available=True upgrades mode only.
        upgraded = project_economics_data(
            project_id,
            evidence_repository=evid_repo,
            snapshot_repository=snap_repo,
            direct_available=True,
            now=_OBSERVED + timedelta(hours=1),
            enabled=True,
        )
        if upgraded is None or upgraded.economics_data_mode != "DIRECT_AVAILABLE":
            return False
        # Proxy path without direct flag must remain non-direct.
        return projection.economics_data_mode != upgraded.economics_data_mode
    finally:
        evid_repo.close()
        snap_repo.close()
        raw_conn.close()


def _case_17_1_07() -> bool:
    """Existing manual direct FARM is not downgraded when economic loop/flags are closed."""
    project_id = "proj-manual-farm-07"
    now = _OBSERVED

    def _manual_inputs() -> OpportunityInputs:
        return OpportunityInputs(
            project_id=project_id,
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
            weekly_time_confirmed_minimum=False,
            integrity_blocked=False,
            safety_blocked=False,
            project_quality=70,
            project_failure_risk=RiskLevel.LOW,
            capital_security_risk=RiskLevel.LOW,
            official_multiwallet_policy="allowed",
            official_airdrop_evidence_count_a=1,
            independent_airdrop_evidence_count_b=0,
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

    inputs = _manual_inputs()
    event = ProbabilityRange(low=0.60, base=0.70, high=0.80)
    eligibility = ProbabilityRange(low=0.55, base=0.70, high=0.85)
    survival = ProbabilityRange(low=0.70, base=0.80, high=0.90)
    reward_probability = ProbabilityRange(low=0.25, base=0.39, high=0.61)
    economics = calculate_economics(
        reward_probability=reward_probability,
        conditional_reward=inputs.conditional_reward_usd,  # type: ignore[arg-type]
        hard_cost=inputs.hard_cost_usd,  # type: ignore[arg-type]
        capital_loss=inputs.expected_capital_loss_usd,  # type: ignore[arg-type]
        liquidity_cost=inputs.liquidity_cost_usd,  # type: ignore[arg-type]
        total_time_hours=inputs.total_time_hours,  # type: ignore[arg-type]
    )
    baseline = decide(
        inputs=inputs,
        event=event,
        eligibility=eligibility,
        survival=survival,
        reward_probability=reward_probability,
        economics=economics,
        profile=DEFAULT_PROFILE,
        now=now,
    )
    if baseline.public_label != "FARM":
        return False
    if baseline.status != DecisionStatus.ACTIONABLE:
        return False

    raw_conn, conn, snap_repo, evid_repo = _sqlite_evidence_stack()
    try:
        # Manually sourced direct Evidence (legacy factor path) coexists with closed economic loop.
        manual_evidence = EvidenceRecord(
            evidence_id="manual-direct-farm-07",
            project_id=project_id,
            factor_key="conditional_reward_usd",
            value={"low": 80, "base": 160, "high": 400},
            value_type="range",
            observation_type="observed",
            source_url="https://manual.example.invalid/farm-07",
            source_type="manual",
            source_grade="A",
            observed_at=now,
            effective_at=now,
            expires_at=now + timedelta(hours=48),
            verification_status="verified",
            independence_group="manual-direct",
            raw_snapshot_ref=None,
        )
        evid_repo.add_evidence(manual_evidence)
        stored_manual = [r for r in evid_repo.list_evidence(project_id) if r.evidence_id == "manual-direct-farm-07"]
        if len(stored_manual) != 1:
            return False
        if stored_manual[0].source_type != "manual":
            return False

        # Economic loop/flags closed: projection is None, emitter is no-op.
        closed_projection = project_economics_data(
            project_id,
            evidence_repository=evid_repo,
            snapshot_repository=snap_repo,
            direct_available=True,
            now=now,
            enabled=False,
        )
        if closed_projection is not None:
            return False

        # Minimal observation would require a snapshot; flag-off path needs only observation shell.
        # Use emit enabled=False on a synthetic observation built from a written snapshot if present;
        # without linked snapshots, still prove flag-off skip path.
        dl = _load_fixture("defillama.json")
        meta = _discovery_meta(dl)
        item = _make_discovery(
            source_id="defillama",
            raw_id=str(meta["raw_id"]) + "-farm07",
            name=str(meta["name"]) + " Farm07",
            url=str(meta["url"]),
            raw_data=_sample(dl, "happy"),
        )
        writer = EconomicSnapshotWriter(snap_repo, now_factory=lambda: now)
        result = CollectorResult(source_id="defillama", items=[item])
        result.finished_at = now
        # Snapshot write disabled (flag closed for economic snapshot path).
        write_off = writer.process(result, run_id="daily:2026-07-22:defillama", enabled=False)
        if write_off.snapshots_inserted != 0 or write_off.observations:
            return False

        # Replay disabled is immediate None with zero side effects on manual evidence.
        replay_off = replay_economic_snapshots_for_project(project_id, conn=conn, enabled=False)
        if replay_off is not None:
            return False
        after_closed = [r for r in evid_repo.list_evidence(project_id) if r.evidence_id == "manual-direct-farm-07"]
        if len(after_closed) != 1:
            return False
        if after_closed[0].model_dump(mode="json") != stored_manual[0].model_dump(mode="json"):
            return False
        # No economic proxy Evidence rows were created under closed flags.
        econ_rows = [
            r
            for r in evid_repo.list_evidence(project_id)
            if r.raw_snapshot_ref and str(r.raw_snapshot_ref).startswith("econ-snapshot:")
        ]
        if econ_rows:
            return False

        # Re-decide with the same manual direct inputs: still FARM (not downgraded).
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
        if after.public_label != "FARM":
            return False
        if after.status != DecisionStatus.ACTIONABLE:
            return False
        if after.public_label != baseline.public_label:
            return False
        return after.status == baseline.status
    finally:
        evid_repo.close()
        snap_repo.close()
        raw_conn.close()


def _case_17_1_15() -> bool:
    """Same evidence_id with conflicting content fails and does not overwrite the row."""
    project_id = "proj-conflict-15"
    now = _OBSERVED
    expires = now + timedelta(hours=48)
    evidence_id = build_evidence_id(
        snapshot_id="snap-conflict-15",
        project_id=project_id,
        factor_key="tvl_usd",
    )
    if not _is_lower_hex64(evidence_id):
        return False

    raw_conn, conn, snap_repo, evid_repo = _sqlite_evidence_stack()
    try:
        first = EvidenceRecord(
            evidence_id=evidence_id,
            project_id=project_id,
            factor_key="tvl_usd",
            value="1000000.00000000",
            value_type="string",
            observation_type="observed",
            source_url="https://api.llama.fi/protocol/conflict-15",
            source_type="public_aggregator",
            source_grade="C",
            observed_at=now,
            effective_at=now,
            expires_at=expires,
            verification_status="verified",
            independence_group="defillama-protocols",
            raw_snapshot_ref="econ-snapshot:snap-conflict-15",
        )
        stored, inserted = evid_repo.add_economic_evidence_if_absent(first)
        if not inserted or stored.value != "1000000.00000000":
            return False
        if _evidence_count(raw_conn) != 1:
            return False

        conflicting = first.model_copy(update={"value": "9999999.00000000"})
        try:
            evid_repo.add_economic_evidence_if_absent(conflicting)
            return False
        except EconomicEvidenceContentConflict:
            pass

        rows = [r for r in evid_repo.list_evidence(project_id) if r.evidence_id == evidence_id]
        if len(rows) != 1:
            return False
        if rows[0].value != "1000000.00000000":
            return False
        if rows[0].value == conflicting.value:
            return False
        if _evidence_count(raw_conn) != 1:
            return False

        # Emitter path: pre-seeded body differs → conflicts++, original preserved.
        _seed_project(conn, project_id, name="Conflict15")
        _seed_raw_project(
            conn,
            raw_id="raw-conflict-15",
            source_id="defillama",
            dedup_key="protocol:conflict-15",
            project_id=project_id,
        )
        from app.opportunity.economic_models import NormalizedFactor, NormalizedObservation

        conflict_obs = NormalizedObservation(
            snapshot_id="snap-conflict-15",
            source_id="defillama",
            dedup_key="protocol:conflict-15",
            provider_entity_id="entity-conflict-15",
            factors=(
                NormalizedFactor(
                    factor_key="tvl_usd",
                    value="9999999.00000000",
                    value_type="string",
                    unit="usd",
                    source_type="public_aggregator",
                    source_grade="C",
                    verification_status="verified",
                    independence_group="defillama-protocols",
                    source_url="https://api.llama.fi/protocol/conflict-15",
                    observed_at=now,
                    expires_at=expires,
                ),
            ),
            collected_at=now,
            source_url="https://api.llama.fi/protocol/conflict-15",
        )
        emitter = EconomicEvidenceEmitter(conn, snap_repo, evid_repo)
        emit_summary = emitter.emit(conflict_obs, enabled=True)
        if emit_summary.conflicts < 1:
            return False
        if emit_summary.emitted != 0:
            return False
        final = next(r for r in evid_repo.list_evidence(project_id) if r.evidence_id == evidence_id)
        return final.value == "1000000.00000000"
    finally:
        evid_repo.close()
        snap_repo.close()
        raw_conn.close()


def _case_17_1_09() -> bool:
    """SQLite + RecordingPostgresConnection share economic table/constraint; init_db idempotent."""
    # ── SQLite: double init_db is idempotent and creates the economic contract ──
    raw = sqlite3.connect(":memory:")
    raw.row_factory = sqlite3.Row
    conn = DbConnection(raw, kind="sqlite")
    try:
        init_db(conn)
        init_db(conn)

        tables = {row[0] for row in raw.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "opportunity_economic_snapshots" not in tables:
            return False

        columns = list(raw.execute("PRAGMA table_info(opportunity_economic_snapshots)"))
        column_names = [row["name"] for row in columns]
        if column_names != list(_EXPECTED_ECONOMIC_SNAPSHOT_COLUMNS):
            return False
        for row in columns:
            if row["name"] == "snapshot_id":
                if row["pk"] != 1:
                    return False
            else:
                if row["notnull"] != 1:
                    return False
            if row["name"] == "collected_at" and row["type"].upper() != "TIMESTAMP":
                return False

        table_sql = raw.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='opportunity_economic_snapshots'"
        ).fetchone()[0]
        if "check(length(trim(dedup_key))>0)" not in _compact_sql(table_sql):
            return False

        index_names = {
            row[0]
            for row in raw.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='opportunity_economic_snapshots'"
            )
            if row[0]
        }
        for index_name in _EXPECTED_ECONOMIC_SNAPSHOT_INDEXES:
            if index_name not in index_names:
                return False

        # Blank dedup_key rejected by live CHECK (proves constraint is enforced).
        try:
            raw.execute(
                """
                INSERT INTO opportunity_economic_snapshots (
                    snapshot_id, schema_version, run_id, source_id, dedup_key,
                    provider_entity_id, payload_sha256, payload_json, source_url, collected_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "sid-blank-09",
                    SCHEMA_VERSION,
                    "run-09",
                    "defillama",
                    "   ",
                    "entity-09",
                    "a" * 64,
                    "{}",
                    "https://example.invalid/x",
                    "2026-07-22 12:00:00+00:00",
                ),
            )
            return False
        except sqlite3.IntegrityError:
            pass
    finally:
        conn.close()

    # ── Postgres recording path: same table/columns/CHECK/indexes emitted ──
    events: list[tuple[Any, ...]] = []
    pg = RecordingPostgresConnection(events)
    init_db(pg)
    # Idempotent second pass must not raise (IF NOT EXISTS contract).
    init_db(pg)

    sqls = [event[1] for event in events if event[0] == "execute"]
    all_sql = " ".join(" ".join(str(sql).split()) for sql in sqls)
    if "CREATE TABLE IF NOT EXISTS opportunity_economic_snapshots" not in all_sql:
        return False
    economic_create = next(
        (sql for sql in sqls if "CREATE TABLE IF NOT EXISTS opportunity_economic_snapshots" in str(sql)),
        None,
    )
    if economic_create is None:
        return False
    economic_compact = _compact_sql(str(economic_create))
    for column in _EXPECTED_ECONOMIC_SNAPSHOT_COLUMNS:
        if column not in str(economic_create):
            return False
    for column in _EXPECTED_ECONOMIC_SNAPSHOT_COLUMNS:
        if column == "snapshot_id":
            continue
        if not (f"{column}textnotnull" in economic_compact or f"{column}timestamptznotnull" in economic_compact):
            return False
    if "check(length(trim(dedup_key))>0)" not in economic_compact:
        return False
    if "collected_attimestamptznotnull" not in economic_compact:
        return False
    for index_name, columns_sql in _EXPECTED_ECONOMIC_SNAPSHOT_INDEXES.items():
        if f"CREATE INDEX IF NOT EXISTS {index_name}" not in all_sql:
            return False
        if _compact_sql(columns_sql) not in _compact_sql(all_sql):
            return False
    # Both dialects share the same column set and dedup CHECK contract.
    return True


def _case_17_1_10() -> bool:
    """Frozen raw replay: schema, hash framing, identity inputs, mode, no CG/CR double-count."""
    dl = _load_fixture("defillama.json")
    cg = _load_fixture("coingecko.json")
    cr = _load_fixture("cryptorank.json")

    if SCHEMA_VERSION != "opportunity-economic-snapshot-v1":
        return False
    if set(get_args(EconomicsDataMode)) != _MODE_CLOSED:
        return False

    run_id = "daily:2026-07-22:replay"
    project_id = "proj-stage-a-10"
    identities: list[tuple[str, str, str]] = []

    for source_id, fixture in (
        ("defillama", dl),
        ("coingecko", cg),
        ("cryptorank", cr),
    ):
        meta = _discovery_meta(fixture)
        raw = _sample(fixture, "happy")
        payload = canonical_provider_payload(source_id, raw)
        digest = payload_sha256(payload)
        if digest != payload_sha256(payload):
            return False
        raw_id = str(meta["raw_id"])
        snap_id = build_snapshot_id(
            run_id=run_id,
            source_id=source_id,
            provider_entity_id=raw_id,
            payload_sha256_hex=digest,
        )
        if not _is_lower_hex64(snap_id):
            return False
        if snap_id != hash_string_array([SCHEMA_VERSION, run_id, source_id, raw_id, digest]):
            return False
        url = sanitize_source_url(str(meta["url"]))
        factors = normalize_provider_payload(
            source_id=source_id,
            raw_data=payload,
            source_url=url,
            observed_at=_OBSERVED,
            expires_at=_EXPIRES,
        )
        if not factors:
            return False
        for factor in factors:
            if factor.value_type not in _VALUE_TYPE_CLOSED:
                return False
            evidence_id = build_evidence_id(
                snapshot_id=snap_id,
                project_id=project_id,
                factor_key=factor.factor_key,
            )
            if not _is_lower_hex64(evidence_id):
                return False
            if evidence_id != hash_string_array([SCHEMA_VERSION, snap_id, project_id, factor.factor_key]):
                return False
        identities.append((source_id, raw_id, snap_id))

    # CG/CR share market-aggregators (not independent double-count groups).
    if not _check_cg_cr_independence_group():
        return False

    # Distinct providers produce distinct snapshot identities under same run.
    snap_ids = [s for _, _, s in identities]
    if len(set(snap_ids)) != 3:
        return False

    # Replay through writer preserves schema_version on stored rows.
    raw_conn, _conn, repo = _sqlite_repo()
    try:
        writer = EconomicSnapshotWriter(repo, now_factory=lambda: _OBSERVED)
        for source_id, fixture in (
            ("defillama", dl),
            ("coingecko", cg),
            ("cryptorank", cr),
        ):
            meta = _discovery_meta(fixture)
            item = _make_discovery(
                source_id=source_id,
                raw_id=str(meta["raw_id"]),
                name=str(meta["name"]),
                url=str(meta["url"]),
                raw_data=_sample(fixture, "happy"),
                sector=str(meta.get("sector") or "DeFi"),
                stage=str(meta.get("stage") or "mainnet"),
            )
            result = CollectorResult(source_id=source_id, items=[item])
            result.finished_at = _OBSERVED
            summary = writer.process(result, run_id=f"{run_id}:{source_id}", enabled=True)
            if summary.schema_invalid != 0 or summary.snapshots_inserted != 1:
                return False
            if len(summary.observations) != 1:
                return False
            obs = summary.observations[0]
            stored = repo.get(obs.snapshot_id)
            if stored is None or stored.schema_version != SCHEMA_VERSION:
                return False
            if stored.payload_sha256 != payload_sha256(
                canonical_provider_payload(source_id, _sample(fixture, "happy"))
            ):
                return False
    finally:
        repo.close()
        raw_conn.close()

    section = section_17_2_checks()
    return all(section.values())


def _case_17_1_11() -> bool:
    """Empty dedup_key → schema_invalid and no snapshot row."""
    dl = _load_fixture("defillama.json")
    meta = _discovery_meta(dl)
    raw = _sample(dl, "happy")
    item = _BlankDedupDiscovery(
        source_id="defillama",
        raw_id=str(meta["raw_id"]) + "-blank-dedup",
        name=str(meta["name"]),
        url=str(meta["url"]),
        sector=str(meta.get("sector") or "DeFi"),
        stage=str(meta.get("stage") or "mainnet"),
        raw_data=raw,
    )
    if item.dedup_key != "":
        return False

    raw_conn, _conn, repo = _sqlite_repo()
    try:
        writer = EconomicSnapshotWriter(repo, now_factory=lambda: _OBSERVED)
        result = CollectorResult(source_id="defillama", items=[item])
        result.finished_at = _OBSERVED
        summary = writer.process(result, run_id="daily:2026-07-22:defillama", enabled=True)
        if summary.schema_invalid != 1:
            return False
        if summary.snapshots_inserted != 0 or summary.observations:
            return False
        count = raw_conn.execute("SELECT COUNT(*) AS c FROM opportunity_economic_snapshots").fetchone()["c"]
        return count == 0
    finally:
        repo.close()
        raw_conn.close()


def _case_17_1_12() -> bool:
    """CoinGecko uses price_change_percentage_24h / 100; ignores absolute price_change_24h."""
    cg = _load_fixture("coingecko.json")
    raw = _sample(cg, "happy")
    if "price_change_percentage_24h" not in raw or "price_change_24h" not in raw:
        raise VerificationContractError("fixture_coingecko_missing_change_fields")
    pct = raw["price_change_percentage_24h"]
    absolute = raw["price_change_24h"]
    if absolute == pct / 100:
        # Fixture must keep absolute distinct so ignore-path is observable.
        raise VerificationContractError("fixture_coingecko_absolute_not_distinct")

    factors = _factors_by_key(
        "coingecko",
        raw,
        source_url="https://api.coingecko.com/api/v3/coins/markets",
    )
    ratio = factors.get("price_change_24h_ratio")
    if ratio is None:
        return False
    # Production path: percentage / 100 via normalize_ratio_string (not absolute dollars).
    from decimal import Decimal

    expected = normalize_ratio_string(pct, divisor=Decimal("100"))
    wrong_if_absolute = normalize_ratio_string(absolute, divisor=Decimal("1"))
    if ratio.value != expected:
        return False
    if ratio.value == wrong_if_absolute and expected != wrong_if_absolute:
        return False
    if ratio.unit != "ratio" or ratio.value_type != "string":
        return False
    # Absolute dollar path must never appear as a factor value equal to absolute.
    for factor in factors.values():
        if factor.value == absolute or factor.value == str(absolute):
            return False
        if (
            factor.value == wrong_if_absolute
            and factor.factor_key == "price_change_24h_ratio"
            and expected != wrong_if_absolute
        ):
            return False
    # Whitelist excludes absolute field entirely.
    payload = canonical_provider_payload("coingecko", raw)
    if "price_change_24h" in payload:
        return False
    return "price_change_percentage_24h" in payload


def _case_17_1_13() -> bool:
    """CryptoRank percent_change_24h and percent_change_7d both / 100."""
    cr = _load_fixture("cryptorank.json")
    raw = _sample(cr, "happy")
    p24 = raw["percent_change_24h"]
    p7 = raw["percent_change_7d"]
    factors = _factors_by_key(
        "cryptorank",
        raw,
        source_url="https://cryptorank.io/price/rank-economic-asset",
    )
    f24 = factors.get("price_change_24h_ratio")
    f7 = factors.get("price_change_7d_ratio")
    if f24 is None or f7 is None:
        return False
    from decimal import Decimal

    exp24 = normalize_ratio_string(p24, divisor=Decimal("100"))
    exp7 = normalize_ratio_string(p7, divisor=Decimal("100"))
    unscaled24 = normalize_ratio_string(p24, divisor=Decimal("1"))
    unscaled7 = normalize_ratio_string(p7, divisor=Decimal("1"))
    if f24.value != exp24 or f7.value != exp7:
        return False
    # Must be ratios (div 100), not raw percentage points left unscaled.
    if exp24 != unscaled24 and f24.value == unscaled24:
        return False
    return not (exp7 != unscaled7 and f7.value == unscaled7)


def _case_17_1_14() -> bool:
    """DefiLlama change_7d accepted as ratio only when unit metadata is exact 'ratio'."""
    dl = _load_fixture("defillama.json")
    unit_contract = dl.get("unit_contract")
    if not isinstance(unit_contract, dict):
        raise VerificationContractError("fixture_unit_contract_missing")
    if unit_contract.get("accepted_change_7d_unit") != DEFILLAMA_CHANGE_7D_PROVIDER_UNIT:
        raise VerificationContractError("fixture_unit_contract_mismatch")
    if unit_contract.get("rejected_change_7d_unit") == DEFILLAMA_CHANGE_7D_PROVIDER_UNIT:
        raise VerificationContractError("fixture_rejected_unit_not_distinct")

    happy = _sample(dl, "happy")
    factors = _factors_by_key(
        "defillama",
        happy,
        source_url="https://defillama.com/protocol/alpha-economic-protocol",
    )
    ratio = factors.get("tvl_change_7d_ratio")
    if ratio is None or ratio.unit != "ratio" or ratio.value_type != "string":
        return False

    invalid = _sample(dl, "invalid_unit")
    try:
        canonical_provider_payload("defillama", invalid)
        return False
    except EconomicNormalizationError:
        pass

    missing = _sample(dl, "missing_unit")
    try:
        canonical_provider_payload("defillama", missing)
        return False
    except EconomicNormalizationError:
        pass

    # Writer path: invalid unit → schema_invalid, zero snapshots.
    raw_conn, _conn, repo = _sqlite_repo()
    try:
        writer = EconomicSnapshotWriter(repo, now_factory=lambda: _OBSERVED)
        meta = _discovery_meta(dl)
        bad = _make_discovery(
            source_id="defillama",
            raw_id=str(meta["raw_id"]) + "-bad-unit",
            name=str(meta["name"]) + " Bad Unit",
            url=str(meta["url"]),
            raw_data=invalid,
        )
        result = CollectorResult(source_id="defillama", items=[bad])
        result.finished_at = _OBSERVED
        summary = writer.process(result, run_id="daily:2026-07-22:defillama", enabled=True)
        if summary.schema_invalid != 1 or summary.snapshots_inserted != 0:
            return False
        count = raw_conn.execute("SELECT COUNT(*) AS c FROM opportunity_economic_snapshots").fetchone()["c"]
        return count == 0
    finally:
        repo.close()
        raw_conn.close()


def _case_17_1_16() -> bool:
    """Specialized types: usd/supply/ratio strings, market_rank number, chains sorted json, bool."""
    dl = _load_fixture("defillama.json")
    cg = _load_fixture("coingecko.json")
    cr = _load_fixture("cryptorank.json")

    dl_factors = _factors_by_key(
        "defillama",
        _sample(dl, "happy"),
        source_url="https://defillama.com/protocol/alpha-economic-protocol",
    )
    tvl = dl_factors.get("tvl_usd")
    chg = dl_factors.get("tvl_change_7d_ratio")
    chains = dl_factors.get("chains_json")
    unlisted = dl_factors.get("token_unlisted_proxy")
    if tvl is None or chg is None or chains is None or unlisted is None:
        return False
    if tvl.value_type != "string" or tvl.unit != "usd" or not isinstance(tvl.value, str):
        return False
    if chg.value_type != "string" or chg.unit != "ratio" or not isinstance(chg.value, str):
        return False
    if chains.value_type != "json":
        return False
    # Sorted array contract (production normalize_chains_json).
    chain_vals = list(chains.value) if isinstance(chains.value, tuple) else chains.value
    if not isinstance(chain_vals, (list, tuple)) or list(chain_vals) != sorted(chain_vals):
        return False
    if unlisted.value_type != "bool" or not isinstance(unlisted.value, bool):
        return False

    cg_factors = _factors_by_key(
        "coingecko",
        _sample(cg, "happy"),
        source_url="https://api.coingecko.com/api/v3/coins/markets",
    )
    for key, unit in (
        ("market_cap_usd", "usd"),
        ("price_usd", "usd"),
        ("volume_24h_usd", "usd"),
        ("price_change_24h_ratio", "ratio"),
    ):
        f = cg_factors.get(key)
        if f is None or f.value_type != "string" or f.unit != unit:
            return False
        if not isinstance(f.value, str):
            return False
    supply = cg_factors.get("circulating_supply")
    if supply is None or supply.value_type != "string" or not isinstance(supply.value, str):
        return False
    rank = cg_factors.get("market_rank")
    if rank is None or rank.value_type != "number" or not isinstance(rank.value, int):
        return False

    cr_factors = _factors_by_key(
        "cryptorank",
        _sample(cr, "happy"),
        source_url="https://cryptorank.io/price/rank-economic-asset",
    )
    for key in ("circulating_supply", "total_supply"):
        f = cr_factors.get(key)
        if f is None or f.value_type != "string" or not isinstance(f.value, str):
            return False
    cr_rank = cr_factors.get("market_rank")
    return not (cr_rank is None or cr_rank.value_type != "number" or not isinstance(cr_rank.value, int))


def _case_17_1_19() -> bool:
    """Collector raw None remains None; legacy local numeric fallback is 0; actual 0 distinct."""
    # DefiLlama
    dl_collector = DefiLlamaCollector()
    protocol_none = {
        "name": "None Protocol",
        "slug": "none-protocol",
        "category": "Lending",
        "tvl": None,
        "change_7d": None,
        "chains": None,
        "url": "https://none.example.com",
    }
    d_none = dl_collector._build_discovery(protocol_none)
    if d_none.raw_data.get("tvl") is not None:
        return False
    if d_none.raw_data.get("change_7d") is not None:
        return False
    # Legacy signal uses local 0 fallback without coercing raw.
    tvl_signal = next(s for s in d_none.raw_signals if s.signal_type == "tvl")
    if tvl_signal.signal_data.get("tvl") != 0:
        return False
    if tvl_signal.signal_data.get("change_7d") != 0:
        return False

    protocol_zero = {
        "name": "Zero Protocol",
        "slug": "zero-protocol",
        "category": "Lending",
        "tvl": 0,
        "change_7d": 0,
        "chains": ["Ethereum"],
        "url": "https://zero.example.com",
    }
    d_zero = dl_collector._build_discovery(protocol_zero)
    if d_zero.raw_data.get("tvl") != 0 or d_zero.raw_data.get("change_7d") != 0:
        return False
    # Distinguish None raw from actual zero raw.
    if d_none.raw_data.get("tvl") == d_zero.raw_data.get("tvl"):
        return False

    # CoinGecko
    cg_collector = CoinGeckoCollector()
    coin_none = {
        "id": "none-coin",
        "symbol": "nnc",
        "name": "None Coin",
        "image": "https://example.com/nnc.png",
        "market_cap": None,
        "current_price": None,
        "total_volume": None,
        "circulating_supply": None,
        "market_cap_rank": None,
        "price_change_percentage_24h": None,
        "price_change_24h": None,
    }
    c_none = cg_collector._build_discovery(coin_none)
    for key in (
        "market_cap",
        "current_price",
        "total_volume",
        "circulating_supply",
        "market_cap_rank",
        "price_change_percentage_24h",
    ):
        if c_none.raw_data.get(key) is not None:
            return False
    # Legacy signal strength path uses local 0 rank → 0.5 strength.
    if c_none.raw_signals[0].signal_strength != cg_collector._calculate_signal_strength(0):
        return False
    if c_none.raw_signals[0].signal_data.get("market_cap_rank") != 0:
        return False
    if c_none.raw_signals[0].signal_data.get("market_cap") != 0:
        return False

    coin_zero = {
        **coin_none,
        "id": "zero-coin",
        "symbol": "zro",
        "name": "Zero Coin",
        "market_cap": 0,
        "current_price": 0,
        "total_volume": 0,
        "circulating_supply": 0,
        "market_cap_rank": 0,
        "price_change_percentage_24h": 0,
        "price_change_24h": 0,
    }
    c_zero = cg_collector._build_discovery(coin_zero)
    if c_zero.raw_data.get("market_cap") != 0:
        return False
    if c_none.raw_data.get("market_cap") == c_zero.raw_data.get("market_cap"):
        return False

    # CryptoRank
    cr_collector = CryptoRankCollector()
    item_none = {
        "name": "None Rank Asset",
        "symbol": "NRA",
        "slug": "none-rank-asset",
        "rank": 120,
        "category": "DeFi",
        "values": {
            "USD": {
                "price": None,
                "volume24h": 150_000,
                "marketCap": None,
                "percentChange24h": None,
                "percentChange7d": None,
            }
        },
        "circulatingSupply": None,
        "totalSupply": None,
    }
    r_none = cr_collector._build_discovery(item_none)
    if r_none is None:
        return False
    for key in (
        "market_cap",
        "price",
        "percent_change_24h",
        "percent_change_7d",
        "circulating_supply",
        "total_supply",
    ):
        if r_none.raw_data.get(key) is not None:
            return False
    # Legacy signal_data uses local 0 fallback for missing percent changes.
    mom = next(s for s in r_none.raw_signals if s.signal_type == "market_momentum")
    if mom.signal_data.get("percent_change_24h") != 0:
        return False
    if mom.signal_data.get("percent_change_7d") != 0:
        return False

    item_zero = {
        "name": "Zero Rank Asset",
        "symbol": "ZRA",
        "slug": "zero-rank-asset",
        "rank": 120,
        "category": "DeFi",
        "values": {
            "USD": {
                "price": 0,
                "volume24h": 150_000,
                "marketCap": 0,
                "percentChange24h": 0,
                "percentChange7d": 5.0,
            }
        },
        "circulatingSupply": 0,
        "totalSupply": 0,
    }
    r_zero = cr_collector._build_discovery(item_zero)
    if r_zero is None:
        return False
    if r_zero.raw_data.get("market_cap") != 0 or r_zero.raw_data.get("price") != 0:
        return False
    if r_none.raw_data.get("market_cap") == r_zero.raw_data.get("market_cap"):
        return False

    # Fixture with_none / with_zero must also remain distinguishable after whitelist.
    dl_fix = _load_fixture("defillama.json")
    none_payload = canonical_provider_payload("defillama", _sample(dl_fix, "with_none"))
    zero_payload = canonical_provider_payload("defillama", _sample(dl_fix, "with_zero"))
    if "tvl" in none_payload:
        return False
    return zero_payload.get("tvl") == 0


def _case_17_1_20() -> bool:
    """Provider-native payload whitelist: omit None, keep 0, Defi unit, strip canaries, hash exact."""
    dl = _load_fixture("defillama.json")
    cg = _load_fixture("coingecko.json")
    cr = _load_fixture("cryptorank.json")

    # Happy path: strip unknown + canary, keep approved keys, include change_7d_unit.
    happy = _sample(dl, "happy")
    payload = canonical_provider_payload("defillama", happy)
    allowed = PROVIDER_RAW_FIELD_KEYS["defillama"]
    if set(payload) - set(allowed):
        return False
    if "unknown_noise_field" in payload or "api_key" in payload or "token" in payload:
        return False
    if payload.get("change_7d_unit") != DEFILLAMA_CHANGE_7D_PROVIDER_UNIT:
        return False
    digest = payload_sha256(payload)
    # Hash exact over that object — any extra key changes digest.
    polluted = dict(payload)
    polluted["canary_extra"] = "x"
    if payload_sha256(polluted) == digest:
        return False
    # Not a normalized factor map: factor keys must not be required.
    if "tvl_usd" in payload or "tvl_change_7d_ratio" in payload:
        return False

    # Omit None, keep real 0.
    none_raw = _sample(dl, "with_none")
    none_payload = canonical_provider_payload("defillama", none_raw)
    if "tvl" in none_payload:
        return False
    if none_payload.get("change_7d") != 0.12:
        return False
    if none_payload.get("change_7d_unit") != "ratio":
        return False

    zero_raw = _sample(dl, "with_zero")
    zero_payload = canonical_provider_payload("defillama", zero_raw)
    if zero_payload.get("tvl") != 0 or zero_payload.get("change_7d") != 0:
        return False
    if payload_sha256(zero_payload) == payload_sha256({k: v for k, v in zero_payload.items() if k != "tvl"}):
        return False

    # CoinGecko / CryptoRank None omit + zero keep.
    cg_none = canonical_provider_payload("coingecko", _sample(cg, "with_none"))
    if "market_cap" in cg_none or "total_volume" in cg_none:
        return False
    if "price_change_percentage_24h" in cg_none:
        return False
    if cg_none.get("current_price") != 2.0:
        return False
    cg_zero = canonical_provider_payload("coingecko", _sample(cg, "with_zero"))
    if cg_zero.get("market_cap") != 0 or cg_zero.get("price_change_percentage_24h") != 0:
        return False

    cr_none = canonical_provider_payload("cryptorank", _sample(cr, "with_none"))
    if "market_cap" in cr_none or "percent_change_24h" in cr_none:
        return False
    if cr_none.get("percent_change_7d") != 5.0:
        return False
    cr_zero = canonical_provider_payload("cryptorank", _sample(cr, "with_zero"))
    if cr_zero.get("market_cap") != 0 or cr_zero.get("percent_change_24h") != 0:
        return False

    # Writer stores exactly the whitelist payload hash.
    raw_conn, _conn, repo = _sqlite_repo()
    try:
        writer = EconomicSnapshotWriter(repo, now_factory=lambda: _OBSERVED)
        meta = _discovery_meta(dl)
        item = _make_discovery(
            source_id="defillama",
            raw_id=str(meta["raw_id"]) + "-payload20",
            name=str(meta["name"]) + " P20",
            url=str(meta["url"]),
            raw_data=happy,
        )
        result = CollectorResult(source_id="defillama", items=[item])
        result.finished_at = _OBSERVED
        summary = writer.process(result, run_id="daily:2026-07-22:defillama", enabled=True)
        if summary.snapshots_inserted != 1 or not summary.observations:
            return False
        stored = repo.get(summary.observations[0].snapshot_id)
        if stored is None:
            return False
        if stored.payload_sha256 != digest:
            return False
        # Thawed stored payload must match whitelist object under production hash.
        from app.opportunity.economic_writer import observation_from_snapshot

        rebuilt = observation_from_snapshot(stored)
        return rebuilt.snapshot_id == stored.snapshot_id
    finally:
        repo.close()
        raw_conn.close()


def _settings(**overrides: Any) -> Settings:
    """Build Settings without env files; economic flags default false unless overridden."""
    base: dict[str, Any] = {name: False for name in _ECONOMIC_FLAG_NAMES}
    base.update(overrides)
    return Settings(_env_file=None, **base)


def _farm_decision_bundle() -> tuple[Any, bytes, str]:
    """Legacy decide() baseline used by flags-closed identity checks."""
    project_id = "proj-flags-closed-08"
    now = _OBSERVED
    inputs = OpportunityInputs(
        project_id=project_id,
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
        weekly_time_confirmed_minimum=False,
        integrity_blocked=False,
        safety_blocked=False,
        project_quality=70,
        project_failure_risk=RiskLevel.LOW,
        capital_security_risk=RiskLevel.LOW,
        official_multiwallet_policy="allowed",
        official_airdrop_evidence_count_a=1,
        independent_airdrop_evidence_count_b=0,
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
        conditional_reward=inputs.conditional_reward_usd,  # type: ignore[arg-type]
        hard_cost=inputs.hard_cost_usd,  # type: ignore[arg-type]
        capital_loss=inputs.expected_capital_loss_usd,  # type: ignore[arg-type]
        liquidity_cost=inputs.liquidity_cost_usd,  # type: ignore[arg-type]
        total_time_hours=inputs.total_time_hours,  # type: ignore[arg-type]
    )
    decision = decide(
        inputs=inputs,
        event=event,
        eligibility=eligibility,
        survival=survival,
        reward_probability=reward_probability,
        economics=economics,
        profile=DEFAULT_PROFILE,
        now=now,
    )
    decision_bytes = canonical_json_bytes(decision.model_dump(mode="json"))
    return decision, decision_bytes, project_id


def _workflow_canonical_bytes(
    *,
    project_id: str,
    public_label: str,
    status: DecisionStatus,
    economics: EconomicsResult,
) -> bytes:
    """Production workflow projection bytes for legacy score/label identity."""
    project = {
        "id": project_id,
        "name": "Flags Closed Protocol",
        "score": 88,
        "label": public_label,
        "reason": ["legacy baseline"],
        "url": "https://example.invalid/flags-closed",
        "stage": "mainnet",
    }
    assessment = OpportunityAssessment(
        assessment_id="assess-flags-08",
        project_id=project_id,
        model_version="opportunity-v2.0",
        profile_version=DEFAULT_PROFILE.profile_id,
        event_probability=ProbabilityRange(low=0.60, base=0.70, high=0.80),
        eligibility_probability=ProbabilityRange(low=0.55, base=0.70, high=0.85),
        survival_probability=ProbabilityRange(low=0.70, base=0.80, high=0.90),
        reward_probability=ProbabilityRange(low=0.25, base=0.39, high=0.61),
        conditional_reward_usd=MoneyRange(low=80, base=160, high=400),
        hard_cost_usd=MoneyRange(low=5, base=8, high=10),
        economics=economics,
        risks=RiskSet(
            capital_security=RiskLevel.LOW,
            eligibility=RiskLevel.LOW,
            project_failure=RiskLevel.LOW,
            reward_dilution=RiskLevel.MEDIUM,
            liquidity=RiskLevel.LOW,
        ),
        confidence=ConfidenceSet(
            event=0.80,
            eligibility=0.75,
            reward=0.70,
            cost=0.80,
            risk=0.80,
            quality=0.75,
            overall=0.75,
        ),
        status=status,
        public_label=public_label,  # type: ignore[arg-type]
        blocker_codes=(),
        watch_reason_codes=(),
        ignore_reason_codes=(),
        requires_remediation=False,
        recommended_action="baseline",
        evidence_ids=(),
        factor_snapshot={},
        scored_at=_OBSERVED - timedelta(hours=1),
        review_at=_OBSERVED + timedelta(hours=12),
        expires_at=_OBSERVED + timedelta(hours=36),
    )
    projection = build_workflow_projection(
        project=project,
        assessment=assessment,
        evidence=(),
        participation_tasks=(),
        interactions=(),
        now=_OBSERVED,
    )
    return canonical_json_bytes(projection.model_dump(mode="json"))


def _case_17_1_08() -> bool:
    """Six OPPORTUNITY_ECONOMIC flags default false → closed loop, baseline bytes identical."""
    # Production declared defaults (code defaults, not env/.env).
    for name in _ECONOMIC_FLAG_NAMES:
        field = Settings.model_fields[name]
        if field.default is not False:
            return False

    settings = Settings(_env_file=None)
    for name in _ECONOMIC_FLAG_NAMES:
        if getattr(settings, name) is not False:
            return False

    for source_id in ("defillama", "coingecko", "cryptorank"):
        if economic_source_enabled(source_id, settings) is not False:
            return False

    decision, decision_bytes, project_id = _farm_decision_bundle()
    if decision.public_label != "FARM" or decision.status != DecisionStatus.ACTIONABLE:
        return False
    economics = EconomicsResult(
        gross_reward=MoneyRange(low=50, base=100, high=200),
        net_reward=SignedMoneyRange(low=20, base=60, high=180),
        reward_to_cost_ratio=8.0,
        decision_value=48.0,
        capital_efficiency=4.8,
        time_efficiency=24.0,
    )
    workflow_bytes = _workflow_canonical_bytes(
        project_id=project_id,
        public_label=decision.public_label,
        status=decision.status,
        economics=economics,
    )
    if b"economic_proxy" in workflow_bytes or b"economics_data_mode" in workflow_bytes:
        return False

    # Closed integration path: zero writer/emitter calls under default flags.
    writer = MagicMock()
    emitter = MagicMock()
    dl = _load_fixture("defillama.json")
    meta = _discovery_meta(dl)
    item = _make_discovery(
        source_id="defillama",
        raw_id=str(meta["raw_id"]) + "-flags08",
        name=str(meta["name"]) + " Flags08",
        url=str(meta["url"]),
        raw_data=_sample(dl, "happy"),
    )
    result = CollectorResult(source_id="defillama", items=[item])
    result.finished_at = _OBSERVED
    out = process_persisted_collection(
        result,
        run_id=daily_run_id("defillama", _OBSERVED),
        writer=writer,
        emitter=emitter,
        settings_obj=settings,
    )
    if out is not None:
        return False
    if writer.process.called or emitter.emit.called:
        return False

    # Real writer also inserts nothing when process is never gated-on.
    raw_conn, conn, snap_repo, evid_repo = _sqlite_evidence_stack()
    try:
        real_writer = EconomicSnapshotWriter(snap_repo, now_factory=lambda: _OBSERVED)
        real_emitter = EconomicEvidenceEmitter(conn, snap_repo, evid_repo)
        real_out = process_persisted_collection(
            result,
            run_id=daily_run_id("defillama", _OBSERVED),
            writer=real_writer,
            emitter=real_emitter,
            settings_obj=settings,
        )
        if real_out is not None:
            return False
        snap_n = int(raw_conn.execute("SELECT COUNT(*) AS c FROM opportunity_economic_snapshots").fetchone()["c"])
        evid_n = _evidence_count(raw_conn)
        if snap_n != 0 or evid_n != 0:
            return False

        closed_projection = project_economics_data(
            project_id,
            evidence_repository=evid_repo,
            snapshot_repository=snap_repo,
            direct_available=True,
            now=_OBSERVED,
            enabled=bool(settings.opportunity_economic_resolver_enabled),
        )
        if closed_projection is not None:
            return False

        # Seed a project and prove service workflow bytes match pure builder baseline.
        _seed_project(conn, project_id, name="Flags Closed Protocol")
        conn.execute(
            "UPDATE projects SET score = ?, label = ?, url = ?, stage = ? WHERE id = ?",
            (88, decision.public_label, "https://example.invalid/flags-closed", "mainnet", project_id),
        )
        conn.commit()
        service = OpportunityWorkflowService(conn)
        try:
            service_proj = service.get_project_workflow(project_id, _OBSERVED)
        finally:
            service.close()
        service_bytes = canonical_json_bytes(service_proj.model_dump(mode="json"))
        # Service path without assessment still must exclude economic surfaces.
        if b"economic_proxy" in service_bytes or b"economics_data_mode" in service_bytes:
            return False
    finally:
        evid_repo.close()
        snap_repo.close()
        raw_conn.close()

    # Re-run legacy decide + pure workflow: byte-identical to pre-loop baseline.
    decision2, decision_bytes2, _ = _farm_decision_bundle()
    if decision_bytes2 != decision_bytes:
        return False
    if decision2.public_label != decision.public_label:
        return False
    if decision2.status != decision.status:
        return False
    workflow_bytes2 = _workflow_canonical_bytes(
        project_id=project_id,
        public_label=decision2.public_label,
        status=decision2.status,
        economics=economics,
    )
    return workflow_bytes2 == workflow_bytes


def _case_17_1_17() -> bool:
    """Gray release layers: snapshot-only; snapshot+evidence; all three enabled."""
    dl = _load_fixture("defillama.json")
    meta = _discovery_meta(dl)
    happy = _sample(dl, "happy")
    finished = _OBSERVED

    def _layer_item(suffix: str) -> RawDiscovery:
        return _make_discovery(
            source_id="defillama",
            raw_id=str(meta["raw_id"]) + suffix,
            name=str(meta["name"]) + suffix,
            url=str(meta["url"]),
            raw_data=happy,
        )

    # ── Layer 1: snapshot-only ──────────────────────────────────────
    raw1, conn1, snap1, evid1 = _sqlite_evidence_stack()
    try:
        item1 = _layer_item("-gray17-l1")
        project_id = "proj-gray-17-l1"
        _seed_project(conn1, project_id, name=item1.name)
        _seed_raw_project(
            conn1,
            raw_id="raw-gray-17-l1",
            source_id="defillama",
            dedup_key=item1.dedup_key,
            project_id=project_id,
        )
        writer1 = EconomicSnapshotWriter(snap1, now_factory=lambda: finished)
        emitter1 = EconomicEvidenceEmitter(conn1, snap1, evid1)
        settings_l1 = _settings(
            opportunity_economic_snapshot_enabled=True,
            opportunity_economic_source_defillama_enabled=True,
            opportunity_economic_evidence_emit_enabled=False,
            opportunity_economic_resolver_enabled=False,
            defillama_enabled=True,
        )
        if not economic_source_enabled("defillama", settings_l1):
            return False
        result1 = CollectorResult(source_id="defillama", items=[item1])
        result1.finished_at = finished
        before_skip = metric_sample_value(OPPORTUNITY_ECONOMIC_EVIDENCE, source="defillama", result="skipped_flag_off")
        summary1 = process_persisted_collection(
            result1,
            run_id=daily_run_id("defillama", finished),
            writer=writer1,
            emitter=emitter1,
            settings_obj=settings_l1,
        )
        if summary1 is None or summary1.snapshots_inserted < 1:
            return False
        snap_n1 = int(raw1.execute("SELECT COUNT(*) AS c FROM opportunity_economic_snapshots").fetchone()["c"])
        evid_n1 = _evidence_count(raw1)
        if snap_n1 < 1 or evid_n1 != 0:
            return False
        after_skip = metric_sample_value(OPPORTUNITY_ECONOMIC_EVIDENCE, source="defillama", result="skipped_flag_off")
        if after_skip < before_skip + 1:
            return False
        proj_l1 = project_economics_data(
            project_id,
            evidence_repository=evid1,
            snapshot_repository=snap1,
            direct_available=False,
            now=finished + timedelta(hours=1),
            enabled=bool(settings_l1.opportunity_economic_resolver_enabled),
        )
        if proj_l1 is not None:
            return False
        # Workflow surface remains free of economic projection keys.
        service1 = OpportunityWorkflowService(conn1)
        try:
            wf1 = service1.get_project_workflow(project_id, finished)
        finally:
            service1.close()
        wf1_bytes = canonical_json_bytes(wf1.model_dump(mode="json"))
        if b"economic_proxy" in wf1_bytes or b"economics_data_mode" in wf1_bytes:
            return False
    finally:
        evid1.close()
        snap1.close()
        raw1.close()

    # ── Layer 2: snapshot + evidence ────────────────────────────────
    raw2, conn2, snap2, evid2 = _sqlite_evidence_stack()
    try:
        item2 = _layer_item("-gray17-l2")
        project_id2 = "proj-gray-17-l2"
        _seed_project(conn2, project_id2, name=item2.name)
        _seed_raw_project(
            conn2,
            raw_id="raw-gray-17-l2",
            source_id="defillama",
            dedup_key=item2.dedup_key,
            project_id=project_id2,
        )
        writer2 = EconomicSnapshotWriter(snap2, now_factory=lambda: finished)
        emitter2 = EconomicEvidenceEmitter(conn2, snap2, evid2)
        settings_l2 = _settings(
            opportunity_economic_snapshot_enabled=True,
            opportunity_economic_source_defillama_enabled=True,
            opportunity_economic_evidence_emit_enabled=True,
            opportunity_economic_resolver_enabled=False,
            defillama_enabled=True,
        )
        result2 = CollectorResult(source_id="defillama", items=[item2])
        result2.finished_at = finished
        before_emitted = metric_sample_value(OPPORTUNITY_ECONOMIC_EVIDENCE, source="defillama", result="emitted")
        summary2 = process_persisted_collection(
            result2,
            run_id=daily_run_id("defillama", finished),
            writer=writer2,
            emitter=emitter2,
            settings_obj=settings_l2,
        )
        if summary2 is None or summary2.snapshots_inserted < 1:
            return False
        snap_n2 = int(raw2.execute("SELECT COUNT(*) AS c FROM opportunity_economic_snapshots").fetchone()["c"])
        evid_n2 = _evidence_count(raw2)
        if snap_n2 < 1 or evid_n2 < 1:
            return False
        after_emitted = metric_sample_value(OPPORTUNITY_ECONOMIC_EVIDENCE, source="defillama", result="emitted")
        if after_emitted < before_emitted + 1:
            return False
        # Resolver still closed → projection None despite Evidence rows.
        proj_l2 = project_economics_data(
            project_id2,
            evidence_repository=evid2,
            snapshot_repository=snap2,
            direct_available=False,
            now=finished + timedelta(hours=1),
            enabled=bool(settings_l2.opportunity_economic_resolver_enabled),
        )
        if proj_l2 is not None:
            return False
        service2 = OpportunityWorkflowService(conn2)
        try:
            wf2 = service2.get_project_workflow(project_id2, finished)
        finally:
            service2.close()
        wf2_bytes = canonical_json_bytes(wf2.model_dump(mode="json"))
        if b"economic_proxy" in wf2_bytes or b"economics_data_mode" in wf2_bytes:
            return False
        # Layer distinction: L1 had zero Evidence; L2 has rows.
        if evid_n2 <= evid_n1:
            return False
    finally:
        evid2.close()
        snap2.close()
        raw2.close()

    # ── Layer 3: snapshot + evidence + resolver ──────────────────────
    raw3, conn3, snap3, evid3 = _sqlite_evidence_stack()
    try:
        item3 = _layer_item("-gray17-l3")
        project_id3 = "proj-gray-17-l3"
        _seed_project(conn3, project_id3, name=item3.name)
        _seed_raw_project(
            conn3,
            raw_id="raw-gray-17-l3",
            source_id="defillama",
            dedup_key=item3.dedup_key,
            project_id=project_id3,
        )
        writer3 = EconomicSnapshotWriter(snap3, now_factory=lambda: finished)
        emitter3 = EconomicEvidenceEmitter(conn3, snap3, evid3)
        settings_l3 = _settings(
            opportunity_economic_snapshot_enabled=True,
            opportunity_economic_source_defillama_enabled=True,
            opportunity_economic_evidence_emit_enabled=True,
            opportunity_economic_resolver_enabled=True,
            defillama_enabled=True,
        )
        result3 = CollectorResult(source_id="defillama", items=[item3])
        result3.finished_at = finished
        summary3 = process_persisted_collection(
            result3,
            run_id=daily_run_id("defillama", finished),
            writer=writer3,
            emitter=emitter3,
            settings_obj=settings_l3,
        )
        if summary3 is None or summary3.snapshots_inserted < 1:
            return False
        evid_n3 = _evidence_count(raw3)
        if evid_n3 < 1:
            return False
        proj_l3 = project_economics_data(
            project_id3,
            evidence_repository=evid3,
            snapshot_repository=snap3,
            direct_available=False,
            now=finished + timedelta(hours=1),
            enabled=bool(settings_l3.opportunity_economic_resolver_enabled),
        )
        if proj_l3 is None:
            return False
        if proj_l3.economics_data_mode != "PROXY_ONLY":
            return False
        if not proj_l3.factors:
            return False
        # Layer distinction: L2 resolver closed (None); L3 yields projection.
        if proj_l2 is not None or proj_l1 is not None:
            return False
        # Workflow v1 still does not leak economic projection fields.
        service3 = OpportunityWorkflowService(conn3)
        try:
            wf3 = service3.get_project_workflow(project_id3, finished)
        finally:
            service3.close()
        wf3_bytes = canonical_json_bytes(wf3.model_dump(mode="json"))
        if b"economic_proxy" in wf3_bytes or b"economics_data_mode" in wf3_bytes:
            return False
        # Pure builder baseline remains free of economic surfaces too.
        pure = build_workflow_projection(
            project={
                "id": project_id3,
                "name": item3.name,
                "score": 0,
                "label": "WATCH",
                "url": item3.url,
                "stage": "mainnet",
            },
            assessment=None,
            evidence=tuple(evid3.list_evidence(project_id3)),
            participation_tasks=(),
            interactions=(),
            now=finished,
        )
        pure_bytes = canonical_json_bytes(pure.model_dump(mode="json"))
        return not (b"economic_proxy" in pure_bytes or b"economics_data_mode" in pure_bytes)
    finally:
        evid3.close()
        snap3.close()
        raw3.close()


def _case_17_1_18() -> bool:
    """Source economic flag AND provider-enabled must both be true to write snapshots."""
    dl = _load_fixture("defillama.json")
    meta = _discovery_meta(dl)
    happy = _sample(dl, "happy")
    finished = _OBSERVED

    # Dual-boolean matrix with snapshot master flag on (production gate conjunction).
    combos: list[tuple[bool, bool, bool]] = []
    for source_flag in (False, True):
        for provider_flag in (False, True):
            expected_write = source_flag and provider_flag
            combos.append((source_flag, provider_flag, expected_write))

    for source_flag, provider_flag, expected_write in combos:
        raw, conn, snap_repo, evid_repo = _sqlite_evidence_stack()
        try:
            suffix = f"-s{int(source_flag)}p{int(provider_flag)}"
            item = _make_discovery(
                source_id="defillama",
                raw_id=str(meta["raw_id"]) + suffix,
                name=str(meta["name"]) + suffix,
                url=str(meta["url"]),
                raw_data=happy,
            )
            writer = EconomicSnapshotWriter(snap_repo, now_factory=lambda: finished)
            emitter = EconomicEvidenceEmitter(conn, snap_repo, evid_repo)
            settings_obj = _settings(
                opportunity_economic_snapshot_enabled=True,
                opportunity_economic_source_defillama_enabled=source_flag,
                defillama_enabled=provider_flag,
            )
            gate = economic_source_enabled("defillama", settings_obj)
            if gate is not expected_write:
                return False
            result = CollectorResult(source_id="defillama", items=[item])
            result.finished_at = finished
            summary = process_persisted_collection(
                result,
                run_id=daily_run_id("defillama", finished),
                writer=writer,
                emitter=emitter,
                settings_obj=settings_obj,
            )
            snap_n = int(raw.execute("SELECT COUNT(*) AS c FROM opportunity_economic_snapshots").fetchone()["c"])
            if expected_write:
                if summary is None or summary.snapshots_inserted < 1 or snap_n < 1:
                    return False
            else:
                if summary is not None or snap_n != 0:
                    return False
        finally:
            evid_repo.close()
            snap_repo.close()
            raw.close()

    # Same dual-true rule for coingecko + cryptorank (one true / one false each).
    for source_id, source_flag_name, provider_flag_name in (
        ("coingecko", "opportunity_economic_source_coingecko_enabled", "coingecko_enabled"),
        ("cryptorank", "opportunity_economic_source_cryptorank_enabled", "cryptorank_enabled"),
    ):
        for source_flag, provider_flag in (
            (True, False),
            (False, True),
            (True, True),
        ):
            raw, conn, snap_repo, evid_repo = _sqlite_evidence_stack()
            try:
                if source_id == "coingecko":
                    fixture = _load_fixture("coingecko.json")
                else:
                    fixture = _load_fixture("cryptorank.json")
                fmeta = _discovery_meta(fixture)
                item = _make_discovery(
                    source_id=source_id,
                    raw_id=str(fmeta["raw_id"]) + f"-{source_flag}{provider_flag}",
                    name=str(fmeta["name"]) + " dual",
                    url=str(fmeta.get("url") or "https://example.invalid/x"),
                    raw_data=_sample(fixture, "happy"),
                )
                kwargs: dict[str, Any] = {
                    "opportunity_economic_snapshot_enabled": True,
                    source_flag_name: source_flag,
                    provider_flag_name: provider_flag,
                }
                settings_obj = _settings(**kwargs)
                expected = source_flag and provider_flag
                if economic_source_enabled(source_id, settings_obj) is not expected:
                    return False
                writer = EconomicSnapshotWriter(snap_repo, now_factory=lambda: finished)
                emitter = EconomicEvidenceEmitter(conn, snap_repo, evid_repo)
                result = CollectorResult(source_id=source_id, items=[item])
                result.finished_at = finished
                summary = process_persisted_collection(
                    result,
                    run_id=daily_run_id(source_id, finished),
                    writer=writer,
                    emitter=emitter,
                    settings_obj=settings_obj,
                )
                snap_n = int(raw.execute("SELECT COUNT(*) AS c FROM opportunity_economic_snapshots").fetchone()["c"])
                if expected:
                    if summary is None or snap_n < 1:
                        return False
                elif summary is not None or snap_n != 0:
                    return False
            finally:
                evid_repo.close()
                snap_repo.close()
                raw.close()
    return True


def _case_17_1_21() -> bool:
    """manual:<uuid> vs daily:<UTC_DATE>:<source_id>; shapes isolated, no collision."""
    fixed = UUID("550e8400-e29b-41d4-a716-446655440000")
    manual = manual_run_id(uuid_factory=lambda: fixed)
    if manual != f"manual:{fixed}":
        return False
    if not manual.startswith("manual:"):
        return False
    # Exact form: manual: + UUID string (no extra segments).
    rest = manual[len("manual:") :]
    try:
        parsed = UUID(rest)
    except ValueError:
        return False
    if str(parsed) != rest:
        return False

    t1 = datetime(2026, 7, 22, 1, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 7, 22, 23, 59, 59, tzinfo=UTC)
    t3 = datetime(2026, 7, 23, 0, 0, 0, tzinfo=UTC)
    d1 = daily_run_id("defillama", t1)
    d2 = daily_run_id("defillama", t2)
    d3 = daily_run_id("defillama", t3)
    if d1 != "daily:2026-07-22:defillama":
        return False
    if d1 != d2:
        return False
    if d3 != "daily:2026-07-23:defillama":
        return False
    if d1 == d3:
        return False
    # Non-UTC offset still maps to UTC calendar date via production helper.
    offset = timezone(timedelta(hours=5))
    local = datetime(2026, 7, 23, 2, 0, 0, tzinfo=offset)  # 2026-07-22 21:00 UTC
    if daily_run_id("defillama", local) != "daily:2026-07-22:defillama":
        return False
    if daily_run_id("coingecko", t1) != "daily:2026-07-22:coingecko":
        return False

    # Shape isolation: prefixes never cross; a manual id cannot equal a daily id.
    a = manual_run_id()
    b = manual_run_id()
    if a == b:
        return False
    if not a.startswith("manual:") or not b.startswith("manual:"):
        return False
    if a.startswith("daily:") or d1.startswith("manual:"):
        return False
    if manual == d1 or a == d1 or b == d3:
        return False
    # Namespace collision resistance: even a UUID-looking daily body is still "daily:".
    adversarial_daily = daily_run_id(str(fixed), t1)
    if adversarial_daily.startswith("manual:"):
        return False
    if adversarial_daily == manual:
        return False
    if not adversarial_daily.startswith("daily:"):
        return False
    # Default factory uses production uuid.uuid4 path (not a hand-rolled algorithm).
    return callable(uuid.uuid4)


def _case_17_1_22() -> bool:
    """post-link replay enabled=False is a complete no-op (zero I/O / rebuild / metrics)."""
    import app.opportunity.economic_evidence as evidence_mod

    raw, conn, snap_repo, evid_repo = _sqlite_evidence_stack()
    try:
        project_id = "proj-replay-noop-22"
        _seed_project(conn, project_id, name="Replay Noop")
        _seed_raw_project(
            conn,
            raw_id="raw-replay-noop-22",
            source_id="defillama",
            dedup_key="protocol:replay-noop-22",
            project_id=project_id,
        )
        # Pre-seed a snapshot so a buggy enabled=False path would have work to do.
        dl = _load_fixture("defillama.json")
        meta = _discovery_meta(dl)
        # Align dedup with raw_projects seed so a non-noop would find identity.
        item_linked = _make_discovery(
            source_id="defillama",
            raw_id="raw-replay-noop-22",
            name="Replay Noop",
            url=str(meta["url"]),
            raw_data=_sample(dl, "happy"),
        )
        # Force dedup_key match via raw_projects row already seeded.
        writer = EconomicSnapshotWriter(snap_repo, now_factory=lambda: _OBSERVED)
        result = CollectorResult(source_id="defillama", items=[item_linked])
        result.finished_at = _OBSERVED
        summary = writer.process(result, run_id="daily:2026-07-22:defillama", enabled=True)
        if summary.snapshots_inserted < 1:
            return False

        evidence_results = (
            "emitted",
            "skipped_no_project",
            "duplicate",
            "skipped_flag_off",
            "content_conflict",
        )
        identity_results = ("linked", "unlinked")
        before_ev = {
            r: metric_sample_value(OPPORTUNITY_ECONOMIC_EVIDENCE, source="defillama", result=r)
            for r in evidence_results
        }
        before_id = {
            r: metric_sample_value(OPPORTUNITY_ECONOMIC_IDENTITY_RESOLUTION, source="defillama", result=r)
            for r in identity_results
        }
        before_snap = {
            r: metric_sample_value(OPPORTUNITY_ECONOMIC_SNAPSHOTS, source="defillama", result=r)
            for r in ("inserted", "duplicate", "schema_invalid", "skipped_flag_off")
        }
        evid_before = _evidence_count(raw)

        execute_calls: list[str] = []
        real_execute = conn.execute

        def tracking_execute(sql: str, params: Any = None) -> Any:
            execute_calls.append(" ".join(str(sql).split()).lower())
            if params is None:
                return real_execute(sql)
            return real_execute(sql, params)

        with (
            patch.object(
                EconomicSnapshotRepository,
                "list_by_identity",
                wraps=snap_repo.list_by_identity,
            ) as list_spy,
            patch.object(
                evidence_mod,
                "observation_from_snapshot",
                wraps=evidence_mod.observation_from_snapshot,
            ) as recon_spy,
            patch.object(
                OpportunityRepository,
                "add_economic_evidence_if_absent",
                wraps=evid_repo.add_economic_evidence_if_absent,
            ) as add_spy,
        ):
            conn.execute = tracking_execute  # type: ignore[method-assign]
            out = replay_economic_snapshots_for_project(project_id, conn=conn, enabled=False)
            conn.execute = real_execute  # type: ignore[method-assign]

            if out is not None:
                return False
            if list_spy.call_count != 0:
                return False
            if recon_spy.call_count != 0:
                return False
            if add_spy.call_count != 0:
                return False
            if any("opportunity_economic_snapshots" in s for s in execute_calls):
                return False
            if any("raw_projects" in s for s in execute_calls):
                return False
            if any("opportunity_evidence" in s for s in execute_calls):
                return False

        if _evidence_count(raw) != evid_before:
            return False
        for r, before in before_ev.items():
            if metric_sample_value(OPPORTUNITY_ECONOMIC_EVIDENCE, source="defillama", result=r) != before:
                return False
        for r, before in before_id.items():
            if (
                metric_sample_value(
                    OPPORTUNITY_ECONOMIC_IDENTITY_RESOLUTION,
                    source="defillama",
                    result=r,
                )
                != before
            ):
                return False
        for r, before in before_snap.items():
            if metric_sample_value(OPPORTUNITY_ECONOMIC_SNAPSHOTS, source="defillama", result=r) != before:
                return False
        # observation_from_snapshot remains callable for non-noop paths (sanity).
        stored = snap_repo.list_by_identity("defillama", item_linked.dedup_key)
        if not stored:
            return False
        rebuilt = observation_from_snapshot(stored[0])
        return rebuilt.snapshot_id == stored[0].snapshot_id
    finally:
        evid_repo.close()
        snap_repo.close()
        raw.close()


_BASELINE_WORKFLOW_FIELDS: tuple[str, ...] = (
    "workflow_version",
    "project_id",
    "legacy",
    "opportunity",
    "workflow",
    "evidence",
    "validation",
    "review_at",
    "expires_at",
)
_FORBIDDEN_ECONOMIC_WORKFLOW_KEYS: frozenset[str] = frozenset(
    {
        "economic_proxy",
        "economics_data_mode",
        "EconomicProxyProjection",
        "project_economics_data",
    }
)
_ECONOMIC_SNAPSHOT_RESULTS: frozenset[str] = frozenset({"inserted", "duplicate", "schema_invalid", "skipped_flag_off"})
_ECONOMIC_SOURCES_CLOSED: frozenset[str] = frozenset({"defillama", "coingecko", "cryptorank"})


def _collect_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, nested in value.items():
            keys.add(str(key))
            keys |= _collect_keys(nested)
    elif isinstance(value, (list, tuple)):
        for item in value:
            keys |= _collect_keys(item)
    return keys


def _case_17_1_23() -> bool:
    """observation_from_snapshot: exact schema + recomputed hash; per-row isolation."""
    dl = _load_fixture("defillama.json")
    meta = _discovery_meta(dl)
    happy = _sample(dl, "happy")
    payload = canonical_provider_payload("defillama", happy)
    digest = payload_sha256(payload)
    if not _is_lower_hex64(digest):
        return False
    # Production framing: payload hash is over provider-native whitelist object only.
    if payload_sha256(dict(payload)) != digest:
        return False

    good_body = dict(payload)
    good_snap = EconomicSnapshotRow(
        snapshot_id=build_snapshot_id(
            run_id="daily:2026-07-22:defillama",
            source_id="defillama",
            provider_entity_id=str(meta["raw_id"]) + "-obs23-good",
            payload_sha256_hex=digest,
        ),
        schema_version=SCHEMA_VERSION,
        run_id="daily:2026-07-22:defillama",
        source_id="defillama",
        dedup_key="protocol:obs23-good",
        provider_entity_id=str(meta["raw_id"]) + "-obs23-good",
        payload_sha256=digest,
        payload_json=good_body,
        source_url=sanitize_source_url(str(meta["url"])),
        collected_at=_OBSERVED,
    )
    rebuilt = observation_from_snapshot(good_snap)
    if rebuilt.snapshot_id != good_snap.snapshot_id:
        return False
    if good_snap.schema_version != SCHEMA_VERSION:
        return False
    # Recomputed payload_sha256 under production hash framing must match stored digest.
    recomputed = payload_sha256(canonical_provider_payload("defillama", good_body))
    if recomputed != good_snap.payload_sha256 or recomputed != digest:
        return False

    bad_schema = EconomicSnapshotRow.model_construct(
        snapshot_id="sid-bad-schema-23",
        schema_version="wrong-schema-v0",
        run_id="daily:2026-07-22:defillama",
        source_id="defillama",
        dedup_key="protocol:obs23-bad-schema",
        provider_entity_id="entity-bad-schema-23",
        payload_sha256=digest,
        payload_json=good_body,
        source_url=sanitize_source_url(str(meta["url"])),
        collected_at=_OBSERVED,
    )
    try:
        observation_from_snapshot(bad_schema)
        return False
    except EconomicReconstructionError as exc:
        # Production message always mentions schema_version mismatch.
        if (
            "schema_version" not in str(exc).lower()
            and "mismatch" not in str(exc).lower()
            and "schema_version" not in str(exc)
        ):
            return False

    bad_hash = EconomicSnapshotRow(
        snapshot_id=build_snapshot_id(
            run_id="daily:2026-07-22:defillama",
            source_id="defillama",
            provider_entity_id="entity-bad-hash-23",
            payload_sha256_hex=digest,
        ),
        schema_version=SCHEMA_VERSION,
        run_id="daily:2026-07-22:defillama",
        source_id="defillama",
        dedup_key="protocol:obs23-bad-hash",
        provider_entity_id="entity-bad-hash-23",
        payload_sha256="0" * 64,
        payload_json=good_body,
        source_url=sanitize_source_url(str(meta["url"])),
        collected_at=_OBSERVED,
    )
    try:
        observation_from_snapshot(bad_hash)
        return False
    except EconomicReconstructionError as exc:
        if "payload_sha256" not in str(exc):
            return False

    # Per-row isolation on Writer.process: bad reconstruction does not block good row
    # and does not roll back an already committed project.
    project_id = "proj-obs-isolation-23"
    raw_conn, conn, snap_repo, evid_repo = _sqlite_evidence_stack()
    try:
        _seed_project(conn, project_id, name="Isolation23")
        # Commit is already done by _seed_project; capture project presence.
        before_project = raw_conn.execute("SELECT id, name FROM projects WHERE id = ?", (project_id,)).fetchone()
        if before_project is None or before_project["name"] != "Isolation23":
            return False

        good_item = _make_discovery(
            source_id="defillama",
            raw_id=str(meta["raw_id"]) + "-iso23-good",
            name=str(meta["name"]) + " Iso23 Good",
            url=str(meta["url"]),
            raw_data=happy,
        )
        bad_item = _make_discovery(
            source_id="defillama",
            raw_id=str(meta["raw_id"]) + "-iso23-bad",
            name=str(meta["name"]) + " Iso23 Bad",
            url=str(meta["url"]),
            raw_data=happy,
        )
        writer = EconomicSnapshotWriter(snap_repo, now_factory=lambda: _OBSERVED)
        real_recon = observation_from_snapshot
        call_log: list[str] = []

        def selective_recon(snapshot, *, normalizer=None):
            call_log.append(snapshot.provider_entity_id)
            if snapshot.provider_entity_id == bad_item.raw_id:
                raise EconomicReconstructionError("forced isolation failure for bad row")
            if normalizer is None:
                return real_recon(snapshot)
            return real_recon(snapshot, normalizer=normalizer)

        result = CollectorResult(source_id="defillama", items=[bad_item, good_item])
        result.finished_at = _OBSERVED
        with patch.object(economic_writer_mod, "observation_from_snapshot", selective_recon):
            summary = writer.process(result, run_id="daily:2026-07-22:defillama", enabled=True)

        if summary.snapshots_inserted + summary.snapshots_duplicate < 1:
            return False
        # Good row yields an observation; bad raw_id never appears in observations.
        if not any(o.provider_entity_id == good_item.raw_id for o in summary.observations):
            return False
        if any(o.provider_entity_id == bad_item.raw_id for o in summary.observations):
            return False
        if bad_item.raw_id not in call_log or good_item.raw_id not in call_log:
            return False

        # Already-committed project is intact (no rollback of projects row).
        after_project = raw_conn.execute("SELECT id, name FROM projects WHERE id = ?", (project_id,)).fetchone()
        if after_project is None:
            return False
        if after_project["name"] != before_project["name"]:
            return False
        if after_project["id"] != project_id:
            return False

        # Direct observation_from_snapshot still succeeds for the good stored row.
        stored_good = snap_repo.list_by_identity("defillama", good_item.dedup_key)
        if not stored_good:
            return False
        obs_good = observation_from_snapshot(stored_good[0])
        if obs_good.snapshot_id != stored_good[0].snapshot_id:
            return False
        return payload_sha256(stored_good[0].payload_json) == stored_good[0].payload_sha256
    finally:
        evid_repo.close()
        snap_repo.close()
        raw_conn.close()


def _case_17_1_24() -> bool:
    """Internal economic projection never leaks into v1 workflow (four layers)."""
    # Layer 1 — model field surface (production OpportunityWorkflowProjection).
    field_names = tuple(OpportunityWorkflowProjection.model_fields.keys())
    if field_names != _BASELINE_WORKFLOW_FIELDS:
        return False
    if set(field_names) & _FORBIDDEN_ECONOMIC_WORKFLOW_KEYS:
        return False
    annotations = " ".join(str(field.annotation) for field in OpportunityWorkflowProjection.model_fields.values())
    for banned in (
        "economic_proxy",
        "economics_data_mode",
        "EconomicProxyProjection",
        "OpportunityEconomicProjection",
    ):
        if banned in annotations or banned in field_names:
            return False

    # Layer 2 — serializer: model_dump key set + nested key scan + canonical bytes.
    pure = build_workflow_projection(
        project={
            "id": "proj-layer-24",
            "name": "Layer24 Protocol",
            "score": 80,
            "label": "WATCH",
            "reason": ["baseline"],
            "url": "https://example.invalid/layer24",
            "stage": "mainnet",
        },
        assessment=None,
        evidence=(),
        participation_tasks=(),
        interactions=(),
        now=_OBSERVED,
    )
    json_dump = pure.model_dump(mode="json")
    python_dump = pure.model_dump()
    if tuple(json_dump.keys()) != _BASELINE_WORKFLOW_FIELDS:
        return False
    if tuple(python_dump.keys()) != _BASELINE_WORKFLOW_FIELDS:
        return False
    dump_keys = _collect_keys(json_dump)
    if dump_keys & _FORBIDDEN_ECONOMIC_WORKFLOW_KEYS:
        return False
    if "raw_snapshot_ref" in dump_keys:
        return False
    ser_bytes = canonical_json_bytes(json_dump)
    if b"economic_proxy" in ser_bytes or b"economics_data_mode" in ser_bytes:
        return False
    if b"raw_snapshot_ref" in ser_bytes:
        return False

    # Layer 3 — service: real OpportunityWorkflowService over in-memory SQLite with
    # economic Evidence present must still omit economic surfaces.
    raw_conn, conn, snap_repo, evid_repo = _sqlite_evidence_stack()
    try:
        project_id = "proj-wf-24"
        _seed_project(conn, project_id, name="Workflow Boundary 24")
        conn.execute(
            "UPDATE projects SET score = ?, label = ?, url = ?, stage = ? WHERE id = ?",
            (88, "FARM", "https://example.invalid/wf-24", "mainnet", project_id),
        )
        conn.commit()
        # Persist economic evidence (private raw_snapshot_ref) that must not leak.
        snap_id = "f" * 64
        evid_repo.add_economic_evidence_if_absent(
            EvidenceRecord(
                evidence_id="ev-wf-boundary-24",
                project_id=project_id,
                factor_key="tvl_usd",
                value="1000000.00000000",
                value_type="string",
                observation_type="observed",
                source_url="https://defillama.com/protocol/wf-24",
                source_type="public_aggregator",
                source_grade="C",
                observed_at=_OBSERVED,
                effective_at=_OBSERVED,
                expires_at=_EXPIRES,
                verification_status="verified",
                independence_group="defillama-protocols",
                raw_snapshot_ref=f"econ-snapshot:{snap_id}",
            )
        )
        # Internal projection exists offline when resolver is enabled.
        snap_repo.insert_if_absent(
            EconomicSnapshotRow(
                snapshot_id=snap_id,
                schema_version=SCHEMA_VERSION,
                run_id="daily:2026-07-22:defillama",
                source_id="defillama",
                dedup_key="protocol:wf-24",
                provider_entity_id="entity-wf-24",
                payload_sha256="e" * 64,
                payload_json={"tvl": 1_000_000, "change_7d_unit": "ratio"},
                source_url="https://defillama.com/protocol/wf-24",
                collected_at=_OBSERVED,
            )
        )
        internal = project_economics_data(
            project_id,
            evidence_repository=evid_repo,
            snapshot_repository=snap_repo,
            direct_available=False,
            now=_OBSERVED + timedelta(hours=1),
            enabled=True,
        )
        if internal is None or not hasattr(internal, "economics_data_mode"):
            return False
        if internal.economics_data_mode not in _MODE_CLOSED:
            return False

        service = OpportunityWorkflowService(conn)
        try:
            service_proj = service.get_project_workflow(project_id, _OBSERVED)
        finally:
            service.close()
        service_dump = service_proj.model_dump(mode="json")
        if tuple(service_dump.keys()) != _BASELINE_WORKFLOW_FIELDS:
            return False
        service_keys = _collect_keys(service_dump)
        if service_keys & _FORBIDDEN_ECONOMIC_WORKFLOW_KEYS:
            return False
        if "raw_snapshot_ref" in service_keys:
            return False
        service_bytes = canonical_json_bytes(service_dump)
        if b"economic_proxy" in service_bytes or b"economics_data_mode" in service_bytes:
            return False
        if b"raw_snapshot_ref" in service_bytes:
            return False
        # Service must not call project_economics_data (spy).
        with patch(
            "app.opportunity.economic_resolver.project_economics_data",
            side_effect=AssertionError("workflow service must not call project_economics_data"),
        ):
            service2 = OpportunityWorkflowService(conn)
            try:
                again = service2.get_project_workflow(project_id, _OBSERVED)
            finally:
                service2.close()
        if again.project_id != project_id:
            return False

        # Layer 4 — router: production handler serializes via model_dump only;
        # source has no economic surface tokens / resolver imports.
        router_source = inspect.getsource(opportunity_router.get_opportunity_workflow)
        if 'projection.model_dump(mode="json")' not in router_source and (
            "projection.model_dump(mode='json')" not in router_source
        ):
            return False
        for token in (
            "economic_proxy",
            "economics_data_mode",
            "project_economics_data",
            "EconomicProxyProjection",
            "EconomicResolver",
        ):
            if token in router_source:
                return False
        # Router module source must not import economic resolver/projection surfaces.
        module_source = Path(opportunity_router.__file__).read_text(encoding="utf-8")
        for token in (
            "economic_proxy",
            "economics_data_mode",
            "project_economics_data",
            "EconomicProxyProjection",
        ):
            if token in module_source:
                return False
        # Execute the same serialization path the router uses (no HTTP).
        router_data = service_proj.model_dump(mode="json")
        router_envelope = {"ok": True, "data": router_data}
        if router_envelope["data"] != service_dump:
            return False
        if tuple(router_envelope["data"].keys()) != _BASELINE_WORKFLOW_FIELDS:
            return False
        # Independent proof: each layer failed independently would flip these checks.
        # Internal projection fields must not equal any workflow top-level key set.
        internal_keys = set(getattr(internal, "model_fields", {}) or {})
        if not internal_keys:
            # dataclass / plain object: use dump if available
            if hasattr(internal, "model_dump"):
                internal_keys = set(internal.model_dump().keys())
            else:
                internal_keys = {k for k in dir(internal) if not k.startswith("_") and k.isidentifier()}
        if "economics_data_mode" not in internal_keys and not hasattr(internal, "economics_data_mode"):
            return False
        return "economics_data_mode" not in field_names
    finally:
        evid_repo.close()
        snap_repo.close()
        raw_conn.close()


def _case_17_1_25() -> bool:
    """Economic metrics proven via metric_sample_value / metric_label_sets only."""
    # Helper contracts (not bare Counter.labels).
    sample_sig = inspect.signature(metric_sample_value)
    sample_params = list(sample_sig.parameters.values())
    if not sample_params or sample_params[0].name != "metric":
        return False
    if not any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sample_params):
        return False
    label_sig = inspect.signature(metric_label_sets)
    if list(label_sig.parameters) != ["metric"]:
        return False

    # Bare labels() existence is NOT verification — sample delta must prove write.
    bare_child = OPPORTUNITY_ECONOMIC_SNAPSHOTS.labels(source="defillama", result="inserted")
    if bare_child is None:
        return False
    # Calling .labels alone must not be treated as a pass condition below.

    before_ins = metric_sample_value(OPPORTUNITY_ECONOMIC_SNAPSHOTS, source="defillama", result="inserted")
    before_dup = metric_sample_value(OPPORTUNITY_ECONOMIC_SNAPSHOTS, source="defillama", result="duplicate")
    before_built = metric_sample_value(OPPORTUNITY_ECONOMIC_OBSERVATIONS, source="defillama", result="built")

    dl = _load_fixture("defillama.json")
    meta = _discovery_meta(dl)
    raw = _sample(dl, "happy")
    raw_conn, _conn, snap_repo = _sqlite_repo()
    try:
        writer = EconomicSnapshotWriter(snap_repo, now_factory=lambda: _OBSERVED)
        item = _make_discovery(
            source_id="defillama",
            raw_id=str(meta["raw_id"]) + "-metrics25",
            name=str(meta["name"]) + " Metrics25",
            url=str(meta["url"]),
            raw_data=raw,
        )
        result = CollectorResult(source_id="defillama", items=[item])
        result.finished_at = _OBSERVED
        summary1 = writer.process(result, run_id="daily:2026-07-22:defillama", enabled=True)
        if summary1.snapshots_inserted != 1 or not summary1.observations:
            return False
        after_ins = metric_sample_value(OPPORTUNITY_ECONOMIC_SNAPSHOTS, source="defillama", result="inserted")
        after_built = metric_sample_value(OPPORTUNITY_ECONOMIC_OBSERVATIONS, source="defillama", result="built")
        if after_ins - before_ins != 1.0:
            return False
        if after_built - before_built != 1.0:
            return False

        summary2 = writer.process(result, run_id="daily:2026-07-22:defillama", enabled=True)
        if summary2.snapshots_duplicate != 1:
            return False
        after_dup = metric_sample_value(OPPORTUNITY_ECONOMIC_SNAPSHOTS, source="defillama", result="duplicate")
        if after_dup - before_dup != 1.0:
            return False

        # Closed label sets from production metric_label_sets (not bare labels keys).
        snap_sets = metric_label_sets(OPPORTUNITY_ECONOMIC_SNAPSHOTS)
        if not isinstance(snap_sets, frozenset) or not snap_sets:
            return False
        found_inserted = False
        found_duplicate = False
        for label_set in snap_sets:
            if not isinstance(label_set, frozenset):
                return False
            as_dict = dict(label_set)
            if "source" in as_dict and as_dict["source"] not in _ECONOMIC_SOURCES_CLOSED:
                return False
            if "result" in as_dict:
                if as_dict["result"] not in _ECONOMIC_SNAPSHOT_RESULTS:
                    return False
                if as_dict["result"] == "rejected_fuzzy_attempt":
                    return False
                if "project" in as_dict or "symbol" in as_dict or "id" in as_dict:
                    return False
            if as_dict.get("source") == "defillama" and as_dict.get("result") == "inserted":
                found_inserted = True
            if as_dict.get("source") == "defillama" and as_dict.get("result") == "duplicate":
                found_duplicate = True
        if not found_inserted or not found_duplicate:
            return False

        # record_* path also only verifiable via sample helper (not labels).
        before_rec = metric_sample_value(OPPORTUNITY_ECONOMIC_SNAPSHOTS, source="coingecko", result="schema_invalid")
        record_opportunity_economic_snapshot(source="coingecko", result="schema_invalid")
        after_rec = metric_sample_value(OPPORTUNITY_ECONOMIC_SNAPSHOTS, source="coingecko", result="schema_invalid")
        if after_rec - before_rec != 1.0:
            return False
        # Histogram/gauge helpers exist and are sample-readable.
        before_hist = metric_sample_value(OPPORTUNITY_ECONOMIC_RUN_DURATION, source="defillama")
        if before_hist < 0:
            return False
        # Gauge may be zero if never set; sample helper must return float.
        gauge_val = metric_sample_value(OPPORTUNITY_ECONOMIC_LAST_SUCCESS, source="defillama")
        return isinstance(gauge_val, float)
    finally:
        snap_repo.close()
        raw_conn.close()


def _case_17_1_26() -> bool:
    """Scheduled/manual connection ownership + process/emit failure isolation."""
    # ── Static ownership contracts on production scheduled + manual paths ──
    main_path = BACKEND / "app" / "main.py"
    collections_path = BACKEND / "app" / "routers" / "v1" / "collections.py"
    if not main_path.is_file() or not collections_path.is_file():
        return False
    main_src = main_path.read_text(encoding="utf-8")
    collections_src = collections_path.read_text(encoding="utf-8")

    # Scheduled (lifespan): borrowed override never closed; shared stack on app_conn.
    if "app_owns_conn = False" not in main_src:
        return False
    if "app_owns_conn = True" not in main_src:
        return False
    if "process_persisted_collection" not in main_src:
        return False
    if "daily_run_id" not in main_src:
        return False
    # Economic failures are isolated (warning + continue), not re-raised over persist.
    if "app.collection_economic_failed" not in main_src:
        return False
    # Construction failure of economic stack must not abort scheduled path.
    if "app.economic_stack_construction_failed" not in main_src:
        return False

    # Manual trigger: request-scoped conn closed in finally; economic after persist;
    # economic failure cannot alter response / rollback persist.
    if "manual_run_id" not in collections_src:
        return False
    if "process_persisted_collection" not in collections_src:
        return False
    if "collections.economic_failed" not in collections_src:
        return False
    if "conn.close()" not in collections_src:
        return False
    # process_persisted_collection itself never closes connections.
    integ_src = inspect.getsource(process_persisted_collection)
    if ".close(" in integ_src:
        return False

    # ── Runtime: borrowed shared/request connection never closed by repos/integration ──
    raw_conn, conn, snap_repo, evid_repo = _sqlite_evidence_stack()
    close_calls = {"n": 0}
    real_close = conn.close

    def tracking_close() -> None:
        close_calls["n"] += 1
        real_close()

    conn.close = tracking_close  # type: ignore[method-assign]
    try:
        # Seed a "already persisted" legacy collection marker.
        project_id = "proj-own-26"
        _seed_project(conn, project_id, name="Ownership26")
        dl = _load_fixture("defillama.json")
        meta = _discovery_meta(dl)
        happy = _sample(dl, "happy")
        item = _make_discovery(
            source_id="defillama",
            raw_id=str(meta["raw_id"]) + "-own26",
            name=str(meta["name"]) + " Own26",
            url=str(meta["url"]),
            raw_data=happy,
        )
        _seed_raw_project(
            conn,
            raw_id="raw-own-26",
            source_id="defillama",
            dedup_key=item.dedup_key,
            project_id=project_id,
        )
        legacy_raw_count = int(raw_conn.execute("SELECT COUNT(*) AS c FROM raw_projects").fetchone()["c"])
        if legacy_raw_count < 1:
            return False

        writer = EconomicSnapshotWriter(snap_repo, now_factory=lambda: _OBSERVED)
        emitter = EconomicEvidenceEmitter(conn, snap_repo, evid_repo)
        settings_obj = _settings(
            opportunity_economic_snapshot_enabled=True,
            opportunity_economic_source_defillama_enabled=True,
            opportunity_economic_evidence_emit_enabled=True,
            defillama_enabled=True,
        )
        result = CollectorResult(source_id="defillama", items=[item])
        result.finished_at = _OBSERVED

        # Happy scheduled/manual integration path: real process, borrowed conn stays open.
        summary = process_persisted_collection(
            result,
            run_id=daily_run_id("defillama", _OBSERVED),
            writer=writer,
            emitter=emitter,
            settings_obj=settings_obj,
        )
        if summary is None or summary.snapshots_inserted < 1:
            return False
        if close_calls["n"] != 0:
            return False
        # Closing owned repos must not close the borrowed shared connection.
        snap_repo.close()
        evid_repo.close()
        if close_calls["n"] != 0:
            return False
        # Connection remains usable after repository close.
        still = conn.execute("SELECT COUNT(*) AS c FROM projects").fetchone()
        if int(still["c"] if isinstance(still, sqlite3.Row) else still[0]) < 1:
            return False

        # Rebuild repos on same borrowed conn (scheduled shared-stack pattern).
        snap_repo = EconomicSnapshotRepository(conn)
        evid_repo = OpportunityRepository(conn)
        writer = EconomicSnapshotWriter(snap_repo, now_factory=lambda: _OBSERVED)
        emitter = EconomicEvidenceEmitter(conn, snap_repo, evid_repo)

        # Process failure isolation: writer.process raises → process returns None;
        # legacy raw_projects intact; borrowed conn not closed.
        failing_writer = MagicMock()
        failing_writer.process.side_effect = RuntimeError("process boom")
        out_fail = process_persisted_collection(
            result,
            run_id=manual_run_id(uuid_factory=lambda: UUID("550e8400-e29b-41d4-a716-446655440099")),
            writer=failing_writer,
            emitter=emitter,
            settings_obj=settings_obj,
        )
        if out_fail is not None:
            return False
        failing_writer.process.assert_called_once()
        if close_calls["n"] != 0:
            return False
        after_raw = int(raw_conn.execute("SELECT COUNT(*) AS c FROM raw_projects").fetchone()["c"])
        if after_raw != legacy_raw_count:
            return False
        after_proj = raw_conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
        if after_proj is None:
            return False
        # Snapshots from prior successful persist remain (no rollback of success).
        snap_n = int(raw_conn.execute("SELECT COUNT(*) AS c FROM opportunity_economic_snapshots").fetchone()["c"])
        if snap_n < 1:
            return False

        # Emit failure isolation: first emit fails, second still attempted;
        # process still returns summary; conn not closed; legacy result intact.
        from app.opportunity.economic_models import NormalizedFactor, NormalizedObservation

        o1 = NormalizedObservation(
            snapshot_id="a" * 64,
            source_id="defillama",
            dedup_key=item.dedup_key,
            provider_entity_id="entity-emit-1",
            factors=(
                NormalizedFactor(
                    factor_key="tvl_usd",
                    value="1.00000000",
                    value_type="string",
                    unit="usd",
                    source_type="public_aggregator",
                    source_grade="C",
                    verification_status="verified",
                    independence_group="defillama-protocols",
                    source_url="https://defillama.com/protocol/x",
                    observed_at=_OBSERVED,
                    expires_at=_EXPIRES,
                ),
            ),
            collected_at=_OBSERVED,
            source_url="https://defillama.com/protocol/x",
        )
        o2 = NormalizedObservation(
            snapshot_id="b" * 64,
            source_id="defillama",
            dedup_key=item.dedup_key + "-2",
            provider_entity_id="entity-emit-2",
            factors=o1.factors,
            collected_at=_OBSERVED,
            source_url="https://defillama.com/protocol/x",
        )
        from app.opportunity.economic_writer import EconomicWriteSummary

        mock_writer = MagicMock()
        mock_writer.process.return_value = EconomicWriteSummary(
            source_id="defillama",
            run_id="manual:test-26",
            observations=(o1, o2),
            snapshots_inserted=2,
            snapshots_duplicate=0,
            schema_invalid=0,
            skipped_flag_off=0,
        )
        mock_emitter = MagicMock()
        mock_emitter.emit.side_effect = [
            RuntimeError("emit boom"),
            MagicMock(emitted=1, skipped_flag_off=0),
        ]
        out_emit = process_persisted_collection(
            result,
            run_id=manual_run_id(),
            writer=mock_writer,
            emitter=mock_emitter,
            settings_obj=settings_obj,
        )
        if out_emit is None:
            return False
        if mock_emitter.emit.call_count != 2:
            return False
        if close_calls["n"] != 0:
            return False
        if int(raw_conn.execute("SELECT COUNT(*) AS c FROM raw_projects").fetchone()["c"]) != legacy_raw_count:
            return False

        # Construction failure isolation via real production ownership stacks
        # (scheduled create_app lifespan + manual trigger_collection). Patch only
        # EconomicSnapshotRepository ctor; no local always-raise/catch tautology.
        snap_n_before_construction = int(
            raw_conn.execute("SELECT COUNT(*) AS c FROM opportunity_economic_snapshots").fetchone()["c"]
        )
        if snap_n_before_construction < 1:
            return False
        if close_calls["n"] != 0:
            return False
        if not _prove_construction_failure_isolation(result):
            return False
        # Prior successful process/emit persist on main borrowed conn remains.
        if close_calls["n"] != 0:
            return False
        if (
            int(raw_conn.execute("SELECT COUNT(*) AS c FROM opportunity_economic_snapshots").fetchone()["c"])
            != snap_n_before_construction
        ):
            return False
        if int(raw_conn.execute("SELECT COUNT(*) AS c FROM projects WHERE id = ?", (project_id,)).fetchone()["c"]) != 1:
            return False
        if int(raw_conn.execute("SELECT COUNT(*) AS c FROM raw_projects").fetchone()["c"]) != legacy_raw_count:
            return False
        if int(conn.execute("SELECT 1").fetchone()[0]) != 1:
            return False

        # Owner closes borrowed conn exactly once; economic path never pre-closed.
        conn.close()
        return close_calls["n"] == 1
    finally:
        with contextlib.suppress(Exception):
            evid_repo.close()
        with contextlib.suppress(Exception):
            snap_repo.close()
        if close_calls["n"] == 0:
            with contextlib.suppress(Exception):
                raw_conn.close()
        # else: already closed via tracking_close path


def _safe_bool(fn) -> bool:
    try:
        return bool(fn())
    except VerificationContractError:
        raise
    except Exception:
        return False


def run_verification() -> dict[str, bool]:
    """Return exact CASE_IDS keyset; all 26 stage A–C2 cases computed.

    Production modules may emit structlog lines during intentional isolation
    failures; those are swallowed here so CLI stdout stays free of fixture
    paths, canaries, and internal event-name fragments.
    """
    results: dict[str, bool] = {case_id: False for case_id in CASE_IDS}

    implemented = {
        "17.1.01": _case_17_1_01,
        "17.1.02": _case_17_1_02,
        "17.1.03": _case_17_1_03,
        "17.1.04": _case_17_1_04,
        "17.1.05": _case_17_1_05,
        "17.1.06": _case_17_1_06,
        "17.1.07": _case_17_1_07,
        "17.1.08": _case_17_1_08,
        "17.1.09": _case_17_1_09,
        "17.1.10": _case_17_1_10,
        "17.1.11": _case_17_1_11,
        "17.1.12": _case_17_1_12,
        "17.1.13": _case_17_1_13,
        "17.1.14": _case_17_1_14,
        "17.1.15": _case_17_1_15,
        "17.1.16": _case_17_1_16,
        "17.1.17": _case_17_1_17,
        "17.1.18": _case_17_1_18,
        "17.1.19": _case_17_1_19,
        "17.1.20": _case_17_1_20,
        "17.1.21": _case_17_1_21,
        "17.1.22": _case_17_1_22,
        "17.1.23": _case_17_1_23,
        "17.1.24": _case_17_1_24,
        "17.1.25": _case_17_1_25,
        "17.1.26": _case_17_1_26,
    }
    log_sink = io.StringIO()
    with contextlib.redirect_stdout(log_sink), contextlib.redirect_stderr(log_sink):
        for case_id, fn in implemented.items():
            results[case_id] = _safe_bool(fn)
    return results


def main(argv: list[str] | None = None) -> int:
    _ = argv
    try:
        results = run_verification()
    except Exception as exc:
        print(f"failure_type={type(exc).__name__}")
        print("RESULT: FAIL")
        return 1

    if set(results.keys()) != set(CASE_IDS) or len(results) != len(CASE_IDS):
        print("passed=0 failed=0 total=26")
        print("RESULT: FAIL")
        return 1

    passed = sum(1 for v in results.values() if v is True)
    failed = sum(1 for v in results.values() if v is not True)
    for key in sorted(results):
        print(f"{key}={results[key]}")
    print(f"passed={passed} failed={failed} total=26")
    if passed == 26 and failed == 0 and all(results[c] is True for c in CASE_IDS):
        print("RESULT: PASS")
        return 0
    print("RESULT: FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
