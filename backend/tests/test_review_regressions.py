"""Regression tests locking in the code-review fixes.

每个用例对应一处审查确认并修复的缺陷，防止回归。分组见各 class 文档串。
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import ClassVar

import pytest

from app.agents.base import AgentContext, PipelineState, RawProject
from app.agents.scorer import ScorerAgent
from app.collectors.rate_limiter import TokenBucketRateLimiter
from app.config import Settings
from app.services.funding import _parse_date
from app.utils.redact import redact


class TestScorerMinimumReasons:
    """Scorer 生成 reason 数量必须 ≥2，否则 ScoreResult 校验失败会把整条评分吞成 None。"""

    @pytest.mark.asyncio
    async def test_sparse_project_still_yields_two_reasons_and_a_score(self):
        # 稀疏信号项目：历史上只产出 1 条 reason → ValidationError → score=None
        project = RawProject(
            id="sparse-001",
            name="GhostSparse",
            url=None,
            sector="Gaming",
            stage="testnet",
            source="twitter_keyword",
            has_testnet=True,
            has_points_program=False,
            no_token_yet=False,
        )
        state = PipelineState(project=project, context=AgentContext(run_id="r"))
        agent = ScorerAgent(sector_counts={"Gaming": 8})
        result = await agent.run(state)
        assert result.score is not None
        assert result.label in {"FARM", "WATCH", "IGNORE"}
        assert len(result.reason) >= 2

    @pytest.mark.asyncio
    @pytest.mark.parametrize("sector", ["Gaming", "DeFi", "L2", "NewNiche", "AI"])
    async def test_various_projects_never_underflow_reasons(self, sector):
        project = RawProject(
            id=f"p-{sector}",
            name=f"P{sector}",
            url=None,
            sector=sector,
            stage="ideation",
            source="defillama",
        )
        state = PipelineState(project=project, context=AgentContext(run_id="r"))
        result = await ScorerAgent(sector_counts={}).run(state)
        assert result.score is not None
        assert len(result.reason) >= 2


class TestRepositoryUpsertPreservesColumns:
    """SQLite 保存必须用 UPSERT，不能 INSERT OR REPLACE（后者清空未列出的列）。"""

    def _init_projects_table(self, conn: sqlite3.Connection) -> None:
        from app.db import DbConnection, init_db

        init_db(DbConnection(conn, kind="sqlite"))

    def test_rescore_keeps_non_updated_columns(self):
        from app.db import DbConnection
        from app.repository import ProjectRepository

        raw = sqlite3.connect(":memory:")
        raw.row_factory = sqlite3.Row
        self._init_projects_table(raw)
        conn = DbConnection(raw, kind="sqlite")

        # 预置一行并带有 seed 专属列
        raw.execute(
            """INSERT INTO projects (id, name, score, label, recommendation,
                                     weight_version, raw_signals, raw_signals_hash)
               VALUES ('keepme', 'KeepMe', 50, 'WATCH', 'hold', 'w-1', '{"s":1}', 'abc')"""
        )
        raw.commit()

        project = RawProject(id="keepme", name="KeepMe", sector="L2", stage="testnet", source="seed")
        state = PipelineState(project=project, context=AgentContext(run_id="r"))
        state.score = 88
        state.label = "FARM"
        state.weight_version = "v1.2"
        state.sub_scores = {"airdrop_signal": 70.0}
        ProjectRepository(conn).save(state)

        row = dict(raw.execute("SELECT * FROM projects WHERE id='keepme'").fetchone())
        assert row["score"] == 88
        assert row["label"] == "FARM"
        # 未在 UPSERT SET 中列出的列必须保留，不能被清空
        assert row["recommendation"] == "hold"
        assert row["raw_signals_hash"] == "abc"
        # raw_signals 存的是采集到的**输入**信号（scripts/seed.py 与 raw_signals_hash
        # 按此语义写入），评分输出不得占用它
        assert row["raw_signals"] == '{"s":1}'
        # weight_version / sub_scores 是有意写入的列（WEIGHT_CALIBRATION §1.2
        # 要求每条分数带权重版本；§4.3 step 1 的离线重加权需要子分快照）
        assert row["weight_version"] == "v1.2"
        assert "airdrop_signal" in (row["sub_scores"] or "")
        conn.close()

    def test_failed_scoring_does_not_erase_previous_snapshot(self):
        """评分失败（sub_scores 为空）不得把上一次的好快照抹成空壳。"""
        from app.db import DbConnection
        from app.repository import ProjectRepository

        raw = sqlite3.connect(":memory:")
        raw.row_factory = sqlite3.Row
        self._init_projects_table(raw)
        conn = DbConnection(raw, kind="sqlite")

        project = RawProject(id="p", name="P", sector="L2", stage="testnet", source="seed")
        good = PipelineState(project=project, context=AgentContext(run_id="r1"))
        good.score, good.label = 88, "FARM"
        good.weight_version = "v1.2"
        good.sub_scores = {"airdrop_signal": 70.0}
        ProjectRepository(conn).save(good)

        # 第二次评分 Scorer 抛异常被吞掉：score/label 为 None，sub_scores 为空
        failed = PipelineState(project=project, context=AgentContext(run_id="r2"))
        ProjectRepository(conn).save(failed)

        row = dict(raw.execute("SELECT * FROM projects WHERE id='p'").fetchone())
        assert row["weight_version"] == "v1.2"
        assert "airdrop_signal" in (row["sub_scores"] or "")
        conn.close()


class TestSecretRedaction:
    """采集器错误信息里的密钥必须脱敏，避免落日志/落 collection_logs。"""

    def test_redacts_api_key_in_url(self, monkeypatch):
        from app import config as config_module

        monkeypatch.setattr(config_module.settings, "etherscan_api_key", "SUPERSECRET123456", raising=False)
        msg = "Client error '403 Forbidden' for url 'https://api.etherscan.io/v2/api?apikey=SUPERSECRET123456'"
        out = redact(msg)
        assert "SUPERSECRET123456" not in out
        assert "***" in out

    def test_redacts_query_token_even_if_value_unknown(self):
        msg = "GET https://x.io/v1?api_key=ZZZunknownVALUE999&limit=1 failed"
        out = redact(msg)
        assert "ZZZunknownVALUE999" not in out


class TestRateLimiterConfig:
    """Twitter 采集器 source_id 必须命中严格限流配置，且每日配额跨日重置。"""

    @pytest.mark.parametrize("source_id", ["twitter_kol", "twitter_keyword"])
    def test_twitter_sources_use_strict_config(self, source_id):
        limiter = TokenBucketRateLimiter(source_id)
        assert limiter.config.requests_per_second == 0.2
        assert limiter.config.burst == 1

    @pytest.mark.asyncio
    async def test_daily_counter_resets_across_utc_day(self):
        limiter = TokenBucketRateLimiter("coingecko")
        limiter._daily_count = limiter.config.daily_limit or 10000
        limiter._daily_epoch -= 1  # 模拟进入新的一天
        # 新的一天首个 acquire 不应因旧计数被永久锁死
        await limiter.acquire()
        assert limiter._daily_count == 1


class TestFundingDateParsing:
    """_parse_date 对无偏移字符串必须返回 tz-aware，否则下游相减崩溃。"""

    @pytest.mark.parametrize(
        "value",
        ["2024-06-01 12:00:00", "2024-06-01T12:00:00", "2024-06-01", "20240601"],
    )
    def test_parse_date_is_timezone_aware_or_none(self, value):
        dt = _parse_date(value)
        if dt is not None:
            assert dt.tzinfo is not None
            # 关键：可与 aware now 相减而不抛 TypeError
            _ = (datetime.now(UTC) - dt).days


class TestProductionConfigValidator:
    """生产环境不安全配置必须在启动时拒绝。"""

    def test_production_rejects_empty_api_key(self):
        with pytest.raises(ValueError, match="API_KEY"):
            Settings(_env_file=None, app_env="production", api_key="")

    def test_production_rejects_wildcard_cors_with_credentials(self):
        with pytest.raises(ValueError, match="CORS"):
            Settings(
                _env_file=None,
                app_env="production",
                api_key="k",
                cors_origins="*",
                cors_credentials=True,
            )

    def test_development_defaults_are_accepted(self):
        s = Settings(_env_file=None)
        assert s.is_production is False


class TestRoutesRunOffEventLoop:
    """只做同步阻塞工作的路由必须是 def（交线程池），否则单个慢请求冻结整个服务。"""

    def _pure_sync_async_handlers(self) -> list[str]:
        import ast
        import pathlib

        class AwaitFinder(ast.NodeVisitor):
            def __init__(self):
                self.found = False

            def visit_Await(self, n):
                self.found = True

            def visit_AsyncFor(self, n):
                self.found = True

            def visit_AsyncWith(self, n):
                self.found = True

            def visit_AsyncFunctionDef(self, n):
                pass  # 不下钻嵌套函数

            def visit_FunctionDef(self, n):
                pass

        # 不做任何 I/O 的纯内存处理器，留在事件循环上比进线程池更快
        trivial_allowlist = {"version"}

        offenders = []
        root = pathlib.Path(__file__).resolve().parent.parent / "app"
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.AsyncFunctionDef):
                    continue
                decorators = [ast.unparse(d) for d in node.decorator_list]
                is_route = any(
                    ("router." in d or "app." in d) and "exception_handler" not in d and "middleware" not in d
                    for d in decorators
                )
                if not is_route or node.name in trivial_allowlist:
                    continue
                finder = AwaitFinder()
                for stmt in node.body:
                    finder.visit(stmt)
                if not finder.found:
                    offenders.append(f"{path.name}:{node.lineno} {node.name}")
        return offenders

    def test_no_async_route_handler_is_purely_synchronous(self):
        offenders = self._pure_sync_async_handlers()
        assert offenders == [], (
            f"以下路由是 async def 但不含任何 await，会在事件循环上执行阻塞工作，应改为 def 交线程池：{offenders}"
        )

    def test_collection_trigger_stays_async(self):
        """采集触发必须留在事件循环上。

        采集器共享的 TokenBucketRateLimiter 持有 asyncio.Lock；若把该端点改成
        同步 def 再内部 asyncio.run()，锁会跨事件循环使用并抛 RuntimeError。
        """
        import inspect

        from app.routers.v1.collections import trigger_collection

        assert inspect.iscoroutinefunction(trigger_collection)


class TestCollectorRegistryIsShared:
    """采集器实例必须进程内共享，否则令牌桶每请求重置 = 出站限流形同虚设。"""

    def test_registry_is_cached_and_resettable(self):
        from app.collectors.factory import get_default_registry, reset_default_registry

        first = get_default_registry()
        assert get_default_registry() is first
        assert first.get("defillama") is get_default_registry().get("defillama")

        reset_default_registry()
        rebuilt = get_default_registry()
        assert rebuilt is not first
        assert len(rebuilt) == len(first)

    def test_rate_limiter_state_survives_across_lookups(self):
        from app.collectors.factory import get_default_registry, reset_default_registry

        reset_default_registry()
        collector = get_default_registry().get("cryptorank")
        collector.rate_limiter._daily_count = 7
        again = get_default_registry().get("cryptorank")
        assert again.rate_limiter._daily_count == 7
        reset_default_registry()


class TestBatchedDedupLookup:
    """批量去重查找必须与旧的逐条 SELECT 语义完全一致。"""

    def _repo_with_db(self, tmp_path, monkeypatch):
        from app.collectors.persistence import CollectionRepository
        from app.config import settings
        from app.db import init_db

        monkeypatch.setattr(settings, "db_path", str(tmp_path / "dedup.db"))
        init_db()
        return CollectionRepository()

    def _result(self, names: list[str]):
        from datetime import UTC, datetime

        from app.collectors.base import CollectorResult, RawDiscovery

        result = CollectorResult(source_id="s1")
        result.started_at = datetime.now(UTC)
        result.items = [
            RawDiscovery(
                source_id="s1",
                raw_id=f"r{i}",
                name=name,
                url=f"https://{i}.example",
                sector="L2",
                stage="testnet",
                raw_data={},
                raw_signals=[],
                discovery_score=0.5,
                discovered_at=datetime.now(UTC),
            )
            for i, name in enumerate(names)
        ]
        result.finished_at = datetime.now(UTC)
        return result

    def test_in_batch_duplicates_counted_as_duplicate(self, tmp_path, monkeypatch):
        repo = self._repo_with_db(tmp_path, monkeypatch)
        # 同一批内两条同名（=同 dedup_key）：第一条新增，第二条算重复
        result = self._result(["Alpha", "Alpha", "Beta"])
        repo.persist_collection_result(result, source_name="s1")
        assert result.items_new == 2
        assert result.items_duplicate == 1

    def test_second_run_is_all_duplicates(self, tmp_path, monkeypatch):
        repo = self._repo_with_db(tmp_path, monkeypatch)
        repo.persist_collection_result(self._result(["Alpha", "Beta"]), source_name="s1")
        second = self._result(["Alpha", "Beta"])
        repo.persist_collection_result(second, source_name="s1")
        assert second.items_new == 0
        assert second.items_duplicate == 2

    def test_dedup_key_with_sql_metacharacters_is_parameterized(self, tmp_path, monkeypatch):
        repo = self._repo_with_db(tmp_path, monkeypatch)
        tricky = ["100% Pure' OR 1=1--", "Name?With?Marks"]
        result = self._result(tricky)
        repo.persist_collection_result(result, source_name="s1")
        assert result.items_new == 2
        repeat = self._result(tricky)
        repo.persist_collection_result(repeat, source_name="s1")
        assert repeat.items_duplicate == 2


class TestBatchSaveSharesConnection:
    """批量保存必须整批复用一条连接，而不是每个项目建一次。"""

    def test_save_batch_opens_single_connection(self, tmp_path, monkeypatch):
        from app.agents.base import AgentContext, PipelineState, RawProject
        from app.config import settings
        from app.db import init_db
        from app.repository import ProjectRepository

        monkeypatch.setattr(settings, "db_path", str(tmp_path / "batch.db"))
        init_db()

        import app.repository as repo_module

        real_get_connection = repo_module.get_connection
        opened = {"n": 0}

        def counting_get_connection():
            opened["n"] += 1
            return real_get_connection()

        monkeypatch.setattr(repo_module, "get_connection", counting_get_connection)

        states = []
        for i in range(25):
            project = RawProject(id=f"b{i}", name=f"B{i}", sector="L2", stage="testnet", source="seed")
            state = PipelineState(project=project, context=AgentContext(run_id="r"))
            state.score = 70
            state.label = "FARM"
            states.append(state)

        saved = ProjectRepository().save_batch(states)
        assert saved == 25
        assert opened["n"] == 1, f"25 个项目应只建 1 次连接，实际 {opened['n']} 次"


class TestCrossSourceMergeReliability:
    """跨源合并必须遵循 DATA_QUALITY.md §128：冲突时取 reliability 最高源。"""

    def test_low_reliability_source_cannot_override_manual_input(self):
        from app.utils.normalize import merge_raw_records

        merged = merge_raw_records(
            [
                {
                    "source": "manual",
                    "name": "X",
                    "no_token_yet": False,
                    "has_task_portal": False,
                    "github_stars": 12,
                    "funding_quality": 0.1,
                },
                {
                    "source": "twitter",
                    "name": "X",
                    "no_token_yet": True,
                    "has_task_portal": True,
                    "github_stars": 999999,
                    "funding_quality": 0.99,
                },
            ]
        )
        # manual 优先级 0（表中标注"最高"），twitter 为 9：一条推文不得推翻人工确认
        assert merged["no_token_yet"] is False
        assert merged["has_task_portal"] is False
        assert merged["github_stars"] == 12
        assert merged["funding_quality"] == 0.1

    def test_sparse_source_does_not_erase_rich_source_signals(self):
        """原缺陷：整条记录择一，落选来源的全部字段被丢弃 → 多一个来源分数反而降。"""
        from app.utils.normalize import merge_raw_records

        merged = merge_raw_records(
            [
                {"source": "defillama", "name": "X", "sector": "L2", "url": None},
                {
                    "source": "galxe",
                    "name": "X",
                    "sector": "L2",
                    "url": "https://x.example",
                    "has_task_portal": True,
                    "explicit_airdrop_mention": True,
                    "has_points_program": True,
                    "github_stars": 400,
                    "funding_tier": "tier1",
                },
            ]
        )
        assert merged["url"] == "https://x.example"
        assert merged["has_task_portal"] is True
        assert merged["explicit_airdrop_mention"] is True
        assert merged["github_stars"] == 400
        assert merged["funding_tier"] == "tier1"
        assert merged["source_count"] == 2

    def test_merge_is_independent_of_input_order(self):
        """上游 ORDER BY 无唯一 tiebreaker；同优先级来源换个顺序不得改变结果。"""
        import itertools

        from app.utils.normalize import merge_raw_records

        records = [
            {"source": "galxe", "name": "X", "sector": "DeFi", "github_stars": 10},
            {"source": "layer3", "name": "X", "sector": "Gaming", "github_stars": 20},
            {"source": "etherscan", "name": "X", "url": "https://e.example"},
        ]
        results = [merge_raw_records(list(perm)) for perm in itertools.permutations(records)]
        assert all(result == results[0] for result in results)

    def test_merge_sources_string_is_deterministic_across_processes(self):
        """merge_sources 曾按 set 迭代序拼接，结果随 PYTHONHASHSEED 漂移。"""
        from app.utils.normalize import merge_sources

        assert merge_sources(["layer3", "galxe", "etherscan", "cryptorank"]) == merge_sources(
            ["etherscan", "cryptorank", "layer3", "galxe"]
        )

    def test_unhashable_field_value_does_not_abort_the_batch(self):
        """上游 JSON 偶尔把标量解析成 list/dict；集合成员测试会抛 TypeError 中断整批采集。"""
        from app.utils.normalize import merge_raw_records

        merged = merge_raw_records(
            [
                {"source": "github", "name": "X", "description": ["a", "b"], "sector": {"x": 1}},
                {"source": "twitter", "name": "X", "description": "real", "sector": "DeFi"},
            ]
        )
        assert merged["name"] == "X"


class TestTokenomicsResultRoundTrip:
    """computed_field + extra='forbid' 会让模型无法回放自己 dump 出来的 dict。"""

    def test_dump_can_be_fed_back_in(self):
        from app.models import TokenomicsResult

        original = TokenomicsResult(vc_share=0.3, team_share=0.2, unlock_penalty=0.5)
        dumped = original.model_dump()
        assert "risk" in dumped
        assert TokenomicsResult(**dumped) == original
        assert TokenomicsResult.model_validate(dumped) == original

    def test_external_risk_value_cannot_override_the_formula(self):
        from app.models import TokenomicsResult

        result = TokenomicsResult.model_validate(
            {"vc_share": 0.3, "team_share": 0.2, "unlock_penalty": 0.5, "risk": 999}
        )
        assert result.risk == pytest.approx(0.3 * 0.4 + 0.2 * 0.3 + 0.5 * 0.3)

    def test_crawler_false_does_not_suppress_another_crawlers_observation(self):
        """抵达合并的是已归一化整行：爬取源缺失的布尔被填成 False。

        这里的 False 含义是"这个源没看到"，不是"核实了不存在"，因此不得压掉
        另一个爬取源的 True——否则「行情源 + 任务门户源」一合并，空投信号全灭。
        """
        from app.utils.normalize import merge_raw_records

        merged = merge_raw_records(
            [
                {
                    "source": "defillama",
                    "name": "X",
                    "has_task_portal": False,
                    "explicit_airdrop_mention": False,
                    "has_docs": False,
                    "has_github": False,
                    "github_stars": 0,
                },
                {
                    "source": "galxe",
                    "name": "X",
                    "has_task_portal": True,
                    "explicit_airdrop_mention": True,
                    "has_docs": True,
                    "has_github": True,
                    "github_stars": 400,
                },
            ]
        )
        assert merged["has_task_portal"] is True
        assert merged["explicit_airdrop_mention"] is True
        assert merged["has_docs"] is True
        assert merged["has_github"] is True
        assert merged["github_stars"] == 400


class TestPipelineNeverLosesDataSilently:
    """持久化失败必须体现在状态里，且失败的项目不得被移出待处理队列。"""

    @pytest.mark.asyncio
    async def test_persist_failure_is_reported_not_swallowed(self, monkeypatch):
        from app.agents.orchestrator_simple import run_orchestrator

        project = RawProject(id="p1", name="P1", sector="L2", stage="testnet", source="seed")

        def boom(self, states):
            raise RuntimeError("disk full")

        monkeypatch.setattr("app.repository.ProjectRepository.save_batch_with_rows", boom)
        response = await run_orchestrator(projects=[project], run_id="r", save_to_db=True)

        # 修复前：status="completed", errors=[]，调用方完全看不出一行都没写进去
        assert response.status == "failed"
        assert any(e.get("stage") == "persist" for e in response.errors)
        assert response.persisted_project_rows == []

    @pytest.mark.asyncio
    async def test_partially_persisted_batch_is_reported_as_partial(self, monkeypatch):
        from app.agents.orchestrator_simple import run_orchestrator

        projects = [RawProject(id=f"p{i}", name=f"P{i}", sector="L2", stage="testnet", source="seed") for i in range(3)]

        def half(self, states):
            # save_batch_with_rows 会逐条吞掉单行异常，只返回成功的那些
            return [{"id": s.project.id} for s in states[:2]]

        monkeypatch.setattr("app.repository.ProjectRepository.save_batch_with_rows", half)
        response = await run_orchestrator(projects=projects, run_id="r", save_to_db=True)

        assert response.status == "partial"
        assert any("not persisted" in e.get("error", "") for e in response.errors)

    def test_unpersisted_projects_stay_in_the_queue(self):
        """出队判据必须是"落库成功"，不是内存里的 state.score。"""
        from unittest.mock import Mock

        from app.pipeline_run import mark_successful_raw_projects

        projects = [
            RawProject(id="ok", name="Ok", sector="L2", stage="testnet", source="seed"),
            RawProject(id="lost", name="Lost", sector="L2", stage="testnet", source="seed"),
        ]
        states = []
        for p in projects:
            st = PipelineState(project=p, context=AgentContext(run_id="r"))
            st.score, st.label = 70, "FARM"  # 两个都评分成功
            states.append(st)

        repo = Mock()
        repo.mark_raw_project_processed.return_value = 1
        # 只有 "ok" 落了库
        marked = mark_successful_raw_projects(projects, states, repo=repo, persisted_rows=[{"id": "ok"}])

        assert marked == 1
        marked_ids = {call.kwargs.get("project_id") for call in repo.mark_raw_project_processed.call_args_list}
        assert marked_ids == {"ok"}, "没落库的项目必须留在队列里等重试"

    def test_pipeline_run_is_recorded_even_when_it_fails(self, tmp_path, monkeypatch):
        from app.config import settings
        from app.db import get_connection, init_db
        from app.pipeline_run import record_pipeline_run

        monkeypatch.setattr(settings, "db_path", str(tmp_path / "runs.db"))
        init_db()
        record_pipeline_run(
            run_id="cron-1", trigger="cron", duration_ms=123, summary={"status": "failed"}, error="boom"
        )
        conn = get_connection()
        try:
            row = conn.execute("SELECT run_id, agent_name, error FROM logs WHERE run_id='cron-1'").fetchone()
        finally:
            conn.close()
        assert row is not None, "崩溃的定时运行必须留下持久记录"
        assert row["error"] == "boom"


class TestSchedulerHonoursConfiguredTimezone:
    """预构造的 CronTrigger 不会继承 scheduler.timezone，必须显式传。"""

    @pytest.mark.asyncio
    async def test_analysis_job_uses_configured_timezone_and_grace(self, monkeypatch):
        from app.analysis_scheduler import AnalysisScheduler
        from app.config import settings

        monkeypatch.setattr(settings, "timezone", "Asia/Shanghai")
        monkeypatch.setattr(settings, "scheduler_enabled", True)
        monkeypatch.setattr(settings, "cron_expression", "0 8 * * *")

        sched = AnalysisScheduler()
        sched.start()
        try:
            job = sched.scheduler.get_job("analysis_run_queue")
            # 修复前这里是容器时钟（TZ 环境变量），TIMEZONE 配置被静默忽略
            assert str(job.trigger.timezone) == "Asia/Shanghai"
            assert job.misfire_grace_time == settings.scheduler_misfire_grace_seconds
            assert job.misfire_grace_time > 1, "默认 1 秒会让日更任务错过一次就整天不跑"
            assert job.coalesce is True
        finally:
            sched.shutdown(wait=False)

    @pytest.mark.asyncio
    async def test_collection_jobs_use_configured_timezone(self, monkeypatch):
        from app.collectors.factory import build_default_registry
        from app.collectors.scheduler import CollectionScheduler
        from app.config import settings

        monkeypatch.setattr(settings, "timezone", "Asia/Shanghai")
        monkeypatch.setattr(settings, "collection_scheduler_enabled", True)

        sched = CollectionScheduler(build_default_registry())
        sched.start()
        try:
            jobs = [j for j in sched.scheduler.get_jobs() if j.id.startswith("collect_")]
            for job in jobs:
                assert str(job.trigger.timezone) == "Asia/Shanghai", job.id
                assert job.misfire_grace_time > 1, job.id
        finally:
            sched.shutdown(wait=False)


class TestSignalChainReachesRawProject:
    """采集到的信号必须真的抵达 RawProject —— 真实库里 7 项检查有 6 项为 0%。"""

    def test_defillama_maps_description_and_derived_flags(self):
        from app.collectors.defillama import DefiLlamaCollector

        protocol = {
            "name": "ZipLend",
            "slug": "ziplend",
            "url": "https://ziplend.xyz",
            "category": "Lending",
            "tvl": 50_000_000,
            "chains": ["Ethereum"],
            "symbol": "ZIP",
            "twitter": "@ziplend",
            "github": "ziplend",
            "description": "ZipLend docs at docs.ziplend.xyz. Points program live; airdrop snapshot for testnet users.",
        }
        raw = DefiLlamaCollector()._build_discovery(protocol).raw_data
        # description 此前完全没被复制，文本判断因此只剩一个 slug 可看
        assert raw["description"] == protocol["description"]
        assert raw["tvl_usd"] == 50_000_000
        assert raw["has_twitter"] is True
        assert raw["has_github"] is True

        from app.agents.collector import CollectorAgent

        flags = CollectorAgent._infer_airdrop_flags("defillama", raw)
        assert flags["has_docs"] is True
        assert flags["explicit_airdrop_mention"] is True

    def test_tvl_alone_no_longer_implies_testnet(self):
        from app.collectors.defillama import DefiLlamaCollector

        collector = DefiLlamaCollector()
        # 原实现把 $10M–$100M 一律判成 testnet，真实库 31.8% 项目因此被误标
        assert collector._infer_stage({"tvl": 50_000_000}) == "mainnet"
        assert collector._infer_stage({"tvl": 0}) == "ideation"

    def test_symbol_is_positive_evidence_of_a_token(self):
        from app.collectors.defillama import DefiLlamaCollector

        collector = DefiLlamaCollector()
        # 真实库 1040 条里 gecko_id 有值 0 条、symbol 有值 1038 条：
        # 只看 gecko_id 会把整个语料判成"未发币"，airdrop_signal 直接顶到 85–100
        assert collector._is_unlisted({"gecko_id": None, "symbol": "ZIP"}) is False
        assert collector._is_unlisted({"gecko_id": None, "symbol": None}) is True
        assert collector._is_unlisted({"has_token": True, "symbol": None}) is False

    def test_tweet_body_participates_in_flag_inference(self):
        from app.agents.collector import CollectorAgent

        raw = {
            "name": "NovaLayer",
            "text": "Official airdrop confirmed for NovaLayer testnet users — snapshot taken. "
            "Points program dashboard live at https://app.novalayer.xyz",
        }
        flags = CollectorAgent._infer_airdrop_flags("twitter_kol", raw)
        # 推文正文是 twitter 采集器唯一的载荷，此前完全不参与解析
        assert flags["explicit_airdrop_mention"] is True
        assert flags["has_points_program"] is True

    def test_github_sector_inference_uses_word_boundaries(self):
        from app.collectors.github import GitHubCollector

        infer = GitHubCollector()._infer_sector
        # 裸子串 "ai" 会命中 blockchain / chain / mainnet / available
        assert infer("TypeScript", "Cross-chain bridge SDK") != "AI"
        assert infer("Go", "A blockchain indexer") != "AI"
        assert infer("Python", "An AI agent framework") == "AI"

    def test_coingecko_does_not_pass_a_logo_off_as_the_website(self):
        from app.collectors.coingecko import CoinGeckoCollector

        coin = {"id": "zip", "name": "ZipLend", "symbol": "zip", "image": "https://cg.example/large/zip.png"}
        discovery = CoinGeckoCollector()._build_discovery(coin)
        assert discovery.url != coin["image"]


class TestCrossSourceMergeCanActuallyHappen:
    """写死赛道与分数阈值让跨源合并在生产中一次都没发生过。"""

    def test_signal_only_sources_do_not_fabricate_a_sector(self):
        from app.collectors.etherscan import EtherscanCollector
        from app.collectors.galxe import GalxeCollector
        from app.collectors.layer3 import Layer3Collector

        for cls in (GalxeCollector, Layer3Collector, EtherscanCollector):
            source = cls.__module__.rsplit(".", 1)[-1]
            assert 'sector="' not in _source_of(cls, "_build_discovery"), f"{source} 仍在写死赛道"

    def test_sectorless_records_fold_into_the_named_project(self):
        from app.agents.collector import _fold_sectorless_groups

        groups = {
            "ziplend::Lending": [{"source": "defillama", "name": "ZipLend"}],
            "ziplend::Unknown": [{"source": "galxe", "name": "ZipLend", "has_task_portal": True}],
        }
        folded = _fold_sectorless_groups(groups)
        assert "ziplend::Unknown" not in folded
        assert len(folded["ziplend::Lending"]) == 2

    def test_ambiguous_fold_is_left_alone(self):
        """同名落在多个赛道时无从判断该归给谁，保持原样比猜错安全。"""
        from app.agents.collector import _fold_sectorless_groups

        groups = {
            "zip::Lending": [{"source": "defillama"}],
            "zip::Gaming": [{"source": "rootdata"}],
            "zip::Unknown": [{"source": "galxe"}],
        }
        assert _fold_sectorless_groups(groups) == groups

    def test_low_score_corroborating_rows_are_loaded_with_their_project(self, tmp_path, monkeypatch):
        """信号补充源分数天然低于分析阈值，只按分数过滤会把它们全部挡在门外。"""
        import json as _json

        from app.collectors.persistence import CollectionRepository
        from app.config import settings
        from app.db import get_connection, init_db

        monkeypatch.setattr(settings, "db_path", str(tmp_path / "corr.db"))
        init_db()
        conn = get_connection()
        rows = [
            ("r-llama", "defillama", "ziplend::Lending", 0.58),
            ("r-cg", "coingecko", "ziplend::Lending", 0.10),  # 低于阈值 0.3
            ("r-other", "coingecko", "other::DeFi", 0.10),  # 无高分同伴，不应被带出
        ]
        for raw_id, source, key, score in rows:
            conn.execute(
                "INSERT INTO raw_projects (raw_id, source_id, dedup_key, raw_data, discovered_at,"
                " processed, discovery_score) VALUES (?, ?, ?, ?, datetime('now'), 0, ?)",
                (raw_id, source, key, _json.dumps({"name": "ZipLend"}), score),
            )
        conn.commit()
        conn.close()

        got = {r["raw_id"] for r in CollectionRepository().get_unprocessed_raw_projects(0.3, 100)}
        assert got == {"r-llama", "r-cg"}


def _source_of(cls, method: str) -> str:
    import inspect

    return inspect.getsource(getattr(cls, method))


class TestSecretsNeverReachClientsOrLogs:
    """SECURITY.md §3.3 / §8.3：密钥不得出现在响应体或日志里。"""

    def test_500_response_does_not_echo_the_exception(self, monkeypatch):
        from fastapi.testclient import TestClient

        from app.main import create_app

        # 模拟 psycopg OperationalError 携带的完整 DSN
        secret = "postgresql://airdrop:P4ssw0rd_PROD@db:5432/airdrop"

        async def boom(**kwargs):
            raise RuntimeError(f"connection failed (dsn={secret})")

        monkeypatch.setattr("app.routers.v1.run.execute_analysis_pipeline", boom)
        with TestClient(create_app(), raise_server_exceptions=False) as client:
            resp = client.post("/api/v1/run", json={"projects": []})
        body = resp.text
        assert "P4ssw0rd_PROD" not in body
        assert "dsn=" not in body

    def test_structlog_redacts_secret_named_fields(self):
        from app.utils.redact import redact_processor

        event = redact_processor(
            None,
            "error",
            {
                "event": "collector.error",
                "api_key": "SUPERSECRET1234567890",
                "authorization": "Bearer abc.def.ghi",
                "twitter_bearer": "AAAA%2F",
                "password": "hunter2",
                "project_id": "p1",
            },
        )
        for field in ("api_key", "authorization", "twitter_bearer", "password"):
            assert event[field] == "***REDACTED***", field
        assert event["project_id"] == "p1", "非密钥字段不应被改写"

    def test_logging_configuration_installs_the_processor(self):
        import structlog

        from app.utils.redact import configure_logging, redact_processor

        configure_logging()
        assert redact_processor in structlog.get_config()["processors"]


class TestProductionConfigCannotBeBypassed:
    """SECURITY.md §4.2：生产环境的安全自检不得被拼写绕过。"""

    @pytest.mark.parametrize("app_env", ["production", "Production", "PRODUCTION", "prod", "production "])
    def test_unsafe_production_config_is_rejected_for_every_spelling(self, app_env):
        with pytest.raises(ValueError, match="不安全的生产配置"):
            Settings(
                _env_file=None,
                app_env=app_env,
                api_key="",
                cors_origins="*",
                cors_credentials=True,
            )

    def test_short_api_key_is_rejected_in_production(self):
        # §4.2 要求 >= 32 字符；原实现只校验非空，一个字符也能过
        with pytest.raises(ValueError, match="API_KEY"):
            Settings(_env_file=None, app_env="production", api_key="x")
        # 合法长度通过（需同时配备 AUTH_TOKEN_SECRET 与非 localhost 的 CORS，
        # 否则会被生产自检拒绝）
        Settings(
            _env_file=None,
            app_env="production",
            api_key="a" * 32,
            auth_token_secret="b" * 48,
            cors_origins="https://app.example.com",
        )

    def test_missing_auth_token_secret_is_rejected_in_production(self):
        """回归：docker-compose 曾漏传 AUTH_TOKEN_SECRET，导致容器 CrashLoop。

        这条自检本身是对的（宁可不启动也不要签名密钥每次重启就变），此处锁死
        它的存在，避免有人为了"让容器起来"而把校验删掉。
        """
        with pytest.raises(ValueError, match="AUTH_TOKEN_SECRET"):
            Settings(
                _env_file=None,
                app_env="production",
                api_key="a" * 32,
                auth_token_secret="",
                cors_origins="https://app.example.com",
            )


class TestProductionRejectsWeakDatabasePasswords:
    """生产环境 PostgreSQL 弱密码必须拒绝启动（2026-09-03 补）。

    此前生产自检校验 `API_KEY` 长度、`AUTH_TOKEN_SECRET`、CORS，
    **完全不看 DB 密码**。而 `postgres_password` 的字段默认值就是
    `airdrop_test`，`docker-compose.yml` 的 `:-` 兜底值也是它，
    同一个文件里 `APP_ENV` 默认是 **production** ——
    `docker compose up` + `DB_BACKEND=postgres` 会以生产身份带着一个
    公开写在仓库里的密码静默跑起来，没有任何警告。

    两条激活路径都必须覆盖（见 `_resolve_db_backend`）：分项 `POSTGRES_*`
    组装、或直接给 `DATABASE_URL`。只查字段会漏掉后者，而把密码写在连接串里
    是生产上更常见的配法。
    """

    _BASE: ClassVar[dict[str, str]] = {
        "app_env": "production",
        "api_key": "a" * 40,
        "auth_token_secret": "b" * 48,
        "cors_origins": "https://app.example.com",
    }
    _STRONG = "Xk9mQ2vL7pR4nT8wZ3yB6c"  # 22 位，非弱口令表成员

    def test_sqlite_production_does_not_check_pg_password(self):
        """SQLite 部署不该被 PG 密码规则误伤 —— 那时 POSTGRES_* 完全不参与。

        默认值 `airdrop_test` 仍在字段上，若无条件校验，所有 SQLite 生产部署
        都会启动失败。
        """
        s = Settings(_env_file=None, **self._BASE, db_backend="sqlite")
        assert s.db_backend == "sqlite"

    @pytest.mark.parametrize("weak", ["airdrop_test", "airdrop", "postgres", "changeme", "admin"])
    def test_weak_password_rejected_via_field(self, weak):
        with pytest.raises(ValueError, match=r"弱口令|占位符"):
            Settings(_env_file=None, **self._BASE, db_backend="postgres", postgres_password=weak)

    def test_long_placeholder_is_rejected_even_though_it_passes_length(self):
        """`change-me-in-production` 有 23 位，能过任何长度检查。

        这就是为什么要维护 `_WEAK_DB_PASSWORDS` 而不只看长度 —— 文档模板里的
        占位符属于"看起来配过了但等于没配"。
        """
        with pytest.raises(ValueError, match=r"弱口令|占位符"):
            Settings(
                _env_file=None,
                **self._BASE,
                db_backend="postgres",
                postgres_password="change-me-in-production",
            )

    def test_short_password_rejected(self):
        with pytest.raises(ValueError, match="密码长度"):
            Settings(_env_file=None, **self._BASE, db_backend="postgres", postgres_password="abc123")

    def test_empty_password_rejected(self):
        with pytest.raises(ValueError, match="必须设置密码"):
            Settings(_env_file=None, **self._BASE, db_backend="postgres", postgres_password="")

    def test_strong_password_passes(self):
        s = Settings(_env_file=None, **self._BASE, db_backend="postgres", postgres_password=self._STRONG)
        assert s.db_backend == "postgres"

    def test_weak_password_hidden_in_database_url_is_rejected(self):
        """把弱密码藏在连接串里同样要拦 —— 这是只查字段会漏掉的那条路径。"""
        with pytest.raises(ValueError, match=r"弱口令|占位符"):
            Settings(
                _env_file=None,
                **self._BASE,
                database_url="postgresql://airdrop:airdrop_test@db:5432/airdrop",
            )

    def test_strong_password_in_database_url_passes(self):
        s = Settings(
            _env_file=None,
            **self._BASE,
            database_url=f"postgresql://airdrop:{self._STRONG}@db:5432/airdrop",
        )
        assert s.db_backend == "postgres", "DATABASE_URL 指向 PG 时应反向修正 db_backend"

    def test_percent_encoded_password_is_decoded_before_checking(self):
        """`p%40ss…` 的真实密码是 `p@ss…`，长度与字面值都必须按解码后算。

        手写 `split("@")` 会在这里切错位置（密码里的 `@` 必须百分号编码），
        所以 `_extract_db_password` 用 `urlsplit` + `unquote`。
        """
        s = Settings(
            _env_file=None,
            **self._BASE,
            database_url="postgresql://u:p%40ssword-strong-1@db:5432/d",
        )
        assert s.db_backend == "postgres"
        # 反面：解码后仍是弱口令则照样拒绝
        with pytest.raises(ValueError, match=r"弱口令|占位符"):
            Settings(_env_file=None, **self._BASE, database_url="postgresql://u:airdrop%5Ftest@db:5432/d")

    def test_non_production_keeps_the_weak_default_usable(self):
        """本地开发必须继续开箱可用 —— 闸门只在生产生效。"""
        s = Settings(_env_file=None, app_env="development", db_backend="postgres", postgres_password="airdrop_test")
        assert s.postgres_password == "airdrop_test"

    @pytest.mark.parametrize(
        "origins",
        [
            "http://localhost:3002",
            "http://127.0.0.1:3002",
            "https://app.example.com,http://localhost:3002",
        ],
    )
    def test_localhost_cors_is_rejected_in_production(self, origins):
        """生产环境 CORS 含 localhost/127.0.0.1 必须拒绝启动。

        cors_origins 的默认值就是 localhost，忘配会把真实前端域名全部挡掉，
        表现为"上线后所有接口跨域失败"，除浏览器控制台外几乎无迹可寻。
        """
        with pytest.raises(ValueError, match="CORS_ORIGINS"):
            Settings(
                _env_file=None,
                app_env="production",
                api_key="a" * 32,
                auth_token_secret="b" * 48,
                cors_origins=origins,
            )

    def test_real_domain_cors_passes_in_production(self):
        s = Settings(
            _env_file=None,
            app_env="production",
            api_key="a" * 32,
            auth_token_secret="b" * 48,
            cors_origins="https://app.example.com,https://admin.example.com",
        )
        assert s.cors_origins_list == ["https://app.example.com", "https://admin.example.com"]


class TestRateLimiting:
    """SECURITY.md §4.2 / §10.4：限流配置项此前无人读取。"""

    def test_per_ip_limit_returns_429_with_retry_after(self, monkeypatch):
        from fastapi.testclient import TestClient

        from app.config import settings
        from app.main import create_app

        monkeypatch.setattr(settings, "rate_limit_enabled", True)
        monkeypatch.setattr(settings, "rate_limit_requests", 3)
        monkeypatch.setattr(settings, "rate_limit_window", 60)

        with TestClient(create_app()) as client:
            codes = [client.get("/api/v1/projects").status_code for _ in range(5)]
        assert 429 in codes, f"限流未生效: {codes}"
        with TestClient(create_app()) as client:
            for _ in range(3):
                client.get("/api/v1/projects")
            resp = client.get("/api/v1/projects")
        assert resp.status_code == 429
        assert int(resp.headers["Retry-After"]) >= 1

    def test_health_and_metrics_are_exempt(self, monkeypatch):
        from fastapi.testclient import TestClient

        from app.config import settings
        from app.main import create_app

        monkeypatch.setattr(settings, "rate_limit_enabled", True)
        monkeypatch.setattr(settings, "rate_limit_requests", 2)
        with TestClient(create_app()) as client:
            codes = {client.get("/health").status_code for _ in range(6)}
        assert 429 not in codes, "探针路径被限流会造成健康检查误判"


class TestTrustedProxyCountPicksTheRightHop:
    """`TRUSTED_PROXY_COUNT > 0` 时 `_client_ip` 必须取对那一跳（2026-09-03 补）。

    此前只有 `trusted_proxy_count = 0` 的绕过测试
    （`test_forged_forwarded_for_cannot_evade_the_rate_limit`），
    **N > 0 的取值正确性零覆盖** —— 而生产必须设 N > 0：反代拓扑下
    `request.client.host` 是 nginx 容器 IP，所有外部客户端会共享同一个限流桶
    （100 req/60s 全站共用），要么全被限、要么等于没限流。

    索引语义（`parts[-trusted]`）的推导，基于本仓 nginx.conf 用的
    `$proxy_add_x_forwarded_for` = 客户端自带 XFF + "," + `$remote_addr`：

    - 1 层（nginx → web）：XFF 末位是 nginx 看到的对端，即真实客户端 → `parts[-1]`
    - 2 层（TLS 反代 → nginx → web）：外层追加真实客户端、nginx 再追加反代 IP，
      末位是反代 IP、倒数第二位才是客户端 → `parts[-2]`

    数错一位的后果是静默的：取到反代 IP 就退化成全站共用一个桶，取到客户端
    自带的伪造段就等于没限流。两种都不报错，所以必须有测试钉住。
    """

    def _ip(self, monkeypatch, trusted, forwarded, peer="203.0.113.9"):
        from starlette.requests import Request

        from app.config import settings
        from app.rate_limit import _client_ip

        monkeypatch.setattr(settings, "trusted_proxy_count", trusted)
        headers = []
        if forwarded is not None:
            headers.append((b"x-forwarded-for", forwarded.encode()))
        scope = {
            "type": "http",
            "headers": headers,
            "client": (peer, 12345) if peer else None,
        }
        return _client_ip(Request(scope))

    def test_one_proxy_layer_takes_the_last_hop(self, monkeypatch):
        """1 层反代：末位是 nginx 看到的真实客户端。"""
        assert self._ip(monkeypatch, 1, "198.51.100.7") == "198.51.100.7"

    def test_one_layer_ignores_client_supplied_prefix(self, monkeypatch):
        """客户端伪造的前缀段必须被忽略 —— 这是 trusted_proxy_count 的全部意义。"""
        got = self._ip(monkeypatch, 1, "1.2.3.4, 5.6.7.8, 198.51.100.7")
        assert got == "198.51.100.7", f"取到了可伪造的段：{got}"

    def test_two_proxy_layers_take_the_second_to_last_hop(self, monkeypatch):
        """2 层反代：末位是内层反代 IP，客户端在倒数第二位。"""
        got = self._ip(monkeypatch, 2, "9.9.9.9, 198.51.100.7, 10.0.0.2")
        assert got == "198.51.100.7", f"数错了跳数：{got}"

    def test_falls_back_to_peer_when_header_is_missing(self, monkeypatch):
        """配了 N 但请求没带 XFF（比如直连绕过反代）→ 退回真实对端，不能崩。"""
        assert self._ip(monkeypatch, 1, None, peer="203.0.113.9") == "203.0.113.9"

    def test_falls_back_when_chain_is_shorter_than_configured(self, monkeypatch):
        """链比配置的层数短 → 退回对端，而不是索引越界或取到伪造段。

        这种情况意味着请求没走完预期的代理链（配置错了或有人直连内网端口）。
        退回对端是安全的一侧：宁可把同一反代的请求归到一个桶，也不能采信短链里
        客户端可控的那一段。
        """
        assert self._ip(monkeypatch, 3, "1.2.3.4, 5.6.7.8", peer="203.0.113.9") == "203.0.113.9"

    def test_zero_never_reads_the_header(self, monkeypatch):
        """N=0（默认）时完全不看 XFF —— 与既有的绕过测试同源，这里钉的是取值。"""
        assert self._ip(monkeypatch, 0, "1.2.3.4", peer="203.0.113.9") == "203.0.113.9"

    def test_unknown_when_there_is_no_peer_either(self, monkeypatch):
        """连对端都取不到时返回 "unknown"，不能抛 AttributeError 把请求打挂。"""
        assert self._ip(monkeypatch, 0, None, peer=None) == "unknown"


class TestInputBounds:
    """SECURITY.md §5.1：入参必须有取值域与长度上限。"""

    def test_oversized_feedback_note_is_rejected(self):
        from fastapi.testclient import TestClient

        from app.main import create_app

        with TestClient(create_app()) as client:
            resp = client.post(
                "/api/v1/feedback",
                json={"project_id": "p1", "signal": "useful", "note": "x" * 100_000},
            )
        assert resp.status_code == 422, "20MB 的 note 此前会原样落库"

    def test_invalid_feedback_signal_is_rejected(self):
        from fastapi.testclient import TestClient

        from app.main import create_app

        with TestClient(create_app()) as client:
            resp = client.post("/api/v1/feedback", json={"project_id": "p1", "signal": "NOT_A_SIGNAL'--"})
        assert resp.status_code == 422

    def test_nan_funding_is_rejected_before_it_reaches_meta(self):
        from pydantic import ValidationError

        from app.routers.v1.funding import FundingUpdate

        # 此前 NaN 会先写进 projects.meta（字面量 NaN，非法 JSON），再以 500 报错
        with pytest.raises(ValidationError):
            FundingUpdate(funding_total_usd=float("nan"))
        with pytest.raises(ValidationError):
            FundingUpdate(funding_total_usd=float("inf"))


class TestAdversarialRound4Findings:
    """对抗式复核在本轮改动里抓到的缺陷，逐条锁死。"""

    def test_defillama_dash_symbol_means_no_token(self):
        """DefiLlama 用 "-" 表示"该协议无代币"；当成 ticker 会让采集量塌掉。"""
        from app.collectors.defillama import DefiLlamaCollector

        collector = DefiLlamaCollector()
        # 真实库 1040 条里 658 条 symbol == "-"，误判会让 _filter_candidates 从 934 掉到 2
        assert collector._is_unlisted({"symbol": "-", "gecko_id": None}) is True
        assert collector._is_unlisted({"symbol": "AAVE", "gecko_id": None}) is False

    def test_no_token_inference_agrees_between_collector_and_agent(self):
        """两处口径必须一致，否则回填/重算写出的 no_token_yet 与采集时相反。"""
        from app.agents.collector import CollectorAgent
        from app.collectors.defillama import DefiLlamaCollector

        collector = DefiLlamaCollector()
        for payload in (
            {"symbol": "-", "gecko_id": None},
            {"symbol": "AAVE", "gecko_id": None},
            {"symbol": None, "gecko_id": "aave"},
            {"symbol": "", "gecko_id": None},
        ):
            flags = CollectorAgent._infer_airdrop_flags("defillama", payload)
            assert flags["no_token_yet"] is collector._is_unlisted(payload), payload

    def test_corroborating_rows_survive_the_project_limit(self, tmp_path, monkeypatch):
        """佐证记录排在结果末尾；按行数截断会让它们永远到不了合并。"""
        import json as _json

        from app.agents.collector import CollectorAgent
        from app.collectors.persistence import CollectionRepository
        from app.config import settings
        from app.db import get_connection, init_db

        monkeypatch.setattr(settings, "db_path", str(tmp_path / "corr_limit.db"))
        init_db()
        conn = get_connection()
        # 3 个过线项目 + 1 条属于第一个项目的低分佐证；limit=3 时佐证仍须进入合并
        for i in range(3):
            conn.execute(
                "INSERT INTO raw_projects (raw_id, source_id, dedup_key, raw_data, discovered_at,"
                " processed, discovery_score) VALUES (?, 'defillama', ?, ?, datetime('now'), 0, ?)",
                (f"p{i}", f"proj{i}::L2", _json.dumps({"name": f"Proj{i}", "sector": "L2"}), 0.9 - i * 0.1),
            )
        conn.execute(
            "INSERT INTO raw_projects (raw_id, source_id, dedup_key, raw_data, discovered_at,"
            " processed, discovery_score) VALUES ('cg', 'coingecko', 'proj0::L2', ?, datetime('now'), 0, 0.10)",
            (_json.dumps({"name": "Proj0", "sector": "L2", "has_contract": True}),),
        )
        conn.commit()
        conn.close()

        projects = CollectorAgent().collect_from_repository(CollectionRepository(), 0.3, limit=3)
        assert len(projects) == 3
        target = next(p for p in projects if p.name == "Proj0")
        assert int(target.source_count or 1) >= 2, "低分佐证记录被 limit 截断了"

    def test_merge_tolerates_mixed_naive_and_aware_timestamps(self):
        """一条裸时间戳不得中断整批采集（min() 会抛 TypeError）。"""
        from datetime import UTC, datetime

        from app.utils.normalize import merge_raw_records

        merged = merge_raw_records(
            [
                {"source": "defillama", "name": "X", "discovered_at": datetime(2026, 1, 2, tzinfo=UTC)},
                {"source": "coingecko", "name": "X", "discovered_at": datetime(2026, 1, 1)},
            ]
        )
        assert merged["discovered_at"] is not None

    def test_redaction_reaches_nested_containers_and_tracebacks(self):
        from app.config import settings
        from app.utils.redact import redact_processor

        settings.etherscan_api_key = "SECRET_ETHERSCAN_KEY_123456"
        event = redact_processor(
            None,
            "error",
            {
                "context": {"api_key": "SECRET_ETHERSCAN_KEY_123456"},
                "urls": ["https://x/?api_key=SECRET_ETHERSCAN_KEY_123456"],
                "exception": "Traceback ... SECRET_ETHERSCAN_KEY_123456 ...",
            },
        )
        assert event["context"]["api_key"] == "***REDACTED***"
        assert "SECRET_ETHERSCAN_KEY_123456" not in event["urls"][0]
        assert "SECRET_ETHERSCAN_KEY_123456" not in event["exception"]

    def test_redaction_runs_after_exception_rendering(self):
        """traceback 是 format_exc_info 那一步才生成的；排在它之前等于没脱敏。"""
        import structlog

        from app.utils.redact import configure_logging

        configure_logging()
        names = [getattr(p, "__name__", type(p).__name__) for p in structlog.get_config()["processors"]]
        exc_idx = next(i for i, n in enumerate(names) if "Exception" in n or n == "format_exc_info")
        assert names.index("redact_processor") > exc_idx

    def test_forged_forwarded_for_cannot_evade_the_rate_limit(self, monkeypatch):
        """nginx 用 $proxy_add_x_forwarded_for 会前置客户端自带值，取首段等于采信攻击者输入。"""
        from fastapi.testclient import TestClient

        from app.config import settings
        from app.main import create_app

        monkeypatch.setattr(settings, "rate_limit_enabled", True)
        monkeypatch.setattr(settings, "rate_limit_requests", 3)
        monkeypatch.setattr(settings, "trusted_proxy_count", 0)

        with TestClient(create_app()) as client:
            codes = [
                client.get("/api/v1/projects", headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code for i in range(8)
            ]
        assert 429 in codes, f"伪造 X-Forwarded-For 绕过了限流: {codes}"

    def test_global_rejection_does_not_burn_the_expensive_quota(self, monkeypatch):
        """被全局配额拒绝的 /run 不该已经扣掉"每小时 1 次"的令牌。"""
        from app.config import settings
        from app.rate_limit import RateLimitMiddleware

        monkeypatch.setattr(settings, "rate_limit_enabled", True)
        monkeypatch.setattr(settings, "rate_limit_requests", 1)
        monkeypatch.setattr(settings, "rate_limit_window", 60)

        mw = RateLimitMiddleware(app=None)
        # 先用掉全局配额
        assert mw._windows.check("ip", 1, 60.0, 100.0) is None
        # 此时 /run 的昂贵端点桶必须还是空的
        assert "ip:/api/v1/run" not in mw._windows._hits

    def test_log_level_setting_actually_filters_structlog_output(self, tmp_path, monkeypatch):
        """`LOG_LEVEL` 必须真的压掉低级别日志，而不是只影响 uvicorn。

        此前 `settings.log_level` 只传给了 `uvicorn.run(log_level=...)`，
        应用自身的 structlog 完全不看它 —— `LOG_LEVEL=WARNING` 下 12 处
        `logger.debug` 照样全量输出。一个"设了但不生效"的开关比没有开关更糟：
        运维以为噪音已经压掉了，实际磁盘和日志后端照旧被灌满。
        """
        import json

        import structlog

        from app.config import settings
        from app.utils.redact import configure_logging

        def emit(level_name: str) -> list[str]:
            log_file = tmp_path / f"{level_name or 'empty'}.jsonl"
            monkeypatch.setattr(settings, "log_level", level_name)
            monkeypatch.setattr(settings, "log_file", str(log_file))
            structlog.reset_defaults()
            configure_logging()
            log = structlog.get_logger("levelprobe")
            log.debug("probe.debug")
            log.info("probe.info")
            log.warning("probe.warning")
            log.error("probe.error")
            for stream in structlog.get_config()["logger_factory"]._file._streams:
                stream.flush()
            if not log_file.exists():
                return []
            return [json.loads(line)["level"] for line in log_file.read_text(encoding="utf-8").splitlines() if line]

        try:
            assert emit("DEBUG") == ["debug", "info", "warning", "error"]
            assert emit("WARNING") == ["warning", "error"], "LOG_LEVEL=WARNING 未压掉 debug/info"
            assert emit("ERROR") == ["error"], "LOG_LEVEL=ERROR 未压掉 warning"
            # `warn` 是 `warning` 的常见别名，不能被当成非法值
            assert emit("warn") == ["warning", "error"]
            # 非法值/留空必须退回 INFO，**不能**降级成 DEBUG ——
            # "配置写错反而把全部 debug 日志放出来"是必须避免的方向。
            assert emit("BOGUS") == ["info", "warning", "error"], "非法 LOG_LEVEL 未退回 INFO"
            assert emit("") == ["info", "warning", "error"], "空 LOG_LEVEL 未退回 INFO"
        finally:
            # 先把 log_file 清空再重装：否则最后一次 configure_logging() 会重新
            # 打开 tmp_path 下的文件，而 tmp_path 随即被清理，留下悬空句柄。
            monkeypatch.setattr(settings, "log_file", "")
            monkeypatch.setattr(settings, "log_level", "INFO")
            structlog.reset_defaults()
            configure_logging()

    def test_reconfiguring_logging_does_not_leak_the_log_file_handle(self, tmp_path, monkeypatch):
        """`configure_logging()` 号称幂等可重复调用，就不能每次都漏一个文件句柄。

        原实现每次调用都 `open()` 一个新的日志文件，旧句柄既不关闭也不再被引用 ——
        只能等 GC 回收，届时 CPython 抛 ResourceWarning。CI 把 ResourceWarning
        当错误，于是这个泄漏会以"某个**无关**测试莫名失败"的形式暴露出来：
        泄漏发生在 A，报错记在恰好触发 GC 的 B 身上。这类错位归因极难排查，
        所以必须在源头钉住。
        """
        import gc
        import warnings

        import structlog

        from app.config import settings
        from app.utils.redact import configure_logging

        log_file = tmp_path / "leak-probe.jsonl"
        monkeypatch.setattr(settings, "log_file", str(log_file))
        monkeypatch.setattr(settings, "log_level", "INFO")

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", ResourceWarning)
                for _ in range(5):
                    structlog.reset_defaults()
                    configure_logging()
                    # 强制回收：若上一轮的句柄真被丢弃了，这里就会抛 ResourceWarning
                    gc.collect()
        finally:
            monkeypatch.setattr(settings, "log_file", "")
            structlog.reset_defaults()
            configure_logging()
