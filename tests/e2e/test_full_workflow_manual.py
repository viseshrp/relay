import pytest


@pytest.mark.asyncio
async def test_full_workflow_manual_smoke(client, project_dir) -> None:
    project = (await client.post("/api/v1/projects", json={"path": str(project_dir)})).json()
    run = (
        await client.post(
            "/api/v1/runs",
            json={"project_id": project["id"], "name": "Manual", "autopilot": False},
        )
    ).json()
    assert run["autopilot"] is False
