"""Scorer Agent - Final scoring and labeling.

Aggregates all analysis agent outputs into a final score, label, and reasons.
Implements the 6-dimensional weighted scoring model.

Reference:
- ENGINEERING_ROADMAP.md §6.6 Scorer
- DATA_SCORING_DICT.md §4-§8
"""

import time
from typing import Dict, List, Tuple

import structlog

from app.agents.base import BaseAgent, PipelineState, AgentError
from app.models import ScoreResult

logger = structlog.get_logger(__name__)


# ── Scoring Weights (v1) ──────────────────────────
WEIGHTS = {
    "airdrop_signal": 0.20,
    "narrative_timing": 0.20,
    "team_reputation": 0.15,
    "risk": 0.15,
    "tokenomics": 0.15,
    "competition": 0.15,
}

# ── Label Thresholds ──────────────────────────────
LABEL_THRESHOLDS = [
    (70, "FARM"),
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
    (3, 100),   # n <= 3
    (8, 75),    # 4 <= n <= 8
    (15, 55),   # 9 <= n <= 15
    (float('inf'), 40),  # n > 15
]


class ScorerAgent(BaseAgent):
    """Scorer Agent - Aggregates all analysis outputs into final score."""

    def __init__(self, sector_counts: Dict[str, int] | None = None):
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

            # Calculate confidence (non-missing analysis agents / 4)
            confidence = self._calculate_confidence(state)

            # Calculate weighted total score
            total_score = self._calculate_total_score(subscores)

            # Determine label from score
            label = self._score_to_label(total_score)

            # Apply confidence degradation if needed
            label = self._apply_confidence_degradation(label, confidence)

            # Generate reasons
            reasons = self._generate_reasons(state, subscores, confidence, label)

            # Create result
            result = ScoreResult(
                score=total_score,
                label=label,
                confidence=confidence,
                reason=reasons,
                sub_scores=subscores,
            )

            # Update state
            state.score = result.score
            state.label = result.label
            state.confidence = result.confidence
            state.reason = result.reason

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

    def _calculate_subscores(self, state: PipelineState) -> Dict[str, float]:
        """Calculate all 6 subscores."""
        return {
            "airdrop_signal": self._calc_airdrop_signal(state),
            "narrative_timing": self._calc_narrative_timing(state),
            "team_reputation": self._calc_team_reputation(state),
            "risk": self._calc_risk(state),
            "tokenomics": self._calc_tokenomics(state),
            "competition": self._calc_competition(state),
        }

    def _calc_airdrop_signal(self, state: PipelineState) -> float:
        """Calculate airdrop signal subscore (0-100).

        Logic:
        - has_points + airdrop_hint: 100
        - only one: 60
        - neither: 20
        """
        project = state.project
        has_points = project.has_points_program
        has_hint = project.no_token_yet  # "airdrop_hint" proxy

        if has_points and has_hint:
            return 100.0
        elif has_points or has_hint:
            return 60.0
        else:
            return 20.0

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

        Logic:
        - subscore = team_score * 100

        Fallback: 50 (neutral) if team missing.
        """
        if state.team is None:
            return 50.0

        return state.team.team_score * 100

    def _calc_risk(self, state: PipelineState) -> float:
        """Calculate risk subscore (0-100).

        Logic:
        - sybil_factor = SYBIL_FACTOR[sybil_difficulty]
        - subscore = (1 - token_risk) * 100 * sybil_factor

        Fallback: 50 (neutral) if risk missing.
        """
        if state.risk is None:
            return 50.0

        sybil_factor = SYBIL_FACTOR.get(
            self._infer_sybil_difficulty(state),
            0.85
        )
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

        # Calculate tokenomics.risk from components
        tok_risk = (
            state.tokenomics.vc_share * 0.4
            + state.tokenomics.team_share * 0.3
            + state.tokenomics.unlock_penalty * 0.3
        )

        subscore = (1 - tok_risk) * 100
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

    def _calculate_total_score(self, subscores: Dict[str, float]) -> int:
        """Calculate weighted total score."""
        total = sum(
            subscores[key] * WEIGHTS[key]
            for key in WEIGHTS
        )

        # Round using banker's rounding (Python default)
        return int(round(self._clamp(total, 0, 100)))

    def _score_to_label(self, score: int) -> str:
        """Map score to label."""
        for threshold, label in LABEL_THRESHOLDS:
            if score >= threshold:
                return label
        return "IGNORE"

    def _apply_confidence_degradation(
        self,
        label: str,
        confidence: float
    ) -> str:
        """Degrade label if confidence < 0.5 (≥3 agents missing)."""
        if confidence < 0.5:
            if label == "FARM":
                return "WATCH"
            elif label == "WATCH":
                return "IGNORE"
        return label

    def _calculate_confidence(self, state: PipelineState) -> float:
        """Calculate confidence (non-missing analysis agents / 4)."""
        agents = [
            state.narrative,
            state.team,
            state.risk,
            state.tokenomics,
        ]

        present_count = sum(1 for agent in agents if agent is not None)
        return present_count / 4.0

    def _generate_reasons(
        self,
        state: PipelineState,
        subscores: Dict[str, float],
        confidence: float,
        label: str,
    ) -> List[str]:
        """Generate decision reasons (≥2 required).

        Algorithm:
        1. Collect all candidate reasons with impact scores
        2. Force-include all missing/low-confidence markers
        3. Sort remaining by impact (distance from neutral 50)
        4. Select top 3 non-forced reasons
        5. Validate constraints (FARM needs ≥1 positive, IGNORE needs ≥1 negative)
        6. Return final list (≥2 items)
        """
        candidates: List[Tuple[str, float, bool]] = []  # (reason, impact, is_forced)

        # Airdrop signal
        airdrop_score = subscores["airdrop_signal"]
        if airdrop_score == 100:
            candidates.append(("strong airdrop signal", abs(100 - 50), False))
        elif airdrop_score == 60:
            candidates.append(("moderate airdrop signal", abs(60 - 50), False))
        elif airdrop_score == 20:
            candidates.append(("no airdrop signal", abs(20 - 50), False))

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
        comp_score = subscores["competition"]
        sector = state.project.sector
        count = self.sector_counts.get(sector, 0) if sector else 0

        if count <= 3:
            candidates.append(("low competition", abs(comp_score - 50), False))
        elif count > 15:
            candidates.append(("high competition", abs(comp_score - 50), False))

        # Low confidence marker (≥3 agents missing)
        if confidence < 0.5:
            candidates.append(("low data confidence", 0, True))

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
            "moderate airdrop signal",
            "early narrative, high heat",
            "early narrative",
            "heated narrative, peak timing",
            "peak narrative",
            "credible team",
            "low competition",
        }

        negative_reasons = {
            "no airdrop signal",
            "late narrative",
            "mature narrative, late timing",
            "team risk: anonymous or prior failure",
            "elevated token structure risk",
            "high token unlock pressure",
            "high competition",
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

        # Ensure minimum 2 reasons
        if len(final_reasons) < 2:
            # Add neutral fallback
            if "moderate airdrop signal" not in final_reasons and optional:
                for reason, _ in optional:
                    if reason not in final_reasons:
                        final_reasons.append(reason)
                        if len(final_reasons) >= 2:
                            break

        # Remove duplicates while preserving order
        seen = set()
        unique_reasons = []
        for r in final_reasons:
            if r not in seen:
                seen.add(r)
                unique_reasons.append(r)

        return unique_reasons[:6]  # Cap at 6 to avoid excessive output

    def _infer_sybil_difficulty(self, state: PipelineState) -> str:
        """Infer sybil difficulty from risk flags.

        Fallback to 'medium' if no flags available.
        """
        if state.risk is None or not state.risk.risk_flags:
            return "medium"

        # Simple heuristic: check for sybil-related flags
        flags = state.risk.risk_flags

        if "kyc required" in flags or "soul-bound" in flags:
            return "high"
        elif "testnet only" in flags:
            return "low"
        else:
            return "medium"

    @staticmethod
    def _clamp(value: float, min_val: float, max_val: float) -> float:
        """Clamp value to [min_val, max_val]."""
        return max(min_val, min(max_val, value))
