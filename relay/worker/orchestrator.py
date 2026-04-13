from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from relay.artifacts.manager import artifact_dir, read_artifact
from relay.config import Settings
from relay.copilot.prompts import build_fix_prompt
from relay.copilot.session import CopilotSession
from relay.db import DatabaseManager
from relay.models import Phase, WorkflowRun
from relay.worker.git_ops import create_branch
from relay.worker.phase_runner import PhaseExecutionResult, run_exploration_phase, run_standard_phase
from relay.worker.retry import backoff_seconds, can_retry


WORKFLOW_TRANSITIONS: dict[str, set[str]] = {
    "queued": {"running", "cancelled"},
    "running": {
        "waiting_for_user",
        "completed",
        "completed_with_unresolved_findings",
        "failed",
        "cancelled",
    },
    "waiting_for_user": {
        "running",
        "completed",
        "completed_with_unresolved_findings",
        "cancelled",
    },
    "failed": {"running"},
    "cancelled": {"running"},
    "completed": set(),
    "completed_with_unresolved_findings": set(),
}

PHASE_TRANSITIONS: dict[str, set[str]] = {
    "queued": {"starting", "running", "cancelled"},
    "starting": {"running", "failed", "cancelled"},
    "running": {"succeeded", "retrying", "failed", "cancelled", "waiting_for_user"},
    "retrying": {"starting", "queued", "cancelled"},
    "succeeded": {"stale", "waiting_for_user", "queued"},
    "failed": {"queued", "cancelled"},
    "cancelled": {"queued", "running"},
    "stale": {"queued"},
    "waiting_for_user": {"succeeded", "queued", "cancelled"},
}

TERMINAL_WORKFLOW_STATES = {"completed", "completed_with_unresolved_findings", "failed", "cancelled"}


@dataclass(slots=True)
class WorkflowRuntime:
    exploration_session: CopilotSession | None = None
    planning_session: CopilotSession | None = None
    execution_session: CopilotSession | None = None

    async def shutdown(self) -> None:
        for session in (self.exploration_session, self.planning_session, self.execution_session):
            if session is not None and session.is_alive():
                await session.kill()
        self.exploration_session = None
        self.planning_session = None
        self.execution_session = None


def _assert_transition(current: str, target: str, allowed: dict[str, set[str]], label: str) -> None:
    if target not in allowed.get(current, set()):
        raise ValueError(f"Invalid {label} transition: {current} -> {target}")


def _loads(value: str) -> list[str]:
    return list(json.loads(value))


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _retry_backoff_elapsed(phase: Phase) -> bool:
    # The retry timer is derived from the phase's last status update so retries
    # remain recoverable across worker restarts without extra persistence fields.
    if phase.updated_at is None:
        return True
    updated_at = datetime.fromisoformat(phase.updated_at.replace("Z", "+00:00"))
    elapsed_seconds = (datetime.now(UTC) - updated_at).total_seconds()
    return elapsed_seconds >= backoff_seconds(phase.current_attempt)


async def _load_run(session: AsyncSession, run_id: str) -> WorkflowRun:
    run = (
        await session.execute(
            select(WorkflowRun)
            .options(
                selectinload(WorkflowRun.project),
                selectinload(WorkflowRun.phases).selectinload(Phase.attempts),
                selectinload(WorkflowRun.exploration_messages),
            )
            .where(WorkflowRun.id == run_id)
        )
    ).scalar_one()
    return run


def _next_actionable_phase(run: WorkflowRun) -> Phase | None:
    ordered = sorted(run.phases, key=lambda item: item.sequence_number)
    for index, phase in enumerate(ordered):
        previous = ordered[:index]
        if phase.status in {"running", "starting", "retrying", "waiting_for_user"}:
            return phase
        if phase.status == "queued" and all(item.status == "succeeded" for item in previous):
            return phase
    return None


async def _update_statuses(
    db: DatabaseManager,
    run_id: str,
    phase_id: str,
    *,
    workflow_status: str | None = None,
    phase_status: str | None = None,
) -> None:
    async with db.session() as session:
        run = await _load_run(session, run_id)
        phase = next(item for item in run.phases if item.id == phase_id)
        if workflow_status is not None and workflow_status != run.status:
            _assert_transition(run.status, workflow_status, WORKFLOW_TRANSITIONS, "workflow")
            run.status = workflow_status
        if phase_status is not None and phase_status != phase.status:
            _assert_transition(phase.status, phase_status, PHASE_TRANSITIONS, "phase")
            phase.status = phase_status
        timestamp = _utc_now()
        phase.updated_at = timestamp
        run.updated_at = timestamp
        await session.commit()


async def _queue_next_phase(db: DatabaseManager, run_id: str, current_phase_id: str) -> None:
    async with db.session() as session:
        run = await _load_run(session, run_id)
        phases = sorted(run.phases, key=lambda item: item.sequence_number)
        current_index = next(index for index, item in enumerate(phases) if item.id == current_phase_id)
        if current_index + 1 >= len(phases):
            await session.commit()
            return
        next_phase = phases[current_index + 1]
        if next_phase.status != "queued":
            _assert_transition(next_phase.status, "queued", PHASE_TRANSITIONS, "phase")
            next_phase.status = "queued"
            next_phase.updated_at = _utc_now()
        await session.commit()


async def _prepare_execution_branch(db: DatabaseManager, run_id: str) -> None:
    async with db.session() as session:
        run = await _load_run(session, run_id)
        if run.project is None or not run.project.is_git_repo:
            return
        if run.branch:
            return
        branch_name = f"relay/{run.id}"
        create_branch(run.project.path, branch_name, run.head_commit)
        run.branch = branch_name
        run.updated_at = _utc_now()
        await session.commit()


async def _pause_after_phase(db: DatabaseManager, run_id: str, phase_id: str) -> None:
    await _update_statuses(db, run_id, phase_id, workflow_status="waiting_for_user", phase_status="waiting_for_user")


async def _mark_phase_succeeded(db: DatabaseManager, run_id: str, phase_id: str) -> None:
    await _update_statuses(db, run_id, phase_id, phase_status="succeeded")


async def _mark_run_cancelled(db: DatabaseManager, run_id: str, phase_id: str) -> None:
    await _update_statuses(db, run_id, phase_id, workflow_status="cancelled", phase_status="cancelled")


async def _handle_failure(
    db: DatabaseManager,
    settings: Settings,
    run_id: str,
    phase_id: str,
    result: PhaseExecutionResult,
) -> Literal["retrying", "failed"]:
    _ = settings
    async with db.session() as session:
        run = await _load_run(session, run_id)
        phase = next(item for item in run.phases if item.id == phase_id)
        timestamp = _utc_now()
        if can_retry(result.attempt_number, run.retry_limit):
            _assert_transition(phase.status, "retrying", PHASE_TRANSITIONS, "phase")
            phase.status = "retrying"
            phase.updated_at = timestamp
            run.updated_at = timestamp
            await session.commit()
            return "retrying"
        _assert_transition(phase.status, "failed", PHASE_TRANSITIONS, "phase")
        phase.status = "failed"
        _assert_transition(run.status, "failed", WORKFLOW_TRANSITIONS, "workflow")
        run.status = "failed"
        phase.updated_at = timestamp
        run.updated_at = timestamp
        await session.commit()
        return "failed"


async def advance_workflow(
    db: DatabaseManager,
    settings: Settings,
    *,
    run_id: str,
    runtime: WorkflowRuntime,
) -> Literal["running", "waiting_for_user", "completed", "failed", "cancelled", "idle"]:
    async with db.session() as session:
        run = await _load_run(session, run_id)
        if run.status in TERMINAL_WORKFLOW_STATES:
            return run.status  # type: ignore[return-value]
        if run.status == "queued":
            _assert_transition("queued", "running", WORKFLOW_TRANSITIONS, "workflow")
            run.status = "running"
            await session.commit()
        if run.status == "waiting_for_user":
            return "waiting_for_user"
        phase = _next_actionable_phase(run)
        if phase is None:
            return "idle"
        phase_type = phase.phase_type
        if phase.status in {"starting", "running"}:
            # A worker restart can re-adopt a live subprocess without a live
            # in-memory runtime task. In that case the database is the source of
            # truth and the worker must not launch a duplicate subprocess.
            return "idle"
        if phase.status == "retrying":
            if not _retry_backoff_elapsed(phase):
                return "idle"
            await _update_statuses(db, run_id, phase.id, phase_status="queued")
            return "running"

    if phase_type == "exploration":
        result, runtime.exploration_session = await run_exploration_phase(
            db,
            settings,
            run_id=run_id,
            phase_id=phase.id,
            session_handle=runtime.exploration_session,
        )
        if not result.success:
            if result.error_message == "cancelled":
                await _mark_run_cancelled(db, run_id, phase.id)
                return "cancelled"
            outcome = await _handle_failure(db, settings, run_id, phase.id, result)
            return "failed" if outcome == "failed" else "idle"
        await _mark_phase_succeeded(db, run_id, phase.id)
        if runtime.exploration_session is not None and runtime.exploration_session.is_alive():
            await runtime.exploration_session.kill()
        runtime.exploration_session = None
        async with db.session() as session:
            run = await _load_run(session, run_id)
            if run.autopilot:
                await _queue_next_phase(db, run_id, phase.id)
                return "running"
        await _pause_after_phase(db, run_id, phase.id)
        return "waiting_for_user"

    if phase_type == "execution":
        await _prepare_execution_branch(db, run_id)

    reusable_session = None
    if phase_type == "plan_correction":
        reusable_session = runtime.planning_session
    elif phase_type == "execution":
        reusable_session = runtime.execution_session

    result, returned_session = await run_standard_phase(
        db,
        settings,
        run_id=run_id,
        phase_id=phase.id,
        phase_type=phase_type,
        reusable_session=reusable_session,
    )

    if phase_type in {"planning", "plan_correction"}:
        runtime.planning_session = returned_session
    if phase_type == "execution":
        runtime.execution_session = returned_session

    if not result.success:
        if result.error_message == "cancelled":
            await _mark_run_cancelled(db, run_id, phase.id)
            return "cancelled"
        outcome = await _handle_failure(db, settings, run_id, phase.id, result)
        return "failed" if outcome == "failed" else "idle"

    await _mark_phase_succeeded(db, run_id, phase.id)

    if phase_type == "planning":
        await _queue_next_phase(db, run_id, phase.id)
        return "running"
    if phase_type == "plan_critique":
        async with db.session() as session:
            run = await _load_run(session, run_id)
            if run.autopilot:
                await _queue_next_phase(db, run_id, phase.id)
                return "running"
        await _pause_after_phase(db, run_id, phase.id)
        return "waiting_for_user"
    if phase_type == "plan_correction":
        if runtime.planning_session is not None and runtime.planning_session.is_alive():
            await runtime.planning_session.kill()
        runtime.planning_session = None
        await _queue_next_phase(db, run_id, phase.id)
        return "running"
    if phase_type == "execution":
        await _queue_next_phase(db, run_id, phase.id)
        return "running"
    if phase_type == "review":
        verdict = result.review_verdict or "FAIL"
        async with db.session() as session:
            run = await _load_run(session, run_id)
            if run.autopilot:
                if verdict == "PASS":
                    _assert_transition(run.status, "completed", WORKFLOW_TRANSITIONS, "workflow")
                    run.status = "completed"
                    await session.commit()
                    return "completed"
                if verdict == "PASS_WITH_WARNINGS":
                    _assert_transition(
                        run.status,
                        "completed_with_unresolved_findings",
                        WORKFLOW_TRANSITIONS,
                        "workflow",
                    )
                    run.status = "completed_with_unresolved_findings"
                    await session.commit()
                    return "completed_with_unresolved_findings"
                if run.review_fix_loop_count >= run.review_fix_loop_limit:
                    _assert_transition(
                        run.status,
                        "completed_with_unresolved_findings",
                        WORKFLOW_TRANSITIONS,
                        "workflow",
                    )
                    run.status = "completed_with_unresolved_findings"
                    await session.commit()
                    return "completed_with_unresolved_findings"
                run.review_fix_loop_count += 1
                run.pending_fix_prompt = build_fix_prompt(
                    result.review_comments or [],
                    result.review_summary or "",
                    read_artifact(run.project.path, run.id, "planning", "SPEC.md"),  # type: ignore[union-attr]
                    read_artifact(run.project.path, run.id, "plan_correction", "IMPLEMENTATION_PLAN.md"),  # type: ignore[union-attr]
                    _loads(run.context_paths),
                )
                execution_phase = next(item for item in run.phases if item.phase_type == "execution")
                review_phase = next(item for item in run.phases if item.phase_type == "review")
                if execution_phase.status != "queued":
                    _assert_transition(execution_phase.status, "queued", PHASE_TRANSITIONS, "phase")
                    execution_phase.status = "queued"
                if review_phase.status != "queued":
                    _assert_transition(review_phase.status, "queued", PHASE_TRANSITIONS, "phase")
                    review_phase.status = "queued"
                await session.commit()
                return "running"
        await _pause_after_phase(db, run_id, phase.id)
        return "waiting_for_user"

    await _queue_next_phase(db, run_id, phase.id)
    return "running"
