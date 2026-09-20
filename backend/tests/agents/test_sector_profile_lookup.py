"""sector 查表必须能吸收真实写法，未命中必须出声。

## 为什么需要这个测试

`narrative_timing` 的输入完全来自 `SECTOR_PROFILE[sector]` 查表，与项目自身
特征无关。原实现是 `SECTOR_PROFILE.get(sector, DEFAULT_PROFILE)` —— 大小写
敏感的精确匹配，未命中时**静默**走默认档。而 `DEFAULT_PROFILE`
（base_heat 0.60 × momentum 1.0，stage="growth" → coeff 1.0）恰好让
narrative_timing **恒等于 60.0**。

于是失效方式是：这一维的 0.15 权重退化成常数，八维模型实际只有七维在区分
项目，而总分看上去完全正常，没有任何信号提示。M2 回测里 19 个样本全部踩中
（`zk-rollup` vs `ZK`），当时误判为「数据集保真度问题」；实测 DefiLlama 的
真实 category 同样大面积未命中（`Dexes` / `Rollup` / `Liquid Restaking`），
所以这是生产路径缺陷，不只是回测数据的问题。

## 为什么归一放在查表侧，而不是扩 utils.normalize.SECTOR_ALIAS

`normalize_sector()` 的产出进 `create_dedup_key()` →
`generate_deterministic_id()` —— sector 是项目**确定性 ID** 的组成部分。
把 `"Dexes"` 归一成 `"DEX"` 会让同一个项目算出不同 UUID，既有行全部变成
孤儿、跨源去重失效。所以查表归一必须是独立的一层，且不改写
`project.sector` 本身。
"""

from __future__ import annotations

import pytest

from app.agents.narrative import (
    _SECTOR_LOOKUP_ALIAS,
    DEFAULT_PROFILE,
    SECTOR_PROFILE,
    resolve_sector_profile,
)


def _run_narrative_capturing_logs(*, project_id: str, name: str, sector: str) -> list[dict]:
    """跑一遍 NarrativeAgent，返回捕获到的结构化日志条目。"""
    import asyncio

    from structlog.testing import capture_logs

    from app.agents.base import AgentContext, PipelineState, RawProject
    from app.agents.narrative import NarrativeAgent

    project = RawProject(id=project_id, name=name, sector=sector, stage="testnet", source="seed")
    state = PipelineState(project=project, context=AgentContext(run_id=f"run-{project_id}"))

    with capture_logs() as events:
        asyncio.run(NarrativeAgent().run(state))
    return events


class TestLookupAliasIntegrity:
    """别名表本身的自洽性 —— 写错一个值就等于静默走默认档。"""

    def test_every_alias_points_at_a_real_profile_key(self) -> None:
        """别名的值必须是 SECTOR_PROFILE 里真实存在的键。

        指向不存在的键时 `SECTOR_PROFILE[canonical]` 会 KeyError，而这条路径
        在 agent 里被宽泛的 try/except 包着 —— 表现为该 agent 静默降级，
        而不是明确报错。所以在这里钉住。
        """
        dangling = {alias: key for alias, key in _SECTOR_LOOKUP_ALIAS.items() if key not in SECTOR_PROFILE}
        assert not dangling, f"别名指向不存在的 SECTOR_PROFILE 键: {dangling}"

    def test_alias_keys_are_already_lowercased(self) -> None:
        """键必须是 lower() 形式 —— 查找时用的是 `sector.strip().lower()`。

        混入大写的键永远匹配不上，是一条看不见的死配置。
        """
        not_lowered = [alias for alias in _SECTOR_LOOKUP_ALIAS if alias != alias.lower()]
        assert not not_lowered, f"别名键必须小写，否则永远匹配不到: {not_lowered}"


class TestRealWorldSectorWritings:
    """真实上游写法必须命中，而不是掉进默认档。"""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            # DefiLlama 的 category 用复数
            ("Dexes", "DEX"),
            ("Derivatives", "DEX"),
            # DefiLlama 把 L2 叫 Rollup
            ("Rollup", "L2"),
            ("Optimistic Rollup", "L2"),
            # LRT 赛道
            ("Liquid Restaking", "Restaking"),
            # CryptoRank / 人工输入的空格与连字符写法
            ("Layer 2", "L2"),
            ("Layer-2", "L2"),
            ("Cross-Chain", "Bridge"),
            # M2 回测数据集用过的写法（当时 19 条全部未命中）
            ("zk-rollup", "ZK"),
            ("interoperability", "Bridge"),
            ("modular-da", "Infrastructure"),
            ("perp-dex", "DEX"),
            ("privacy-rollup", "Privacy"),
            # 纯大小写差异
            ("l2", "L2"),
            ("zk", "ZK"),
            ("defi", "DeFi"),
            # 泛类归档
            ("Yield", "DeFi"),
            ("Liquid Staking", "DeFi"),
            ("CDP", "Lending"),
            ("Chain", "Infrastructure"),
            ("Oracle", "Infrastructure"),
        ],
    )
    def test_alias_resolves_to_canonical_profile(self, raw: str, expected: str) -> None:
        profile, matched = resolve_sector_profile(raw)
        assert matched == expected, f"{raw!r} 应归一到 {expected!r}，实际 {matched!r}"
        assert profile is SECTOR_PROFILE[expected]

    def test_exact_canonical_keys_still_match_themselves(self) -> None:
        """已经是规范键的输入不能被别名层改写。"""
        for key in SECTOR_PROFILE:
            profile, matched = resolve_sector_profile(key)
            assert matched == key
            assert profile is SECTOR_PROFILE[key]


class TestMissIsObservableNotSilent:
    """未命中必须可观测 —— 这是整个改动的核心。"""

    @pytest.mark.parametrize("unknown", ["RWA", "Prediction Markets", "SocialFi", "NoSuchSector", "", "  "])
    def test_unknown_sector_reports_no_match(self, unknown: str) -> None:
        """未命中时第二个返回值必须是 None。

        原实现只返回 profile，调用方**无法区分**「命中了一个恰好等于默认值的
        档位」与「压根没命中」。区分不出来就没法打日志，没日志就没人会发现
        0.15 的权重正在被白扔。
        """
        profile, matched = resolve_sector_profile(unknown)
        assert matched is None, f"{unknown!r} 不该被判为命中"
        assert profile is DEFAULT_PROFILE

    def test_unmatched_sector_does_not_get_a_fabricated_profile(self) -> None:
        """没有对应档位的赛道不得被硬塞进别的档。

        `RWA` 在 SECTOR_PROFILE 里确实没有档位。给它编一个 base_heat 等于
        凭空造赛道热度 —— 宁可走默认档并打 warning，让人来补真实档位。
        """
        profile, matched = resolve_sector_profile("RWA")
        assert matched is None
        assert profile["base_heat"] == DEFAULT_PROFILE["base_heat"]

    def test_agent_warns_on_unknown_sector(self) -> None:
        """agent 跑到未命中的 sector 时必须打 narrative.sector_profile_missing。

        用 `structlog.testing.capture_logs()` 而不是 caplog：本仓库日志走
        structlog 自己的处理器链，不经过 stdlib logging，caplog 抓不到
        （同 test_agent_budget_refusal.py 的说明）。
        """
        events = _run_narrative_capturing_logs(
            project_id="sector-miss-001",
            name="Unknown Sector Proj",
            sector="Prediction Markets",
        )

        misses = [e for e in events if e.get("event") == "narrative.sector_profile_missing"]
        assert misses, "未命中却没有告警 —— narrative_timing 已退化为常数，但没人会知道。"
        assert misses[0]["sector"] == "Prediction Markets"
        # 附上已知赛道列表，排障时不必再去翻源码找可用取值。
        assert "known_sectors" in misses[0]

    def test_agent_stays_quiet_when_alias_resolves(self) -> None:
        """能归一的写法不得再告警，否则真问题会被噪声淹没。"""
        events = _run_narrative_capturing_logs(
            project_id="sector-alias-001",
            name="Llama Style",
            sector="Dexes",
        )

        assert not [e for e in events if e.get("event") == "narrative.sector_profile_missing"]


class TestLookupDoesNotTouchProjectIdentity:
    """查表归一不得影响 dedup_key / 确定性 ID —— 否则既有行会全部变孤儿。"""

    def test_lookup_alias_is_not_wired_into_normalize_sector(self) -> None:
        """`normalize_sector()` 不得吸收查表别名。

        它的产出进 `generate_deterministic_id()`。一旦 "Dexes" 在那里被改成
        "DEX"，同一个项目就会算出两个不同 UUID：既有行失联、跨源去重失效。
        这个断言是刻意的**反向**约束 —— 看到它失败请先想清楚 ID 迁移方案，
        而不是顺手让两张表"统一"。
        """
        from app.utils.normalize import normalize_sector

        assert normalize_sector("Dexes") == "Dexes"
        assert normalize_sector("Rollup") == "Rollup"

    def test_resolve_returns_profile_without_rewriting_input(self) -> None:
        """resolve 只返回档位，不回写 sector 字段。"""
        import asyncio

        from app.agents.base import AgentContext, PipelineState, RawProject
        from app.agents.narrative import NarrativeAgent

        project = RawProject(
            id="sector-keep-001",
            name="Keep Raw Sector",
            sector="Rollup",
            stage="testnet",
            source="seed",
        )
        state = PipelineState(project=project, context=AgentContext(run_id="sector-keep"))
        asyncio.run(NarrativeAgent().run(state))

        assert state.project.sector == "Rollup", "查表归一污染了 project.sector —— 会连带改变确定性 ID"
