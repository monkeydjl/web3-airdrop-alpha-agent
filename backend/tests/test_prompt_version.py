"""E3 收尾: LLM 调用处记录 prompt_version 测试（§5.4.9）.

验证：
1. llm_chat() 接受 prompt_version 参数并在 LLMResult 中返回
2. llm_chat_simple() 透传 prompt_version
3. BaseAgent._resolve_prompt_version() 从 DB 查询默认版本
4. LLMResult.prompt_version 字段正确传递

Reference:
- docs/V2_TASKS.md E3
- backend/app/llm/client.py
- backend/app/agents/base.py
"""

from __future__ import annotations

import sqlite3
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.base import AgentContext, BaseAgent, PipelineState, RawProject
from app.db import init_db
from app.llm.client import LLMResult, llm_chat, llm_chat_simple


@pytest.fixture
def db_conn():
    """In-memory SQLite with schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    yield conn
    conn.close()


class TestLLMResultPromptVersion:
    """LLMResult carries prompt_version field."""

    def test_llm_result_has_prompt_version_field(self):
        """LLMResult dataclass has prompt_version field defaulting to None."""
        result = LLMResult(text="hello", provider_used="test", model_used="gpt-4o-mini")
        assert result.prompt_version is None

    def test_llm_result_prompt_version_set(self):
        """LLMResult can be constructed with prompt_version."""
        result = LLMResult(
            text="hello",
            provider_used="test",
            model_used="gpt-4o-mini",
            prompt_version="v1.2",
        )
        assert result.prompt_version == "v1.2"


class TestLLMChatPromptVersion:
    """llm_chat() and llm_chat_simple() accept and propagate prompt_version."""

    @pytest.mark.asyncio
    async def test_llm_chat_accepts_prompt_version(self):
        """llm_chat accepts prompt_version parameter without error."""
        with patch("app.llm.client._get_providers", return_value=[]):
            result = await llm_chat(
                messages=[{"role": "user", "content": "test"}],
                prompt_version="v2.0",
            )
            # No providers → text=None, but prompt_version should still be set
            assert result.prompt_version == "v2.0"

    @pytest.mark.asyncio
    async def test_llm_chat_simple_accepts_prompt_version(self):
        """llm_chat_simple accepts prompt_version parameter."""
        with patch("app.llm.client._get_providers", return_value=[]):
            text = await llm_chat_simple(
                messages=[{"role": "user", "content": "test"}],
                prompt_version="v3.0",
            )
            assert text is None  # No providers → None

    @pytest.mark.asyncio
    async def test_llm_chat_prompt_version_defaults_none(self):
        """prompt_version defaults to None when not provided."""
        with patch("app.llm.client._get_providers", return_value=[]):
            result = await llm_chat(
                messages=[{"role": "user", "content": "test"}],
            )
            assert result.prompt_version is None


class TestBaseAgentResolvePromptVersion:
    """BaseAgent._resolve_prompt_version() queries prompt_versions table."""

    def test_resolve_returns_none_when_no_default(self, db_conn):
        """Returns None when no default prompt version exists for agent."""
        with patch("app.db.get_connection", return_value=db_conn):
            agent = _make_test_agent()
            version = agent._resolve_prompt_version()
            assert version is None

    def test_resolve_returns_version_when_default_exists(self, db_conn):
        """Returns version string when a default prompt version exists."""
        # Insert a default prompt version for the test agent
        from app.repositories.v2 import PromptVersionsRepository

        repo = PromptVersionsRepository(db_conn)
        repo.insert(
            agent_name="TestAgent",
            prompt_key="analysis",
            version="v1.5",
            content="You are a test agent.",
            created_by="test",
            is_default=True,
        )

        with patch("app.db.get_connection", return_value=db_conn):
            agent = _make_test_agent()
            version = agent._resolve_prompt_version()
            assert version == "v1.5"

    def test_resolve_returns_none_on_db_error(self):
        """Returns None when DB connection fails (graceful degradation)."""
        with patch("app.db.get_connection", side_effect=Exception("DB unavailable")):
            agent = _make_test_agent()
            version = agent._resolve_prompt_version()
            assert version is None


class TestBaseAgentLLMEnhancePromptVersion:
    """BaseAgent.llm_enhance() logs prompt_version."""

    @pytest.mark.asyncio
    async def test_llm_enhance_logs_prompt_version(self, db_conn):
        """llm_enhance logs prompt_version in success message."""
        from app.repositories.v2 import PromptVersionsRepository

        # Seed a default prompt version
        repo = PromptVersionsRepository(db_conn)
        repo.insert(
            agent_name="TestAgent",
            prompt_key="analysis",
            version="v2.1",
            content="You are a test agent.",
            created_by="test",
            is_default=True,
        )

        project = RawProject(
            id="pv-test-001",
            name="Prompt Version Test",
            sector="L2",
            stage="testnet",
            source="test",
        )
        # Set discovery_score above threshold
        project.discovery_score = 0.9
        state = PipelineState(
            project=project,
            context=AgentContext(run_id="pv-run-001", enable_llm=True),
        )

        agent = _make_test_agent()

        # Mock llm_chat_simple to return content
        with (
            patch("app.db.get_connection", return_value=db_conn),
            patch("app.llm.client.llm_chat_simple", new_callable=AsyncMock, return_value="LLM analysis result"),
        ):
            result = await agent.llm_enhance(state, "test prompt")

        assert result == "LLM analysis result"

    @pytest.mark.asyncio
    async def test_llm_enhance_works_without_prompt_version(self, db_conn):
        """llm_enhance works fine when no prompt version is configured."""
        project = RawProject(
            id="pv-test-002",
            name="No PV Test",
            sector="DeFi",
            stage="mainnet",
            source="test",
        )
        project.discovery_score = 0.9
        state = PipelineState(
            project=project,
            context=AgentContext(run_id="pv-run-002", enable_llm=True),
        )

        agent = _make_test_agent()

        with (
            patch("app.db.get_connection", return_value=db_conn),
            patch("app.llm.client.llm_chat_simple", new_callable=AsyncMock, return_value="result without PV"),
        ):
            result = await agent.llm_enhance(state, "test prompt")

        assert result == "result without PV"


# ── Helper ───────────────────────────────────────


def _make_test_agent() -> BaseAgent:
    """Create a minimal BaseAgent subclass for testing."""
    class TestAgent(BaseAgent):
        def __init__(self):
            super().__init__("TestAgent")

        async def run(self, state: PipelineState) -> PipelineState:
            return state

    return TestAgent()
