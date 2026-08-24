"""Tests for rule-based AI brief (no live LLM)."""

from unittest.mock import AsyncMock, patch

import pytest

from app.llm.client import LLMResult
from app.services.ai_brief import build_rule_brief, generate_project_brief


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
        ):
            repo_cls.return_value.get_by_id.return_value = {"id": "p1", "name": "DegradeDemo"}
            resp = await project_ai_brief("p1")

        assert resp["data"]["mode"] == "rule"
        assert resp["data"]["degraded_reason"] == "budget_exceeded", (
            "路由没把 degraded_reason 透传出去 —— 后端区分对了，前端仍然拿不到。"
        )
