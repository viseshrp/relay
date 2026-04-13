import pytest
from sqlalchemy import select

from relay.models import WorkflowRun


@pytest.mark.asyncio
async def test_create_and_list_runs(client, app, project_dir) -> None:
    project = (await client.post("/api/v1/projects", json={"path": str(project_dir)})).json()
    response = await client.post("/api/v1/runs", json={"project_id": project["id"], "name": "Test workflow"})
    assert response.status_code == 200
    run = response.json()

    detail = await client.get(f"/api/v1/runs/{run['id']}")
    assert detail.status_code == 200
    assert detail.json()["name"] == "Test workflow"

    second = (await client.post("/api/v1/runs", json={"project_id": project["id"], "name": "Second workflow"})).json()
    async with app.state.db.session() as session:
        second_run = (await session.execute(select(WorkflowRun).where(WorkflowRun.id == second["id"]))).scalar_one()
        second_run.status = "failed"
        await session.commit()

    listing = await client.get(f"/api/v1/runs?project_id={project['id']}")
    assert listing.status_code == 200
    assert listing.json()["total"] == 2

    filtered = await client.get(f"/api/v1/runs?project_id={project['id']}&status=queued,failed")
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 2
