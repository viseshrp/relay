from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from relay.config import PHASE_TYPES
from relay.models import Phase, PhaseAttempt, Project, WorkflowRun
from relay.schemas.run import (
    AttemptSummary,
    PhaseSummary,
    RunCreateRequest,
    RunDetailResponse,
    RunListQuery,
    RunListResponse,
    RunSummary,
)
from relay.services.settings_service import SettingsService
from relay.worker.git_ops import get_head_commit


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _latest_attempt(phase: Phase) -> PhaseAttempt | None:
    return phase.attempts[-1] if phase.attempts else None


def _serialize_phase(phase: Phase) -> PhaseSummary:
    latest_attempt = _latest_attempt(phase)
    return PhaseSummary(
        id=phase.id,
        phase_type=phase.phase_type,
        sequence_number=phase.sequence_number,
        status=phase.status,
        current_attempt=phase.current_attempt,
        latest_attempt=(
            AttemptSummary(
                attempt_number=latest_attempt.attempt_number,
                status=latest_attempt.status,
                started_at=latest_attempt.started_at,
                ended_at=latest_attempt.ended_at,
            )
            if latest_attempt is not None
            else None
        ),
    )


def _serialize_run(run: WorkflowRun, project_name: str) -> RunSummary:
    return RunSummary(
        id=run.id,
        project_id=run.project_id,
        project_name=project_name,
        name=run.name,
        status=run.status,
        branch=run.branch,
        head_commit=run.head_commit,
        autopilot=run.autopilot,
        review_fix_loop_count=run.review_fix_loop_count,
        review_fix_loop_limit=run.review_fix_loop_limit,
        retry_limit=run.retry_limit,
        context_paths=json.loads(run.context_paths),
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


class RunService:
    def __init__(self, settings_service: SettingsService) -> None:
        self.settings_service = settings_service

    async def create_run(self, session: AsyncSession, payload: RunCreateRequest) -> RunDetailResponse:
        project = await session.get(Project, payload.project_id)
        if project is None:
            raise ValueError("Project not found.")
        resolved = await self.settings_service.resolve_run_settings(
            session,
            payload.project_id,
            phase_model_mapping=payload.phase_model_mapping,
            retry_limit=payload.retry_limit,
            review_fix_loop_limit=payload.review_fix_loop_limit,
            autopilot=payload.autopilot,
        )
        now = _utc_now()
        run = WorkflowRun(
            id=str(uuid.uuid4()),
            project_id=project.id,
            name=payload.name,
            status="queued",
            branch=None,
            head_commit=get_head_commit(project.path) if project.is_git_repo else None,
            autopilot=resolved.autopilot,
            review_fix_loop_count=0,
            review_fix_loop_limit=resolved.review_fix_loop_limit,
            retry_limit=resolved.retry_limit,
            phase_model_mapping=json.dumps(resolved.phase_model_mapping),
            context_paths="[]",
            finalize_requested=False,
            cancel_requested=False,
            pending_fix_prompt=None,
            created_at=now,
            updated_at=now,
        )
        session.add(run)
        for sequence, phase_type in enumerate(PHASE_TYPES):
            session.add(
                Phase(
                    id=str(uuid.uuid4()),
                    workflow_run_id=run.id,
                    phase_type=phase_type,
                    sequence_number=sequence,
                    status="queued",
                    current_attempt=0,
                    created_at=now,
                    updated_at=now,
                )
            )
        await session.commit()
        return await self.get_run(session, run.id)

    async def list_runs(self, session: AsyncSession, query: RunListQuery) -> RunListResponse:
        filters = []
        if query.project_id:
            filters.append(WorkflowRun.project_id == query.project_id)
        if query.status:
            filters.append(WorkflowRun.status.in_([status.value for status in query.status]))
        total = (
            await session.execute(select(func.count(WorkflowRun.id)).join(Project).where(*filters))
        ).scalar_one()
        rows = (
            await session.execute(
                select(WorkflowRun, Project.name)
                .join(Project)
                .where(*filters)
                .order_by(WorkflowRun.created_at.desc())
                .offset(query.offset)
                .limit(query.limit)
            )
        ).all()
        return RunListResponse(items=[_serialize_run(run, project_name) for run, project_name in rows], total=total)

    async def get_run(self, session: AsyncSession, run_id: str) -> RunDetailResponse:
        run = (
            await session.execute(
                select(WorkflowRun)
                .options(selectinload(WorkflowRun.project), selectinload(WorkflowRun.phases).selectinload(Phase.attempts))
                .where(WorkflowRun.id == run_id)
            )
        ).scalar_one_or_none()
        if run is None or run.project is None:
            raise ValueError("Run not found.")
        response = _serialize_run(run, run.project.name)
        return RunDetailResponse(**response.model_dump(), phases=[_serialize_phase(phase) for phase in run.phases])

    async def delete_run(self, session: AsyncSession, run_id: str) -> None:
        run = await session.get(WorkflowRun, run_id)
        if run is None:
            raise ValueError("Run not found.")
        if run.status == "running":
            raise ValueError("Cannot delete a running workflow.")
        await session.delete(run)
        await session.commit()
