"""Editor recovery remains usable across tabs without losing another edit."""

from __future__ import annotations

import json
from typing import Any

from django.http import HttpResponse
from django.test import Client
import pytest

from relay.web.models import EditorLease
from relay.workflows.actions.language import workflow_diagnostics
from tests.support import RelayProject, git

SOURCE = "name: Recovery\njobs: {check: {steps: [{run: echo Ready}]}}\n"


def post(client: Client, path: str, body: dict[str, Any]) -> HttpResponse:
    return client.post(path, json.dumps(body), content_type="application/json")


@pytest.fixture
def owner(project: RelayProject, monkeypatch: pytest.MonkeyPatch) -> Client:
    monkeypatch.setenv("RELAY_PROJECT_ROOT", str(project.repository))
    client = Client()
    response = post(
        client,
        "/api/auth/onboard",
        {
            "username": "owner",
            "password": "Relay-Test-Passphrase-2026!",
        },
    )
    assert response.status_code == 201
    project.write_workflow("check", SOURCE)
    return client


def test_takeover_invalidates_writes_and_old_release_cannot_release_the_new_tab(
    owner: Client,
) -> None:
    path = "/api/workflows/check.yaml"
    assert post(owner, path + "/lease", {"holder": "first"}).status_code == 200
    conflict = post(owner, path + "/lease", {"holder": "second", "soft_conflict": True})
    assert conflict.status_code == 200 and conflict.json()["lease"] is None
    assert post(owner, path + "/lease", {"holder": "second", "takeover": True}).status_code == 200
    document = owner.get(path).json()
    edit = {"holder": "first", "yaml": SOURCE, "base_hash": document["base_hash"]}
    assert post(owner, path + "/save", edit).status_code == 409
    assert post(owner, path + "/lease/release", {"holder": "first"}).status_code == 200
    edit["holder"] = "second"
    assert post(owner, path + "/save", edit).status_code == 200
    assert owner.post(path + "/lease/release", {"holder": "second"}).status_code == 200
    assert post(owner, path + "/lease", {"holder": "first"}).status_code == 200


def test_draft_discard_needs_no_lease_but_rejects_a_newer_draft(owner: Client) -> None:
    path = "/api/workflows/check.yaml"
    post(owner, path + "/lease", {"holder": "first"})
    document = owner.get(path).json()
    payload = {"holder": "first", "yaml": "jobs: [", "base_hash": document["base_hash"]}
    draft = post(owner, path + "/draft", payload).json()["draft"]
    assert draft["validation_state"] == "invalid"
    payload["yaml"] = "jobs: [newer"
    newer = post(owner, path + "/draft", payload).json()["draft"]
    assert (
        post(owner, path + "/draft/discard", {"updated_at": draft["updated_at"]}).status_code == 409
    )
    assert owner.get(path).json()["draft"]["yaml"] == payload["yaml"]
    assert (
        post(owner, path + "/draft/discard", {"updated_at": newer["updated_at"]}).status_code == 200
    )
    assert owner.get(path).json()["draft"] is None
    assert owner.get(path).json()["yaml"] == SOURCE


def test_failed_create_does_not_acquire_a_lease(owner: Client) -> None:
    response = post(owner, "/api/workflows", {"key": "bad", "holder": "tab", "yaml": "jobs: ["})
    assert response.status_code == 422
    assert not EditorLease.objects.filter(workflow_key="bad.yaml").exists()


def test_workflow_commit_requires_exact_reviewed_bytes_and_preserves_owner_files(
    owner: Client, project: RelayProject
) -> None:
    second = project.write(".relay/workflows/second.yaml", SOURCE.replace("Recovery", "Second"))
    project.write("REVIEW.md", "Owner report\n")
    project.write("unfinished.py", "Owner code\n")
    path = "/api/workflows/check.yaml/commit"
    preview = owner.get(path).json()
    assert [item["path"] for item in preview["files"]] == [".relay/workflows/second.yaml"]
    body = {
        "head": preview["head"],
        "hashes": {item["path"]: item["hash"] for item in preview["files"]},
    }
    assert post(owner, path, body).status_code == 400
    body["confirmed"] = True
    second.write_text(SOURCE.replace("Recovery", "Changed"), encoding="utf-8")
    assert post(owner, path, body).status_code == 409
    assert git(project.repository, "rev-parse", "HEAD") == preview["head"]
    preview = owner.get(path).json()
    body["hashes"] = {item["path"]: item["hash"] for item in preview["files"]}
    assert post(owner, path, body).status_code == 200
    assert (
        git(project.repository, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD")
        == ".relay/workflows/second.yaml"
    )
    assert git(project.repository, "diff", "--cached", "--name-only") == ""
    assert (project.repository / "REVIEW.md").read_text() == "Owner report\n"
    assert "unfinished.py" in git(project.repository, "status", "--porcelain")
    project.write(".relay/workflows/third.yaml", SOURCE)
    git(project.repository, "add", "unfinished.py")
    assert owner.get(path).status_code == 409


def test_independent_language_errors_are_reported_together_with_locations(owner: Client) -> None:
    text = (
        "jobs:\n  check:\n    runs-on: ubuntu-latest\n    container: alpine\n"
        "    steps:\n      - uses: actions/checkout@v4\n"
    )
    result = post(owner, "/api/workflow-language/validate", {"yaml": text}).json()
    assert result["valid"] is False
    assert len(result["diagnostics"]) == 3
    messages = "\n".join(item["message"] for item in result["diagnostics"])
    assert "Remove runs-on" in messages
    assert "local script" in messages
    assert "Only frozen local" in messages
    assert all(item["context"].get("line") for item in result["diagnostics"])


@pytest.mark.parametrize(
    "text",
    [
        'jobs:\n  check:\n    steps:\n      - run: echo "Task: example"\n',
        "jobs:\n\tcheck: {}\n",
        "jobs: [check\n",
        "jobs: {check\n",
        'name: "Unclosed\njobs: {}\n',
        'name: "bad\\q"\njobs: {}\n',
        "jobs: *missing\n",
        "jobs: {}\njobs: {}\n",
        "jobs: {}\n---\njobs: {}\n",
        "jobs:\n  check:\n    steps:\n     - run: echo ok\n      - run: echo bad\n",
    ],
)
def test_common_yaml_mistakes_include_a_reason_and_location(text: str) -> None:
    issues = workflow_diagnostics(text)
    assert issues
    assert issues[0].message != "Invalid YAML document."
    assert issues[0].context.get("line") or "Duplicate YAML key" in issues[0].message
