import pytest


@pytest.mark.asyncio
async def test_exploration_message_context_and_finalize(client, project_dir) -> None:
    project = (await client.post("/api/v1/projects", json={"path": str(project_dir)})).json()
    run = (await client.post("/api/v1/runs", json={"project_id": project["id"], "name": "Explore"})).json()

    message = await client.post(f"/api/v1/runs/{run['id']}/exploration/messages", json={"content": "Need a plan"})
    assert message.status_code == 200

    context = await client.put(
        f"/api/v1/runs/{run['id']}/exploration/context",
        json={"context_paths": [str(project_dir / 'src')]},
    )
    assert context.status_code == 200

    finalize = await client.post(f"/api/v1/runs/{run['id']}/exploration/finalize")
    assert finalize.status_code == 200
    assert finalize.json()["finalize_requested"] is True
