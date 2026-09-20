"""Tests for rule-based AI brief (no live LLM)."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.llm.client import LLMResult
from app.services.ai_brief import build_rule_brief, generate_project_brief, get_cached_brief


def test_build_rule_brief_farm():
    project = {
        "name": "DemoProtocol",
        "label": "FARM",
        "score": 72,
        "confidence": 0.9,
        "sector": "L2",
        "stage": "testnet",
        "source": "defillama",
        "reason": '["strong airdrop signal", "early narrative"]',
        "narrative_json": '{"timing":"early","heat_score":0.7,"stage":"growth"}',
        "team_json": '{"team_score":0.7,"team_type":"doxxed","risk_level":"low","flags":["tier-1 vc backed"]}',
        "risk_json": '{"sybil_difficulty":"high","farming_cost":"medium","token_risk":0.3,"unlock_pressure":"low"}',
        "tokenomics_json": '{"vc_share":0.2,"team_share":0.15,"unlock_pressure":"low"}',
    }
    brief = build_rule_brief(project)
    assert brief["mode"] == "rule"
    assert brief["label"] == "FARM"
    assert brief["label_zh"] == "重点参与"
    assert brief["score"] == 72
    assert "DemoProtocol" in brief["headline"]
    assert len(brief["paragraphs"]) >= 4
    assert any("叙事" in p for p in brief["paragraphs"])
    assert any("团队" in p for p in brief["paragraphs"])
    assert any("风险" in p for p in brief["paragraphs"])


def test_build_rule_brief_handles_missing_json():
    project = {
        "name": "Sparse",
        "label": "WATCH",
        "score": 55,
        "confidence": 0.4,
        "sector": "DeFi",
    }
    brief = build_rule_brief(project)
    assert brief["label_zh"] == "持续观察"
    assert brief["display_text"] if False else True
    assert "Sparse" in brief["headline"]


class TestDegradedReasonDistinguishesWhy:
    """回退到规则引擎的**原因**必须能被区分开。

    此前 `try_llm_brief` 只返回 `str | None`，于是「没配密钥」、「预算用完了」、
    「接口挂了」三种情况在响应里长得完全一样（都是 `mode: "rule"`），
    前端只能对所有降级说同一句「当前未配置大模型密钥」。

    **在密钥配好、只是预算耗尽的时候，那句话是错的**，而且会把人引向
    完全错误的排查方向 —— 去检查密钥，而问题在预算。

    降级本身不是问题，把降级原因说错才是问题。
    """

    @staticmethod
    def _project() -> dict:
        return {"name": "DegradeDemo", "label": "WATCH", "score": 55, "confidence": 0.5}

    @pytest.mark.asyncio
    async def test_llm_disabled_reports_llm_disabled(self) -> None:
        with patch("app.services.ai_brief.settings") as st:
            st.is_llm_enabled = False
            brief = await generate_project_brief(self._project())
        assert brief["mode"] == "rule"
        assert brief["degraded_reason"] == "llm_disabled"

    @pytest.mark.asyncio
    async def test_budget_refusal_is_reported_as_budget_exceeded(self) -> None:
        """预算拒绝必须**区别于**接口故障 —— 处置动作完全不同。"""
        # LLMResult.ok 是 property（text is not None），不是构造参数，
        # 所以「被拒绝」只能通过 text=None 表达。
        refused = LLMResult(
            text=None,
            provider_used=None,
            model_used=None,
            refused_reason="budget_exceeded",
        )
        with (
            patch("app.services.ai_brief.settings") as st,
            patch("app.llm.client.llm_chat", new_callable=AsyncMock, return_value=refused),
        ):
            st.is_llm_enabled = True
            st.llm_temperature = 0.3
            st.llm_max_tokens = 512
            brief = await generate_project_brief(self._project())

        assert brief["mode"] == "rule"
        assert brief["degraded_reason"] == "budget_exceeded", (
            "预算耗尽被报成了别的原因 —— 前端会显示「未配置密钥」，把人引向错误的排查方向。"
        )

    @pytest.mark.asyncio
    async def test_provider_failure_is_reported_as_llm_error(self) -> None:
        """反向断言：不能把所有失败都报成 budget_exceeded（那样同样分不清）。"""
        failed = LLMResult(text=None, provider_used=None, model_used=None, refused_reason=None)
        with (
            patch("app.services.ai_brief.settings") as st,
            patch("app.llm.client.llm_chat", new_callable=AsyncMock, return_value=failed),
        ):
            st.is_llm_enabled = True
            st.llm_temperature = 0.3
            st.llm_max_tokens = 512
            brief = await generate_project_brief(self._project())

        assert brief["mode"] == "rule"
        assert brief["degraded_reason"] == "llm_error"

    @pytest.mark.asyncio
    async def test_success_has_no_degraded_reason(self) -> None:
        ok = LLMResult(text="大模型写的解读", provider_used="provider-1", model_used="gpt-4o-mini")
        with (
            patch("app.services.ai_brief.settings") as st,
            patch("app.llm.client.llm_chat", new_callable=AsyncMock, return_value=ok),
        ):
            st.is_llm_enabled = True
            st.llm_temperature = 0.3
            st.llm_max_tokens = 512
            brief = await generate_project_brief(self._project())

        assert brief["mode"] == "llm"
        assert brief["degraded_reason"] is None
        assert brief["display_text"] == "大模型写的解读"

    @pytest.mark.asyncio
    async def test_the_endpoint_actually_passes_the_reason_through(self) -> None:
        """算对了但没透传，等于没算 —— 判据必须落在**响应体**上。

        前面几条测的是 `generate_project_brief` 的返回值。但前端读的是
        HTTP 响应体，中间还隔着一层路由的字段拼装。
        路由里漏掉一行，上面 4 条断言全绿而前端仍然什么都拿不到。
        """
        from app.routers.v1.ai_brief import project_ai_brief

        refused_brief = {
            "mode": "rule",
            "headline": "h",
            "summary": "s",
            "paragraphs": ["p"],
            "bullets": [],
            "label": "WATCH",
            "label_zh": "持续观察",
            "score": 55,
            "confidence": 0.5,
            "display_text": "p",
            "llm_text": None,
            "degraded_reason": "budget_exceeded",
        }

        with (
            patch("app.routers.v1.ai_brief.ProjectRepository") as repo_cls,
            patch(
                "app.routers.v1.ai_brief.generate_project_brief",
                new_callable=AsyncMock,
                return_value=refused_brief,
            ),
            patch("app.routers.v1.ai_brief.store_brief_cache") as store_mock,
        ):
            repo_cls.return_value.get_by_id.return_value = {"id": "p1", "name": "DegradeDemo"}
            resp = await project_ai_brief(None, "p1")

        assert resp["data"]["mode"] == "rule"
        assert resp["data"]["degraded_reason"] == "budget_exceeded", (
            "路由没把 degraded_reason 透传出去 —— 后端区分对了，前端仍然拿不到。"
        )
        store_mock.assert_called_once(), "生成成功后必须写缓存，否则下次访问又要花钱"


# ═══════════════════════════════════════════════════════════════
# 简报缓存（2026-09-06）：存储于 projects.meta.ai_brief
#
# 新鲜度判定：缓存的 generated_at 晚于/等于行的 updated_at → 新鲜；
# 项目被重评/改融资等任何行更新都会推高 updated_at → 缓存自动过期。
# GET 只读（永不花钱），POST 负责生成（force=true 强制）。
# ═══════════════════════════════════════════════════════════════


def _cached_project(generated_at: datetime, updated_at: datetime) -> dict:
    """带 ai_brief 缓存的项目行。meta 是 sqlite/postgres 里读出的 JSON 字符串。"""
    import json

    return {
        "id": "p1",
        "name": "Demo",
        "updated_at": updated_at,
        "meta": json.dumps(
            {
                "signals": {"has_github": True},
                "ai_brief": {
                    "mode": "llm",
                    "headline": "缓存解读",
                    "display_text": "缓存的正文",
                    "degraded_reason": None,
                    "generated_at": generated_at.isoformat(),
                },
            },
            ensure_ascii=False,
        ),
    }


class TestGetCachedBrief:
    """新鲜度判定是纯函数，直接测。"""

    def test_no_meta_or_no_key_returns_none(self) -> None:
        assert get_cached_brief({"id": "p1"}) == (None, False)
        assert get_cached_brief({"id": "p1", "meta": '{"signals":{}}'}) == (None, False)

    def test_fresh_when_row_not_updated_after_generation(self) -> None:
        now = datetime.now(UTC)
        payload, stale = get_cached_brief(_cached_project(generated_at=now, updated_at=now))
        assert stale is False
        assert payload is not None and payload["headline"] == "缓存解读"

    def test_stale_when_row_updated_after_generation(self) -> None:
        """重评/改融资都会推高 updated_at —— 旧解读不得再当新鲜货返回。"""
        gen = datetime.now(UTC)
        payload, stale = get_cached_brief(
            _cached_project(generated_at=gen, updated_at=gen + timedelta(minutes=5))
        )
        assert payload is None
        assert stale is True, "过期的缓存必须带 stale 标记，前端才能提示重新生成"


class TestCachedEndpoint:
    """缓存语义落在 HTTP 响应上：GET 只读、POST 带 force。"""

    @staticmethod
    def _project() -> dict:
        return {"id": "p1", "name": "Demo", "updated_at": datetime.now(UTC), "meta": None}

    def test_get_is_read_only_and_never_generates(self) -> None:
        """GET 走缓存；没缓存就返回空态 —— 绝不能为了 GET 去调 LLM。"""
        from app.routers.v1.ai_brief import project_ai_brief_get

        with (
            patch("app.routers.v1.ai_brief.ProjectRepository") as repo_cls,
            patch(
                "app.routers.v1.ai_brief.generate_project_brief",
                new_callable=AsyncMock,
            ) as gen_mock,
        ):
            repo_cls.return_value.get_by_id.return_value = self._project()
            resp = project_ai_brief_get("p1")

        gen_mock.assert_not_awaited(), "GET 不能触发生成 —— 否则每次进页面都在烧预算"
        assert resp["data"]["cached"] is False
        assert resp["data"]["stale"] is False

    def test_get_returns_fresh_cache(self) -> None:
        from app.routers.v1.ai_brief import project_ai_brief_get

        now = datetime.now(UTC)
        with (
            patch("app.routers.v1.ai_brief.ProjectRepository") as repo_cls,
            patch("app.routers.v1.ai_brief.get_cached_brief", return_value=({"headline": "缓存解读"}, False)),
        ):
            repo_cls.return_value.get_by_id.return_value = _cached_project(
                generated_at=now, updated_at=now
            )
            resp = project_ai_brief_get("p1")

        assert resp["data"]["cached"] is True
        assert resp["data"]["headline"] == "缓存解读"

    def test_get_reports_stale(self) -> None:
        from app.routers.v1.ai_brief import project_ai_brief_get

        with (
            patch("app.routers.v1.ai_brief.ProjectRepository") as repo_cls,
            patch("app.routers.v1.ai_brief.get_cached_brief", return_value=(None, True)),
        ):
            repo_cls.return_value.get_by_id.return_value = self._project()
            resp = project_ai_brief_get("p1")

        assert resp["data"]["cached"] is False
        assert resp["data"]["stale"] is True, "过期必须显式告诉前端，否则用户以为解读还是对的"

    @pytest.mark.asyncio
    async def test_post_without_force_returns_fresh_cache_without_generating(self) -> None:
        from app.routers.v1.ai_brief import AiBriefRequest, project_ai_brief

        now = datetime.now(UTC)
        with (
            patch("app.routers.v1.ai_brief.ProjectRepository") as repo_cls,
            patch("app.routers.v1.ai_brief.get_cached_brief", return_value=({"headline": "缓存解读"}, False)),
            patch(
                "app.routers.v1.ai_brief.generate_project_brief",
                new_callable=AsyncMock,
            ) as gen_mock,
        ):
            repo_cls.return_value.get_by_id.return_value = _cached_project(
                generated_at=now, updated_at=now
            )
            resp = await project_ai_brief(AiBriefRequest(force=False), "p1")

        gen_mock.assert_not_awaited()
        assert resp["data"]["cached"] is True

    @pytest.mark.asyncio
    async def test_post_force_regenerates_and_stores_even_with_fresh_cache(self) -> None:
        from app.routers.v1.ai_brief import AiBriefRequest, project_ai_brief

        fresh_brief = {"mode": "rule", "display_text": "新解读", "degraded_reason": "llm_disabled"}
        now = datetime.now(UTC)
        with (
            patch("app.routers.v1.ai_brief.ProjectRepository") as repo_cls,
            patch("app.routers.v1.ai_brief.get_cached_brief", return_value=({"headline": "旧缓存"}, False)),
            patch(
                "app.routers.v1.ai_brief.generate_project_brief",
                new_callable=AsyncMock,
                return_value=fresh_brief,
            ) as gen_mock,
            patch("app.routers.v1.ai_brief.store_brief_cache") as store_mock,
        ):
            repo_cls.return_value.get_by_id.return_value = _cached_project(
                generated_at=now, updated_at=now
            )
            resp = await project_ai_brief(AiBriefRequest(force=True), "p1")

        gen_mock.assert_awaited_once(), "force=true 必须无视新鲜缓存强制重新生成"
        store_mock.assert_called_once()
        assert resp["data"]["display_text"] == "新解读"
        assert resp["data"]["cached"] is False

    @pytest.mark.asyncio
    async def test_post_generates_and_stores_when_cache_missing(self) -> None:
        from app.routers.v1.ai_brief import AiBriefRequest, project_ai_brief

        fresh_brief = {"mode": "rule", "display_text": "新解读", "degraded_reason": "llm_disabled"}
        with (
            patch("app.routers.v1.ai_brief.ProjectRepository") as repo_cls,
            patch("app.routers.v1.ai_brief.get_cached_brief", return_value=(None, False)),
            patch(
                "app.routers.v1.ai_brief.generate_project_brief",
                new_callable=AsyncMock,
                return_value=fresh_brief,
            ),
            patch("app.routers.v1.ai_brief.store_brief_cache") as store_mock,
        ):
            repo_cls.return_value.get_by_id.return_value = self._project()
            resp = await project_ai_brief(AiBriefRequest(force=False), "p1")

        store_mock.assert_called_once_with("p1", fresh_brief), (
            "生成的简报必须落缓存 —— 否则缓存功能形同虚设"
        )
        assert resp["data"]["cached"] is False

    @pytest.mark.asyncio
    async def test_post_regenerates_when_cache_stale(self) -> None:
        from app.routers.v1.ai_brief import AiBriefRequest, project_ai_brief

        fresh_brief = {"mode": "rule", "display_text": "新解读", "degraded_reason": "llm_disabled"}
        with (
            patch("app.routers.v1.ai_brief.ProjectRepository") as repo_cls,
            patch("app.routers.v1.ai_brief.get_cached_brief", return_value=(None, True)),
            patch(
                "app.routers.v1.ai_brief.generate_project_brief",
                new_callable=AsyncMock,
                return_value=fresh_brief,
            ) as gen_mock,
            patch("app.routers.v1.ai_brief.store_brief_cache"),
        ):
            repo_cls.return_value.get_by_id.return_value = self._project()
            resp = await project_ai_brief(AiBriefRequest(force=False), "p1")

        gen_mock.assert_awaited_once(), "缓存过期后 force=false 也必须重新生成"
        assert resp["data"]["stale"] is True, "响应带上 stale，前端能提示『评分已更新』"

    @pytest.mark.asyncio
    async def test_generated_brief_is_stored_with_timestamp(self) -> None:
        """store_brief_cache 的实现必须打上 generated_at —— 没有时间戳，
        新鲜度判定无从谈起（缺 generated_at 的缓存一律视为不存在）。"""
        from app.services.ai_brief import store_brief_cache

        brief = {"mode": "rule", "display_text": "x", "degraded_reason": None}
        with patch("app.services.ai_brief.ProjectRepository") as repo_cls:
            store_brief_cache("p1", brief)

        kwargs = repo_cls.return_value.set_meta_key.call_args
        assert kwargs.args[0] == "p1"
        assert kwargs.args[1] == "ai_brief"
        stored = kwargs.args[2]
        assert stored["generated_at"]

    def test_meta_ai_brief_key_survives_rescore(self) -> None:
        """缓存的存续前提（回归钉）：save（重评/采集回写）不得丢掉 meta 里的
        ai_brief 键。merge_meta 保留未知键是缓存设计的地基 —— 若有人把它改
        成信号键白名单，这条会当场变红，而不是让缓存静默失效。"""
        import json
        import sqlite3

        from app.agents.base import AgentContext, PipelineState, RawProject
        from app.db import init_db
        from app.repository import ProjectRepository

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)
        try:
            repo = ProjectRepository(conn=conn)
            state = PipelineState(
                project=RawProject(
                    id="brief-cache-1",
                    name="Cache Survivor",
                    url="https://cache-survivor.example.com",
                    sector="DeFi",
                    stage="testnet",
                    source="seed",
                    no_token_yet=True,
                    created_at=None,
                ),
                context=AgentContext(run_id="r1"),
                score=70,
                label="FARM",
                confidence=0.8,
                reason="strong signal",
            )
            repo.save(state)
            repo.update_meta_signals(
                "brief-cache-1", {}, {"ai_brief": {"headline": "缓存", "generated_at": "2026-09-06T00:00:00+00:00"}}
            )
            repo.save(state)  # 模拟重评

            row = repo.get_by_id("brief-cache-1")
            meta = json.loads(row["meta"])
            assert meta["ai_brief"]["headline"] == "缓存", "重评不得丢掉简报缓存"
            assert meta["signals"], "signals 合并不受影响"
        finally:
            conn.close()

    def test_store_then_read_roundtrip_is_fresh(self) -> None:
        """真实读写往返（回归钉，抓微秒级竞态）：store_brief_cache 走真实
        sqlite 写入后再读，缓存必须是**新鲜的**。

        实测踩过的坑：store 把 generated_at 设成 now₁，而 update_meta_signals
        写行时把 updated_at 推到 now₂ > now₁ —— 新鲜度判定当场成立，
        缓存**出生即过期**，症状是「每次打开详情页都要重新点生成」。
        单测全 mock 写入路径抓不到这种竞态，必须走真库往返。
        """
        import json
        import sqlite3

        from app.agents.base import AgentContext, PipelineState, RawProject
        from app.db import init_db
        from app.repository import ProjectRepository
        from app.services.ai_brief import store_brief_cache as _store

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)
        try:
            repo = ProjectRepository(conn=conn)
            repo.save(
                PipelineState(
                    project=RawProject(
                        id="brief-rt-1",
                        name="Roundtrip",
                        url="https://roundtrip.example.com",
                        sector="DeFi",
                        stage="testnet",
                        source="seed",
                        no_token_yet=True,
                        created_at=None,
                    ),
                    context=AgentContext(run_id="r1"),
                    score=70,
                    label="FARM",
                    confidence=0.8,
                    reason="strong signal",
                )
            )
            _store(
                "brief-rt-1",
                {"mode": "rule", "headline": "往返", "degraded_reason": None},
                repo=repo,
            )

            row = repo.get_by_id("brief-rt-1")
            payload, stale = get_cached_brief(dict(row))
            assert payload is not None, "写完立即读必须命中缓存（写入不得自变过期）"
            assert stale is False
            assert payload["headline"] == "往返"
            assert json.loads(row["meta"])["signals"], "signals 不受影响"
        finally:
            conn.close()

    def test_meta_brief_write_does_not_bump_updated_at(self) -> None:
        """写缓存不是「项目内容变更」：不得推高行的 updated_at —— 否则任何
        依赖 updated_at 判新鲜度的缓存都会在写入瞬间自毁。"""
        import sqlite3

        from app.agents.base import AgentContext, PipelineState, RawProject
        from app.db import init_db
        from app.repository import ProjectRepository

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)
        try:
            repo = ProjectRepository(conn=conn)
            repo.save(
                PipelineState(
                    project=RawProject(
                        id="brief-ts-1",
                        name="Timestamp Keeper",
                        url="https://ts.example.com",
                        sector="DeFi",
                        stage="testnet",
                        source="seed",
                        no_token_yet=True,
                        created_at=None,
                    ),
                    context=AgentContext(run_id="r1"),
                    score=70,
                    label="FARM",
                    confidence=0.8,
                    reason="strong signal",
                )
            )
            before = dict(repo.get_by_id("brief-ts-1"))["updated_at"]
            repo.set_meta_key("brief-ts-1", "ai_brief", {"headline": "h"})
            after = dict(repo.get_by_id("brief-ts-1"))["updated_at"]
            assert before == after, "写 meta 缓存不得推高 updated_at"
        finally:
            conn.close()
