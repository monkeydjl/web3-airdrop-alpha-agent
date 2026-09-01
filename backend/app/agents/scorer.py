"""Scorer Agent - Final scoring and labeling.

Aggregates all analysis agent outputs into a final score, label, and reasons.
Implements the 6-dimensional weighted scoring model.

Reference:
- ENGINEERING_ROADMAP.md §6.6 Scorer
- DATA_SCORING_DICT.md §4-§8
"""

import time
from typing import Literal

import structlog

from app.agents.airdrop_signal import airdrop_signal_subscore
from app.agents.base import AgentError, BaseAgent, PipelineState
from app.agents.eligibility import apply_eligibility_gate
from app.config import settings
from app.models import ScoreResult

logger = structlog.get_logger(__name__)


# ── Scoring Weights ───────────────────────────────
# 在 v1 六维上增加：execution（路线图/GitHub 推进）、transparency（文档/社媒）。
#
# 权重的唯一真源是 `settings.weight_*`（WEIGHT_CALIBRATION.md §2 明确要求配置
# 位于 config.py）。此前这里硬编码了第二份副本，settings 那份被零处代码读取，
# 于是启动时的 Σ=1.0 校验校验的是一组不起作用的数，改 .env 也静默无效。
def _load_weights() -> dict[str, float]:
    return {
        "airdrop_signal": settings.weight_airdrop_signal,
        "narrative_timing": settings.weight_narrative_timing,
        "team_reputation": settings.weight_team_reputation,
        "risk": settings.weight_risk,
        "tokenomics": settings.weight_tokenomics,
        "competition": settings.weight_competition,
        "execution": settings.weight_execution,
        "transparency": settings.weight_transparency,
    }


WEIGHTS = _load_weights()

# 生效权重版本，写入 ScoreResult / projects.weight_version（WEIGHT_CALIBRATION §1.2）。
# 没有它就无法区分历史分数由哪版权重产出，§5 的回滚方案也无从执行。
WEIGHT_VERSION = settings.weight_version

# ── Label Thresholds (v1.1: FARM 70→65 for auto-scan early-signal mix) ──
LABEL_THRESHOLDS: list[tuple[int, Literal["FARM", "WATCH", "IGNORE"]]] = [
    (65, "FARM"),
    (50, "WATCH"),
    (0, "IGNORE"),
]

# ── Narrative Timing Coefficients ─────────────────
TIMING_COEFF = {
    "early": 1.0,
    "peak": 0.8,
    "late": 0.5,
}

# ── Risk Sybil Difficulty Factors ─────────────────
SYBIL_FACTOR = {
    "high": 1.0,
    "medium": 0.85,
    "low": 0.70,
}

# ── Competition Mapping ───────────────────────────
# sector_count -> subscore
COMPETITION_MAP = [
    (3, 100),  # n <= 3
    (8, 75),  # 4 <= n <= 8
    (15, 55),  # 9 <= n <= 15
    (float("inf"), 40),  # n > 15
]


class ScorerAgent(BaseAgent):
    """Scorer Agent - Aggregates all analysis outputs into final score."""

    def __init__(self, sector_counts: dict[str, int] | None = None):
        """Initialize Scorer Agent.

        Args:
            sector_counts: Pre-computed sector project counts for competition subscore.
                         If None, competition subscore defaults to 50 (neutral).
        """
        super().__init__("scorer")
        self.sector_counts = sector_counts or {}

    async def run(self, state: PipelineState) -> PipelineState:
        """Run scoring analysis."""
        self._log_start(state)
        start_time = time.time()

        try:
            # Calculate all subscores
            subscores = self._calculate_subscores(state)

            # Evidence-aware confidence (agents + verifiable signals)
            confidence = self._calc_evidence_confidence(state)

            # Calculate weighted total score
            total_score = self._calculate_total_score(subscores)

            # Map the weighted score first, then apply deterministic eligibility vetoes.
            # The veto never changes total_score: score means project quality, label
            # means whether a currently actionable airdrop path exists (ADR-015).
            label = self._score_to_label(total_score)
            eligibility = apply_eligibility_gate(state.project, label)
            label = eligibility.label

            if eligibility.veto:
                logger.info(
                    "scorer.veto_applied",
                    project_id=state.project.id,
                    veto=eligibility.veto,
                    original_label=self._score_to_label(total_score),
                    final_label=label,
                )

            # Apply confidence degradation if needed
            label = self._apply_confidence_degradation(label, confidence)

            # Generate reasons. A veto explanation deliberately comes first so a
            # downgraded label is never presented as an unexplained score anomaly.
            reasons = self._generate_reasons(state, subscores, confidence, label)
            if eligibility.reason:
                reasons = [eligibility.reason, *reasons][:6]

            # Create result
            result = ScoreResult(
                score=total_score,
                label=label,
                confidence=confidence,
                reason=reasons,
                sub_scores=subscores,
                weight_version=WEIGHT_VERSION,
                veto=eligibility.veto,
            )

            # Update state
            state.score = result.score
            state.label = result.label
            state.confidence = result.confidence
            state.veto = result.veto
            state.reason = result.reason
            # 供 Repository 持久化到 projects.weight_version / raw_signals
            state.sub_scores = result.sub_scores
            state.weight_version = result.weight_version

            logger.info(
                "scorer.completed",
                project_id=state.project.id,
                project_name=state.project.name,
                score=total_score,
                label=label,
                confidence=confidence,
                subscores=subscores,
            )

        except Exception as e:
            error = AgentError(
                agent_name=self.name,
                kind="scoring_error",
                message=str(e),
                project_id=state.project.id,
            )
            state.add_error(error)

        duration_ms = (time.time() - start_time) * 1000
        self._log_complete(state, duration_ms)
        return state

    def _calculate_subscores(self, state: PipelineState) -> dict[str, float]:
        """Calculate all 8 subscores (v1.2)."""
        return {
            "airdrop_signal": self._calc_airdrop_signal(state),
            "narrative_timing": self._calc_narrative_timing(state),
            "team_reputation": self._calc_team_reputation(state),
            "risk": self._calc_risk(state),
            "tokenomics": self._calc_tokenomics(state),
            "competition": self._calc_competition(state),
            "execution": self._calc_execution(state),
            "transparency": self._calc_transparency(state),
        }

    def _calc_airdrop_signal(self, state: PipelineState) -> float:
        """Calculate airdrop signal subscore (0-100).

        实现收敛到 `app.agents.airdrop_signal`，与 Risk Agent 共用同一份阶梯，
        避免两份复制实现继续漂移。
        """
        return airdrop_signal_subscore(state.project)

    def _calc_execution(self, state: PipelineState) -> float:
        """Repo health / roadmap **delivery** / product running (0-100).

        v1.3: roadmap_delivery aligned/partial/unclear, has_contract, TVL.
        """
        p = state.project
        score = 38.0  # base

        if getattr(p, "has_github", False):
            score += 10.0
            stars = int(getattr(p, "github_stars", 0) or 0)
            if stars >= 1000:
                score += 16.0
            elif stars >= 200:
                score += 11.0
            elif stars >= 50:
                score += 7.0
            elif stars > 0:
                score += 3.0

            days = getattr(p, "github_recent_push_days", None)
            if days is not None:
                if days <= 14:
                    score += 16.0
                elif days <= 45:
                    score += 11.0
                elif days <= 90:
                    score += 6.0
                elif days > 180:
                    score -= 12.0
        else:
            if p.url:
                score += 4.0

        # Roadmap presence vs delivery (履约)
        delivery = str(getattr(p, "roadmap_delivery", "unknown") or "unknown").lower()
        if delivery == "aligned":
            score += 16.0
        elif delivery == "partial":
            score += 8.0
        elif delivery == "unclear":
            score -= 8.0  # paper roadmap only
        elif getattr(p, "has_roadmap", False):
            score += 6.0

        if p.has_testnet or (p.stage or "").lower() == "testnet":
            score += 7.0
        if getattr(p, "has_contract", False):
            score += 10.0  # product/contracts actually exist

        tvl = getattr(p, "tvl_usd", None)
        if tvl is not None:
            try:
                t = float(tvl)
                if t >= 10_000_000:
                    score += 12.0
                elif t >= 1_000_000:
                    score += 8.0
                elif t >= 100_000:
                    score += 4.0
            except (TypeError, ValueError):
                pass

        return self._clamp(score, 0, 100)

    def _calc_transparency(self, state: PipelineState) -> float:
        """Docs / social / multi-source evidence (0-100). v1.3 + evidence density."""
        p = state.project
        score = 28.0

        if getattr(p, "has_whitepaper", False):
            score += 18.0
        elif getattr(p, "has_docs", False):
            score += 12.0

        if getattr(p, "has_roadmap", False):
            score += 8.0
        if getattr(p, "has_twitter", False):
            score += 10.0
        if getattr(p, "has_discord", False):
            score += 8.0
        if getattr(p, "has_github", False):
            score += 8.0
        if p.url:
            score += 6.0
        if p.recent_funding:
            score += 4.0
        if getattr(p, "has_task_portal", False):
            score += 6.0  # public campaign = some transparency

        # Multi-source evidence density
        sources = int(getattr(p, "source_count", 1) or 1)
        if sources >= 3:
            score += 12.0
        elif sources >= 2:
            score += 6.0

        # Disclosed fundraising (RootData) improves transparency of capital story
        fq = float(getattr(p, "funding_quality", 0) or 0)
        if fq >= 0.5:
            score += 8.0
        elif fq >= 0.25:
            score += 4.0
        if str(getattr(p, "funding_tier", "")).lower() == "tier1":
            score += 4.0

        # anonymous + no docs is a red flag
        if state.team is not None:
            if state.team.team_type == "anon" and not getattr(p, "has_docs", False):
                score -= 12.0
            if state.team.team_type == "doxxed":
                score += 6.0

        return self._clamp(score, 0, 100)

    def _calc_evidence_confidence(self, state: PipelineState) -> float:
        """Data evidence completeness 0-1 (not just agent presence).

        Mixes agent coverage with concrete signal coverage so confidence
        reflects 'can we verify this project' rather than only pipeline shape.
        """
        agent_cov = self._agent_coverage(state)
        p = state.project
        checks = [
            bool(p.url),
            bool(getattr(p, "has_docs", False) or getattr(p, "has_whitepaper", False)),
            bool(getattr(p, "has_github", False)),
            bool(getattr(p, "has_twitter", False) or getattr(p, "has_discord", False)),
            bool(
                p.has_points_program
                or getattr(p, "has_task_portal", False)
                or getattr(p, "explicit_airdrop_mention", False)
            ),
            bool(getattr(p, "has_contract", False) or (getattr(p, "tvl_usd", None) is not None) or p.has_testnet),
            int(getattr(p, "source_count", 1) or 1) >= 2,
        ]
        signal_cov = sum(1 for c in checks if c) / len(checks)
        # DATA_SCORING_DICT §97（v1.3）：confidence = 0.35×Agent覆盖 + 0.65×可验证信号。
        # 此前系数为 0.40/0.60，且在 agent_cov>=1.0 时加了 0.55 的下限。
        # 影响面要说准：旧公式在 Agent 缺失时仍可能 <0.5（缺 1–3 个 Agent 的下限
        # 依次为 0.45 / 0.20 / 0.10），但那是异常路径；**四个 Agent 全部成功的正常
        # 路径**下 confidence 恒 >= 0.55（穷举 256 种信号配置最低值恰为 0.5500），
        # 于是"证据再稀疏也不降级"——降级保护只在 Agent 崩溃时生效，而它本意是
        # 防"信号不足"，两者管的根本不是同一件事。
        # 现按规格取系数并移除该下限：零可验证信号时 confidence = 0.35，降级生效。
        conf = 0.35 * agent_cov + 0.65 * signal_cov
        return self._clamp(conf, 0.0, 1.0)

    def _agent_coverage(self, state: PipelineState) -> float:
        agents = [
            state.narrative,
            state.team,
            state.risk,
            state.tokenomics,
        ]
        return sum(1 for agent in agents if agent is not None) / 4.0

    def _calc_narrative_timing(self, state: PipelineState) -> float:
        """Calculate narrative timing subscore (0-100).

        Logic:
        - base = heat_score * 100
        - coeff = TIMING_COEFF[timing]
        - subscore = base * coeff

        Fallback: 50 (neutral) if narrative missing.
        """
        if state.narrative is None:
            return 50.0

        base = state.narrative.heat_score * 100
        coeff = TIMING_COEFF.get(state.narrative.timing, 0.8)
        subscore = base * coeff

        return self._clamp(subscore, 0, 100)

    def _calc_team_reputation(self, state: PipelineState) -> float:
        """Calculate team reputation subscore (0-100).

        Base: team_score * 100. v1.4: blend in funding_quality so RootData
        tier-1 raises lift team even if flag heuristics are sparse.
        """
        base = 50.0 if state.team is None else state.team.team_score * 100

        fq = float(getattr(state.project, "funding_quality", 0) or 0)
        if fq > 0:
            # up to +18 from excellent capital formation
            base = base * 0.85 + (fq * 100) * 0.15
            if str(getattr(state.project, "funding_tier", "")).lower() == "tier1":
                base += 6.0
        return self._clamp(base, 0, 100)

    def _calc_risk(self, state: PipelineState) -> float:
        """Calculate risk subscore (0-100).

        Logic:
        - sybil_factor = SYBIL_FACTOR[sybil_difficulty]
        - subscore = (1 - token_risk) * 100 * sybil_factor

        Fallback: 50 (neutral) if risk missing.
        """
        if state.risk is None:
            return 50.0

        sybil_factor = SYBIL_FACTOR.get(self._infer_sybil_difficulty(state), 0.85)
        subscore = (1 - state.risk.token_risk) * 100 * sybil_factor

        return self._clamp(subscore, 0, 100)

    def _calc_tokenomics(self, state: PipelineState) -> float:
        """Calculate tokenomics subscore (0-100).

        Logic:
        - subscore = (1 - tokenomics.risk) * 100
        - tokenomics.risk = vc_share * 0.4 + team_share * 0.3 + unlock_penalty * 0.3

        Fallback: 50 (neutral) if tokenomics missing.
        """
        if state.tokenomics is None:
            return 50.0

        # 使用模型上的单一权威定义，避免在多处内联重算而漂移
        subscore = (1 - state.tokenomics.risk) * 100
        return self._clamp(subscore, 0, 100)

    def _calc_competition(self, state: PipelineState) -> float:
        """Calculate competition subscore (0-100).

        Logic:
        - Based on same-sector project count
        - n <= 3: 100
        - 4 <= n <= 8: 75
        - 9 <= n <= 15: 55
        - n > 15: 40

        Fallback: 50 (neutral) if sector missing or not in counts.
        """
        sector = state.project.sector
        if not sector or sector not in self.sector_counts:
            return 50.0

        count = self.sector_counts[sector]

        for threshold, score in COMPETITION_MAP:
            if count <= threshold:
                return float(score)

        return 40.0

    def _calculate_total_score(self, subscores: dict[str, float]) -> int:
        """Calculate weighted total score."""
        total = sum(subscores[key] * WEIGHTS[key] for key in WEIGHTS)

        # Round using banker's rounding (Python default)
        return round(self._clamp(total, 0, 100))

    def _score_to_label(self, score: int) -> Literal["FARM", "WATCH", "IGNORE"]:
        """Map score to label."""
        for threshold, label in LABEL_THRESHOLDS:
            if score >= threshold:
                return label
        return "IGNORE"

    def _apply_confidence_degradation(
        self, label: Literal["FARM", "WATCH", "IGNORE"], confidence: float
    ) -> Literal["FARM", "WATCH", "IGNORE"]:
        """Degrade label if confidence < 0.5 (≥3 agents missing)."""
        if confidence < 0.5:
            if label == "FARM":
                return "WATCH"
            elif label == "WATCH":
                return "IGNORE"
        return label

    def _calculate_confidence(self, state: PipelineState) -> float:
        """Backward-compatible alias → evidence confidence (v1.3)."""
        return self._calc_evidence_confidence(state)

    def _generate_reasons(
        self,
        state: PipelineState,
        subscores: dict[str, float],
        confidence: float,
        label: str,
    ) -> list[str]:
        """Generate decision reasons (≥2 required).

        Algorithm:
        1. Collect all candidate reasons with impact scores
        2. Force-include all missing/low-confidence markers
        3. Sort remaining by impact (distance from neutral 50)
        4. Select top 3 non-forced reasons
        5. Validate constraints (FARM needs ≥1 positive, IGNORE needs ≥1 negative)
        6. Return final list (≥2 items)
        """
        candidates: list[tuple[str, float, bool]] = []  # (reason, impact, is_forced)

        # Airdrop signal
        airdrop_score = subscores["airdrop_signal"]
        if airdrop_score >= 90:
            candidates.append(("strong airdrop signal", abs(airdrop_score - 50), False))
        elif airdrop_score >= 70:
            candidates.append(("clear airdrop / points path", abs(airdrop_score - 50), False))
        elif airdrop_score >= 50:
            candidates.append(("moderate airdrop signal", abs(airdrop_score - 50), False))
        elif airdrop_score <= 25:
            candidates.append(("no airdrop signal", abs(airdrop_score - 50), False))
        if getattr(state.project, "explicit_airdrop_mention", False):
            candidates.append(("explicit airdrop mention", 25, False))
        if getattr(state.project, "has_task_portal", False):
            candidates.append(("verifiable task / points portal", 28, False))
        sources = int(getattr(state.project, "source_count", 1) or 1)
        if sources >= 3:
            candidates.append(("multi-source evidence", 22, False))
        elif sources >= 2:
            candidates.append(("cross-checked by 2 sources", 12, False))
        fq = float(getattr(state.project, "funding_quality", 0) or 0)
        tier = str(getattr(state.project, "funding_tier", "unknown") or "unknown")
        if tier == "tier1" or fq >= 0.65:
            candidates.append(("tier-1 / high-quality funding", 26, False))
        elif fq >= 0.4:
            candidates.append(("solid disclosed fundraising", 16, False))
        elif getattr(state.project, "recent_funding", False):
            candidates.append(("recent funding signal", 10, False))

        # Narrative timing
        if state.narrative is None:
            candidates.append(("narrative heat unknown", 0, True))
        else:
            narrative_score = subscores["narrative_timing"]
            timing = state.narrative.timing

            if timing == "early" and narrative_score >= 70:
                candidates.append(("early narrative, high heat", abs(narrative_score - 50), False))
            elif timing == "early":
                candidates.append(("early narrative", abs(narrative_score - 50), False))
            elif timing == "peak" and narrative_score >= 70:
                candidates.append(("heated narrative, peak timing", abs(narrative_score - 50), False))
            elif timing == "peak":
                candidates.append(("peak narrative", abs(narrative_score - 50), False))
            elif timing == "late" and narrative_score >= 70:
                candidates.append(("mature narrative, late timing", abs(narrative_score - 50), False))
            elif timing == "late":
                candidates.append(("late narrative", abs(narrative_score - 50), False))

        # Team reputation
        if state.team is None:
            candidates.append(("team data missing", 0, True))
        else:
            team_score = state.team.team_score
            if team_score >= 0.7:
                candidates.append(("credible team", abs(team_score * 100 - 50), False))
            elif team_score < 0.4:
                candidates.append(("team risk: anonymous or prior failure", abs(team_score * 100 - 50), False))

        # Risk
        if state.risk is None:
            candidates.append(("risk estimate uncertain", 0, True))
        else:
            if state.risk.token_risk > 0.6:
                candidates.append(("elevated token structure risk", abs((1 - state.risk.token_risk) * 100 - 50), False))

        # Tokenomics
        if state.tokenomics is None:
            candidates.append(("tokenomics data missing", 0, True))
        else:
            tok_risk = (
                state.tokenomics.vc_share * 0.4
                + state.tokenomics.team_share * 0.3
                + state.tokenomics.unlock_penalty * 0.3
            )
            if tok_risk > 0.6:
                candidates.append(("high token unlock pressure", abs((1 - tok_risk) * 100 - 50), False))

        # Competition
        # 只有在确实有该赛道的统计数据时才给竞争度理由。原实现把"赛道不在
        # sector_counts 里"（即无数据，_calc_competition 返回中性 50）当作
        # count=0 从而宣称"低竞争"——子分说"我们不知道"，理由却说"竞争很低"。
        comp_score = subscores["competition"]
        sector = state.project.sector

        if sector and sector in self.sector_counts:
            count = self.sector_counts[sector]
            if count <= 3:
                candidates.append(("low competition", abs(comp_score - 50), False))
            elif count > 15:
                candidates.append(("high competition", abs(comp_score - 50), False))

        # Execution (v1.2)
        exec_score = subscores.get("execution", 50)
        if exec_score >= 70:
            candidates.append(("active development / roadmap traction", abs(exec_score - 50), False))
        elif exec_score <= 35:
            candidates.append(("weak execution signals (stale repo or no roadmap)", abs(exec_score - 50), False))
        days = getattr(state.project, "github_recent_push_days", None)
        if days is not None and days <= 14 and getattr(state.project, "has_github", False):
            candidates.append(("github updated recently", 20, False))
        if getattr(state.project, "has_roadmap", False):
            candidates.append(("public roadmap present", 12, False))
        delivery = str(getattr(state.project, "roadmap_delivery", "unknown") or "unknown")
        if delivery == "aligned":
            candidates.append(("roadmap delivery looks aligned with shipping", 24, False))
        elif delivery == "unclear":
            candidates.append(("roadmap unclear vs shipping signals", 18, False))
        if getattr(state.project, "has_contract", False):
            candidates.append(("on-chain product / contract signal", 16, False))

        # Transparency (v1.2/v1.3)
        tr_score = subscores.get("transparency", 50)
        if tr_score >= 70:
            candidates.append(("strong public docs / social presence", abs(tr_score - 50), False))
        elif tr_score <= 35:
            candidates.append(("low transparency (thin docs/social)", abs(tr_score - 50), False))
        if getattr(state.project, "has_whitepaper", False) or getattr(state.project, "has_docs", False):
            candidates.append(("docs or whitepaper available", 14, False))

        # Low confidence marker (evidence-aware)
        if confidence < 0.5:
            candidates.append(("low data confidence", 0, True))
        elif confidence >= 0.8:
            candidates.append(("high evidence confidence", 10, False))

        # Separate forced and optional reasons
        forced = [reason for reason, _, is_forced in candidates if is_forced]
        optional = [(reason, impact) for reason, impact, is_forced in candidates if not is_forced]

        # Sort optional by impact (descending)
        optional.sort(key=lambda x: x[1], reverse=True)

        # Select top 3 optional reasons
        selected_optional = [reason for reason, _ in optional[:3]]

        # Combine forced + selected
        final_reasons = forced + selected_optional

        # Validate constraints
        positive_reasons = {
            "strong airdrop signal",
            "clear airdrop / points path",
            "moderate airdrop signal",
            "explicit airdrop mention",
            "verifiable task / points portal",
            "multi-source evidence",
            "early narrative, high heat",
            "early narrative",
            "heated narrative, peak timing",
            "peak narrative",
            "credible team",
            "low competition",
            "active development / roadmap traction",
            "roadmap delivery looks aligned with shipping",
            "strong public docs / social presence",
            "on-chain product / contract signal",
            "high evidence confidence",
            "tier-1 / high-quality funding",
            "solid disclosed fundraising",
            "recent funding signal",
            "reputable vc backed",
        }

        negative_reasons = {
            "no airdrop signal",
            "late narrative",
            "mature narrative, late timing",
            "team risk: anonymous or prior failure",
            "elevated token structure risk",
            "high token unlock pressure",
            "high competition",
            "weak execution signals (stale repo or no roadmap)",
            "roadmap unclear vs shipping signals",
            "low transparency (thin docs/social)",
            "low data confidence",
        }

        has_positive = any(r in positive_reasons for r in final_reasons)
        has_negative = any(r in negative_reasons for r in final_reasons)

        # Fix constraint violations
        if label == "FARM" and not has_positive and optional:
            # Replace last non-forced with top positive
            for reason, _ in optional:
                if reason in positive_reasons:
                    if selected_optional:
                        final_reasons.remove(selected_optional[-1])
                    final_reasons.append(reason)
                    break

        if label == "IGNORE" and not has_negative and optional:
            # Replace last non-forced with top negative
            for reason, _ in optional:
                if reason in negative_reasons:
                    if selected_optional:
                        final_reasons.remove(selected_optional[-1])
                    final_reasons.append(reason)
                    break

        # Remove duplicates while preserving order (先去重，避免把重复项当作两条)
        seen: set[str] = set()
        unique_reasons: list[str] = []
        for r in final_reasons:
            if r not in seen:
                seen.add(r)
                unique_reasons.append(r)

        # Ensure minimum 2 reasons (ScoreResult.reason 要求 min_length=2)。
        # 先补充未选中的 optional，再用与标签匹配的确定性兜底，保证任何输入都不会
        # 因 <2 条 reason 触发 ValidationError 而把整条评分吞成 None。
        if len(unique_reasons) < 2:
            for reason, _ in optional:
                if reason not in seen:
                    seen.add(reason)
                    unique_reasons.append(reason)
                    if len(unique_reasons) >= 2:
                        break
        if len(unique_reasons) < 2:
            fallback_pool = (
                ["airdrop signal detected", "early-stage opportunity"]
                if label == "FARM"
                else ["mixed signals, monitor closely", "insufficient standout signals"]
                if label == "WATCH"
                else ["weak overall signals", "limited airdrop evidence"]
            )
            for reason in fallback_pool:
                if reason not in seen:
                    seen.add(reason)
                    unique_reasons.append(reason)
                    if len(unique_reasons) >= 2:
                        break

        return unique_reasons[:6]  # Cap at 6 to avoid excessive output

    def _infer_sybil_difficulty(self, state: PipelineState) -> str:
        """Infer sybil difficulty from project friction, else the Risk Agent's own assessment.

        原实现在 risk_flags 里匹配 "kyc required" / "easy sybil" 等字符串，而
        generate_risk_flags 从不产出这些词（交集为空），使该维度恒为 medium。
        Risk Agent 本就计算了难度，现在直接读它的结论。
        """
        friction = str(getattr(state.project, "sybil_friction", "unknown") or "unknown").lower()
        if friction in ("high", "medium", "low"):
            return friction

        if state.risk is None:
            return "medium"

        assessed = str(getattr(state.risk, "sybil_difficulty", "medium") or "medium").lower()
        return assessed if assessed in ("high", "medium", "low") else "medium"

    @staticmethod
    def _clamp(value: float, min_val: float, max_val: float) -> float:
        """Clamp value to [min_val, max_val]."""
        return max(min_val, min(max_val, value))
