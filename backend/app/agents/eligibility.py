"""Eligibility predicates and label vetoes for current airdrop participation.

Score measures overall project quality; eligibility decides whether the currently known
signals leave a participation path.  Keep the post-launch predicate shared with the
airdrop-signal cap so those two policy surfaces cannot drift apart (ADR-015).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from app.agents.base import RawProject


Label = Literal["FARM", "WATCH", "IGNORE"]
VETO_ALREADY_LAUNCHED = "already_launched"
VETO_NO_PARTICIPATION_PATH = "no_participation_path"


@dataclass(frozen=True)
class EligibilityDecision:
    """Final label adjustment from deterministic eligibility policy."""

    label: Label
    veto: str | None = None
    reason: str | None = None


def has_post_launch_airdrop_path(project: RawProject) -> bool:
    """Whether a launched token still has explicit evidence of a campaign path."""
    return bool(
        project.has_points_program
        or getattr(project, "explicit_airdrop_mention", False)
        or getattr(project, "has_task_portal", False)
    )


def is_already_launched_without_airdrop_path(project: RawProject) -> bool:
    """Match the airdrop-signal listed-token cap condition exactly."""
    return not bool(project.no_token_yet) and not has_post_launch_airdrop_path(project)


def has_participation_path(project: RawProject) -> bool:
    """Whether current signals show at least one actionable participation route."""
    return bool(project.has_testnet or project.has_points_program or getattr(project, "has_task_portal", False))


def apply_eligibility_gate(project: RawProject, label: Label) -> EligibilityDecision:
    """Apply ADR-015 vetoes without changing the underlying weighted score.

    Only FARM can be downgraded.  A pre-existing WATCH/IGNORE is already no more
    permissive than either rule and must never be promoted or otherwise rewritten.
    """
    if label != "FARM":
        return EligibilityDecision(label=label)

    if is_already_launched_without_airdrop_path(project):
        return EligibilityDecision(
            label="IGNORE",
            veto=VETO_ALREADY_LAUNCHED,
            reason="token already launched with no verified follow-on airdrop path",
        )

    if not has_participation_path(project):
        return EligibilityDecision(
            label="WATCH",
            veto=VETO_NO_PARTICIPATION_PATH,
            reason="no verified participation path; monitor for a testnet, points, or task portal",
        )

    return EligibilityDecision(label=label)
