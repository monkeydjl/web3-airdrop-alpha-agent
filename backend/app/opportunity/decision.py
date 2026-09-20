from collections.abc import Iterable
from datetime import datetime, timedelta

from app.opportunity.models import (
    DecisionResult,
    DecisionStatus,
    EconomicsResult,
    OpportunityInputs,
    OpportunityProfile,
    ProbabilityRange,
    RiskLevel,
)

WATCH_REASON_ACTIONS = {
    "WAIT_TASK_OPEN": "Wait for official participation to open, then reassess.",
    "WAIT_RULES": "Wait for official eligibility and multiwallet rules, then reassess.",
    "WAIT_CATALYST": "Monitor official distribution catalysts within the 3-6 month horizon.",
    "WAIT_COST_DROP": "Wait for the recommended hard cost to fall within the profile limit.",
    "WAIT_MORE_EVIDENCE": "Collect stronger, independent evidence for the unmet FARM gates.",
    "WAIT_EARLY_ENTRY": "Monitor for an actionable participation window or clearer eligibility path.",
    "REWARD_TOO_UNCERTAIN": "Validate conservative reward economics before participating.",
    "SINGLE_WALLET_ONLY": "Use a compatible single-wallet profile if official rules permit it.",
}

IGNORE_REASON_ACTIONS = {
    "NEGATIVE_EXPECTED_VALUE": "Do not participate while base expected net value is negative.",
    "DUST_REWARD": "Do not participate when even the optimistic reward is immaterial.",
    "TOO_EXPENSIVE": "Do not participate when the minimum hard cost exceeds this profile.",
    "TOO_TIME_INTENSIVE": "Do not participate when minimum maintenance exceeds this profile.",
    "TOO_LATE": "Do not participate after the eligible entry window has closed.",
    "NO_AIRDROP_CASE": "Do not participate without a viable distribution case.",
    "PROJECT_INACTIVE": "Do not participate while the project is confirmed inactive.",
    "PROFILE_MISMATCH": "Do not participate under this user profile.",
}

BLOCK_REASON_ACTIONS = {
    "SAFETY_BLOCK": "Do not interact until credible remediation evidence is verified.",
    "INTEGRITY_BLOCK": "Do not interact until credible remediation evidence is verified.",
    "RULE_BLOCK": "Do not interact until credible remediation evidence is verified.",
}

# critical_unknowns 有两个生产者，各用一套命名：
#   - build_inputs 用 CRITICAL_KEYS（无后缀，如 conditional_reward）
#   - service.evaluate_row 用模型字段名（带 _usd/_hours 后缀）
# 此前映射表只收录了前者，导致后者注入的 8 个名字全部落到通用码
# WAIT_MORE_EVIDENCE；且 conditional_reward 与 conditional_reward_usd 同时出现
# 时会为同一件缺失事实产出两条自相矛盾的理由。此处两套命名都登记。
_UNKNOWN_REASON_CODES = {
    # build_inputs 命名
    "participation_open": "WAIT_TASK_OPEN",
    "multiwallet_policy": "WAIT_RULES",
    "distribution_catalyst_3_6m": "WAIT_CATALYST",
    "conditional_reward": "REWARD_TOO_UNCERTAIN",
    "hard_cost": "WAIT_MORE_EVIDENCE",
    "weekly_maintenance": "WAIT_MORE_EVIDENCE",
    # service.evaluate_row 命名（模型字段名）
    "conditional_reward_usd": "REWARD_TOO_UNCERTAIN",
    "reward_probability": "REWARD_TOO_UNCERTAIN",
    "hard_cost_usd": "WAIT_MORE_EVIDENCE",
    "capital_at_risk_usd": "WAIT_MORE_EVIDENCE",
    "expected_capital_loss_usd": "WAIT_MORE_EVIDENCE",
    "liquidity_cost_usd": "WAIT_MORE_EVIDENCE",
    "total_time_hours": "WAIT_MORE_EVIDENCE",
    "economics_direct_evidence": "WAIT_MORE_EVIDENCE",
}

_ACTIONABLE_ACTION = "Run 1-2 wallets, record actual cost and time, then reassess before expanding."
_INSUFFICIENT_ACTION = "Collect the missing critical evidence before participating."
_NOT_FIT_ACTION = "Do not allocate time or funds under the current profile."
_BLOCKED_ACTION = "Do not interact until credible remediation evidence is verified."

WATCH_REASON_ACTIONS_ZH = {
    "WAIT_TASK_OPEN": "等待官方参与通道开启后再行评估。",
    "WAIT_RULES": "等待官方资格与多钱包规则明朗后再行评估。",
    "WAIT_CATALYST": "关注 3-6 个月内的官方分发催化剂。",
    "WAIT_COST_DROP": "等待推荐硬性成本回落至画像限额内。",
    "WAIT_MORE_EVIDENCE": "针对未达标的 FARM 门槛收集更有力的独立证据。",
    "WAIT_EARLY_ENTRY": "观察可参与的时间窗口或更清晰的资格路径。",
    "REWARD_TOO_UNCERTAIN": "在参与前先核验保守收益预期。",
    "SINGLE_WALLET_ONLY": "若官方规则允许，使用兼容的单钱包画像参与。",
}

IGNORE_REASON_ACTIONS_ZH = {
    "NEGATIVE_EXPECTED_VALUE": "在基准预期净收益为负时切勿参与。",
    "DUST_REWARD": "在乐观预估收益仍微不足道时不建议参与。",
    "TOO_EXPENSIVE": "当最低硬性成本超出当前画像承受能力时不参与。",
    "TOO_TIME_INTENSIVE": "当最低维护时间超出当前画像设定时不参与。",
    "TOO_LATE": "资格准入窗口关闭后切勿参与。",
    "NO_AIRDROP_CASE": "在缺乏可行分发依据时不建议参与。",
    "PROJECT_INACTIVE": "项目已确认处于非活跃状态，切勿参与。",
    "PROFILE_MISMATCH": "在当前用户画像下不建议参与。",
}

BLOCK_REASON_ACTIONS_ZH = {
    "SAFETY_BLOCK": "在可信整改证据核实前切勿交互。",
    "INTEGRITY_BLOCK": "在可信整改证据核实前切勿交互。",
    "RULE_BLOCK": "在官方规则明朗或完成整改前切勿交互。",
}

ACTION_RECOMMENDATIONS_ZH = {
    _ACTIONABLE_ACTION: "建议先运行 1-2 个钱包，记录实际成本与时间，再评估是否扩容。",
    _INSUFFICIENT_ACTION: "在参与前先补齐缺失的关键证据。",
    _NOT_FIT_ACTION: "在当前画像下切勿投入时间或资金。",
    _BLOCKED_ACTION: "在可信整改证据核实前切勿交互。",
}


def decide(
    *,
    inputs: OpportunityInputs,
    event: ProbabilityRange | None,
    eligibility: ProbabilityRange | None,
    survival: ProbabilityRange | None,
    reward_probability: ProbabilityRange | None,
    economics: EconomicsResult | None,
    profile: OpportunityProfile,
    now: datetime,
) -> DecisionResult:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")

    capital_security_risk = _safest_risk(
        inputs.capital_security_risk,
        inputs.risks.capital_security if inputs.risks is not None else None,
    )
    project_failure_risk = _safest_risk(
        inputs.project_failure_risk,
        inputs.risks.project_failure if inputs.risks is not None else None,
    )

    if inputs.safety_blocked or capital_security_risk == RiskLevel.CRITICAL:
        return _blocked("SAFETY_BLOCK", now)
    if inputs.integrity_blocked:
        return _blocked("INTEGRITY_BLOCK", now)
    if inputs.official_multiwallet_policy == "forbidden":
        return _blocked("RULE_BLOCK", now)

    # 已确知为"不符合画像"的硬约束必须先于"证据不足"判定。
    # 超预算成本会让 _derive_eligibility 返回 None（probability.py:115），进而把
    # reward_probability 塞进 critical_unknowns，于是在这里被短路成
    # INSUFFICIENT_EVIDENCE——用户被告知"去补证据"，而真实原因是"太贵了"，
    # 且 _structural_reason 里的 TOO_EXPENSIVE 在真实链路上永远不可达。
    determinate_code = _determinate_misfit(inputs, profile)
    if determinate_code is not None:
        return _not_fit(determinate_code, now)

    if inputs.critical_unknowns:
        codes = _unique_codes(
            _UNKNOWN_REASON_CODES.get(unknown, "WAIT_MORE_EVIDENCE") for unknown in inputs.critical_unknowns
        )
        return _insufficient(codes, now)

    missing_codes = _missing_evidence_codes(
        inputs=inputs,
        event=event,
        eligibility=eligibility,
        survival=survival,
        reward_probability=reward_probability,
        economics=economics,
    )
    if missing_codes:
        return _insufficient(missing_codes, now)

    if inputs.task_path_known is False:
        return _insufficient(("WAIT_RULES",), now)
    if inputs.authorization_exit_known is False:
        return _insufficient(("WAIT_MORE_EVIDENCE",), now)

    assert event is not None
    assert eligibility is not None
    assert survival is not None
    assert reward_probability is not None
    assert economics is not None
    assert inputs.hard_cost_usd is not None
    assert inputs.weekly_maintenance_hours is not None
    assert inputs.project_quality is not None
    assert inputs.confidence is not None
    assert capital_security_risk is not None
    assert project_failure_risk is not None

    structural_code = _structural_reason(
        inputs=inputs,
        event=event,
        economics=economics,
        profile=profile,
    )
    if structural_code is not None:
        return _not_fit(structural_code, now)

    if inputs.profile_fit == "single_wallet_only":
        return _monitor(("SINGLE_WALLET_ONLY",), now)
    if inputs.participation_open is False:
        return _monitor(("WAIT_TASK_OPEN",), now)

    confidence = inputs.confidence
    has_airdrop_evidence = (
        inputs.official_airdrop_evidence_count_a >= 1 or inputs.independent_airdrop_evidence_count_b >= 2
    )
    failed_checks = (
        (event.low >= 0.50, "WAIT_CATALYST"),
        (eligibility.low >= 0.50, "WAIT_EARLY_ENTRY"),
        (survival.low >= 0.60, "WAIT_RULES"),
        (reward_probability.low >= 0.20, "REWARD_TOO_UNCERTAIN"),
        (economics.net_reward.low > 0, "REWARD_TOO_UNCERTAIN"),
        (economics.net_reward.base >= 30, "REWARD_TOO_UNCERTAIN"),
        (economics.reward_to_cost_ratio >= 3, "REWARD_TOO_UNCERTAIN"),
        (
            inputs.hard_cost_usd.high <= profile.hard_cost_limit_per_wallet_usd,
            "WAIT_COST_DROP",
        ),
        (
            inputs.weekly_maintenance_hours <= profile.weekly_time_limit_hours,
            "WAIT_MORE_EVIDENCE",
        ),
        (inputs.project_quality >= 50, "WAIT_MORE_EVIDENCE"),
        (
            project_failure_risk not in {RiskLevel.HIGH, RiskLevel.CRITICAL},
            "WAIT_MORE_EVIDENCE",
        ),
        (
            capital_security_risk not in {RiskLevel.HIGH, RiskLevel.CRITICAL},
            "WAIT_MORE_EVIDENCE",
        ),
        (
            inputs.risks.eligibility not in {RiskLevel.HIGH, RiskLevel.CRITICAL},
            "WAIT_RULES",
        ),
        (
            inputs.risks.reward_dilution not in {RiskLevel.HIGH, RiskLevel.CRITICAL},
            "REWARD_TOO_UNCERTAIN",
        ),
        (
            inputs.risks.liquidity not in {RiskLevel.HIGH, RiskLevel.CRITICAL},
            "REWARD_TOO_UNCERTAIN",
        ),
        (confidence.overall >= 0.65, "WAIT_MORE_EVIDENCE"),
        (confidence.event >= 0.70, "WAIT_MORE_EVIDENCE"),
        (confidence.eligibility >= 0.65, "WAIT_MORE_EVIDENCE"),
        (confidence.reward >= 0.50, "REWARD_TOO_UNCERTAIN"),
        (confidence.cost >= 0.70, "WAIT_MORE_EVIDENCE"),
        (confidence.risk >= 0.70, "WAIT_MORE_EVIDENCE"),
        (has_airdrop_evidence, "WAIT_MORE_EVIDENCE"),
    )
    watch_codes = _unique_codes(code for passed, code in failed_checks if not passed)
    if watch_codes:
        return _monitor(watch_codes, now)
    return _actionable(now)


def _missing_evidence_codes(
    *,
    inputs: OpportunityInputs,
    event: ProbabilityRange | None,
    eligibility: ProbabilityRange | None,
    survival: ProbabilityRange | None,
    reward_probability: ProbabilityRange | None,
    economics: EconomicsResult | None,
) -> tuple[str, ...]:
    checks = (
        (event is None, "WAIT_MORE_EVIDENCE"),
        (eligibility is None, "WAIT_MORE_EVIDENCE"),
        (survival is None, "WAIT_RULES"),
        (reward_probability is None, "REWARD_TOO_UNCERTAIN"),
        (inputs.conditional_reward_usd is None, "REWARD_TOO_UNCERTAIN"),
        (economics is None, "REWARD_TOO_UNCERTAIN"),
        (inputs.hard_cost_usd is None, "WAIT_MORE_EVIDENCE"),
        (inputs.weekly_maintenance_hours is None, "WAIT_MORE_EVIDENCE"),
        (inputs.participation_open is None, "WAIT_TASK_OPEN"),
        (inputs.task_path_known is None, "WAIT_RULES"),
        (inputs.authorization_exit_known is None, "WAIT_MORE_EVIDENCE"),
        (inputs.distribution_catalyst_3_6m is None, "WAIT_CATALYST"),
        (inputs.project_active is None, "WAIT_MORE_EVIDENCE"),
        (inputs.opportunity_timing == "unknown", "WAIT_EARLY_ENTRY"),
        (inputs.profile_fit == "unknown", "WAIT_MORE_EVIDENCE"),
        (inputs.official_multiwallet_policy == "unknown", "WAIT_RULES"),
        (inputs.safety_blocked is None, "WAIT_MORE_EVIDENCE"),
        (inputs.integrity_blocked is None, "WAIT_MORE_EVIDENCE"),
        (inputs.project_quality is None, "WAIT_MORE_EVIDENCE"),
        (inputs.confidence is None, "WAIT_MORE_EVIDENCE"),
        (inputs.risks is None, "WAIT_MORE_EVIDENCE"),
        (
            inputs.risks is not None and inputs.risks.eligibility is None,
            "WAIT_MORE_EVIDENCE",
        ),
        (inputs.project_failure_risk is None, "WAIT_MORE_EVIDENCE"),
        (inputs.capital_security_risk is None, "WAIT_MORE_EVIDENCE"),
        (
            inputs.risks is not None and inputs.risks.project_failure is None,
            "WAIT_MORE_EVIDENCE",
        ),
        (
            inputs.risks is not None and inputs.risks.capital_security is None,
            "WAIT_MORE_EVIDENCE",
        ),
        (
            inputs.risks is not None and inputs.risks.reward_dilution is None,
            "WAIT_MORE_EVIDENCE",
        ),
        (
            inputs.risks is not None and inputs.risks.liquidity is None,
            "WAIT_MORE_EVIDENCE",
        ),
        (
            _safest_risk(
                inputs.project_failure_risk,
                inputs.risks.project_failure if inputs.risks is not None else None,
            )
            is None,
            "WAIT_MORE_EVIDENCE",
        ),
        (
            _safest_risk(
                inputs.capital_security_risk,
                inputs.risks.capital_security if inputs.risks is not None else None,
            )
            is None,
            "WAIT_MORE_EVIDENCE",
        ),
    )
    return _unique_codes(code for missing, code in checks if missing)


def _structural_reason(
    *,
    inputs: OpportunityInputs,
    event: ProbabilityRange,
    economics: EconomicsResult,
    profile: OpportunityProfile,
) -> str | None:
    assert inputs.hard_cost_usd is not None
    assert inputs.weekly_maintenance_hours is not None
    if inputs.opportunity_timing in {"late", "closed"}:
        return "TOO_LATE"
    if inputs.project_active is False:
        return "PROJECT_INACTIVE"
    if inputs.profile_fit == "mismatch":
        return "PROFILE_MISMATCH"
    if inputs.distribution_catalyst_3_6m is False or event.high == 0:
        return "NO_AIRDROP_CASE"
    if economics.net_reward.base < 0:
        return "NEGATIVE_EXPECTED_VALUE"
    if economics.gross_reward.high < 30:
        return "DUST_REWARD"
    if inputs.hard_cost_usd.low > profile.hard_cost_limit_per_wallet_usd:
        return "TOO_EXPENSIVE"
    if inputs.weekly_time_confirmed_minimum and inputs.weekly_maintenance_hours > profile.weekly_time_limit_hours:
        return "TOO_TIME_INTENSIVE"
    return None


def _determinate_misfit(inputs: OpportunityInputs, profile: OpportunityProfile) -> str | None:
    """已确知（而非未知）就不符合画像的硬约束。

    与 `_structural_reason` 的区别：这里只看那些**证据已经充分、结论已经确定**
    的维度，因此可以在"证据不足"短路之前判定，不依赖 economics/probability。
    """
    cost = inputs.hard_cost_usd
    # `hard_cost_confirmed_minimum` 是必须的：`resolve_factor` 不设来源等级下限，
    # 一条 U 档（权重 0）的 "assumed" 成本记录也能填满 hard_cost_usd。若不校验，
    # 一句道听途说就足以让项目被判 30 天 IGNORE——那正是"证据不足"该管的情形。
    if cost is not None and inputs.hard_cost_confirmed_minimum and cost.low > profile.hard_cost_limit_per_wallet_usd:
        # 最乐观的成本都超出画像上限——这不是证据不足，是确定不合适
        return "TOO_EXPENSIVE"
    if (
        inputs.weekly_time_confirmed_minimum
        and inputs.weekly_maintenance_hours is not None
        and inputs.weekly_maintenance_hours > profile.weekly_time_limit_hours
    ):
        return "TOO_TIME_INTENSIVE"
    return None


def _safest_risk(*values: RiskLevel | None) -> RiskLevel | None:
    severity = {
        RiskLevel.LOW: 0,
        RiskLevel.MEDIUM: 1,
        RiskLevel.HIGH: 2,
        RiskLevel.CRITICAL: 3,
    }
    known = [value for value in values if value is not None]
    return max(known, key=severity.__getitem__) if known else None


def _unique_codes(codes: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(codes))


def _actionable(now: datetime) -> DecisionResult:
    deadline = now + timedelta(hours=48)
    return DecisionResult(
        status=DecisionStatus.ACTIONABLE,
        public_label="FARM",
        recommended_action=_ACTIONABLE_ACTION,
        review_at=deadline,
        expires_at=deadline,
    )


def _monitor(codes: tuple[str, ...], now: datetime) -> DecisionResult:
    deadline = now + timedelta(days=7)
    return DecisionResult(
        status=DecisionStatus.MONITOR,
        public_label="WATCH",
        watch_reason_codes=codes,
        recommended_action=WATCH_REASON_ACTIONS[codes[0]],
        review_at=deadline,
        expires_at=deadline,
    )


def _insufficient(codes: tuple[str, ...], now: datetime) -> DecisionResult:
    deadline = now + timedelta(days=7)
    return DecisionResult(
        status=DecisionStatus.INSUFFICIENT_EVIDENCE,
        public_label="WATCH",
        watch_reason_codes=codes,
        recommended_action=_INSUFFICIENT_ACTION,
        review_at=deadline,
        expires_at=deadline,
    )


def _not_fit(code: str, now: datetime) -> DecisionResult:
    deadline = now + timedelta(days=30)
    return DecisionResult(
        status=DecisionStatus.NOT_FIT,
        public_label="IGNORE",
        ignore_reason_codes=(code,),
        recommended_action=_NOT_FIT_ACTION,
        review_at=deadline,
        expires_at=deadline,
    )


def _blocked(code: str, now: datetime) -> DecisionResult:
    deadline = now + timedelta(days=30)
    return DecisionResult(
        status=DecisionStatus.BLOCKED,
        public_label="IGNORE",
        blocker_codes=(code,),
        requires_remediation=True,
        recommended_action=_BLOCKED_ACTION,
        review_at=deadline,
        expires_at=deadline,
    )
