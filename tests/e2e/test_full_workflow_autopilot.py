import pytest


@pytest.mark.asyncio
async def test_full_workflow_autopilot_smoke(client, project_dir) -> None:
    project = (await client.post("/api/v1/projects", json={"path": str(project_dir)})).json()
    run = (await client.post("/api/v1/runs", json={"project_id": project["id"], "name": "Autopilot"})).json()
    assert run["status"] == "queued"
    assert len(run["phases"]) == 6
