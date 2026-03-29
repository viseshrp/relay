import pytest


@pytest.mark.asyncio
async def test_create_and_list_runs(client, project_dir) -> None:
    project = (await client.post("/api/v1/projects", json={"path": str(project_dir)})).json()
    response = await client.post("/api/v1/runs", json={"project_id": project["id"], "name": "Test workflow"})
    assert response.status_code == 200
    run = response.json()

    detail = await client.get(f"/api/v1/runs/{run['id']}")
    assert detail.status_code == 200
    assert detail.json()["name"] == "Test workflow"

    listing = await client.get(f"/api/v1/runs?project_id={project['id']}")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
