import pytest


@pytest.mark.asyncio
async def test_project_crud_and_file_tree(client, project_dir) -> None:
    response = await client.post("/api/v1/projects", json={"path": str(project_dir)})
    assert response.status_code == 200
    project = response.json()

    list_response = await client.get("/api/v1/projects")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    file_tree_response = await client.get(f"/api/v1/projects/{project['id']}/files")
    assert file_tree_response.status_code == 200
    assert any(node["name"] == "src" for node in file_tree_response.json())
