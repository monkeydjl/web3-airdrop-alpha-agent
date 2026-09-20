"""Multi-wallet strategy recommendation engine (US-019 / Roadmap W12-01).

Analyzes project sybil difficulty, stage, cost profile, and participation paths to
produce actionable multi-wallet allocation advice, capital estimates, and anti-sybil hygiene guidelines.

Reference:
- docs/USER_STORIES.md US-019 (多钱包管理建议)
- docs/TASK_BREAKDOWN.md W12-01 (多钱包策略建议)
- docs/DATA_SCORING_DICT.md §5.4 sybil_factor
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.agents.eligibility import (
    VETO_ALREADY_LAUNCHED,
    VETO_EXPLICIT_NO_AIRDROP,
    VETO_NO_PARTICIPATION_PATH,
)
from app.services.project_signals import signals_view


@dataclass(frozen=True)
class HygieneRule:
    rule_id: str
    title: str
    description: str
    severity: str  # "critical" | "warning" | "tip"


@dataclass(frozen=True)
class MultiWalletStrategy:
    project_id: str
    project_name: str
    status: str  # "recommended" | "selective" | "ineligible"
    recommended_wallets_min: int
    recommended_wallets_max: int
    recommended_wallets_optimal: int
    tier: str  # "not_recommended" | "single_curated" | "small_cluster" | "medium_scale"
    tier_zh: str
    strategy_summary: str
    capital_per_wallet_usd_min: float
    capital_per_wallet_usd_max: float
    total_capital_usd_min: float
    total_capital_usd_max: float
    capital_notes: str
    weekly_hours_per_wallet: float
    total_weekly_hours: float
    hygiene_guidelines: list[dict[str, str]] = field(default_factory=list)
    risk_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_STANDARD_HYGIENE_RULES: list[HygieneRule] = [
    HygieneRule(
        rule_id="zero_wallet_transfer",
        title="严禁钱包互转（资金零关联）",
        description="所有参与钱包之间绝对不要在链上有直接资金往来。提币必须经由中心化交易所不同子账号独立出金。",
        severity="critical",
    ),
    HygieneRule(
        rule_id="temporal_dispersion",
        title="时间与金额离散化",
        description="避免多钱包同区块或相近时间段执行同质操作。各钱包交互时间随机间隔数小时或数天，交互金额加入随机小数位。",
        severity="critical",
    ),
    HygieneRule(
        rule_id="path_differentiation",
        title="链上轨迹差异化",
        description="不同钱包选择不同的交互路径、协议与路由组合（如主号重借贷与流动性，副号重 DEX 与合约交互），避免行为镜像被聚类清洗。",
        severity="warning",
    ),
    HygieneRule(
        rule_id="environment_isolation",
        title="环境与设备隔离",
        description="多账号配合防关联指纹浏览器（配置独立 Cookie/Canvas 隔离）和固定代理节点，避免同一 IP/浏览器指纹多登。",
        severity="warning",
    ),
]


def generate_multi_wallet_strategy(project_data: Any) -> MultiWalletStrategy:
    """Generate multi-wallet recommendations for a given project.

    Accepts a RawProject, a DB row mapping, or an API project dict.
    """
    if hasattr(project_data, "to_dict"):
        raw_dict = project_data.to_dict()
    elif isinstance(project_data, dict):
        raw_dict = project_data
    else:
        raw_dict = dict(project_data)
    p = signals_view(raw_dict)
    pid = str(p.get("id") or "unknown")
    name = str(p.get("name") or "Project")
    label = str(p.get("label") or "WATCH").upper()
    veto = p.get("veto")
    stage = str(p.get("stage") or "unknown").lower()
    sector = str(p.get("sector") or "").lower()
    desc = str(p.get("description") or "").lower()
    friction = str(p.get("sybil_friction") or "unknown").lower()

    is_perp = any(k in sector for k in ("perp", "derivative", "perpetual")) or any(
        k in desc for k in ("perpetual", "perp dex", "derivative")
    )
    is_mainnet = stage == "mainnet"
    is_testnet = stage == "testnet" or (not is_mainnet and bool(p.get("has_testnet")))
    has_points = bool(p.get("has_points_program"))

    # 1. Ineligible projects: token already launched or explicit refusal
    if label == "IGNORE" or veto in (VETO_ALREADY_LAUNCHED, VETO_EXPLICIT_NO_AIRDROP):
        return MultiWalletStrategy(
            project_id=pid,
            project_name=name,
            status="ineligible",
            recommended_wallets_min=0,
            recommended_wallets_max=0,
            recommended_wallets_optimal=0,
            tier="not_recommended",
            tier_zh="不建议投入",
            strategy_summary="该项目无有效空投捕获空间（已发行代币或官方声明无激励），不建议投入任何钱包或时间资源。",
            capital_per_wallet_usd_min=0.0,
            capital_per_wallet_usd_max=0.0,
            total_capital_usd_min=0.0,
            total_capital_usd_max=0.0,
            capital_notes="零投入预估（建议将资金分配至其他高优先级 FARM 项目）。",
            weekly_hours_per_wallet=0.0,
            total_weekly_hours=0.0,
            hygiene_guidelines=[],
            risk_warnings=["资格已否决：投入大概率沉没。"],
        )

    # 2. Selective watchlist: missing verifiable path
    if veto == VETO_NO_PARTICIPATION_PATH or (label == "WATCH" and not (is_testnet or has_points)):
        return MultiWalletStrategy(
            project_id=pid,
            project_name=name,
            status="selective",
            recommended_wallets_min=1,
            recommended_wallets_max=2,
            recommended_wallets_optimal=1,
            tier="single_curated",
            tier_zh="单号轻度观察（1~2 个）",
            strategy_summary="当前项目暂未公布明确的测试网、积分或交互入口，不适宜铺开多钱包。建议保留 1 个主号保持关注与社交绑定。",
            capital_per_wallet_usd_min=0.0,
            capital_per_wallet_usd_max=10.0,
            total_capital_usd_min=0.0,
            total_capital_usd_max=15.0,
            capital_notes="仅需预留少量用于早期身份绑定或基础跨链的 Gas。",
            weekly_hours_per_wallet=0.25,
            total_weekly_hours=0.25,
            hygiene_guidelines=[_as_dict(r) for r in _STANDARD_HYGIENE_RULES[:2]],
            risk_warnings=["参与路径尚在形成中，过早多号会造成资金空转。"],
        )

    # 3. Actionable opportunities (FARM or active WATCH)
    # Determine sybil tier
    if friction == "high" or "kyc" in desc or "passport" in desc:
        # High sybil friction: KYC/humanhood/Gitcoin passport
        w_min, w_max, w_opt = 1, 2, 1
        tier = "single_curated"
        tier_zh = "精品主号深耕（1~2 个）"
        summary = "反女巫门槛较高（涉及人脸识别、社交认证或高资金留存要求），大批量多号极易遭遇清洗。建议以 1~2 个主号重点做深。"
        hours_per_wallet = 1.5
    elif friction == "low" and is_testnet:
        # Low sybil friction + testnet: broad distribution but high dilution
        w_min, w_max, w_opt = 5, 10, 5
        tier = "medium_scale"
        tier_zh = "测试节点适度铺开（5~10 个）"
        summary = "门槛较低且无需真实本金，预期刷量稀释严重。建议以 5~10 个钱包形成中等规模矩阵适度覆盖，控制时间边际效益。"
        hours_per_wallet = 0.3
    else:
        # Medium sybil friction: standard on-chain contracts / L2 ecosystem
        w_min, w_max, w_opt = 3, 5, 3
        tier = "small_cluster"
        tier_zh = "梯度小梯队（3~5 个）"
        summary = "综合女巫难度中等，最适合 3~5 个钱包梯度参与：1 个核心精品号深入交互，搭配 2~4 个阶梯副号完成核心交互指标。"
        hours_per_wallet = 0.8

    # Calculate capital requirements
    if is_perp and not is_testnet:
        cap_min = 50.0
        cap_max = 200.0
        cap_note = "合约交易保证金、手续费磨损与资金费率预留（单号建议充值 ≥50 USD）。"
    elif is_testnet:
        cap_min = 0.0
        cap_max = 5.0
        cap_note = "测试网水龙头零成本，仅预留极少量主网 Gas 或跨链测试手续费。"
    else:
        cap_min = 15.0
        cap_max = 50.0
        cap_note = "主网交互 Gas、流动性底仓与跨链损耗预算。"

    tot_cap_min = round(cap_min * w_opt, 1)
    tot_cap_max = round(cap_max * w_opt, 1)
    tot_hours = round(hours_per_wallet * w_opt, 1)

    warnings: list[str] = []
    if is_perp and not is_testnet:
        warnings.append("Perp DEX 磨损风险：开仓时请选择对冲或极低杠杆，防止波动导致本金亏损。")
    if friction == "low":
        warnings.append("同质化稀释风险：由于交互低门槛，官方大概率在发币前设置严格女巫规则，请务必执行环境隔离。")
    if w_opt >= 3:
        warnings.append("关联清洗风险：切忌将参与钱包互转或归集至同一充值地址。")

    return MultiWalletStrategy(
        project_id=pid,
        project_name=name,
        status="recommended",
        recommended_wallets_min=w_min,
        recommended_wallets_max=w_max,
        recommended_wallets_optimal=w_opt,
        tier=tier,
        tier_zh=tier_zh,
        strategy_summary=summary,
        capital_per_wallet_usd_min=cap_min,
        capital_per_wallet_usd_max=cap_max,
        total_capital_usd_min=tot_cap_min,
        total_capital_usd_max=tot_cap_max,
        capital_notes=cap_note,
        weekly_hours_per_wallet=hours_per_wallet,
        total_weekly_hours=tot_hours,
        hygiene_guidelines=[_as_dict(r) for r in _STANDARD_HYGIENE_RULES],
        risk_warnings=warnings,
    )


def _as_dict(rule: HygieneRule) -> dict[str, str]:
    return {
        "rule_id": rule.rule_id,
        "title": rule.title,
        "description": rule.description,
        "severity": rule.severity,
    }

