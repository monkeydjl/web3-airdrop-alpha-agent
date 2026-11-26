"""Airdrop Expected Yield & Portfolio Capital Allocation Simulator.

Deterministic pre-farming economic modeling.
Estimates FDV, community airdrop pool size, per-wallet expected returns (conservative, base, optimistic),
and solves optimal portfolio budget/time allocation across active FARM projects.
Zero commercial API cost.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.db import connection_scope, dict_from_row
from app.repository import ProjectRepository
from app.services.project_signals import signals_view
from app.utils.data_quality import mark_simulated


@dataclass(frozen=True)
class ProjectRoiSimulation:
    project_id: str
    project_name: str
    score: float
    funding_usd: float
    tvl_usd: float
    stage: str
    sector: str
    fdv_conservative_usd: float
    fdv_base_usd: float
    fdv_optimistic_usd: float
    airdrop_pool_base_usd: float
    estimated_participants: int
    expected_reward_conservative_usd: float
    expected_reward_base_usd: float
    expected_reward_optimistic_usd: float
    capital_invested_usd: float
    hours_spent: float
    net_profit_base_usd: float
    roi_multiple_base: float
    hourly_return_base_usd: float
    efficiency_rating: str  # "S" | "A" | "B" | "C"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def simulate_project_roi(
    project_id: str,
    capital_invested_usd: float = 100.0,
    hours_spent: float = 5.0,
) -> dict[str, Any]:
    """Simulate expected airdrop yield for a single project."""
    repo = ProjectRepository()
    project = repo.get_by_id(project_id)
    if not project:
        return {"ok": False, "error": f"Project {project_id} not found"}

    p = signals_view(project)
    name = str(p.get("name") or "Project")
    score = float(p.get("score") or 70.0)
    stage = str(p.get("stage") or "testnet").lower()
    sector = str(p.get("sector") or "infra").lower()

    # Extract funding and TVL
    meta = p.get("meta") or {}
    # 键契约（2026-11-19 深审 P1）：canonical 信号键是 funding_total_usd /
    # tvl_usd（structured_signals + defillama 写入侧）。旧键 "funding_total" /
    # "tvl" 不存在于任何写入路径，导致 FDV 公式的 TVL 项恒为 0。
    funding_val = p.get("funding_total_usd")
    if funding_val is None:
        funding_val = meta.get("funding", {}).get("total_raised")
    funding_usd = float(funding_val or 0.0)
    if funding_usd <= 0:
        # Fallback baseline funding estimation based on score & stage
        funding_usd = 15_000_000.0 if score >= 75 else 5_000_000.0

    tvl_usd = float(p.get("tvl_usd") or p.get("tvl") or 0.0)

    # Valuation (FDV) projection
    fdv_base = max(funding_usd * 8.0, tvl_usd * 1.5, 40_000_000.0)
    if score >= 80:
        fdv_base *= 1.4
    fdv_conservative = fdv_base * 0.45
    fdv_optimistic = fdv_base * 2.2

    # Airdrop community pool (typically 5% - 10%)
    airdrop_pool_base = fdv_base * 0.075

    # Estimated eligible addresses
    estimated_participants = 120_000 if "restaking" in sector else 200_000
    if bool(p.get("has_testnet")):
        estimated_participants = max(estimated_participants, 250_000)

    # Per-wallet expected yield
    # Top 30% active accounts usually capture 60% of tokens
    pool_per_account_base = (airdrop_pool_base * 0.60) / (estimated_participants * 0.30)
    pool_per_account_cons = (fdv_conservative * 0.04 * 0.60) / (estimated_participants * 0.30)
    pool_per_account_opt = (fdv_optimistic * 0.12 * 0.60) / (estimated_participants * 0.30)

    cap_invested = max(1.0, float(capital_invested_usd))
    hrs = max(0.5, float(hours_spent))

    net_profit = pool_per_account_base - cap_invested
    roi_multiple = round(pool_per_account_base / cap_invested, 2)
    hourly_return = round(max(0.0, net_profit) / hrs, 2)

    if roi_multiple >= 8.0 or hourly_return >= 50.0:
        rating = "S"
    elif roi_multiple >= 3.0 or hourly_return >= 25.0:
        rating = "A"
    elif roi_multiple >= 1.5:
        rating = "B"
    else:
        rating = "C"

    sim = ProjectRoiSimulation(
        project_id=project_id,
        project_name=name,
        score=score,
        funding_usd=funding_usd,
        tvl_usd=tvl_usd,
        stage=stage,
        sector=sector,
        fdv_conservative_usd=round(fdv_conservative, 0),
        fdv_base_usd=round(fdv_base, 0),
        fdv_optimistic_usd=round(fdv_optimistic, 0),
        airdrop_pool_base_usd=round(airdrop_pool_base, 0),
        estimated_participants=estimated_participants,
        expected_reward_conservative_usd=round(pool_per_account_cons, 1),
        expected_reward_base_usd=round(pool_per_account_base, 1),
        expected_reward_optimistic_usd=round(pool_per_account_opt, 1),
        capital_invested_usd=cap_invested,
        hours_spent=hrs,
        net_profit_base_usd=round(net_profit, 1),
        roi_multiple_base=roi_multiple,
        hourly_return_base_usd=hourly_return,
        efficiency_rating=rating,
    )
    return mark_simulated(
        {"ok": True, "data": sim.to_dict()},
        note="单项目 ROI 推演基于启发式倍数模型，非收益承诺",
    )


_RISK_PROFILES: dict[str, dict[str, float]] = {
    "conservative": {
        "restaking_budget_share": 0.70,
        "restaking_hours_share": 0.30,
        "restaking_multiple": 2.0,
        "testnet_budget_share": 0.60,
        "testnet_hours_share": 0.50,
        "testnet_multiple": 6.0,
        "faucet_reward": 100.0,
        "conservative_factor": 0.55,
        "optimistic_factor": 1.8,
    },
    "balanced": {
        "restaking_budget_share": 0.55,
        "restaking_hours_share": 0.25,
        "restaking_multiple": 2.2,
        "testnet_budget_share": 0.70,
        "testnet_hours_share": 0.60,
        "testnet_multiple": 8.5,
        "faucet_reward": 120.0,
        "conservative_factor": 0.45,
        "optimistic_factor": 2.2,
    },
    "aggressive": {
        "restaking_budget_share": 0.30,
        "restaking_hours_share": 0.15,
        "restaking_multiple": 2.6,
        "testnet_budget_share": 0.85,
        "testnet_hours_share": 0.70,
        "testnet_multiple": 12.0,
        "faucet_reward": 150.0,
        "conservative_factor": 0.30,
        "optimistic_factor": 3.0,
    },
}


def simulate_portfolio_allocation(
    total_budget_usd: float = 500.0,
    weekly_hours: float = 6.0,
    risk_appetite: str = "balanced",
) -> dict[str, Any]:
    """Optimize capital and time allocation across top active FARM projects."""
    # 存量泄漏修复：此前连接从不关闭；现由 connection_scope 保证 close 恰一次。
    with connection_scope() as conn:
        cursor = conn.execute(
            """
            SELECT id, name, score, stage, sector, meta
            FROM projects
            WHERE label = 'FARM' AND (source != 'historical_backfill' OR source IS NULL) AND hidden_reason IS NULL
            ORDER BY score DESC
            LIMIT 25
            """
        )
        rows = cursor.fetchall()
        farm_projects = [signals_view(dict_from_row(r)) for r in rows]

        if not farm_projects:
            # Fallback to top scored projects if FARM empty
            cursor = conn.execute(
                """
                SELECT id, name, score, stage, sector, meta
                FROM projects
                WHERE (source != 'historical_backfill' OR source IS NULL) AND hidden_reason IS NULL
                ORDER BY score DESC
                LIMIT 15
                """
            )
            farm_projects = [signals_view(dict_from_row(r)) for r in cursor.fetchall()]

    budget = max(20.0, float(total_budget_usd))
    hours = max(1.0, float(weekly_hours))
    normalized_appetite = risk_appetite if risk_appetite in _RISK_PROFILES else "balanced"
    profile = _RISK_PROFILES[normalized_appetite]

    allocations: list[dict[str, Any]] = []
    used_ids: set[str] = set()

    # Category buckets:
    # 1. Restaking / Yield Principal (captures large capital)
    # 2. Testnet Alpha (consumes low gas, high ROI multiple)
    # 3. Community / Faucet Grinds (zero gas, time only)

    restaking_projects = [
        p
        for p in farm_projects
        if any(k in str(p.get("sector") or "").lower() for k in ("restaking", "staking", "yield", "defi"))
    ]
    testnet_projects = [
        p
        for p in farm_projects
        if p not in restaking_projects and (p.get("stage") == "testnet" or "testnet" in str(p.get("name")).lower())
    ]
    other_projects = [p for p in farm_projects if p not in restaking_projects and p not in testnet_projects]

    remaining_budget = budget
    remaining_hours = hours

    # 1. Allocate to top Restaking project if budget >= $50
    if budget >= 50.0 and restaking_projects:
        p_res = restaking_projects[0]
        used_ids.add(str(p_res["id"]))
        res_budget = round(budget * profile["restaking_budget_share"], 1)
        res_hours = round(hours * profile["restaking_hours_share"], 1)
        res_mult = profile["restaking_multiple"]
        remaining_budget -= res_budget
        remaining_hours -= res_hours
        allocations.append(
            {
                "project_id": p_res["id"],
                "project_name": p_res["name"],
                "score": p_res.get("score", 75),
                "role": "核心本金沉淀 (质押/金库生息)",
                "allocated_budget_usd": res_budget,
                "allocated_hours_weekly": res_hours,
                "expected_multiple": res_mult,
                "expected_reward_usd": round(res_budget * res_mult, 1),
                "priority": "HIGH",
            }
        )

    # 2. Allocate Gas budget to top 2 Testnets (deduplicated via used_ids)
    testnet_candidates = [p for p in (testnet_projects + other_projects) if str(p["id"]) not in used_ids][:2]
    if testnet_candidates:
        per_gas = round(remaining_budget * profile["testnet_budget_share"] / len(testnet_candidates), 1)
        per_hrs = round(remaining_hours * profile["testnet_hours_share"] / len(testnet_candidates), 1)
        t_mult = profile["testnet_multiple"]
        for p_t in testnet_candidates:
            used_ids.add(str(p_t["id"]))
            allocations.append(
                {
                    "project_id": p_t["id"],
                    "project_name": p_t["name"],
                    "score": p_t.get("score", 72),
                    "role": "高弹性测试网 (Gas 交互与合约部署)",
                    "allocated_budget_usd": per_gas,
                    "allocated_hours_weekly": per_hrs,
                    "expected_multiple": t_mult,
                    "expected_reward_usd": round(max(15.0, per_gas * t_mult + 180.0), 1),
                    "priority": "HIGH",
                }
            )
            remaining_budget -= per_gas
            remaining_hours -= per_hrs

    # 3. Allocate remaining to zero-cost faucet/community tasks (strictly excluding used_ids)
    faucet_candidates = [p for p in (other_projects + testnet_projects) if str(p["id"]) not in used_ids][:2]
    for p_f in faucet_candidates:
        used_ids.add(str(p_f["id"]))
        f_hrs = round(max(0.5, remaining_hours / max(1, len(faucet_candidates))), 1)
        allocations.append(
            {
                "project_id": p_f["id"],
                "project_name": p_f["name"],
                "score": p_f.get("score", 70),
                "role": "零成本领水与社群交互 (0 Gas 保本)",
                "allocated_budget_usd": 0.0,
                "allocated_hours_weekly": f_hrs,
                "expected_multiple": 20.0,
                "expected_reward_usd": profile["faucet_reward"],
                "priority": "MEDIUM",
            }
        )

    total_expected_return = sum(a["expected_reward_usd"] for a in allocations)
    portfolio_roi = round(total_expected_return / max(1.0, budget), 2)
    hourly_yield = round(total_expected_return / max(1.0, hours * 4.0), 2)  # monthly basis

    return mark_simulated(
        {
            "ok": True,
            "data": {
                "total_budget_usd": budget,
                "weekly_hours": hours,
                "risk_appetite": normalized_appetite,
                "allocations": allocations,
                "total_expected_return_usd": round(total_expected_return, 1),
                "conservative_return_usd": round(total_expected_return * profile["conservative_factor"], 1),
                "optimistic_return_usd": round(total_expected_return * profile["optimistic_factor"], 1),
                "portfolio_roi_multiple": portfolio_roi,
                "monthly_hourly_yield_usd": hourly_yield,
                "summary_advice": (
                    f"将 ${budget} 资金与每周 {hours} 小时按「{normalized_appetite}」档位集中在 {len(allocations)} 个精选组合，"
                    f"在保持 0 成本防女巫隔离前提下，预估基准总产出约 ${round(total_expected_return, 0)} "
                    f"(投入产出倍数 ~{portfolio_roi}x)。"
                ),
            },
        },
        note="组合 ROI 分配模拟基于启发式倍数模型，非真实历史收益或收益承诺",
    )
