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
    """Whether current signals show at least one actionable participation route.

    三条"可操作"路径（testnet / points / task portal）之外，额外承认
    `explicit_airdrop_mention`：官方已明说要空投，但参与方式可能是
    **历史行为型**（按过往交易量/持仓快照发放），这类根本不存在"去哪点一下"
    的入口，三条路径全为 False 却确实有参与价值。

    实测依据（`airdrops_2024_2025.json`）：三路径全无的 4 个样本中，只有
    Jupiter 的 `explicit_airdrop_mention` 为真，也只有它真的空投了
    （按历史交易用户分多轮发放）。另外三个（Farcaster / Worldcoin /
    Chainlink）explicit 均为 False，所以这条放宽**不会**把它们放进来。

    为什么不是无条件放行：`explicit_airdrop_mention` 只说明"有空投这件事"，
    不说明"现在还赶得上"。已发币且无后续路径的项目仍由
    `is_already_launched_without_airdrop_path()` 先一步拦成 IGNORE ——
    那条规则在 `apply_eligibility_gate` 里排在本条之前，顺序不能调换。
    """
    return bool(
        project.has_testnet
        or project.has_points_program
        or getattr(project, "has_task_portal", False)
        or getattr(project, "explicit_airdrop_mention", False)
    )


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
