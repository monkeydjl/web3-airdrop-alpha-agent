"""Base Agent abstraction and Pipeline State.

Defines the agent contract and shared state for the pipeline.
All agents inherit from BaseAgent and implement the run() method.

Reference:
- ENGINEERING_ROADMAP.md §6 Agent 系统设计
- CONVENTIONS.md §5 类设计规范
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog

from app.models import (
    NarrativeResult,
    TeamResult,
    RiskResult,
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
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

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

    # Metadata
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

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
    reason: list[str] = field(default_factory=list)

    # Errors encountered
    errors: list[AgentError] = field(default_factory=list)

    # Timing
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None

    def add_error(self, error: AgentError):
        """Add error to state."""
        self.errors.append(error)
        logger.warning(
            "pipeline.agent_error",
            project_id=self.project.id,
            agent=error.agent_name,
            kind=error.kind,
            message=error.message
        )

    def mark_completed(self):
        """Mark pipeline as completed."""
        self.completed_at = datetime.now(timezone.utc)

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

    async def llm_enhance(self, state: PipelineState, prompt: str) -> str | None:
        """Optional LLM enhancement.

        Args:
            state: Current pipeline state
            prompt: LLM prompt

        Returns:
            LLM response or None if disabled/failed

        Note:
            - Only called if state.context.enable_llm is True
            - Failures are logged but not raised
            - Falls back to rule-based logic (ADR-001)
        """
        if not state.context.enable_llm:
            return None

        try:
            # TODO: Implement LLM call in V2
            # For MVP, just return None (rule-based only)
            self.logger.info(
                "llm.skipped",
                agent=self.name,
                project_id=state.project.id,
                reason="MVP: rule-based only"
            )
            return None

        except Exception as e:
            self.logger.error(
                "llm.failed",
                agent=self.name,
                project_id=state.project.id,
                error=str(e)
            )
            return None

    def _log_start(self, state: PipelineState):
        """Log agent start."""
        self.logger.info(
            "agent.started",
            agent=self.name,
            project_id=state.project.id,
            project_name=state.project.name
        )

    def _log_complete(self, state: PipelineState, duration_ms: float):
        """Log agent completion."""
        self.logger.info(
            "agent.completed",
            agent=self.name,
            project_id=state.project.id,
            duration_ms=round(duration_ms, 2),
            has_error=len(state.errors) > 0
        )


if __name__ == "__main__":
    # Test models
    import uuid

    # Create test project
    project = RawProject(
        id=str(uuid.uuid4()),
        name="TestProject",
        sector="L2",
        stage="testnet",
        source="seed"
    )

    # Create context
    context = AgentContext(
        run_id="test-run-001",
        enable_llm=False
    )

    # Create state
    state = PipelineState(
        project=project,
        context=context
    )

    print("✓ BaseAgent models created successfully")
    print(f"  Project: {state.project.name}")
    print(f"  Context: {state.context.run_id}")
    print(f"  State: {len(state.errors)} errors")
