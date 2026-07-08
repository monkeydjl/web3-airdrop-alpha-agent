"""Agent system package.

All agents inherit from BaseAgent and implement the run() method.
"""

from app.agents.base import (
    BaseAgent,
    AgentContext,
    AgentError,
    PipelineState,
    RawProject,
)
from app.agents.collector import CollectorAgent
from app.agents.narrative import NarrativeAgent

__all__ = [
    "BaseAgent",
    "AgentContext",
    "AgentError",
    "PipelineState",
    "RawProject",
    "CollectorAgent",
    "NarrativeAgent",
]
