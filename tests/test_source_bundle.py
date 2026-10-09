"""A single save publishes all source bytes or recovers the previous bundle."""

from __future__ import annotations

from hashlib import sha256
import json

from django.test import Client
import pytest

from relay.errors import WorkflowValidationError
from relay.workflows import source_bundle
from tests.support import RelayProject
from tests.test_editor_recovery import SOURCE, owner, post

__all__ = ["owner"]


def test_source_bundle_save_and_draft_recovery(owner: Client, project: RelayProject) -> None:
    path = "/api/workflows/check.yaml"
    post(owner, path + "/lease", {"holder": "tab"})
    body = {
        "holder": "tab",
        "yaml": SOURCE.replace("Recovery", "Updated"),
        "base_hash": owner.get(path).json()["base_hash"],
        "prompts": {
            "prompts/new.md": {"text": "# Instructions\nDo the work.\n", "base_hash": None}
        },
    }
    assert post(owner, path + "/draft", body).status_code == 200
    assert owner.get(path).json()["draft"]["prompts"] == body["prompts"]
    assert not (project.repository / ".relay/prompts/new.md").exists()
    assert post(owner, path + "/save", body).status_code == 200
    assert (
        project.repository / ".relay/prompts/new.md"
    ).read_text() == "# Instructions\nDo the work.\n"
    document = owner.get(path).json()
    assert document["draft"] is None and document["yaml"] == body["yaml"]
    assert post(owner, path + "/save", body).status_code == 409
    assert owner.get(path).json()["yaml"] == body["yaml"]


def test_literal_prompt_preflight_preserves_the_launch_exemptions(
    owner: Client, project: RelayProject
) -> None:
    from relay.execution.preflight import inspect_launch_cleanliness

    text = (
        "jobs:\n  check:\n    steps:\n      - uses: relay/agent@v1\n"
        "        with: {agent: codex, model: m1, prompt-files: prompts/instructions.md}\n"
    )
    project.write(".relay/workflows/check.yaml", text)
    project.write(".relay/prompts/instructions.md", "Captured instructions\n")
    project.write(".relay/prompts/unused.md", "Unrelated instructions\n")
    preview = inspect_launch_cleanliness(project.relay_root, "check.yaml")
    files = {row.path: row.allowed for row in preview.files}
    assert files[".relay/prompts/instructions.md"] is True
    assert files[".relay/prompts/unused.md"] is False


def test_validation_failure_rolls_back_prompts_even_when_yaml_is_unchanged(
    owner: Client, project: RelayProject, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = "/api/workflows/check.yaml"
    post(owner, path + "/lease", {"holder": "tab"})
    prompt = project.write(".relay/prompts/existing.md", "Original\n")

    def reject(*_args: object, **_kwargs: object) -> None:
        message = "Missing reusable source"
        raise WorkflowValidationError(message)

    monkeypatch.setattr("relay.workflows.validation.validate_loaded_workflow", reject)
    body = {
        "holder": "tab",
        "yaml": SOURCE,
        "base_hash": owner.get(path).json()["base_hash"],
        "prompts": {
            "prompts/existing.md": {
                "text": "Changed\n",
                "base_hash": sha256(b"Original\n").hexdigest(),
            },
            "prompts/new.md": {"text": "New\n", "base_hash": None},
        },
    }
    assert post(owner, path + "/save", body).status_code == 422
    assert prompt.read_text() == "Original\n"
    assert not (project.repository / ".relay/prompts/new.md").exists()
    assert (project.repository / ".relay/workflows/check.yaml").read_text() == SOURCE


def test_restart_recovers_an_interrupted_bundle_and_refuses_foreign_edits(
    project: RelayProject,
) -> None:
    root = project.repository / ".relay"
    prompt = project.write(".relay/prompts/existing.md", "Partial\n")
    journal = source_bundle._journal(root)
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text(
        json.dumps(
            {
                "owner": str(root.resolve()),
                "files": {"prompts/existing.md": {"old": "Original\n", "new": "Partial\n"}},
            }
        )
    )
    with source_bundle.source_lock(root):
        assert prompt.read_text() == "Original\n"
    assert not journal.exists()
    journal.write_text(
        json.dumps(
            {
                "owner": str(root.resolve()),
                "files": {"prompts/existing.md": {"old": "Old\n", "new": "Partial\n"}},
            }
        )
    )
    with pytest.raises(source_bundle.PermissionFlowError), source_bundle.source_lock(root):
        pass
    assert prompt.read_text() == "Original\n" and journal.exists()
