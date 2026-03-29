from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from relay.artifacts.manager import artifact_dir
from relay.copilot.session import set_session_factory
from relay.models import ExplorationMessage, WorkflowRun
from relay.schemas.run import RunCreateRequest
from relay.worker.orchestrator import WorkflowRuntime
from tests.helpers.workflow import SessionFactoryQueue, drive_workflow, load_run
from tests.mocks.fake_copilot import FakeCopilotSession


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _planning_prompt() -> str:
    return """# Problem
Build the requested feature.

# Goals
- Implement the workflow end to end.

# Constraints
- Keep tests deterministic.

# Preferred Stack
- Python and React.

# Files to Read
- src/main.py

# Desired Output
- Working code and passing tests.
"""


def _review_output(verdict: str, comments: list[dict[str, object]] | None = None) -> str:
    return f"""```relay-review-comments
{json.dumps(comments or [])}
```

## Summary
Review summary.

## Verdict
{verdict}
"""


async def _create_run_with_finalized_exploration(
    app,
    project_dir,
    *,
    autopilot: bool = True,
    retry_limit: int | None = None,
    review_fix_loop_limit: int | None = None,
) -> str:
    async with app.state.db.session() as session:
        project = await app.state.project_service.create_project(session, str(project_dir))
        run = await app.state.run_service.create_run(
            session,
            RunCreateRequest(
                project_id=project.id,
                name="Workflow",
                autopilot=autopilot,
                retry_limit=retry_limit,
                review_fix_loop_limit=review_fix_loop_limit,
            ),
        )
        session.add(
            ExplorationMessage(
                id=str(uuid.uuid4()),
                workflow_run_id=run.id,
                role="user",
                content="Please build the requested feature.",
                sequence_number=1,
                created_at=_utc_now(),
            )
        )
        db_run = (await session.execute(select(WorkflowRun).where(WorkflowRun.id == run.id))).scalar_one()
        db_run.finalize_requested = True
        await session.commit()
        return run.id


async def _force_retry_ready(app, run_id: str, phase_type: str) -> None:
    async with app.state.db.session() as session:
        run = (await session.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))).scalar_one()
        phase = next(item for item in run.phases if item.phase_type == phase_type)
        phase.updated_at = (datetime.now(UTC) - timedelta(minutes=10)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        run.updated_at = phase.updated_at
        await session.commit()


class BlockingExecutionSession:
    """Hold the phase open until the worker cancellation path kills the session."""

    def __init__(self) -> None:
        self._alive = False
        self._released = asyncio.Event()

    async def start(self, cmd: list[str], cwd: str, env: dict | None = None) -> None:
        _ = (cmd, cwd, env)
        self._alive = True

    async def send(self, prompt: str) -> AsyncIterator[str]:
        _ = prompt
        yield "execution-started\n"
        await self._released.wait()

    async def send_followup(self, prompt: str) -> AsyncIterator[str]:
        async for chunk in self.send(prompt):
            yield chunk

    def is_alive(self) -> bool:
        return self._alive

    async def kill(self) -> None:
        self._alive = False
        self._released.set()

    async def wait(self) -> int:
        return -9

    @property
    def pid(self) -> int | None:
        return 99991 if self._alive else None

    @property
    def process(self) -> None:
        return None


@pytest.mark.asyncio
async def test_orchestrator_completes_full_autopilot_workflow(app, test_settings, project_dir) -> None:
    run_id = await _create_run_with_finalized_exploration(app, project_dir)
    set_session_factory(
        SessionFactoryQueue(
            [
                FakeCopilotSession(["Exploration response", _planning_prompt()]),
                FakeCopilotSession(["Planning output", "Corrected plan output"]),
                FakeCopilotSession(["Critiqued plan output"]),
                FakeCopilotSession(["Execution output"]),
                FakeCopilotSession([_review_output("PASS")]),
            ]
        )
    )

    outcome = await drive_workflow(app, test_settings, run_id, WorkflowRuntime())
    run = await load_run(app, run_id)

    assert outcome == "completed"
    assert run.status == "completed"
    assert all(phase.status == "succeeded" for phase in run.phases)
    assert (artifact_dir(str(project_dir), run_id, "exploration") / "planning_prompt.md").exists()
    assert (artifact_dir(str(project_dir), run_id, "planning") / "SPEC.md").exists()
    assert (artifact_dir(str(project_dir), run_id, "planning") / "IMPLEMENTATION_PLAN.md").exists()
    assert (artifact_dir(str(project_dir), run_id, "plan_critique") / "IMPLEMENTATION_PLAN_CRITIQUED.md").exists()
    assert (artifact_dir(str(project_dir), run_id, "review") / "REVIEW_SUMMARY.md").exists()


@pytest.mark.asyncio
async def test_orchestrator_review_fix_loop_completes_after_two_failures(app, test_settings, project_dir) -> None:
    run_id = await _create_run_with_finalized_exploration(app, project_dir)
    set_session_factory(
        SessionFactoryQueue(
            [
                FakeCopilotSession(["Exploration response", _planning_prompt()]),
                FakeCopilotSession(["Planning output", "Corrected plan output"]),
                FakeCopilotSession(["Critiqued plan output"]),
                FakeCopilotSession(["Execution output", "Fix output 1", "Fix output 2"]),
                FakeCopilotSession([_review_output("FAIL", [{"file": "src/main.py", "line": 1, "severity": "error", "comment": "Issue"}])]),
                FakeCopilotSession([_review_output("FAIL", [{"file": "src/main.py", "line": 2, "severity": "warning", "comment": "Still not fixed"}])]),
                FakeCopilotSession([_review_output("PASS")]),
            ]
        )
    )

    outcome = await drive_workflow(app, test_settings, run_id, WorkflowRuntime())
    run = await load_run(app, run_id)

    assert outcome == "completed"
    assert run.status == "completed"
    assert run.review_fix_loop_count == 2


@pytest.mark.asyncio
async def test_orchestrator_stops_at_review_fix_loop_limit(app, test_settings, project_dir) -> None:
    run_id = await _create_run_with_finalized_exploration(app, project_dir, review_fix_loop_limit=2)
    set_session_factory(
        SessionFactoryQueue(
            [
                FakeCopilotSession(["Exploration response", _planning_prompt()]),
                FakeCopilotSession(["Planning output", "Corrected plan output"]),
                FakeCopilotSession(["Critiqued plan output"]),
                FakeCopilotSession(["Execution output", "Fix output 1", "Fix output 2"]),
                FakeCopilotSession([_review_output("FAIL")]),
                FakeCopilotSession([_review_output("FAIL")]),
                FakeCopilotSession([_review_output("FAIL")]),
            ]
        )
    )

    outcome = await drive_workflow(app, test_settings, run_id, WorkflowRuntime())
    run = await load_run(app, run_id)

    assert outcome == "completed_with_unresolved_findings"
    assert run.status == "completed_with_unresolved_findings"
    assert run.review_fix_loop_count == 2


@pytest.mark.asyncio
async def test_orchestrator_retries_failed_phase(app, test_settings, project_dir) -> None:
    run_id = await _create_run_with_finalized_exploration(app, project_dir)
    execution_session = FakeCopilotSession(["Execution output", "Execution retry output"], fail_on_attempt=[1])
    set_session_factory(
        SessionFactoryQueue(
            [
                FakeCopilotSession(["Exploration response", _planning_prompt()]),
                FakeCopilotSession(["Planning output", "Corrected plan output"]),
                FakeCopilotSession(["Critiqued plan output"]),
                execution_session,
                FakeCopilotSession([_review_output("PASS")]),
            ]
        )
    )

    runtime = WorkflowRuntime()
    first_outcome = await drive_workflow(app, test_settings, run_id, runtime)
    await _force_retry_ready(app, run_id, "execution")
    second_outcome = await drive_workflow(app, test_settings, run_id, runtime)
    run = await load_run(app, run_id)
    execution_phase = next(phase for phase in run.phases if phase.phase_type == "execution")

    assert first_outcome == "idle"
    assert second_outcome == "completed"
    assert execution_phase.current_attempt == 2
    assert execution_phase.status == "succeeded"


@pytest.mark.asyncio
async def test_orchestrator_cancels_mid_phase(app, test_settings, project_dir) -> None:
    run_id = await _create_run_with_finalized_exploration(app, project_dir)
    blocking_execution_session = BlockingExecutionSession()
    set_session_factory(
        SessionFactoryQueue(
            [
                FakeCopilotSession(["Exploration response", _planning_prompt()]),
                FakeCopilotSession(["Planning output", "Corrected plan output"]),
                FakeCopilotSession(["Critiqued plan output"]),
                blocking_execution_session,
            ]
        )
    )

    runtime = WorkflowRuntime()
    advance_task = asyncio.create_task(drive_workflow(app, test_settings, run_id, runtime))

    for _ in range(200):
        async with app.state.db.session() as session:
            run = (await session.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))).scalar_one()
            execution_phase = next(phase for phase in run.phases if phase.phase_type == "execution")
            if execution_phase.status == "running":
                run.cancel_requested = True
                await session.commit()
                break
        await asyncio.sleep(0)
    else:
        raise AssertionError("Execution phase never entered the running state.")

    outcome = await asyncio.wait_for(advance_task, timeout=5)
    run = await load_run(app, run_id)

    assert outcome == "cancelled"
    assert run.status == "cancelled"
    assert next(phase for phase in run.phases if phase.phase_type == "execution").status == "cancelled"


@pytest.mark.asyncio
async def test_orchestrator_rerun_marks_downstream_phases_stale(app, client, test_settings, project_dir) -> None:
    run_id = await _create_run_with_finalized_exploration(app, project_dir, retry_limit=0)
    planning_session = FakeCopilotSession(["Planning output"], fail_on_attempt=[1])
    set_session_factory(
        SessionFactoryQueue(
            [
                FakeCopilotSession(["Exploration response", _planning_prompt()]),
                planning_session,
            ]
        )
    )

    runtime = WorkflowRuntime()
    first_outcome = await drive_workflow(app, test_settings, run_id, runtime)
    rerun_response = await client.post(f"/api/v1/runs/{run_id}/rerun", json={"from_phase_type": "planning"})
    run = await load_run(app, run_id)

    assert first_outcome == "failed"
    assert rerun_response.status_code == 200
    assert next(phase for phase in run.phases if phase.phase_type == "planning").status == "queued"
    assert all(
        phase.status == "stale"
        for phase in run.phases
        if phase.phase_type in {"plan_critique", "plan_correction", "execution", "review"}
    )
