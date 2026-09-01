"""Airdrop signal subscore — single source of truth.

此前 `ScorerAgent._calc_airdrop_signal` 与 `risk.calculate_airdrop_signal_subscore`
是两份复制实现，v1.4 的 funding_quality 分支只加到了 Scorer 一侧，导致 2304 种
输入组合中有 666 种两边给出不同分数（最大相差 13 分）。而 Risk 用的是漂移的那一
份来算 `token_risk`，使得 `risk.token_risk` 与展示给用户的空投子分互相矛盾。

参考：DATA_SCORING_DICT.md §5.1 / §166 / §175
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.agents.eligibility import is_already_launched_without_airdrop_path

if TYPE_CHECKING:
    from app.agents.base import RawProject


def airdrop_signal_subscore(project: RawProject) -> float:
    """Compute the airdrop-signal subscore (0-100) for a project.

    阶梯：
      - 有积分计划 + 未发币          → 100
      - 未发币 + 有测试网            → 85
      - 有积分计划 或 未发币          → 60
      - 有测试网                     → 40
      - 其他                        → 20

    加成：显式空投提及 +10；可验证任务入口 +14；高质量融资 +8（tier1 再 +5）或
    普通融资 +5；多源交叉验证 ≥3 源 +6 / ≥2 源 +3。

    已上市且无空投叙事的项目封顶 35。
    """
    has_points = bool(project.has_points_program)
    no_token = bool(project.no_token_yet)
    has_testnet = bool(project.has_testnet) or ((project.stage or "").lower() == "testnet")
    explicit = bool(getattr(project, "explicit_airdrop_mention", False))
    funding = bool(project.recent_funding)
    fq = float(getattr(project, "funding_quality", 0) or 0)
    f_tier = str(getattr(project, "funding_tier", "unknown") or "unknown").lower()
    task_portal = bool(getattr(project, "has_task_portal", False))
    sources = int(getattr(project, "source_count", 1) or 1)

    if has_points and no_token:
        base = 100.0
    elif no_token and has_testnet:
        base = 85.0
    elif has_points or no_token:
        base = 60.0
    elif has_testnet:
        base = 40.0
    else:
        base = 20.0

    bonus = 0.0
    if explicit:
        bonus += 10.0
    if task_portal:
        # Galxe/Layer3/quest portal is stronger than wording alone
        bonus += 14.0
    # Funding quality (RootData etc.): better capital = more likely real campaign later
    if fq >= 0.55 and (has_points or no_token or has_testnet or task_portal):
        bonus += 8.0 + (5.0 if f_tier == "tier1" else 0.0)
    elif funding and (has_points or no_token or has_testnet or task_portal):
        bonus += 5.0
    if sources >= 3 and (has_points or no_token or task_portal or explicit):
        bonus += 6.0
    elif sources >= 2 and (has_points or no_token or task_portal):
        bonus += 3.0

    # listed tokens without airdrop story stay capped. This predicate is shared
    # with ADR-015's eligibility veto so the two policy paths cannot drift.
    if is_already_launched_without_airdrop_path(project):
        return min(35.0, base + bonus)
    return min(100.0, base + bonus)
