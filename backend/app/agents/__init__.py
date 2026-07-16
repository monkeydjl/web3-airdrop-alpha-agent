"""Agent system package.

All agents inherit from BaseAgent and implement the run() method.
"""

from app.agents.base import (
    AgentContext,
    AgentError,
    BaseAgent,
    PipelineState,
    RawProject,
)
from app.agents.collector import CollectorAgent
from app.agents.narrative import NarrativeAgent

__all__ = [
    "AgentContext",
    "AgentError",
    "BaseAgent",
    "CollectorAgent",
    "NarrativeAgent",
    "PipelineState",
    "RawProject",
]
