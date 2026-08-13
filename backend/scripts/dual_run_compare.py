#!/usr/bin/env python3
"""新旧引擎双跑对比（主评分决策引擎 + 旁路机会引擎）。

用法：
    # 1) 在旧代码上导出基线
    git stash && python scripts/dual_run_compare.py dump /tmp/before.json && git stash pop
    # 2) 在新代码上导出
    python scripts/dual_run_compare.py dump /tmp/after.json
    # 3) 对比
    python scripts/dual_run_compare.py diff /tmp/before.json /tmp/after.json

    # 旁路机会引擎（opportunity-v2.0）同理：
    git stash && python scripts/dual_run_compare.py dump-opp /tmp/opp_before.json && git stash pop
    python scripts/dual_run_compare.py dump-opp /tmp/opp_after.json
    python scripts/dual_run_compare.py diff-opp /tmp/opp_before.json /tmp/opp_after.json

评分语料 = 12 个 Golden 用例 + 覆盖信号空间的合成网格 + 走真实跨源合并路径的 60 个项目。
机会语料 = 覆盖「事件强度 × 资格机制 × 多钱包政策 × 成本档位 × 证据年龄」的确定性网格。
全部确定性、无随机。目的：量化有多少项目跨越决策边界，以及分布如何漂移。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from itertools import product
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(prefix="dualrun-"), "d.db"))
os.environ.setdefault("APP_ENV", "testing")

import asyncio

from app.agents.base import AgentContext, RawProject
from app.agents.orchestrator_simple import SimpleOrchestrator

SECTORS = ["L2", "DeFi", "Gaming", "AI", "Bridge"]


def build_corpus() -> list[RawProject]:
    """确定性语料：Golden 用例 + 信号空间网格。"""
    projects: list[RawProject] = []

    # 1) Golden 用例（引擎的回归锚点）
    try:
        from tests.golden.cases import GOLDEN_CASES

        for case in GOLDEN_CASES:
            projects.append(case.project)
    except Exception as exc:  # pragma: no cover
        print(f"warn: golden cases unavailable: {exc}", file=sys.stderr)

    # 2) 信号空间网格：覆盖影响各修复点的维度组合
    idx = 0
    for has_points, no_token, has_testnet, funding, task_portal, explicit in product([True, False], repeat=6):
        for stage in ("ideation", "testnet", "mainnet"):
            idx += 1
            projects.append(
                RawProject(
                    id=f"grid-{idx:05d}",
                    name=f"GridProject{idx}",
                    url=f"https://grid{idx}.example" if idx % 3 else None,
                    sector=SECTORS[idx % len(SECTORS)],
                    stage=stage,
                    source="seed",
                    has_points_program=has_points,
                    no_token_yet=no_token,
                    has_testnet=has_testnet,
                    recent_funding=funding,
                    has_task_portal=task_portal,
                    explicit_airdrop_mention=explicit,
                    has_docs=idx % 2 == 0,
                    has_github=idx % 3 == 0,
                    github_stars=(idx * 37) % 1500,
                    github_recent_push_days=(idx * 13) % 300,
                    has_twitter=idx % 4 != 0,
                    source_count=1 + (idx % 3),
                    funding_quality=round(((idx * 7) % 100) / 100, 2),
                    funding_tier=["unknown", "tier3", "tier2", "tier1"][idx % 4],
                    sybil_friction="unknown",
                    roadmap_delivery=["unknown", "aligned", "partial", "unclear"][idx % 4],
                )
            )
    return projects


def build_merge_path_corpus() -> list[RawProject]:
    """经过真实采集器合并路径的语料。

    直接把 RawProject 喂给编排器会绕过 `merge_raw_records`，而跨源合并丢信号
    与 source_count 恒为 1 恰恰发生在那里。这里落库多源 raw_projects 记录，
    再走 `CollectorAgent.collect_from_repository`，覆盖真实生产路径。
    """
    from datetime import UTC, datetime

    from app.agents.collector import CollectorAgent
    from app.collectors.base import CollectorResult, RawDiscovery
    from app.collectors.persistence import CollectionRepository
    from app.db import init_db

    init_db()
    repo = CollectionRepository()

    now = datetime.now(UTC)
    # 每个项目由「信号丰富的任务门户源」+「信号稀疏的行情源」两条记录构成，
    # 这是生产中最常见的形态，也是合并丢信号最致命的场景。
    for i in range(60):
        name = f"MergeProject{i}"
        rich = RawDiscovery(
            source_id="galxe",
            raw_id=f"galxe-{i}",
            name=name,
            url=f"https://{name.lower()}.example",
            sector=SECTORS[i % len(SECTORS)],
            stage="testnet",
            raw_data={
                "name": name,
                "description": "points program on galxe.com — airdrop snapshot eligible",
                "has_task_portal": True,
                "explicit_airdrop_mention": True,
                "has_docs": True,
                "has_whitepaper": True,
                "has_github": True,
                "github_stars": 400 + i,
                "github_recent_push_days": i % 30,
                "has_twitter": True,
                "has_points_program": True,
                "no_token_yet": True,
                "sybil_friction": "high",
                "roadmap_delivery": "aligned",
                "funding_quality": 0.7,
                "funding_tier": "tier1",
            },
            raw_signals=[],
            discovery_score=0.8,
            discovered_at=now,
        )
        sparse = RawDiscovery(
            source_id="defillama",
            raw_id=f"llama-{i}",
            name=name,
            url=None,
            sector=SECTORS[i % len(SECTORS)],
            stage="testnet",
            raw_data={"name": name, "sector": SECTORS[i % len(SECTORS)]},
            raw_signals=[],
            discovery_score=0.4,
            discovered_at=now,
        )
        for disc in (rich, sparse):
            result = CollectorResult(source_id=disc.source_id)
            result.started_at = now
            result.items = [disc]
            result.finished_at = now
            repo.persist_collection_result(result, source_name=disc.source_id)

    return CollectorAgent().collect_from_repository(repo, min_discovery_score=0.0, limit=200)


async def dump(path: str) -> None:
    projects = build_corpus()
    try:
        projects += build_merge_path_corpus()
    except Exception as exc:  # pragma: no cover
        print(f"warn: merge-path corpus unavailable: {exc}", file=sys.stderr)
    orch = SimpleOrchestrator()
    ctx = AgentContext(run_id="dual-run")
    counts = orch._calculate_sector_counts(projects)

    rows = []
    for project in projects:
        state = await orch._run_single_project(project, ctx, counts)
        rows.append(
            {
                "id": project.id,
                "name": project.name,
                "sector": project.sector,
                "stage": project.stage,
                "score": state.score,
                "label": state.label,
                "confidence": round(state.confidence, 4) if state.confidence is not None else None,
                "reason": list(state.reason or []),
                "sub_scores": {k: round(v, 3) for k, v in (getattr(state, "sub_scores", None) or {}).items()},
            }
        )
    Path(path).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    scored = [r for r in rows if r["score"] is not None]
    print(f"dumped {len(rows)} projects ({len(scored)} scored) -> {path}")


def diff(before_path: str, after_path: str) -> None:
    # 按 name 而非 id 对齐：项目 id 由内容派生（uuid5），跨源合并结果一变 id 就变，
    # 而"合并结果变了"恰恰是本轮最重要的改动。按 id 对齐会把这 60 个项目
    # 静默判为"新旧各自独有"从而排除在对比之外——正好漏掉影响最大的那部分。
    before = {r["name"]: r for r in json.loads(Path(before_path).read_text(encoding="utf-8"))}
    after = {r["name"]: r for r in json.loads(Path(after_path).read_text(encoding="utf-8"))}
    common = [pid for pid in before if pid in after]
    dropped = len(before) - len(common)
    if dropped:
        print(f"warn: {dropped} 个项目仅出现在基线中，未纳入对比", file=sys.stderr)

    label_moves: dict[str, int] = {}
    deltas: list[tuple[str, int, dict, dict]] = []
    unscored_before = unscored_after = 0

    for pid in common:
        b, a = before[pid], after[pid]
        if b["score"] is None:
            unscored_before += 1
        if a["score"] is None:
            unscored_after += 1
        if b["score"] is None or a["score"] is None:
            continue
        d = a["score"] - b["score"]
        deltas.append((pid, d, b, a))
        if b["label"] != a["label"]:
            key = f"{b['label']} -> {a['label']}"
            label_moves[key] = label_moves.get(key, 0) + 1

    n = len(deltas)
    changed = [d for d in deltas if d[1] != 0]
    print("=" * 68)
    print(f"语料规模              : {n} 个可比项目")
    print(f"分数发生变化          : {len(changed)} ({len(changed) / max(n, 1) * 100:.1f}%)")
    if changed:
        vals = sorted(d[1] for d in changed)
        print(f"分数变化区间          : {vals[0]:+d} .. {vals[-1]:+d}")
        print(f"平均变化              : {sum(vals) / len(vals):+.2f}")
        print(f"中位变化              : {vals[len(vals) // 2]:+d}")
    print(f"未评分(旧/新)         : {unscored_before} / {unscored_after}")
    print()
    print("标签迁移:")
    if label_moves:
        for key in sorted(label_moves, key=lambda k: -label_moves[k]):
            print(f"  {key:<24} {label_moves[key]:>5}")
        total_moved = sum(label_moves.values())
        print(f"  {'合计':<24} {total_moved:>5} ({total_moved / max(n, 1) * 100:.1f}%)")
    else:
        print("  无")

    def dist(rows: dict) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in rows.values():
            if r["label"]:
                out[r["label"]] = out.get(r["label"], 0) + 1
        return out

    print()
    print("标签分布:")
    db_, da_ = dist(before), dist(after)
    for label in ("FARM", "WATCH", "IGNORE"):
        print(
            f"  {label:<8} {db_.get(label, 0):>6} -> {da_.get(label, 0):>6}  ({da_.get(label, 0) - db_.get(label, 0):+d})"
        )

    print()
    print("变化最大的 15 个项目:")
    for pid, d, b, a in sorted(changed, key=lambda x: -abs(x[1]))[:15]:
        moved = "" if b["label"] == a["label"] else f"  [{b['label']}->{a['label']}]"
        print(f"  {pid:<16} {b['score']:>3} -> {a['score']:>3}  ({d:+d}){moved}")

    # 置信度分布（决定是否触发"低置信降级"）
    conf_pairs = [
        (b["confidence"], a["confidence"])
        for _, _, b, a in deltas
        if b["confidence"] is not None and a["confidence"] is not None
    ]
    if conf_pairs:
        cb = sorted(x for x, _ in conf_pairs)
        ca = sorted(y for _, y in conf_pairs)
        print()
        print("置信度分布:")
        print(f"  最小值   {cb[0]:.4f} -> {ca[0]:.4f}")
        print(f"  中位数   {cb[len(cb) // 2]:.4f} -> {ca[len(ca) // 2]:.4f}")
        print(f"  最大值   {cb[-1]:.4f} -> {ca[-1]:.4f}")
        print(
            f"  < 0.50   {sum(1 for x in cb if x < 0.5):>4} -> {sum(1 for y in ca if y < 0.5):>4}   (可触发低置信降级的项目数)"
        )

    # 子分维度归因
    print()
    print("子分平均变化（归因到具体修复点）:")
    keys = sorted({k for _, _, b, _ in deltas for k in b["sub_scores"]})
    printed = 0
    for k in keys:
        pairs = [(b["sub_scores"].get(k), a["sub_scores"].get(k)) for _, _, b, a in deltas]
        pairs = [(x, y) for x, y in pairs if x is not None and y is not None]
        if not pairs:
            continue
        avg = sum(y - x for x, y in pairs) / len(pairs)
        nz = sum(1 for x, y in pairs if abs(y - x) > 1e-9)
        print(f"  {k:<18} {avg:+7.2f}   (变化项目数 {nz})")
        printed += 1
    if not printed:
        print("  （不可用：基线版本尚未把 sub_scores 快照写进结果，无可比字段）")
    print("=" * 68)


# --------------------------------------------------------------------------
# 旁路机会引擎（opportunity-v2.0）
# --------------------------------------------------------------------------

OPP_NOW = None  # 在 dump_opportunity 内固定，避免模块导入期调用 datetime.now


def _opp_evidence(project_id, factor_key, value, now, **overrides):
    from datetime import timedelta

    from app.opportunity.models import EvidenceRecord

    value_types = {bool: "bool", float: "number", int: "number", str: "string", dict: "range"}
    data = {
        "evidence_id": f"{project_id}-{factor_key}",
        "project_id": project_id,
        "factor_key": factor_key,
        "value": value,
        "value_type": value_types[type(value)],
        "observation_type": "observed",
        "source_url": f"https://evidence.example/{factor_key}",
        "source_type": "official_docs",
        "source_grade": "A",
        "observed_at": now - timedelta(hours=1),
        "expires_at": now + timedelta(days=3650),
        "verification_status": "verified",
        "independence_group": f"source-{factor_key}",
        "raw_snapshot_ref": f"raw/{factor_key}",
    }
    data.update(overrides)
    return EvidenceRecord(**data)


def build_opportunity_corpus(now):
    """确定性机会语料。

    维度组合刻意覆盖本轮四处改动的触发面：
      - 资格机制 / 事件强度 / 多钱包政策 → 决定规则栈，命中 joint_probability 区间算法
      - 成本档位（预算内 / 超预算）      → 命中 TOO_EXPENSIVE 可达性
      - 证据年龄（含 >180 天与 >365 天） → 命中 freshness 长尾衰减
      - 显式概率 vs 规则派生             → 区分两条概率来源路径
    返回 [(project_id, [EvidenceRecord, ...]), ...]
    """
    from datetime import timedelta

    mechanisms = ["deterministic", "points_based", "behavioral"]
    events = ["statement_and_catalyst", "statement_only", "points_value"]
    policies = ["allowed", "not_forbidden"]
    costs = [("cheap", 1.0, 2.0, 3.0), ("near_limit", 5.0, 9.0, 12.0), ("over_budget", 25.0, 30.0, 40.0)]
    ages_days = [1, 100, 200, 400, 1825]

    corpus = []
    for idx, (mechanism, event, policy, (cost_name, c_lo, c_base, c_hi), age) in enumerate(
        product(mechanisms, events, policies, costs, ages_days), start=1
    ):
        pid = f"opp-{idx:04d}-{mechanism}-{event}-{policy}-{cost_name}-{age}d"
        observed_at = now - timedelta(days=age)
        aged = {"observed_at": observed_at}
        official = dict(aged, independence_group="official-rules")
        economics = dict(
            aged,
            observation_type="derived",
            source_grade="B",
            source_type="cost_model",
            independence_group="economics-model",
        )
        risk = dict(
            aged,
            observation_type="derived",
            source_grade="A",
            source_type="verified_risk_model",
            independence_group="risk-review",
        )

        records = [
            _opp_evidence(pid, "official_identity", True, now, **official),
            _opp_evidence(pid, "participation_open", True, now, **official),
            _opp_evidence(pid, "task_path_known", True, now, **official),
            _opp_evidence(pid, "authorization_exit_known", True, now, **official),
            _opp_evidence(pid, "project_active", True, now, **official),
            _opp_evidence(pid, "opportunity_timing", "open", now, **official),
            _opp_evidence(pid, "profile_fit", "fit", now, **official),
            _opp_evidence(pid, "multiwallet_policy", policy, now, **official),
            _opp_evidence(pid, "eligibility_mechanism", mechanism, now, **official),
            _opp_evidence(pid, "integrity_blocked", False, now, **official),
            _opp_evidence(pid, "safety_blocked", False, now, **official),
            _opp_evidence(pid, "conditional_reward_usd", {"low": 100, "base": 150, "high": 250}, now, **economics),
            _opp_evidence(pid, "hard_cost_usd", {"low": c_lo, "base": c_base, "high": c_hi}, now, **economics),
            _opp_evidence(pid, "capital_at_risk_usd", {"low": 0, "base": 0, "high": 0}, now, **economics),
            _opp_evidence(pid, "expected_capital_loss_usd", {"low": 0, "base": 0, "high": 0}, now, **economics),
            _opp_evidence(pid, "liquidity_cost_usd", {"low": 0, "base": 0, "high": 0}, now, **economics),
            _opp_evidence(pid, "total_time_hours", {"low": 1, "base": 2, "high": 3}, now, **economics),
            _opp_evidence(pid, "weekly_maintenance_hours", 1.0, now, **economics),
            _opp_evidence(
                pid,
                "project_quality",
                80.0,
                now,
                **dict(
                    aged,
                    observation_type="derived",
                    source_grade="B",
                    source_type="quality_model",
                    independence_group="quality-model",
                ),
            ),
            _opp_evidence(pid, "project_failure_risk", "low", now, **risk),
            _opp_evidence(pid, "capital_security_risk", "low", now, **risk),
            _opp_evidence(pid, "eligibility_risk", "low", now, **risk),
            _opp_evidence(pid, "reward_dilution_risk", "low", now, **risk),
            _opp_evidence(pid, "liquidity_risk", "low", now, **risk),
        ]
        # 事件侧：三档强度，全部走规则派生（不注入显式 event_probability）
        if event == "statement_and_catalyst":
            records.append(_opp_evidence(pid, "official_airdrop_statement", True, now, **official))
            records.append(_opp_evidence(pid, "distribution_catalyst_3_6m", True, now, **official))
        elif event == "statement_only":
            records.append(_opp_evidence(pid, "official_airdrop_statement", True, now, **official))
            records.append(_opp_evidence(pid, "distribution_catalyst_3_6m", True, now, **official))
            records.append(_opp_evidence(pid, "official_points_future_value", False, now, **official))
        else:
            records.append(_opp_evidence(pid, "official_points_future_value", True, now, **official))
            records.append(_opp_evidence(pid, "distribution_catalyst_3_6m", True, now, **official))
            records.append(_opp_evidence(pid, "official_airdrop_statement", False, now, **official))
        corpus.append((pid, records))
    return corpus


def dump_opportunity(path: str) -> None:
    import sqlite3
    from datetime import UTC, datetime

    from app.db import init_db
    from app.opportunity.repository import OpportunityRepository
    from app.opportunity.service import OpportunityService
    from app.repository import ProjectRepository

    now = datetime(2026, 7, 15, 12, tzinfo=UTC)  # 固定 now，保证两次跑完全可比
    corpus = build_opportunity_corpus(now)

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    for pid, _ in corpus:
        conn.execute(
            "INSERT INTO projects (id, name, sector, stage, score, label, confidence, source)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (pid, pid, "DeFi", "testnet", 70, "FARM", 0.8, "seed"),
        )
    conn.commit()

    service = OpportunityService(
        project_repo=ProjectRepository(conn),
        opportunity_repo=OpportunityRepository(conn),
        now_factory=lambda: now,
    )
    rows = []
    for pid, records in corpus:
        for record in records:
            service.opportunity_repo.add_evidence(record)
        a = service.evaluate(pid, persist=False)
        rp = a.reward_probability
        rows.append(
            {
                "id": pid,
                "status": a.status.value if hasattr(a.status, "value") else str(a.status),
                "label": a.public_label,
                "ignore_codes": list(a.ignore_reason_codes),
                "watch_codes": list(a.watch_reason_codes),
                "blocker_codes": list(a.blocker_codes),
                "reward_p_low": round(rp.low, 6) if rp else None,
                "reward_p_base": round(rp.base, 6) if rp else None,
                "reward_p_high": round(rp.high, 6) if rp else None,
                "confidence_overall": round(a.confidence.overall, 6) if a.confidence else None,
                "confidence_cost": round(a.confidence.cost, 6) if a.confidence else None,
                "net_reward_base": (round(a.economics.net_reward.base, 4) if a.economics else None),
            }
        )
    conn.close()
    Path(path).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"dumped {len(rows)} opportunity assessments -> {path}")


def diff_opportunity(before_path: str, after_path: str) -> None:
    before = {r["id"]: r for r in json.loads(Path(before_path).read_text(encoding="utf-8"))}
    after = {r["id"]: r for r in json.loads(Path(after_path).read_text(encoding="utf-8"))}
    common = [pid for pid in before if pid in after]

    status_moves: dict[str, int] = {}
    label_moves: dict[str, int] = {}
    code_moves: dict[str, int] = {}
    width_deltas: list[float] = []
    low_deltas: list[float] = []
    conf_deltas: list[float] = []
    gate_gained = gate_lost = 0

    for pid in common:
        b, a = before[pid], after[pid]
        if b["status"] != a["status"]:
            status_moves[f"{b['status']} -> {a['status']}"] = status_moves.get(f"{b['status']} -> {a['status']}", 0) + 1
        if b["label"] != a["label"]:
            label_moves[f"{b['label']} -> {a['label']}"] = label_moves.get(f"{b['label']} -> {a['label']}", 0) + 1
        bc = tuple(b["ignore_codes"] or b["watch_codes"] or b["blocker_codes"])
        ac = tuple(a["ignore_codes"] or a["watch_codes"] or a["blocker_codes"])
        if bc != ac:
            key = f"{'/'.join(bc) or '-'} -> {'/'.join(ac) or '-'}"
            code_moves[key] = code_moves.get(key, 0) + 1
        if b["reward_p_low"] is not None and a["reward_p_low"] is not None:
            low_deltas.append(a["reward_p_low"] - b["reward_p_low"])
            width_deltas.append((a["reward_p_high"] - a["reward_p_low"]) - (b["reward_p_high"] - b["reward_p_low"]))
            if b["reward_p_low"] < 0.20 <= a["reward_p_low"]:
                gate_gained += 1
            if a["reward_p_low"] < 0.20 <= b["reward_p_low"]:
                gate_lost += 1
        if b["confidence_overall"] is not None and a["confidence_overall"] is not None:
            conf_deltas.append(a["confidence_overall"] - b["confidence_overall"])

    n = len(common)
    print("=" * 74)
    print(f"机会语料规模                : {n} 个可比项目")
    print(
        f"决策状态发生变化            : {sum(status_moves.values())} ({sum(status_moves.values()) / max(n, 1) * 100:.1f}%)"
    )
    print(
        f"公开标签发生变化            : {sum(label_moves.values())} ({sum(label_moves.values()) / max(n, 1) * 100:.1f}%)"
    )
    if low_deltas:
        print(
            f"reward_probability.low      : 均值 {sum(low_deltas) / len(low_deltas):+.4f}"
            f"  区间 {min(low_deltas):+.4f} .. {max(low_deltas):+.4f}"
        )
        print(
            f"reward_probability 区间宽度 : 均值 {sum(width_deltas) / len(width_deltas):+.4f}"
            f"  区间 {min(width_deltas):+.4f} .. {max(width_deltas):+.4f}"
        )
        print(f"跨过 low>=0.20 FARM 门槛    : 新获得 {gate_gained} / 新失去 {gate_lost}")
    if conf_deltas:
        print(
            f"confidence.overall          : 均值 {sum(conf_deltas) / len(conf_deltas):+.4f}"
            f"  区间 {min(conf_deltas):+.4f} .. {max(conf_deltas):+.4f}"
        )

    for title, moves in (("决策状态迁移", status_moves), ("公开标签迁移", label_moves), ("理由码迁移", code_moves)):
        print()
        print(f"{title}:")
        if not moves:
            print("  无")
            continue
        for key in sorted(moves, key=lambda k: -moves[k])[:12]:
            print(f"  {key:<58} {moves[key]:>5}")

    def dist(rows, field):
        out: dict[str, int] = {}
        for r in rows.values():
            out[r[field]] = out.get(r[field], 0) + 1
        return out

    print()
    print("决策状态分布:")
    db_, da_ = dist(before, "status"), dist(after, "status")
    for key in sorted(set(db_) | set(da_)):
        print(f"  {key:<24} {db_.get(key, 0):>6} -> {da_.get(key, 0):>6}  ({da_.get(key, 0) - db_.get(key, 0):+d})")
    print("=" * 74)


# --------------------------------------------------------------------------
# 真实库双跑（读取生产 SQLite，不写回）
# --------------------------------------------------------------------------


async def dump_db(path: str, db_path: str) -> None:
    """按 `/rescore` 的真实链路重算整库，导出结果快照。

    重建方式与 `routers/v1/funding.py` 的单项目重算完全一致
    （`_row_to_raw_project` + `_run_single_project`），因此这份对比就是
    "如果对存量库执行一次全量 re-score，会发生什么"的直接答案。

    **只读**：库被复制到临时目录后才打开，原文件不受影响。
    """
    import shutil
    import sqlite3

    work_db = os.path.join(tempfile.mkdtemp(prefix="realdb-"), "copy.db")
    shutil.copy(db_path, work_db)

    raw = sqlite3.connect(work_db)
    raw.row_factory = sqlite3.Row
    rows = [dict(r) for r in raw.execute("SELECT * FROM projects ORDER BY id")]
    raw.close()

    from app.routers.v1.funding import _row_to_raw_project

    projects = []
    skipped = 0
    for row in rows:
        try:
            projects.append(_row_to_raw_project(row))
        except Exception as exc:  # pragma: no cover
            skipped += 1
            print(f"warn: 跳过 {row.get('id')}: {exc}", file=sys.stderr)

    orch = SimpleOrchestrator()
    ctx = AgentContext(run_id="dual-run-realdb")
    counts = orch._calculate_sector_counts(projects)

    by_id = {row["id"]: row for row in rows}
    out = []
    for project in projects:
        state = await orch._run_single_project(project, ctx, counts)
        row = by_id.get(project.id, {})
        out.append(
            {
                "id": project.id,
                "name": project.name,
                "sector": project.sector,
                "stage": project.stage,
                "source": row.get("source"),
                "source_count": int(getattr(project, "source_count", 1) or 1),
                "old_score": row.get("score"),
                "old_label": row.get("label"),
                "score": state.score,
                "label": state.label,
                "confidence": round(state.confidence, 4) if state.confidence is not None else None,
                "reason": list(state.reason or []),
                "sub_scores": {k: round(v, 3) for k, v in (getattr(state, "sub_scores", None) or {}).items()},
            }
        )
    Path(path).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"dumped {len(out)} projects from {db_path} -> {path} (skipped {skipped})")


def diff_db(before_path: str, after_path: str) -> None:
    """真实库双跑对比，按 sector / stage / 来源分层。"""
    before = {r["id"]: r for r in json.loads(Path(before_path).read_text(encoding="utf-8"))}
    after = {r["id"]: r for r in json.loads(Path(after_path).read_text(encoding="utf-8"))}
    common = [pid for pid in before if pid in after]

    deltas = []
    label_moves: dict[str, int] = {}
    for pid in common:
        b, a = before[pid], after[pid]
        if b["score"] is None or a["score"] is None:
            continue
        deltas.append((pid, a["score"] - b["score"], b, a))
        if b["label"] != a["label"]:
            key = f"{b['label']} -> {a['label']}"
            label_moves[key] = label_moves.get(key, 0) + 1

    n = len(deltas)
    changed = [d for d in deltas if d[1] != 0]
    print("=" * 72)
    print(f"真实库项目数            : {n}")
    print(f"分数发生变化            : {len(changed)} ({len(changed) / max(n, 1) * 100:.1f}%)")
    if changed:
        vals = sorted(d[1] for d in changed)
        print(f"分数变化区间            : {vals[0]:+d} .. {vals[-1]:+d}")
        print(f"平均变化(仅变化项)      : {sum(vals) / len(vals):+.2f}")
        print(f"中位变化(仅变化项)      : {vals[len(vals) // 2]:+d}")
        allv = sorted(d[1] for d in deltas)
        print(f"平均变化(全部项目)      : {sum(allv) / len(allv):+.2f}")

    print()
    print("标签迁移:")
    if label_moves:
        for key in sorted(label_moves, key=lambda k: -label_moves[k]):
            print(f"  {key:<24} {label_moves[key]:>5}")
        total = sum(label_moves.values())
        print(f"  {'合计':<24} {total:>5} ({total / max(n, 1) * 100:.1f}%)")
    else:
        print("  无")

    def dist(rows):
        out: dict[str, int] = {}
        for r in rows:
            if r["label"]:
                out[r["label"]] = out.get(r["label"], 0) + 1
        return out

    print()
    print("标签分布:")
    db_ = dist([before[p] for p in common])
    da_ = dist([after[p] for p in common])
    for label in ("FARM", "WATCH", "IGNORE"):
        b_, a_ = db_.get(label, 0), da_.get(label, 0)
        print(
            f"  {label:<8} {b_:>5} ({b_ / max(n, 1) * 100:4.1f}%) -> {a_:>5} ({a_ / max(n, 1) * 100:4.1f}%)   ({a_ - b_:+d})"
        )

    for dim in ("sector", "stage", "source"):
        buckets: dict[str, list] = {}
        for _pid, d, b, a in deltas:
            buckets.setdefault(str(b.get(dim) or "-"), []).append((d, b, a))
        print()
        print(f"按 {dim} 分层（仅列前 8 组）:")
        print(f"  {'':<18} {'项目数':>6} {'均值Δ':>8} {'换标签':>7}")
        for key in sorted(buckets, key=lambda k: -len(buckets[k]))[:8]:
            items = buckets[key]
            avg = sum(d for d, _, _ in items) / len(items)
            moved = sum(1 for _, b, a in items if b["label"] != a["label"])
            print(f"  {key:<18} {len(items):>6} {avg:>+8.2f} {moved:>7}")

    print()
    print("变化最大的 15 个项目:")
    for _pid, d, b, a in sorted(changed, key=lambda x: -abs(x[1]))[:15]:
        moved = "" if b["label"] == a["label"] else f"  [{b['label']}->{a['label']}]"
        print(f"  {b['name'][:26]:<27} {b['score']:>3} -> {a['score']:>3}  ({d:+d}){moved}")

    conf = [
        (b["confidence"], a["confidence"])
        for _, _, b, a in deltas
        if b["confidence"] is not None and a["confidence"] is not None
    ]
    if conf:
        cb = sorted(x for x, _ in conf)
        ca = sorted(y for _, y in conf)
        print()
        print("置信度分布:")
        print(f"  最小值   {cb[0]:.4f} -> {ca[0]:.4f}")
        print(f"  中位数   {cb[len(cb) // 2]:.4f} -> {ca[len(ca) // 2]:.4f}")
        print(f"  最大值   {cb[-1]:.4f} -> {ca[-1]:.4f}")
        print(f"  < 0.50   {sum(1 for x in cb if x < 0.5):>5} -> {sum(1 for y in ca if y < 0.5):>5}   (触发低置信降档)")
    print("=" * 72)


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "dump":
        asyncio.run(dump(sys.argv[2]))
    elif len(sys.argv) >= 4 and sys.argv[1] == "diff":
        diff(sys.argv[2], sys.argv[3])
    elif len(sys.argv) >= 3 and sys.argv[1] == "dump-opp":
        dump_opportunity(sys.argv[2])
    elif len(sys.argv) >= 4 and sys.argv[1] == "diff-opp":
        diff_opportunity(sys.argv[2], sys.argv[3])
    elif len(sys.argv) >= 4 and sys.argv[1] == "dump-db":
        asyncio.run(dump_db(sys.argv[2], sys.argv[3]))
    elif len(sys.argv) >= 4 and sys.argv[1] == "diff-db":
        diff_db(sys.argv[2], sys.argv[3])
    else:
        print(__doc__)
        sys.exit(1)
