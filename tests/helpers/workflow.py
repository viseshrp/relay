from __future__ import annotations

from collections import deque

from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from relay.config import Settings
from relay.models import Phase, WorkflowRun
from relay.worker.orchestrator import WorkflowRuntime, advance_workflow


class SessionFactoryQueue:
    """Return pre-built fake sessions in the exact order the worker needs them."""

    def __init__(self, sessions: list[object]) -> None:
        self._sessions = deque(sessions)

    def __call__(self) -> object:
        if not self._sessions:
            raise AssertionError("No fake sessions remain in the queue.")
        return self._sessions.popleft()


async def drive_workflow(app: FastAPI, test_settings: Settings, run_id: str, runtime: WorkflowRuntime, *, max_steps: int = 50) -> str:
    """Advance a workflow until it pauses, becomes idle, or reaches a terminal state."""

    outcome = "idle"
    for _ in range(max_steps):
        outcome = await advance_workflow(app.state.db, test_settings, run_id=run_id, runtime=runtime)
        if outcome in {"waiting_for_user", "idle", "completed", "completed_with_unresolved_findings", "failed", "cancelled"}:
            return outcome
    raise AssertionError("Workflow did not reach a stable outcome within the step limit.")


async def load_run(app: FastAPI, run_id: str) -> WorkflowRun:
    async with app.state.db.session() as session:
        run = (
            await session.execute(
                select(WorkflowRun)
                .options(selectinload(WorkflowRun.phases).selectinload(Phase.attempts))
                .where(WorkflowRun.id == run_id)
            )
        ).scalar_one()
        return run
