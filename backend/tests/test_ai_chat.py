"""Tests for project AI chat (追问对话) — no live LLM.

与 test_ai_brief.py 同一套约定：service 层测降级语义与上下文构造，
路由层测校验与字段透传。全部 mock `app.llm.client.llm_chat`，不联网。
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.llm.client import LLMResult
from app.routers.v1.ai_chat import AiChatRequest, ChatMessage, project_ai_chat
from app.services.ai_chat import CHAT_MAX_HISTORY_MESSAGES, generate_chat_reply


def _req(*msgs: tuple[str, str]) -> AiChatRequest:
    return AiChatRequest(messages=[ChatMessage(role=r, content=c) for r, c in msgs])


def _project() -> dict:
    return {
        "id": "p1",
        "name": "DemoProtocol",
        "label": "FARM",
        "score": 72,
        "confidence": 0.9,
        "sector": "L2",
        "stage": "testnet",
    }


# ═══════════════════════════════════════════════════════════════
# Service 层
# ═══════════════════════════════════════════════════════════════


class TestGenerateChatReply:
    @pytest.mark.asyncio
    async def test_llm_disabled_reports_llm_disabled(self) -> None:
        """对话没有规则引擎可回退，没配密钥就必须明确说 llm_disabled，
        且**一个字节都不该发给 LLM**。"""
        with (
            patch("app.services.ai_chat.settings") as st,
            patch("app.llm.client.llm_chat", new_callable=AsyncMock) as chat,
        ):
            st.is_llm_enabled = False
            result = await generate_chat_reply(_project(), [{"role": "user", "content": "hi"}])

        assert result["reply"] is None
        assert result["degraded_reason"] == "llm_disabled"
        chat.assert_not_awaited(), "llm_disabled 时不应发起任何 LLM 调用"

    @pytest.mark.asyncio
    async def test_budget_refusal_passthrough(self) -> None:
        """预算拒绝必须原样透传 —— 「预算用完」和「接口挂了」处置动作不同。"""
        refused = LLMResult(
            text=None,
            provider_used=None,
            model_used=None,
            refused_reason="budget_exceeded",
        )
        with (
            patch("app.services.ai_chat.settings") as st,
            patch("app.llm.client.llm_chat", new_callable=AsyncMock, return_value=refused),
        ):
            st.is_llm_enabled = True
            st.llm_temperature = 0.3
            st.llm_max_tokens = 512
            result = await generate_chat_reply(_project(), [{"role": "user", "content": "hi"}])

        assert result["reply"] is None
        assert result["degraded_reason"] == "budget_exceeded"

    @pytest.mark.asyncio
    async def test_empty_text_without_refusal_is_llm_error(self) -> None:
        """text=None 且没有 refused_reason = 接口失败，不能被当成预算问题。"""
        failed = LLMResult(text=None, provider_used=None, model_used=None, refused_reason=None)
        with (
            patch("app.services.ai_chat.settings") as st,
            patch("app.llm.client.llm_chat", new_callable=AsyncMock, return_value=failed),
        ):
            st.is_llm_enabled = True
            st.llm_temperature = 0.3
            st.llm_max_tokens = 512
            result = await generate_chat_reply(_project(), [{"role": "user", "content": "hi"}])

        assert result["reply"] is None
        assert result["degraded_reason"] == "llm_error"

    @pytest.mark.asyncio
    async def test_exception_is_llm_error(self) -> None:
        with (
            patch("app.services.ai_chat.settings") as st,
            patch("app.llm.client.llm_chat", new_callable=AsyncMock, side_effect=RuntimeError("boom")),
        ):
            st.is_llm_enabled = True
            st.llm_temperature = 0.3
            st.llm_max_tokens = 512
            result = await generate_chat_reply(_project(), [{"role": "user", "content": "hi"}])

        assert result["reply"] is None
        assert result["degraded_reason"] == "llm_error"

    @pytest.mark.asyncio
    async def test_success_returns_reply(self) -> None:
        ok = LLMResult(text="因为叙事分高，所以 72。", provider_used="p1", model_used="m1")
        with (
            patch("app.services.ai_chat.settings") as st,
            patch("app.llm.client.llm_chat", new_callable=AsyncMock, return_value=ok),
        ):
            st.is_llm_enabled = True
            st.llm_temperature = 0.3
            st.llm_max_tokens = 512
            result = await generate_chat_reply(_project(), [{"role": "user", "content": "为什么 72 分？"}])

        assert result["reply"] == "因为叙事分高，所以 72。"
        assert result["degraded_reason"] is None

    @pytest.mark.asyncio
    async def test_messages_start_with_system_and_are_truncated_to_recent(self) -> None:
        """system 必须在最前；历史只保留最近 N 条（保留末端，丢最旧的）。"""
        ok = LLMResult(text="回复", provider_used="p1", model_used="m1")
        history = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg-{i}"}
            for i in range(CHAT_MAX_HISTORY_MESSAGES + 5)
        ]  # 17 条，末条（msg-16）是 user
        with (
            patch("app.services.ai_chat.settings") as st,
            patch("app.llm.client.llm_chat", new_callable=AsyncMock, return_value=ok) as chat,
        ):
            st.is_llm_enabled = True
            st.llm_temperature = 0.3
            st.llm_max_tokens = 512
            await generate_chat_reply(_project(), history)

        messages = chat.call_args.kwargs["messages"]
        assert messages[0]["role"] == "system"
        assert len(messages) == 1 + CHAT_MAX_HISTORY_MESSAGES
        assert messages[1]["content"] == f"msg-{len(history) - CHAT_MAX_HISTORY_MESSAGES}"
        assert messages[-1] == {"role": "user", "content": f"msg-{len(history) - 1}"}

    @pytest.mark.asyncio
    async def test_system_prompt_grounds_on_project_data(self) -> None:
        """system prompt 必须注入项目数据与「非投资建议」口径，
        否则模型只能靠自己的（过时的）记忆回答。"""
        ok = LLMResult(text="回复", provider_used="p1", model_used="m1")
        with (
            patch("app.services.ai_chat.settings") as st,
            patch("app.llm.client.llm_chat", new_callable=AsyncMock, return_value=ok) as chat,
        ):
            st.is_llm_enabled = True
            st.llm_temperature = 0.3
            st.llm_max_tokens = 512
            await generate_chat_reply(_project(), [{"role": "user", "content": "为什么是这个分？"}])

        system = chat.call_args.kwargs["messages"][0]["content"]
        assert "DemoProtocol" in system
        assert "72" in system
        assert "FARM" in system
        assert "投资建议" in system, "缺少非投资建议口径"


# ═══════════════════════════════════════════════════════════════
# 路由层
# ═══════════════════════════════════════════════════════════════


class TestEndpoint:
    @pytest.mark.asyncio
    async def test_rejects_empty_messages(self) -> None:
        with pytest.raises(HTTPException) as ei:
            await project_ai_chat(project_id="p1", req=_req())
        assert ei.value.status_code == 400

    @pytest.mark.asyncio
    async def test_rejects_history_ending_with_assistant(self) -> None:
        with pytest.raises(HTTPException) as ei:
            await project_ai_chat(project_id="p1", req=_req(("user", "hi"), ("assistant", "yo")))
        assert ei.value.status_code == 400

    @pytest.mark.asyncio
    async def test_rejects_blank_content(self) -> None:
        with pytest.raises(HTTPException) as ei:
            await project_ai_chat(project_id="p1", req=_req(("user", "   ")))
        assert ei.value.status_code == 400

    @pytest.mark.asyncio
    async def test_rejects_oversized_content(self) -> None:
        with pytest.raises(HTTPException) as ei:
            await project_ai_chat(project_id="p1", req=_req(("user", "x" * 2001)))
        assert ei.value.status_code == 400

    @pytest.mark.asyncio
    async def test_rejects_too_many_messages(self) -> None:
        msgs = tuple(
            ("user", "hi") if i % 2 == 0 else ("assistant", "yo") for i in range(21)
        )
        with pytest.raises(HTTPException) as ei:
            await project_ai_chat(project_id="p1", req=_req(*msgs))
        assert ei.value.status_code == 400

    @pytest.mark.asyncio
    async def test_404_unknown_project(self) -> None:
        with patch("app.routers.v1.ai_chat.ProjectRepository") as repo_cls:
            repo_cls.return_value.get_by_id.return_value = None
            with pytest.raises(HTTPException) as ei:
                await project_ai_chat(project_id="missing", req=_req(("user", "hi")))
        assert ei.value.status_code == 404

    @pytest.mark.asyncio
    async def test_passes_project_and_history_to_service(self) -> None:
        """路由必须把项目行和消息历史**真的**传给 service —— 拼装漏一行，
        service 测得再对前端也拿不到。"""
        service_reply = {"reply": "答案", "degraded_reason": None}
        with (
            patch("app.routers.v1.ai_chat.ProjectRepository") as repo_cls,
            patch(
                "app.routers.v1.ai_chat.generate_chat_reply",
                new_callable=AsyncMock,
                return_value=service_reply,
            ) as reply_mock,
            patch("app.routers.v1.ai_chat.settings") as st,
        ):
            project = _project()
            repo_cls.return_value.get_by_id.return_value = project
            st.is_llm_enabled = True
            resp = await project_ai_chat(project_id="p1", req=_req(("user", "为什么 72 分？")))

        reply_mock.assert_awaited_once_with(
            dict(project), [{"role": "user", "content": "为什么 72 分？"}]
        )
        assert resp["ok"] is True
        assert resp["data"]["reply"] == "答案"
        assert resp["data"]["degraded_reason"] is None
        assert resp["data"]["llm_available"] is True

    @pytest.mark.asyncio
    async def test_degraded_reason_is_passed_through(self) -> None:
        service_reply = {"reply": None, "degraded_reason": "budget_exceeded"}
        with (
            patch("app.routers.v1.ai_chat.ProjectRepository") as repo_cls,
            patch(
                "app.routers.v1.ai_chat.generate_chat_reply",
                new_callable=AsyncMock,
                return_value=service_reply,
            ),
            patch("app.routers.v1.ai_chat.settings") as st,
        ):
            repo_cls.return_value.get_by_id.return_value = _project()
            st.is_llm_enabled = True
            resp = await project_ai_chat(project_id="p1", req=_req(("user", "hi")))

        assert resp["data"]["reply"] is None
        assert resp["data"]["degraded_reason"] == "budget_exceeded", (
            "路由没把 degraded_reason 透传出去 —— 前端会说错处置方向。"
        )
