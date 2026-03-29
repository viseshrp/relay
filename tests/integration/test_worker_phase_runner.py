import pytest
from sqlalchemy import select

from relay.artifacts.manager import read_artifact, save_artifact
from relay.copilot.session import set_session_factory
from relay.models import WorkflowRun
from relay.schemas.run import RunCreateRequest
from relay.worker.phase_runner import run_standard_phase
from tests.mocks.fake_copilot import FakeCopilotSession


@pytest.mark.asyncio
async def test_phase_runner_writes_attempt_and_artifacts(app, test_settings, project_dir) -> None:
    async with app.state.db.session() as session:
        project = await app.state.project_service.create_project(session, str(project_dir))
        run = await app.state.run_service.create_run(session, RunCreateRequest(project_id=project.id, name="Plan"))
        save_artifact(str(project_dir), run.id, "exploration", "planning_prompt.md", "Build a feature.")

    set_session_factory(lambda: FakeCopilotSession(["Spec and plan output"]))

    async with app.state.db.session() as session:
        db_run = (await session.execute(select(WorkflowRun).where(WorkflowRun.id == run.id))).scalar_one()
        phase = next(item for item in db_run.phases if item.phase_type == "planning")

    result, _session = await run_standard_phase(
        app.state.db,
        test_settings,
        run_id=run.id,
        phase_id=phase.id,
        phase_type="planning",
    )
    assert result.success is True
    assert "Spec and plan output" in read_artifact(str(project_dir), run.id, "planning", "SPEC.md")


@pytest.mark.asyncio
async def test_phase_runner_passes_selected_phase_model_to_copilot(app, test_settings, project_dir) -> None:
    async with app.state.db.session() as session:
        project = await app.state.project_service.create_project(session, str(project_dir))
        run = await app.state.run_service.create_run(
            session,
            RunCreateRequest(
                project_id=project.id,
                name="Plan with model override",
                phase_model_mapping={"planning": "gpt-5.4"},
            ),
        )
        save_artifact(str(project_dir), run.id, "exploration", "planning_prompt.md", "Build a feature.")

    fake_session = FakeCopilotSession(["Spec and plan output"])
    set_session_factory(lambda: fake_session)

    async with app.state.db.session() as session:
        db_run = (await session.execute(select(WorkflowRun).where(WorkflowRun.id == run.id))).scalar_one()
        phase = next(item for item in db_run.phases if item.phase_type == "planning")

    result, _session = await run_standard_phase(
        app.state.db,
        test_settings,
        run_id=run.id,
        phase_id=phase.id,
        phase_type="planning",
    )

    assert result.success is True
    assert len(fake_session.started_commands) == 1
    assert fake_session.started_commands[0][1:] == [
        "--output-format",
        "text",
        "--stream",
        "off",
        "--allow-all-tools",
        "--allow-all-paths",
        "--no-ask-user",
        "--model",
        "gpt-5.4",
    ]
