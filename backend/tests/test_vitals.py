"""Tests for site liveness probing (vitals).

背景（2026-09-08）：评分系统只查了项目和数据层的证据，从不关心
「这个项目的官网还能不能打开」。Goose 这类僵尸项目的官网域名往往
早已过期或停服，而系统上根本没有人探过 —— 这个信号很容易拿到，
比第三方 API 诚实得多，所以走强起量。

设计约束：
- site_alive=False 只在真的「打出去过」后写，区分得出「没探测过」（None）
- 状态变化才写库（防止两次探测结果相同却每次刷新 updated_at、
  顺便把 AI 简报缓存的新鲜度判定冲掉）。
- 首连状态必须落史（site_http_status），诊断用。
"""

from __future__ import annotations

import sqlite3
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.agents.base import AgentContext, PipelineState, RawProject
from app.db import init_db
from app.repository import ProjectRepository
from app.services.vitals import probe_site, run_vitals_probe


def _make_client(status_code: int | None, error: Exception | None = None):
    """构造假的 httpx.AsyncClient：给定状态码或直接抛错。

    真实网络在测试里不稳定且违反无尘室原则 —— 探测要么 mock 要么禁走。
    """

    class FakeResp:
        def __init__(self, code: int) -> None:
            self.status_code = code

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def head(self, url, **kw):
            if error:
                raise error
            return FakeResp(status_code or 200)

        async def get(self, url, **kw):
            if error:
                raise error
            return FakeResp(status_code or 200)

    return FakeClient()


class TestProbeSite:
    @pytest.mark.asyncio
    async def test_ok_status_marks_alive(self):
        with patch("httpx.AsyncClient", return_value=_make_client(200)):
            verdict, status = await probe_site("https://ok.example")
        assert verdict == "ok"
        assert status == 200

    @pytest.mark.asyncio
    async def test_404_marks_down(self):
        with patch("httpx.AsyncClient", return_value=_make_client(404)):
            verdict, status = await probe_site("https://dead.example")
        assert verdict == "dead"
        assert status == 404

    @pytest.mark.asyncio
    async def test_timeout_marks_down_without_status(self):
        with patch(
            "httpx.AsyncClient",
            return_value=_make_client(None, error=httpx.ConnectTimeout("timed out")),
        ):
            verdict, status = await probe_site("https://stuck.example")
        assert verdict == "unknown"
        assert status is None

    @pytest.mark.asyncio
    async def test_head_405_falls_back_to_get(self):
        """405 Method Not Allowed（HEAD 不支持）应落到 GET，不能顺手判死。"""

        class FallbackClient:
            def __init__(self):
                self.calls = []

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def head(self, url, **kw):
                self.calls.append("HEAD")
                class Resp:
                    status_code = 405
                return Resp()

            async def get(self, url, **kw):
                self.calls.append("GET")
                class Resp:
                    status_code = 200
                return Resp()

        with patch("httpx.AsyncClient", return_value=FallbackClient()):
            verdict, status = await probe_site("https://headless.example")
        assert verdict == "ok"
        assert status == 200


def _save_project(repo: ProjectRepository, pid: str, url: str | None) -> None:
    repo.save(
        PipelineState(
            project=RawProject(
                id=pid,
                name=f"P-{pid}",
                url=url,
                sector="DeFi",
                stage="mainnet",
                source="test",
                no_token_yet=True,
                created_at=None,
            ),
            context=AgentContext(run_id="r"),
            score=70,
            label="WATCH",
            confidence=0.6,
            reason=[],
        )
    )


@pytest.mark.asyncio
class TestRunVitalsProbe:
    async def test_writes_signals_and_skips_url_less(self, tmp_path):
        ok = {"https://a.example": ("ok", 200), "https://b.example": ("dead", 404)}
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)
        try:
            repo = ProjectRepository(conn)
            _save_project(repo, "a", "https://a.example")
            _save_project(repo, "b", "https://b.example")
            _save_project(repo, "c", None)  # 没有官网：不该被探

            with patch("app.services.vitals.probe_site", new_callable=AsyncMock) as probe:
                probe.side_effect = lambda url: ok.get(url, (False, None))
                stats = await run_vitals_probe(repo=repo)

            assert stats["probed"] == 2
            assert stats["down"] == 1
            assert stats["skipped_no_url"] == 1

            a = dict(repo.get_by_id("a"))
            import json
            sa = json.loads(a["meta"]).get("signals", {})
            assert sa.get("site_alive") is True
            assert sa.get("site_http_status") == 200
            assert sa.get("site_checked_at")

            b = dict(repo.get_by_id("b"))
            sb = json.loads(b["meta"]).get("signals", {})
            assert sb.get("site_alive") is False
            assert sb.get("site_http_status") == 404
        finally:
            conn.close()

    async def test_unchanged_state_is_not_rewritten(self, tmp_path):
        """Gecko 状态没变就不重写：防止每次探测都把 updated_at 推高，
        顺带冲掉 AI 简报缓存的新鲜度（updated_at > generated_at → 报错）。"""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)
        try:
            repo = ProjectRepository(conn)
            _save_project(repo, "a", "https://a.example")

            with patch("app.services.vitals.probe_site", new_callable=AsyncMock) as probe:
                probe.return_value = ("ok", 200)
                await run_vitals_probe(repo=repo)

            before = dict(repo.get_by_id("a"))["updated_at"]
            with patch("app.services.vitals.probe_site", new_callable=AsyncMock) as probe:
                probe.return_value = ("ok", 200)
                stats = await run_vitals_probe(repo=repo)
                assert stats["changed"] == 0, "状态没变就不该重写"

            after = dict(repo.get_by_id("a"))["updated_at"]
            assert after == before
        finally:
            conn.close()
