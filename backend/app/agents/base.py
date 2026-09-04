"""Base Agent abstraction and Pipeline State.

Defines the agent contract and shared state for the pipeline.
All agents inherit from BaseAgent and implement the run() method.

Reference:
- ENGINEERING_ROADMAP.md §6 Agent 系统设计
- CONVENTIONS.md §5 类设计规范
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog

from app.models import (
    NarrativeResult,
    RiskResult,
    TeamResult,
    TokenomicsResult,
)

logger = structlog.get_logger(__name__)


@dataclass
class AgentError:
    """Agent execution error."""

    agent_name: str
    kind: str  # "validation_error", "llm_error", "timeout", etc.
    message: str
    project_id: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "kind": self.kind,
            "message": self.message,
            "project_id": self.project_id,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class RawProject:
    """Raw project data from collector.

    This is the input to the pipeline.
    """

    id: str  # UUID v5 deterministic ID
    name: str
    url: str | None = None
    sector: str | None = None
    stage: str | None = None  # "testnet", "mainnet", "ideation"
    source: str = "unknown"  # "seed", "defillama", "cryptorank", "twitter"

    # Raw signals (not yet scored)
    has_testnet: bool = False
    has_points_program: bool = False
    no_token_yet: bool = False
    recent_funding: bool = False

    # v1.2 extended signals (docs / social / repo health / airdrop clarity)
    has_docs: bool = False  # docs site / whitepaper / litepaper
    has_whitepaper: bool = False
    has_roadmap: bool = False
    has_github: bool = False
    has_twitter: bool = False
    has_discord: bool = False
    github_stars: int = 0
    github_recent_push_days: int | None = None  # days since last push; None = unknown
    explicit_airdrop_mention: bool = False  # "airdrop confirmed" / official wording
    tvl_usd: float | None = None
    description: str | None = None

    # v1.3 evidence / verifiable path / delivery
    has_task_portal: bool = False  # Galxe / Layer3 / quest / points portal
    has_contract: bool = False  # on-chain product / verified contract signal
    source_count: int = 1  # distinct discovery sources after merge
    roadmap_delivery: str = "unknown"  # "aligned" | "partial" | "unclear" | "unknown"
    sybil_friction: str = "unknown"  # "high" | "medium" | "low" | "unknown"

    # v1.4 funding quality (RootData / CryptoRank / manual)
    funding_total_usd: float | None = None
    funding_rounds: int = 0
    funding_last_date: str | None = None  # ISO date
    funding_investors: list[str] = field(default_factory=list)
    funding_lead_investors: list[str] = field(default_factory=list)
    funding_tier: str = "unknown"  # tier1 | tier2 | tier3 | unknown | none
    funding_quality: float = 0.0  # 0-1 composite

    # v2.0 自动采集元数据
    discovery_source: str | None = None  # "defillama", "github", "manual", etc.
    auto_discovered: bool = False
    discovered_at: datetime | None = None
    discovery_score: float = 0.0  # 0-1, ADR-012 LLM 分级阈值依据
    # 来源 raw_projects.raw_id 列表（handoff：成功评分后按项 mark processed）
    raw_ids: list[str] = field(default_factory=list)

    # Metadata
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "sector": self.sector,
            "stage": self.stage,
            "source": self.source,
            "has_testnet": self.has_testnet,
            "has_points_program": self.has_points_program,
            "no_token_yet": self.no_token_yet,
            "recent_funding": self.recent_funding,
            "has_docs": self.has_docs,
            "has_whitepaper": self.has_whitepaper,
            "has_roadmap": self.has_roadmap,
            "has_github": self.has_github,
            "has_twitter": self.has_twitter,
            "has_discord": self.has_discord,
            "github_stars": self.github_stars,
            "github_recent_push_days": self.github_recent_push_days,
            "explicit_airdrop_mention": self.explicit_airdrop_mention,
            "tvl_usd": self.tvl_usd,
            "description": self.description,
            "has_task_portal": self.has_task_portal,
            "has_contract": self.has_contract,
            "source_count": self.source_count,
            "roadmap_delivery": self.roadmap_delivery,
            "sybil_friction": self.sybil_friction,
            "funding_total_usd": self.funding_total_usd,
            "funding_rounds": self.funding_rounds,
            "funding_last_date": self.funding_last_date,
            "funding_investors": list(self.funding_investors),
            "funding_lead_investors": list(self.funding_lead_investors),
            "funding_tier": self.funding_tier,
            "funding_quality": self.funding_quality,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class AgentContext:
    """Shared context passed to all agents.

    Contains configuration and shared state.
    """

    run_id: str  # Unique ID for this pipeline run
    enable_llm: bool = False
    llm_model: str = "gpt-4o-mini"
    llm_discovery_score_threshold: float = 0.7  # ADR-012: 仅 discovery_score >= 阈值启用 LLM

    # Concurrency control (V2)
    max_concurrent_projects: int = 10
    llm_semaphore_size: int = 5

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "enable_llm": self.enable_llm,
            "llm_model": self.llm_model,
            "max_concurrent_projects": self.max_concurrent_projects,
            "llm_semaphore_size": self.llm_semaphore_size,
        }


@dataclass
class PipelineState:
    """State object passed through the pipeline.

    Each agent reads from and writes to this state.
    Immutable agents produce new state (functional style).
    """

    # Input
    project: RawProject
    context: AgentContext

    # Agent outputs (populated during pipeline)
    narrative: NarrativeResult | None = None
    team: TeamResult | None = None
    risk: RiskResult | None = None
    tokenomics: TokenomicsResult | None = None

    # Final score (populated by Scorer)
    score: int | None = None
    label: str | None = None  # "FARM", "WATCH", "IGNORE"
    confidence: float | None = None
    veto: str | None = None
    reason: list[str] = field(default_factory=list)
    # 子分快照与生效权重版本：WEIGHT_CALIBRATION §4.3 step 1 的离线重加权需要
    # 子分快照，§1.2 要求每条分数带 weight_version；此前二者都未落到 state/DB，
    # 使离线调权在结构上无输入、历史分数无法归属到具体权重版本。
    sub_scores: dict[str, float] = field(default_factory=dict)
    weight_version: str | None = None

    # Errors encountered
    errors: list[AgentError] = field(default_factory=list)

    # Timing
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None

    def add_error(self, error: AgentError) -> None:
        """Add error to state."""
        self.errors.append(error)
        logger.warning(
            "pipeline.agent_error",
            project_id=self.project.id,
            agent=error.agent_name,
            kind=error.kind,
            message=error.message,
        )

    def mark_completed(self) -> None:
        """Mark pipeline as completed."""
        self.completed_at = datetime.now(UTC)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for DB storage."""
        return {
            "project": self.project.to_dict(),
            "narrative": self.narrative.model_dump() if self.narrative else None,
            "team": self.team.model_dump() if self.team else None,
            "risk": self.risk.model_dump() if self.risk else None,
            "tokenomics": self.tokenomics.model_dump() if self.tokenomics else None,
            "score": self.score,
            "label": self.label,
            "confidence": self.confidence,
            "veto": self.veto,
            "reason": self.reason,
            "errors": [e.to_dict() for e in self.errors],
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class BaseAgent(ABC):
    """Abstract base class for all agents.

    Defines the agent contract:
    - run(): Main execution method (must implement)
    - llm_enhance(): Optional LLM enhancement hook

    All agents are stateless and async.
    """

    def __init__(self, name: str):
        self.name = name
        self.logger = structlog.get_logger(f"agent.{name}")

    @abstractmethod
    async def run(self, state: PipelineState) -> PipelineState:
        """Execute agent logic and return updated state.

        Args:
            state: Current pipeline state

        Returns:
            Updated pipeline state

        Raises:
            Should NOT raise - catch exceptions and add to state.errors
        """
        pass

    async def llm_enhance(self, state: PipelineState, _prompt: str) -> str | None:
        """Optional LLM enhancement.

        Args:
            state: Current pipeline state
            _prompt: LLM prompt (reserved for V2 implementation)

        Returns:
            LLM response or None if disabled/failed

        Note:
            - Only called if state.context.enable_llm is True AND
              project.discovery_score >= llm_discovery_score_threshold (ADR-012)
            - Failures are logged but not raised
            - Falls back to rule-based logic (ADR-001)
        """
        if not state.context.enable_llm:
            return None

        threshold = state.context.llm_discovery_score_threshold
        score = state.project.discovery_score
        if score < threshold:
            self.logger.info(
                "llm.skipped_by_score",
                agent=self.name,
                project_id=state.project.id,
                discovery_score=score,
                threshold=threshold,
                reason="ADR-012: discovery_score below LLM threshold",
            )
            return None

        try:
            from app.llm.client import llm_chat

            # E3 (§5.4.9): 尝试从 prompt_versions 表获取当前 agent 的默认版本
            prompt_version = self._resolve_prompt_version()

            # ⚠ 这里刻意用完整的 llm_chat()，不用 llm_chat_simple()：
            # simple 版丢掉 `refused_reason`，于是「预算拦下（预期行为）」
            # 和「接口全挂了（要告警）」在 agent 路径上长成一模一样 ——
            # 都返回 None、都只剩一条日志。OPERATIONS 排障清单里
            # "budget refusals indistinguishable from failures" 指的就是这里。
            result = await llm_chat(
                messages=[
                    {"role": "system", "content": f"You are the {self.name} analysis agent."},
                    {"role": "user", "content": _prompt},
                ],
                temperature=0.3,
                max_tokens=512,
                prompt_version=prompt_version,
            )

            if result.refused_reason:
                if result.refused_reason == "ledger_unavailable":
                    # fail-closed：账本读不出来 → 整个 LLM 路径被拦。
                    # 这是**事故**不是策略（alert_rules 里的
                    # LLMBudgetLedgerUnavailable 是 critical），必须用 error 级别。
                    self.logger.error(
                        "llm.ledger_fail_closed",
                        agent=self.name,
                        project_id=state.project.id,
                        reason=result.refused_reason,
                    )
                else:
                    # budget_exceeded 等：预期内的当日降级（ADR-001 的
                    # 规则引擎接管），info 级别即可 —— 打成 error 会让
                    # "预算用完了"和"LLM 坏了"再次混在一起。
                    self.logger.info(
                        "llm.budget_refused",
                        agent=self.name,
                        project_id=state.project.id,
                        reason=result.refused_reason,
                    )
                return None

            if result.leak_detected:
                # 输出泄漏被丢弃（SECURITY §10.5）：这是安全事件，不是"接口全挂"
                # 也不是"预算拦下"，单独的事件名 + error 级别，方便告警盯住。
                self.logger.error(
                    "llm.secret_leak_discarded",
                    agent=self.name,
                    project_id=state.project.id,
                    prompt_version=prompt_version,
                )
                return None

            content = result.text
            if content:
                self.logger.info(
                    "llm.success",
                    agent=self.name,
                    project_id=state.project.id,
                    prompt_version=prompt_version,
                )
                return content

            self.logger.info("llm.no_response", agent=self.name, project_id=state.project.id)
            return None

        except Exception as e:
            self.logger.error("llm.failed", agent=self.name, project_id=state.project.id, error=str(e))
            return None

    def _resolve_prompt_version(self, prompt_key: str = "analysis") -> str | None:
        """E3 (§5.4.9): 从 prompt_versions 表查询当前 agent 的默认 prompt 版本。

        查询失败或无默认版本时返回 None（不影响 LLM 调用）。
        """
        try:
            from app.db import get_connection
            from app.repositories.v2 import PromptVersionsRepository

            conn = get_connection()
            try:
                repo = PromptVersionsRepository(conn)
                row = repo.get_default(self.name, prompt_key)
                if row:
                    return f"{row.get('version', 'unknown')}"
                return None
            finally:
                conn.close()
        except Exception:
            return None

    def _log_start(self, state: PipelineState) -> None:
        """Log agent start."""
        self.logger.info("agent.started", agent=self.name, project_id=state.project.id, project_name=state.project.name)

    def _log_complete(self, state: PipelineState, duration_ms: float) -> None:
        """Log agent completion."""
        self.logger.info(
            "agent.completed",
            agent=self.name,
            project_id=state.project.id,
            duration_ms=round(duration_ms, 2),
            has_error=len(state.errors) > 0,
        )


if __name__ == "__main__":
    # Test models
    import uuid

    # Create test project
    project = RawProject(id=str(uuid.uuid4()), name="TestProject", sector="L2", stage="testnet", source="seed")

    # Create context
    context = AgentContext(run_id="test-run-001", enable_llm=False)

    # Create state
    state = PipelineState(project=project, context=context)

    print("✓ BaseAgent models created successfully")
    print(f"  Project: {state.project.name}")
    print(f"  Context: {state.context.run_id}")
    print(f"  State: {len(state.errors)} errors")
