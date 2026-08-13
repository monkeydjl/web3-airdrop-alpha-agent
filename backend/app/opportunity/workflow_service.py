"""Thin read-only orchestration for Opportunity Action Workflow projections.

Loads already-persisted project/assessment/evidence/interaction rows and
composes them through pure `build_workflow_projection`. Never evaluates,
never writes, and never invents wallet/LLM side effects.
"""

from __future__ import annotations

from datetime import datetime
from types import TracebackType
from typing import Any

from app.db import _as_db_connection, dict_from_row
from app.opportunity.profile import DEFAULT_PROFILE
from app.opportunity.repository import OpportunityRepository
from app.opportunity.workflow import OpportunityWorkflowProjection, build_workflow_projection
from app.repository import ProjectRepository
from app.services.participation_tasks import generate_participation_tasks


class OpportunityWorkflowService:
    """Request-scoped read orchestrator for workflow projections."""

    def __init__(self, conn: Any = None) -> None:
        self._conn, self._owns_connection = _as_db_connection(conn)
        self._project_repo = ProjectRepository(self._conn)
        self._opportunity_repo = OpportunityRepository(self._conn)

    def get_project_workflow(self, project_id: str, now: datetime) -> OpportunityWorkflowProjection:
        project = self._project_repo.get_by_id(project_id)
        if project is None:
            raise LookupError(project_id)

        assessment = self._opportunity_repo.latest_assessment(project_id, DEFAULT_PROFILE.profile_id)
        evidence = self._opportunity_repo.list_evidence(project_id, include_invalid=True)
        participation = generate_participation_tasks(project)
        participation_tasks = participation.get("tasks") or []
        interactions = self._list_project_interactions(project_id)

        return build_workflow_projection(
            project=project,
            assessment=assessment,
            evidence=evidence,
            participation_tasks=participation_tasks,
            interactions=interactions,
            now=now,
        )

    def _list_project_interactions(self, project_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """SELECT * FROM interactions
               WHERE project_id = ?
               ORDER BY created_at DESC, id DESC""",
            (project_id,),
        ).fetchall()
        return [dict_from_row(row) for row in rows]

    def close(self) -> None:
        if self._owns_connection:
            self._conn.close()
            # Owned OpportunityRepository may wrap the same connection; keep close idempotent.
            self._owns_connection = False

    def __enter__(self) -> OpportunityWorkflowService:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
