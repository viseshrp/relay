import pytest
from sqlalchemy import select

from relay.models import WorkflowRun
from relay.schemas.run import RunCreateRequest
from relay.worker.orchestrator import WorkflowRuntime, advance_workflow
from relay.worker.phase_runner import PhaseExecutionResult


@pytest.mark.asyncio
async def test_orchestrator_pauses_after_exploration_when_manual(app, test_settings, monkeypatch, project_dir) -> None:
    async with app.state.db.session() as session:
        project = await app.state.project_service.create_project(session, str(project_dir))
        run = await app.state.run_service.create_run(
            session,
            RunCreateRequest(project_id=project.id, name="Manual", autopilot=False),
        )

    async def fake_exploration(*args, **kwargs):
        async with app.state.db.session() as session:
            db_run = (await session.execute(select(WorkflowRun).where(WorkflowRun.id == run.id))).scalar_one()
            exploration_phase = next(phase for phase in db_run.phases if phase.phase_type == "exploration")
            exploration_phase.status = "running"
            await session.commit()
        return PhaseExecutionResult(True, 1, 0, raw_output="prompt"), None

    monkeypatch.setattr("relay.worker.orchestrator.run_exploration_phase", fake_exploration)

    result = await advance_workflow(app.state.db, test_settings, run_id=run.id, runtime=WorkflowRuntime())
    assert result == "waiting_for_user"

    async with app.state.db.session() as session:
        db_run = (await session.execute(select(WorkflowRun).where(WorkflowRun.id == run.id))).scalar_one()
        assert db_run.status == "waiting_for_user"
