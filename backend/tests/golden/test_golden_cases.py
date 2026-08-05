"""Golden test suite for end-to-end pipeline validation.

Tests the complete pipeline against golden cases to ensure:
1. Scoring algorithm consistency
2. Label mapping correctness
3. Reason generation quality
4. Confidence calculation accuracy

These tests serve as regression tests - any changes to scoring logic
should be validated against these cases.

Reference:
- DATA_SCORING_DICT.md §12
- backend/tests/golden/cases.py
"""

import pytest

from app.agents.orchestrator_simple import run_orchestrator
from tests.golden.cases import GoldenCase, get_all_golden_cases, get_golden_case


class TestGoldenCases:
    """Test all golden cases end-to-end."""

    @pytest.mark.asyncio
    async def test_layerx_high_quality(self):
        """Test LayerX reference case from DATA_SCORING_DICT.md §12."""
        case = get_golden_case("layerx_high_quality")
        await self._run_golden_case(case)

    @pytest.mark.asyncio
    async def test_restaking_peak_narrative(self):
        """Test Restaking project at peak narrative timing."""
        case = get_golden_case("restaking_peak_narrative")
        await self._run_golden_case(case)

    @pytest.mark.asyncio
    async def test_defi_mature_late(self):
        """Test mature DeFi with late narrative timing."""
        case = get_golden_case("defi_mature_late")
        await self._run_golden_case(case)

    @pytest.mark.asyncio
    async def test_gaming_early_moderate(self):
        """Test early Gaming with moderate signals."""
        case = get_golden_case("gaming_early_moderate")
        await self._run_golden_case(case)

    @pytest.mark.asyncio
    async def test_infrastructure_strong(self):
        """Test strong infrastructure with low competition."""
        case = get_golden_case("infrastructure_strong")
        await self._run_golden_case(case)

    @pytest.mark.asyncio
    async def test_anonymous_team_risk(self):
        """Test project with anonymous team risk."""
        case = get_golden_case("anonymous_team_risk")
        await self._run_golden_case(case)

    @pytest.mark.asyncio
    async def test_ideation_high_uncertainty(self):
        """Test ideation-stage with high uncertainty."""
        case = get_golden_case("ideation_high_uncertainty")
        await self._run_golden_case(case)

    @pytest.mark.asyncio
    async def test_bridge_mature_moderate(self):
        """Test bridge in mature sector."""
        case = get_golden_case("bridge_mature_moderate")
        await self._run_golden_case(case)

    @pytest.mark.asyncio
    async def test_l2_high_competition(self):
        """Test L2 in highly competitive market."""
        case = get_golden_case("l2_high_competition")
        await self._run_golden_case(case)

    @pytest.mark.asyncio
    async def test_minimal_signals(self):
        """Test project with minimal signals."""
        case = get_golden_case("minimal_signals")
        await self._run_golden_case(case)

    @pytest.mark.asyncio
    async def test_mixed_signals_balanced(self):
        """Test project with mixed signals."""
        case = get_golden_case("mixed_signals_balanced")
        await self._run_golden_case(case)

    @pytest.mark.asyncio
    async def test_recent_funding_boost(self):
        """Test project with recent funding."""
        case = get_golden_case("recent_funding_boost")
        await self._run_golden_case(case)

    async def _run_golden_case(self, case: GoldenCase):
        """Run a single golden case and validate results.

        Args:
            case: Golden case to test
        """
        # Create projects list with correct sector count
        # We need (sector_count - 1) additional projects to match expected competition
        projects = [case.project]

        # Add dummy projects to match sector count
        for i in range(case.sector_count - 1):
            from app.agents.base import RawProject

            dummy = RawProject(
                id=f"dummy-{case.project.sector}-{i}",
                name=f"Dummy{i}",
                sector=case.project.sector,
                stage="testnet",
                source="seed",
            )
            projects.append(dummy)

        # Run orchestrator
        response = await run_orchestrator(projects, run_id=f"golden-{case.name}")

        # Response should be successful
        assert response.status in ["completed", "partial"], f"{case.name}: Pipeline failed"

        # Find the project we care about (not dummies)
        # We need to run orchestrator and check the state
        # Let's run it properly with orchestrator to get state
        from app.agents.base import AgentContext
        from app.agents.orchestrator_simple import SimpleOrchestrator

        context = AgentContext(run_id=f"golden-{case.name}")
        orchestrator = SimpleOrchestrator()
        response = await orchestrator.run_pipeline(projects, context)

        # Get sector counts
        sector_counts = orchestrator._calculate_sector_counts(projects)
        assert sector_counts[case.project.sector] == case.sector_count, f"{case.name}: Sector count mismatch"

        # Run single project to get state
        state = await orchestrator._run_single_project(case.project, context, sector_counts)

        # Validate score (±5 tolerance: v1.2 eight-factor model + agent heuristics)
        assert state.score is not None, f"{case.name}: Score is None"
        assert abs(state.score - case.expected_score) <= 5, (
            f"{case.name}: Score {state.score} not within ±5 of expected {case.expected_score}"
        )

        # Validate label
        assert state.label == case.expected_label, f"{case.name}: Label {state.label} != expected {case.expected_label}"

        # Validate confidence (v1.3 evidence mix — not pure agent ratio)
        assert state.confidence is not None, f"{case.name}: Confidence is None"
        assert 0.0 <= state.confidence <= 1.0
        # confidence 是"证据完整度"（DATA_SCORING_DICT §97），低证据项目本就该低置信度。
        # 此前这里是一条 >= 0.45 的硬地板，与代码里那条 0.55 的地板同源，二者共同
        # 让规格中的低置信度降级永不触发；而 expected_confidence 字段从未被断言过。
        # 现改为对声明值做带容差的正向断言，把空字段变成真正的回归守卫。
        assert abs(state.confidence - case.expected_confidence) <= 0.10, (
            f"{case.name}: Confidence {state.confidence:.3f} != expected {case.expected_confidence:.3f} (±0.10)"
        )

        # Validate reasons (at least 2 of expected keywords should match)
        matched_reasons = sum(
            1 for expected in case.expected_reasons if any(expected in actual for actual in state.reason)
        )

        assert matched_reasons >= 2, (
            f"{case.name}: Only {matched_reasons} reasons matched. "
            f"Expected keywords: {case.expected_reasons}, "
            f"Actual reasons: {state.reason}"
        )


class TestGoldenCasesBatch:
    """Test all golden cases in batch."""

    @pytest.mark.asyncio
    async def test_all_golden_cases(self):
        """Run all golden cases and report results."""
        cases = get_all_golden_cases()
        results = []

        for case in cases:
            try:
                # Create projects with correct sector count
                projects = [case.project]
                for i in range(case.sector_count - 1):
                    from app.agents.base import RawProject

                    dummy = RawProject(
                        id=f"dummy-{case.project.sector}-{i}",
                        name=f"Dummy{i}",
                        sector=case.project.sector,
                        stage="testnet",
                        source="seed",
                    )
                    projects.append(dummy)

                # Run orchestrator
                from app.agents.base import AgentContext
                from app.agents.orchestrator_simple import SimpleOrchestrator

                context = AgentContext(run_id=f"batch-{case.name}")
                orchestrator = SimpleOrchestrator()

                sector_counts = orchestrator._calculate_sector_counts(projects)
                state = await orchestrator._run_single_project(case.project, context, sector_counts)

                # Check results
                score_match = abs(state.score - case.expected_score) <= 3
                label_match = state.label == case.expected_label

                results.append(
                    {
                        "name": case.name,
                        "passed": score_match and label_match,
                        "score": state.score,
                        "expected_score": case.expected_score,
                        "label": state.label,
                        "expected_label": case.expected_label,
                    }
                )

            except Exception as e:
                results.append(
                    {
                        "name": case.name,
                        "passed": False,
                        "error": str(e),
                    }
                )

        # Report summary
        passed_count = sum(1 for r in results if r.get("passed", False))
        total_count = len(results)

        print(f"\n{'=' * 60}")
        print(f"Golden Cases Summary: {passed_count}/{total_count} passed")
        print(f"{'=' * 60}")

        for result in results:
            status = "✅" if result.get("passed", False) else "❌"
            print(f"{status} {result['name']}")
            if not result.get("passed", False):
                if "error" in result:
                    print(f"   Error: {result['error']}")
                else:
                    print(f"   Score: {result.get('score')} (expected {result.get('expected_score')})")
                    print(f"   Label: {result.get('label')} (expected {result.get('expected_label')})")

        # All must pass
        assert passed_count == total_count, f"Only {passed_count}/{total_count} golden cases passed"


class TestGoldenCaseAccess:
    """Test golden case accessor functions."""

    def test_get_golden_case_by_name(self):
        """Test getting golden case by name."""
        case = get_golden_case("layerx_high_quality")
        assert case.name == "layerx_high_quality"
        assert case.project.name == "LayerX"

    def test_get_golden_case_not_found(self):
        """Test getting non-existent golden case."""
        with pytest.raises(ValueError, match="not found"):
            get_golden_case("nonexistent_case")

    def test_get_all_golden_cases(self):
        """Test getting all golden cases."""
        cases = get_all_golden_cases()
        assert len(cases) == 12
        assert all(isinstance(case, GoldenCase) for case in cases)

    def test_golden_cases_have_required_fields(self):
        """Test all golden cases have required fields."""
        cases = get_all_golden_cases()

        for case in cases:
            assert case.name, "Case missing name"
            assert case.description, f"{case.name}: Missing description"
            assert case.project, f"{case.name}: Missing project"
            assert case.sector_count > 0, f"{case.name}: Invalid sector_count"
            assert 0 <= case.expected_score <= 100, f"{case.name}: Invalid score"
            assert case.expected_label in ["FARM", "WATCH", "IGNORE"], f"{case.name}: Invalid label"
            assert case.expected_reasons, f"{case.name}: Missing reasons"
            assert 0.0 <= case.expected_confidence <= 1.0, f"{case.name}: Invalid confidence"


class TestGoldenCaseCategories:
    """Test golden cases by category."""

    @pytest.mark.asyncio
    async def test_farm_category_cases(self):
        """Test all FARM-labeled golden cases."""
        cases = [c for c in get_all_golden_cases() if c.expected_label == "FARM"]
        assert len(cases) >= 3, "Should have at least 3 FARM cases"

        for case in cases:
            projects = [case.project]
            for i in range(case.sector_count - 1):
                from app.agents.base import RawProject

                dummy = RawProject(
                    id=f"dummy-{case.project.sector}-{i}",
                    name=f"Dummy{i}",
                    sector=case.project.sector,
                    stage="testnet",
                    source="seed",
                )
                projects.append(dummy)

            from app.agents.base import AgentContext
            from app.agents.orchestrator_simple import SimpleOrchestrator

            context = AgentContext(run_id=f"farm-{case.name}")
            orchestrator = SimpleOrchestrator()

            sector_counts = orchestrator._calculate_sector_counts(projects)
            state = await orchestrator._run_single_project(case.project, context, sector_counts)

            assert state.label == "FARM", f"{case.name}: Expected FARM label"
            assert state.score >= 65, f"{case.name}: FARM score should be >= 65"

    @pytest.mark.asyncio
    async def test_watch_category_cases(self):
        """Test all WATCH-labeled golden cases."""
        cases = [c for c in get_all_golden_cases() if c.expected_label == "WATCH"]
        assert len(cases) >= 3, "Should have at least 3 WATCH cases"

        for case in cases:
            projects = [case.project]
            for i in range(case.sector_count - 1):
                from app.agents.base import RawProject

                dummy = RawProject(
                    id=f"dummy-{case.project.sector}-{i}",
                    name=f"Dummy{i}",
                    sector=case.project.sector,
                    stage="testnet",
                    source="seed",
                )
                projects.append(dummy)

            from app.agents.base import AgentContext
            from app.agents.orchestrator_simple import SimpleOrchestrator

            context = AgentContext(run_id=f"watch-{case.name}")
            orchestrator = SimpleOrchestrator()

            sector_counts = orchestrator._calculate_sector_counts(projects)
            state = await orchestrator._run_single_project(case.project, context, sector_counts)

            assert state.label == "WATCH", f"{case.name}: Expected WATCH label"
            assert 50 <= state.score < 65, f"{case.name}: WATCH score should be 50-64"

    @pytest.mark.asyncio
    async def test_ignore_category_cases(self):
        """Test all IGNORE-labeled golden cases."""
        cases = [c for c in get_all_golden_cases() if c.expected_label == "IGNORE"]
        assert len(cases) >= 2, "Should have at least 2 IGNORE cases"

        for case in cases:
            projects = [case.project]
            for i in range(case.sector_count - 1):
                from app.agents.base import RawProject

                dummy = RawProject(
                    id=f"dummy-{case.project.sector}-{i}",
                    name=f"Dummy{i}",
                    sector=case.project.sector,
                    stage="testnet",
                    source="seed",
                )
                projects.append(dummy)

            from app.agents.base import AgentContext
            from app.agents.orchestrator_simple import SimpleOrchestrator

            context = AgentContext(run_id=f"ignore-{case.name}")
            orchestrator = SimpleOrchestrator()

            sector_counts = orchestrator._calculate_sector_counts(projects)
            state = await orchestrator._run_single_project(case.project, context, sector_counts)

            assert state.label == "IGNORE", f"{case.name}: Expected IGNORE label"
            # IGNORE 有两条来源：分数低于阈值，或分数够但证据置信度过低被降级
            # （DATA_SCORING_DICT 的低置信度降级）。此前降级因 confidence 恒 >= 0.55
            # 而永不触发，于是"IGNORE ⟹ 分数<50"看起来总成立。
            assert state.score < 50 or state.confidence < 0.5, (
                f"{case.name}: IGNORE 需来自低分(<50)或低置信度降级(<0.5)，"
                f"实际 score={state.score} confidence={state.confidence:.3f}"
            )
