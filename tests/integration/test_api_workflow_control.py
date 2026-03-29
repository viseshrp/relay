import pytest
from sqlalchemy import select

from relay.artifacts.manager import save_artifact
from relay.models import WorkflowRun


@pytest.mark.asyncio
async def test_advance_cancel_and_rerun(client, app, project_dir) -> None:
    project = (await client.post("/api/v1/projects", json={"path": str(project_dir)})).json()
    run = (await client.post("/api/v1/runs", json={"project_id": project["id"], "name": "Control"})).json()

    async with app.state.db.session() as session:
        db_run = (await session.execute(select(WorkflowRun).where(WorkflowRun.id == run["id"]))).scalar_one()
        exploration_phase = next(phase for phase in db_run.phases if phase.phase_type == "exploration")
        db_run.status = "waiting_for_user"
        exploration_phase.status = "waiting_for_user"
        await session.commit()

    advance = await client.post(f"/api/v1/runs/{run['id']}/advance")
    assert advance.status_code == 200
    assert advance.json()["status"] == "running"

    cancel = await client.post(f"/api/v1/runs/{run['id']}/cancel")
    assert cancel.status_code == 200

    rerun = await client.post(f"/api/v1/runs/{run['id']}/rerun", json={"from_phase_type": "planning"})
    assert rerun.status_code == 200
    assert rerun.json()["status"] == "running"


@pytest.mark.asyncio
async def test_review_fix_prompt_preview_endpoint(client, app, project_dir) -> None:
    project = (await client.post("/api/v1/projects", json={"path": str(project_dir)})).json()
    run = (await client.post("/api/v1/runs", json={"project_id": project["id"], "name": "Review"})).json()

    save_artifact(str(project_dir), run["id"], "planning", "SPEC.md", "# Spec")
    save_artifact(str(project_dir), run["id"], "plan_correction", "IMPLEMENTATION_PLAN.md", "# Plan")
    save_artifact(
        str(project_dir),
        run["id"],
        "review",
        "REVIEW_SUMMARY.md",
        "## Summary\nLooks good.\n\n## Verdict\nFAIL\n",
    )
    save_artifact(str(project_dir), run["id"], "review", "REVIEW_COMMENTS.json", "[]")

    preview = await client.get(f"/api/v1/runs/{run['id']}/review/fix-prompt")

    assert preview.status_code == 200
    assert "REVIEW_SUMMARY.md" in preview.json()["prompt"]
