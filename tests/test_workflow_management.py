"""Owner management protects current edits and retains historical records."""

from __future__ import annotations

from django.test import Client
import pytest

from relay.web.models import WorkflowControl
from tests.support import RelayProject
from tests.test_editor_recovery import SOURCE, owner, post

__all__ = ["owner"]


def test_management_requires_a_lease_and_unchanged_source(
    owner: Client, project: RelayProject
) -> None:
    path = "/api/workflows/check.yaml"
    document = owner.get(path).json()
    body = {
        "action": "rename",
        "holder": "tab",
        "base_hash": document["base_hash"],
        "new_key": "renamed.yaml",
        "name": "Renamed",
    }
    assert post(owner, path + "/manage", body).status_code == 409
    assert post(owner, path + "/lease", {"holder": "tab"}).status_code == 200
    project.write(".relay/workflows/check.yaml", SOURCE + "# owner changed this\n")
    assert post(owner, path + "/manage", body).status_code == 409
    assert not (project.repository / ".relay/workflows/renamed.yaml").exists()


def test_duplicate_rename_disable_and_delete_preserve_shared_files(
    owner: Client, project: RelayProject
) -> None:
    path = "/api/workflows/check.yaml"
    document = owner.get(path).json()
    post(owner, path + "/lease", {"holder": "tab"})
    project.write(".relay/prompts/shared.md", "Shared instructions\n")
    body = {
        "holder": "tab",
        "base_hash": document["base_hash"],
        "new_key": "copy.yaml",
        "name": "Copy",
    }
    assert post(owner, path + "/manage", {**body, "action": "duplicate"}).status_code == 200
    assert (project.repository / ".relay/workflows/check.yaml").read_text() == SOURCE
    assert "Copy" in (project.repository / ".relay/workflows/copy.yaml").read_text()
    result = post(owner, path + "/manage", {**body, "action": "rename", "new_key": "renamed.yaml"})
    assert result.status_code == 200
    path = "/api/workflows/renamed.yaml"
    body["base_hash"] = owner.get(path).json()["base_hash"]
    assert post(owner, path + "/manage", {**body, "action": "disable"}).status_code == 200
    disabled = next(
        row
        for row in owner.get("/api/workflows").json()["workflows"]
        if row["key"] == "renamed.yaml"
    )
    assert disabled["disabled"] is True
    assert (
        post(owner, "/api/runs", {"workflow_key": "renamed.yaml", "inputs": {}}).status_code == 409
    )
    assert post(owner, path + "/manage", {**body, "action": "enable"}).status_code == 200
    assert not WorkflowControl.objects.get(workflow_key="renamed.yaml").disabled
    assert post(owner, path + "/manage", {**body, "action": "delete"}).status_code == 400
    assert (
        post(owner, path + "/manage", {**body, "action": "delete", "confirmed": True}).status_code
        == 200
    )
    assert owner.get(path).status_code == 404
    assert (project.repository / ".relay/prompts/shared.md").read_text() == "Shared instructions\n"


@pytest.mark.parametrize("action", ["rename", "delete"])
def test_referenced_workflows_cannot_be_removed(
    owner: Client, project: RelayProject, action: str
) -> None:
    project.write(
        ".relay/workflows/parent.yaml", "jobs:\n  reuse:\n    uses: ./.relay/workflows/check.yaml\n"
    )
    path = "/api/workflows/check.yaml"
    post(owner, path + "/lease", {"holder": "tab"})
    result = post(
        owner,
        path + "/manage",
        {
            "action": action,
            "holder": "tab",
            "base_hash": owner.get(path).json()["base_hash"],
            "new_key": "new.yaml",
            "confirmed": True,
        },
    )
    assert result.status_code == 409
    assert "parent.yaml" in result.json()["message"]
    assert (project.repository / ".relay/workflows/check.yaml").exists()
