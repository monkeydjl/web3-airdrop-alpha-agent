"""积分计划判定：全仓唯一入口。

历史问题（2026-11-09 统一口径）：`has_points_program` 曾被两套逻辑分别写值——
采集侧用 incentive / restaking / stakers / vaults / liquidity mining 这类**通用
DeFi 词**推断为 True，而资格门与已发币复查只认 `explicit_points_program`
（明确字段或"points program / points + airdrop"措辞）。于是同一份数据在
"空投信号阶梯"里算积分、在"已发币否决"里不算积分，已发币项目靠通用词拿到
积分分且绕过否决。

现在只有一条规则：

1. `explicit_points_program` 这类**字段级证据**是权威，优先采信；
2. 没有明确字段时，`has_points_program` 本身就是按同一口径归一化后的值
   （采集侧不再用通用词置真）；
3. 本模块是全仓唯一判定入口，agent 侧与 DB 行/信号字典侧都走这里，
   不再各写一份 `explicit if not None else has_points`。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = ["project_has_points_program", "resolve_points_program", "signals_have_points_program"]


def resolve_points_program(*, explicit: bool | None, has_points: bool) -> bool:
    """单一判定：明确证据优先；缺失时采用已归一化的 `has_points_program`。"""
    return bool(has_points if explicit is None else explicit)


def project_has_points_program(project: Any) -> bool:
    """RawProject / 对象形态的积分计划判定。"""
    return resolve_points_program(
        explicit=getattr(project, "explicit_points_program", None),
        has_points=bool(getattr(project, "has_points_program", False)),
    )


def signals_have_points_program(signals: Mapping[str, Any] | None) -> bool:
    """DB 行 / `meta["signals"]` 字典形态的积分计划判定。"""
    if not isinstance(signals, Mapping):
        return False
    explicit = signals.get("explicit_points_program")
    return resolve_points_program(
        explicit=None if explicit is None else bool(explicit),
        has_points=bool(signals.get("has_points_program")),
    )
