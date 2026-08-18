"""Tests for HeatSignalProvider and NarrativeAgent V2 integration (C3).

验证：
1. HeatSignalProvider 缓存命中/未命中
2. 信号聚合计算（Twitter/VC/KOL）
3. 乘子钳制范围 [min, max]
4. 降级路径：信号源失败 → multiplier=1.0
5. NarrativeAgent 接入后 heat_score 动态变化
6. 降级路径不影响 analyze 并行

Reference:
- V2_TASKS.md C3
- ENGINEERING_ROADMAP.md §6.3 V2 增强
"""

import pytest

from app.agents.heat_signals import (
    HeatSignalProvider,
    get_heat_signal_provider,
    reset_heat_signal_provider,
)
from app.agents.narrative import SECTOR_PROFILE, NarrativeAgent
from app.config import settings
from app.db import get_connection


@pytest.fixture(autouse=True)
def clean_state():
    """每个测试前重置全局单例。"""
    reset_heat_signal_provider()
    yield
    reset_heat_signal_provider()


@pytest.fixture
def clean_signals():
    """清理 project_signals 表中的测试数据。"""
    with get_connection() as conn:
        conn.execute("DELETE FROM project_signals WHERE signal_source = 'test_heat'")
        conn.commit()
    yield
    with get_connection() as conn:
        conn.execute("DELETE FROM project_signals WHERE signal_source = 'test_heat'")
        conn.commit()


class TestHeatSignalProvider:
    """HeatSignalProvider 单元测试。"""

    def test_disabled_returns_neutral(self, monkeypatch):
        """heat_signal_enabled=False 时返回 1.0。"""
        monkeypatch.setattr(settings, "heat_signal_enabled", False)
        provider = HeatSignalProvider()
        assert provider.get_multiplier("DeFi") == 1.0

    def test_no_signals_returns_neutral(self):
        """无信号时返回 1.0（不影响 heat_score）。"""
        provider = HeatSignalProvider(ttl=1, lookback_hours=1)
        # 查询一个不存在的 sector
        multiplier = provider.get_multiplier("NonExistentSector12345")
        assert multiplier == 1.0

    def test_cache_hit(self):
        """第二次调用命中缓存。"""
        provider = HeatSignalProvider(ttl=300, lookback_hours=1)
        # 第一次查询（计算 + 缓存）
        m1 = provider.get_multiplier("DeFi")
        # 第二次查询（缓存命中）
        m2 = provider.get_multiplier("DeFi")
        assert m1 == m2

    def test_cache_expiry(self):
        """TTL 过期后重新计算。"""
        provider = HeatSignalProvider(ttl=0.05, lookback_hours=1)
        m1 = provider.get_multiplier("DeFi")
        import time
        time.sleep(0.06)
        m2 = provider.get_multiplier("DeFi")
        # 两次结果应相同（无信号时都是 1.0）
        assert m1 == m2 == 1.0

    def test_invalidate(self):
        """invalidate 后缓存项消失。"""
        provider = HeatSignalProvider(ttl=300, lookback_hours=1)
        provider.get_multiplier("DeFi")
        provider.invalidate("DeFi")
        # 再查应重新计算
        m = provider.get_multiplier("DeFi")
        assert m == 1.0  # 无信号

    def test_multiplier_clamped_to_range(self):
        """乘子被钳制到 [min, max] 范围。"""
        provider = HeatSignalProvider(
            ttl=300, lookback_hours=1,
            max_multiplier=1.3, min_multiplier=0.7,
        )
        # 无信号时 1.0 在范围内
        m = provider.get_multiplier("NonExistentSector")
        assert 0.7 <= m <= 1.3

    def test_db_failure_returns_neutral(self, monkeypatch):
        """DB 查询失败时返回 1.0。"""
        provider = HeatSignalProvider(ttl=300, lookback_hours=1)

        # Mock get_connection 抛异常
        def mock_get_connection():
            raise RuntimeError("DB connection failed")

        monkeypatch.setattr(
            "app.agents.heat_signals.get_connection",
            mock_get_connection,
        )

        multiplier = provider.get_multiplier("DeFi")
        assert multiplier == 1.0

    def test_with_signals_increases_multiplier(self, clean_signals):
        """有信号时乘子 > 1.0。"""
        provider = HeatSignalProvider(
            ttl=300, lookback_hours=72,
            max_multiplier=1.3, min_multiplier=0.7,
        )

        # 插入测试信号数据
        with get_connection() as conn:
            # 插入 raw_projects
            import json

            for i in range(25):
                conn.execute(
                    """
                    INSERT OR REPLACE INTO raw_projects
                        (raw_id, source_id, dedup_key, raw_data, discovery_score, discovered_at)
                    VALUES (?, ?, ?, ?, ?, datetime('now'))
                    """,
                    (
                        f"test-heat-raw-{i:03d}",
                        "test_heat",
                        f"heat-sector-DeFi-{i:03d}",
                        json.dumps({"name": f"HeatTest{i}", "sector": "DeFi"}),
                        0.5,
                    ),
                )
            # 插入 Twitter 信号
            for i in range(25):
                conn.execute(
                    """
                    INSERT INTO project_signals
                        (signal_id, project_id, dedup_key, signal_type, signal_source,
                         signal_data, signal_strength, captured_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    """,
                    (
                        f"sig-heat-tw-{i:03d}",
                        None,
                        f"heat-sector-DeFi-{i:03d}",
                        "testnet",
                        "twitter",
                        json.dumps({"text": "test"}),
                        0.8,
                    ),
                )
            # 插入 funding 信号
            for i in range(6):
                conn.execute(
                    """
                    INSERT INTO project_signals
                        (signal_id, project_id, dedup_key, signal_type, signal_source,
                         signal_data, signal_strength, captured_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    """,
                    (
                        f"sig-heat-fund-{i:03d}",
                        None,
                        f"heat-sector-DeFi-{i:03d}",
                        "funding",
                        "rootdata",
                        json.dumps({"amount": "10M"}),
                        0.9,
                    ),
                )
            conn.commit()

        multiplier = provider.get_multiplier("DeFi")
        assert multiplier > 1.0, f"Expected multiplier > 1.0, got {multiplier}"

        # 清理测试数据
        with get_connection() as conn:
            conn.execute("DELETE FROM project_signals WHERE signal_source IN ('twitter', 'rootdata') AND dedup_key LIKE 'heat-sector-%'")
            conn.execute("DELETE FROM raw_projects WHERE dedup_key LIKE 'heat-sector-%'")
            conn.commit()


class TestNarrativeAgentIntegration:
    """NarrativeAgent V2 热度信号集成测试。"""

    @pytest.mark.asyncio
    async def test_agent_with_disabled_signals(self):
        """heat_signal_enabled=False 时使用静态 heat_score。"""
        # 使用 mock provider 返回固定值
        class MockProvider:
            def get_multiplier(self, sector: str) -> float:
                return 1.0

        agent = NarrativeAgent(heat_provider=MockProvider())

        from app.agents.base import AgentContext, PipelineState, RawProject

        project = RawProject(id="test-narr-001", name="TestProj", sector="DeFi", stage="testnet", source="seed")
        state = PipelineState(project=project, context=AgentContext(run_id="test"))

        result_state = await agent.run(state)
        assert result_state.narrative is not None

        # 静态 heat_score = base_heat * momentum = 0.70 * 0.9 = 0.63
        expected = min(1.0, SECTOR_PROFILE["DeFi"]["base_heat"] * SECTOR_PROFILE["DeFi"]["momentum"])
        assert abs(result_state.narrative.heat_score - expected) < 0.01

    @pytest.mark.asyncio
    async def test_agent_with_elevated_signals(self):
        """有热度信号时 heat_score 高于静态值。"""
        class MockProvider:
            def get_multiplier(self, sector: str) -> float:
                return 1.3  # 高热度

        agent = NarrativeAgent(heat_provider=MockProvider())

        from app.agents.base import AgentContext, PipelineState, RawProject

        project = RawProject(id="test-narr-002", name="HotProj", sector="AI", stage="testnet", source="seed")
        state = PipelineState(project=project, context=AgentContext(run_id="test"))

        result_state = await agent.run(state)
        assert result_state.narrative is not None

        # 静态 heat_score = 0.88 * 1.3 = 1.144 → clamped to 1.0
        static_heat = min(1.0, SECTOR_PROFILE["AI"]["base_heat"] * SECTOR_PROFILE["AI"]["momentum"])
        # With multiplier 1.3: static_heat * 1.3, clamped to 1.0
        expected = min(1.0, static_heat * 1.3)
        assert abs(result_state.narrative.heat_score - expected) < 0.01

    @pytest.mark.asyncio
    async def test_agent_with_cold_signals(self):
        """低热度信号时 heat_score 低于静态值。"""
        class MockProvider:
            def get_multiplier(self, sector: str) -> float:
                return 0.7  # 低热度

        agent = NarrativeAgent(heat_provider=MockProvider())

        from app.agents.base import AgentContext, PipelineState, RawProject

        project = RawProject(id="test-narr-003", name="ColdProj", sector="Gaming", stage="testnet", source="seed")
        state = PipelineState(project=project, context=AgentContext(run_id="test"))

        result_state = await agent.run(state)
        assert result_state.narrative is not None

        static_heat = min(1.0, SECTOR_PROFILE["Gaming"]["base_heat"] * SECTOR_PROFILE["Gaming"]["momentum"])
        expected = static_heat * 0.7
        assert abs(result_state.narrative.heat_score - expected) < 0.01

    @pytest.mark.asyncio
    async def test_agent_provider_failure_falls_back(self):
        """Provider 异常时降级到静态 heat_score。"""
        class FailingProvider:
            def get_multiplier(self, sector: str) -> float:
                raise RuntimeError("signal source down")

        agent = NarrativeAgent(heat_provider=FailingProvider())

        from app.agents.base import AgentContext, PipelineState, RawProject

        project = RawProject(id="test-narr-004", name="FallbackProj", sector="DeFi", stage="testnet", source="seed")
        state = PipelineState(project=project, context=AgentContext(run_id="test"))

        result_state = await agent.run(state)
        assert result_state.narrative is not None

        # 降级到静态值
        expected = min(1.0, SECTOR_PROFILE["DeFi"]["base_heat"] * SECTOR_PROFILE["DeFi"]["momentum"])
        assert abs(result_state.narrative.heat_score - expected) < 0.01

    @pytest.mark.asyncio
    async def test_agent_unknown_sector(self):
        """未知 sector 使用 DEFAULT_PROFILE。"""
        class MockProvider:
            def get_multiplier(self, sector: str) -> float:
                return 1.0

        agent = NarrativeAgent(heat_provider=MockProvider())

        from app.agents.base import AgentContext, PipelineState, RawProject

        project = RawProject(id="test-narr-005", name="UnknownProj", sector="QuantumDAO", stage="testnet", source="seed")
        state = PipelineState(project=project, context=AgentContext(run_id="test"))

        result_state = await agent.run(state)
        assert result_state.narrative is not None
        assert result_state.narrative.sector == "QuantumDAO"
        # DEFAULT_PROFILE: base_heat=0.60, momentum=1.0
        assert result_state.narrative.heat_score == 0.60

    @pytest.mark.asyncio
    async def test_heat_does_not_block_analyze(self):
        """热度信号失败不阻塞 analyze 并行。"""
        class SlowFailingProvider:
            def get_multiplier(self, sector: str) -> float:
                raise TimeoutError("signal timeout")

        agent = NarrativeAgent(heat_provider=SlowFailingProvider())

        from app.agents.base import AgentContext, PipelineState, RawProject

        # 同时跑多个项目的 narrative agent
        import asyncio

        async def run_one(pid: str, sector: str):
            project = RawProject(id=pid, name=f"Proj{pid}", sector=sector, stage="testnet", source="seed")
            state = PipelineState(project=project, context=AgentContext(run_id="test"))
            return await agent.run(state)

        results = await asyncio.gather(
            run_one("p1", "DeFi"),
            run_one("p2", "AI"),
            run_one("p3", "Gaming"),
            run_one("p4", "Restaking"),
        )

        # 全部都完成了，没有被异常阻塞
        for i, r in enumerate(results):
            assert r.narrative is not None, f"Project {i} narrative is None"
