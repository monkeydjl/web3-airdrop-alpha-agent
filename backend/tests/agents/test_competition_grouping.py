"""competition 分组必须按规范键，否则竞争度分虚高。

## 缺陷是什么

`competition` 子分只看一个输入：本赛道有多少个项目（`COMPETITION_MAP`
把 n<=3 映射成 100 分、n>15 映射成 40 分）。而 `sector` 在真实采集里同一个
逻辑赛道有多种写法 —— DefiLlama 给 `"Dexes"`、CryptoRank 给 `"DEX"`、
github 推断给 `"dex"`、衍生品交易所又写成 `"Derivatives"`。

原实现按**原始写法**分组：12 个 DEX 项目会裂成 4 组（4/3/2/3），每组都落在
「几乎没有竞品」的档位，competition 从应有的 55 变成 75~100。方向是**系统性
偏乐观**：赛道越挤、写法越杂，虚高越严重。

## 为什么不在 normalize 侧修

`normalize_sector()` 的产出进 `create_dedup_key()` →
`generate_deterministic_id()`。把 `"Dexes"` 归一成 `"DEX"` 会让既有项目算出
不同 UUID。所以归一只能做在**分组这一侧**，`project.sector` 原样保留。
反向约束见 `test_sector_profile_lookup.py::
test_lookup_alias_is_not_wired_into_normalize_sector`。

## 两侧口径必须一致

`_calculate_sector_counts()` 按规范键计数，`_calc_competition()` 也必须按
规范键查。一边规范键、一边原始写法会全部 miss，然后静默退到中性 50 分 ——
比虚高更难发现，因为 50 分看起来完全正常。
"""

from __future__ import annotations

import pytest

from app.agents.base import AgentContext, PipelineState, RawProject
from app.agents.narrative import canonical_sector_key
from app.agents.orchestrator_simple import SimpleOrchestrator
from app.agents.scorer import ScorerAgent


def _project(project_id: str, sector: str) -> RawProject:
    return RawProject(
        id=project_id,
        name=f"P-{project_id}",
        sector=sector,
        stage="testnet",
        source="seed",
    )


class TestCanonicalSectorKey:
    """规范键函数本身的语义。"""

    @pytest.mark.parametrize(
        ("writing", "expected"),
        [
            ("DEX", "DEX"),
            ("Dexes", "DEX"),
            ("dex", "DEX"),
            ("Derivatives", "DEX"),
            ("L2", "L2"),
            ("Rollup", "L2"),
            ("Layer 2", "L2"),
            ("Restaking", "Restaking"),
            ("Liquid Restaking", "Restaking"),
            # ZK 是独立档位，不折进 L2 —— 分组沿用 SECTOR_PROFILE 的赛道划分，
            # 那张表给 ZK 和 L2 不同的热度档，说明它们被当成两个赛道。
            ("zk-rollup", "ZK"),
            ("ZK Rollup", "ZK"),
        ],
    )
    def test_real_world_writings_fold_to_one_key(self, writing: str, expected: str) -> None:
        """真实采集见到的写法必须折成同一个键，否则一个赛道被拆成多组。"""
        assert canonical_sector_key(writing) == expected

    def test_unknown_sectors_stay_distinct(self) -> None:
        """未知赛道各自独立成组，不能塌成同一个桶。

        这是与 `resolve_sector_profile()` 刻意不同的地方：查热度档位需要
        「没命中」信号（返回 None），分组不需要 —— 把未知写法都变成 None
        会让 RWA 和 SocialFi 互相算成竞品，凭空制造竞争度。
        """
        assert canonical_sector_key("RWA") == "RWA"
        assert canonical_sector_key("SocialFi") == "SocialFi"
        assert canonical_sector_key("RWA") != canonical_sector_key("SocialFi")

    def test_whitespace_is_trimmed_but_value_preserved(self) -> None:
        """采集来的字符串常带空白，trim 后仍是同一组。"""
        assert canonical_sector_key("  Dexes  ") == "DEX"
        assert canonical_sector_key("  RWA  ") == "RWA"

    @pytest.mark.parametrize("empty", [None, "", "   "])
    def test_empty_stays_falsy(self, empty: str | None) -> None:
        """空值必须保持 falsy，调用方靠这个跳过计数。"""
        assert not canonical_sector_key(empty)

    def test_does_not_mutate_project_sector(self) -> None:
        """规范键只是查表用的派生值，`project.sector` 必须原样保留。

        `project.sector` 参与 `generate_deterministic_id()`，被改写会让既有
        项目 ID 漂移、跨源去重失效。
        """
        project = _project("p-1", "Dexes")
        assert canonical_sector_key(project.sector) == "DEX"
        assert project.sector == "Dexes"


class TestOrchestratorGrouping:
    """`_calculate_sector_counts()` 的分组口径。"""

    def test_mixed_writings_collapse_into_one_group(self) -> None:
        """这就是缺陷本体：12 个 DEX 不能被拆成 4 组。"""
        writings = ["Dexes"] * 4 + ["DEX"] * 3 + ["dex"] * 2 + ["Derivatives"] * 3
        projects = [_project(f"p-{i}", s) for i, s in enumerate(writings)]

        counts = SimpleOrchestrator()._calculate_sector_counts(projects)

        assert counts == {"DEX": 12}

    def test_two_sectors_each_with_multiple_writings(self) -> None:
        """多赛道混杂时各自折叠，互不串台。"""
        writings = ["Dexes"] * 4 + ["DEX"] * 3 + ["Rollup"] * 5 + ["L2"] * 6 + ["Layer 2"] * 2
        projects = [_project(f"p-{i}", s) for i, s in enumerate(writings)]

        counts = SimpleOrchestrator()._calculate_sector_counts(projects)

        assert counts == {"DEX": 7, "L2": 13}

    def test_unknown_sectors_are_separate_groups(self) -> None:
        """未知赛道不能被合并 —— 那会凭空制造竞争度。"""
        projects = [
            _project("p-1", "RWA"),
            _project("p-2", "RWA"),
            _project("p-3", "SocialFi"),
        ]

        counts = SimpleOrchestrator()._calculate_sector_counts(projects)

        assert counts == {"RWA": 2, "SocialFi": 1}

    def test_stays_a_pure_function_of_the_batch(self) -> None:
        """只统计传入批次，不查 DB —— Golden 用例「同输入同输出」的前提。

        分组归一是纯字符串映射，不能引入任何外部状态。同一批次跑两次必须
        完全一致。
        """
        projects = [_project(f"p-{i}", s) for i, s in enumerate(["Dexes", "DEX", "RWA"])]
        orchestrator = SimpleOrchestrator()

        first = orchestrator._calculate_sector_counts(projects)
        second = orchestrator._calculate_sector_counts(projects)

        assert first == second == {"DEX": 2, "RWA": 1}

    def test_missing_sector_is_not_counted(self) -> None:
        """sector 缺失的项目不进任何分组。"""
        projects = [_project("p-1", "DEX"), RawProject(id="p-2", name="NoSector", source="seed")]

        counts = SimpleOrchestrator()._calculate_sector_counts(projects)

        assert counts == {"DEX": 1}


class TestScorerLooksUpWithTheSameKey:
    """`_calc_competition()` 必须与分组口径一致。"""

    @pytest.mark.parametrize(
        "writing",
        ["Dexes", "DEX", "dex", "Derivatives"],
    )
    def test_all_writings_get_the_same_competition_score(self, writing: str) -> None:
        """无论项目自己的 sector 怎么写，都要查到同一个分组的计数。

        修复前：counts 按规范键存 `{"DEX": 12}`，而查表用原始写法 `"Dexes"`
        → miss → 静默退到中性 50。修复后一致得 55（n=12 落 9~15 档）。
        """
        agent = ScorerAgent(sector_counts={"DEX": 12})
        state = PipelineState(
            project=_project("p-1", writing),
            context=AgentContext(run_id="run-competition"),
        )

        assert agent._calculate_subscores(state)["competition"] == 55.0

    def test_orchestrator_and_scorer_agree_end_to_end(self) -> None:
        """把两侧接起来跑：分组产出的 counts 必须能被 scorer 查到。

        这条测试是防回归的关键 —— 单看任一侧都可能"正确"，只有串起来才能
        发现口径不一致。
        """
        writings = ["Dexes"] * 4 + ["DEX"] * 3 + ["dex"] * 2 + ["Derivatives"] * 3
        projects = [_project(f"p-{i}", s) for i, s in enumerate(writings)]

        counts = SimpleOrchestrator()._calculate_sector_counts(projects)
        agent = ScorerAgent(sector_counts=counts)
        context = AgentContext(run_id="run-e2e")

        scores = {
            p.sector: agent._calculate_subscores(PipelineState(project=p, context=context))["competition"]
            for p in projects
        }

        # 12 个同赛道项目 → 55（拆组时会是 75~100）
        assert set(scores.values()) == {55.0}

    def test_raw_writing_counts_still_work(self) -> None:
        """老路径兼容：调用方直接用原始写法构造 sector_counts 时仍要命中。

        既有测试与部分调用方（回测脚本、手工构造）传的是原始写法字典。
        规范键 miss 后要回退查原始写法，否则这些路径会集体退到中性 50。
        """
        agent = ScorerAgent(sector_counts={"Dexes": 2})
        state = PipelineState(
            project=_project("p-1", "Dexes"),
            context=AgentContext(run_id="run-legacy"),
        )

        assert agent._calculate_subscores(state)["competition"] == 100.0

    def test_unknown_sector_absent_from_counts_is_neutral(self) -> None:
        """既不在规范键也不在原始写法里 → 中性 50，不编造竞争度。"""
        agent = ScorerAgent(sector_counts={"DEX": 12})
        state = PipelineState(
            project=_project("p-1", "RWA"),
            context=AgentContext(run_id="run-unknown"),
        )

        assert agent._calculate_subscores(state)["competition"] == 50.0


class TestRepositoryFoldsGlobalCounts:
    """全库计数也要折叠 —— 否则批次内折叠、批次外不折叠，合并出来的数字没意义。"""

    def test_canonical_sector_counts_folds_raw_writings(self) -> None:
        """库里存的是原始写法，返回的分布必须按规范键折叠。"""
        import sqlite3

        from app.db import init_db
        from app.repository import ProjectRepository

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            init_db(conn)
            rows = ["Dexes"] * 4 + ["DEX"] * 3 + ["Rollup"] * 5 + ["RWA"] * 2
            for i, sector in enumerate(rows):
                conn.execute(
                    "INSERT INTO projects (id, name, sector, source) VALUES (?, ?, ?, ?)",
                    (f"db-{i}", f"DBProject{i}", sector, "seed"),
                )
            conn.commit()

            counts = ProjectRepository(conn).canonical_sector_counts()
        finally:
            conn.close()

        assert counts == {"DEX": 7, "L2": 5, "RWA": 2}

    def test_exact_match_query_would_miss_the_rows(self) -> None:
        """反证：为什么不能复用 `WHERE sector = ?` 精确匹配。

        库里存 `"Dexes"`，拿规范键 `"DEX"` 去精确匹配得 0。这正是必须换成
        `GROUP BY sector` + Python 侧折叠的原因。
        """
        import sqlite3

        from app.db import init_db
        from app.repository import ProjectRepository

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            init_db(conn)
            for i in range(4):
                conn.execute(
                    "INSERT INTO projects (id, name, sector, source) VALUES (?, ?, ?, ?)",
                    (f"db-{i}", f"DBProject{i}", "Dexes", "seed"),
                )
            conn.commit()
            repo = ProjectRepository(conn)

            assert repo.count_by_sector("DEX") == 0
            assert repo.count_by_sector("Dexes") == 4
            assert repo.canonical_sector_counts()["DEX"] == 4
        finally:
            conn.close()
