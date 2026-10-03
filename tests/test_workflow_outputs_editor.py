"""Output selectors over worktree artifacts and the workflow editor service."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path

import pytest

from relay.errors import (
    OutputValidationError,
    PermissionFlowError,
    ProjectDiscoveryError,
    WorkflowValidationError,
)
from relay.execution.state import DraftValidationState
from relay.workflows.editor import (
    autosave_workflow_draft,
    read_workflow_document,
    save_workflow_document,
)
from relay.workflows.outputs import extract_output, extract_outputs
from relay.workflows.schema import (
    ExistsSelector,
    JsonPathSelector,
    LabelSelector,
    YamlPathSelector,
)
from tests.support import symlink_or_skip

VALID = "version: 1\nname: Saved\nnodes: {}\n"


def _label(artifact: str, label: str) -> LabelSelector:
    return LabelSelector.model_validate({"label": {"artifact": artifact, "label": label}})


def _json(artifact: str, path: str) -> JsonPathSelector:
    return JsonPathSelector.model_validate({"json_path": {"artifact": artifact, "path": path}})


def _yaml(artifact: str, path: str) -> YamlPathSelector:
    return YamlPathSelector.model_validate({"yaml_path": {"artifact": artifact, "path": path}})


@dataclass
class _MemoryDrafts:
    drafts: dict[tuple[str, str], dict[str, object]] = field(default_factory=dict)

    def get_draft(self, project_id: str, workflow_key: str) -> dict[str, object] | None:
        return self.drafts.get((project_id, workflow_key))

    def save_draft(
        self,
        project_id: str,
        workflow_key: str,
        yaml_text: str,
        base_hash: str,
        validation_state: DraftValidationState,
    ) -> dict[str, object]:
        draft = {"yaml": yaml_text, "base_hash": base_hash, "state": validation_state.value}
        self.drafts[(project_id, workflow_key)] = draft
        return draft

    def discard_draft(self, project_id: str, workflow_key: str) -> None:
        self.drafts.pop((project_id, workflow_key), None)


@pytest.fixture
def relay_root(tmp_path: Path) -> Path:
    root = tmp_path / ".relay"
    (root / "workflows" / "nested").mkdir(parents=True)
    (root / "workflows" / "main.yaml").write_text(VALID, encoding="utf-8")
    (root / "workflows" / "nested" / "child.yml").write_text(VALID, encoding="utf-8")
    return root


def test_selectors_read_values_from_artifacts(tmp_path: Path) -> None:
    (tmp_path / "report.md").write_text("Intro\nReady: Yes\nReady: No\n", encoding="utf-8")
    (tmp_path / "data.json").write_text('{"build": {"status": "green"}}', encoding="utf-8")
    (tmp_path / "data.yaml").write_text("build:\n  count: 3\n", encoding="utf-8")

    outputs = extract_outputs(
        tmp_path,
        {
            "present": ExistsSelector(exists="report.md"),
            "absent": ExistsSelector(exists="missing.md"),
            "ready": _label("report.md", "Ready"),
            "status": _json("data.json", "build.status"),
            "count": _yaml("data.yaml", "build.count"),
        },
    )

    assert outputs == {
        "present": True,
        "absent": False,
        "ready": "Yes",
        "status": "green",
        "count": 3,
    }


@pytest.mark.parametrize(
    ("files", "selector"),
    [
        ({}, _label("missing.md", "Ready")),
        ({"report.md": "ready: Yes\n"}, _label("report.md", "Ready")),
        ({"data.json": "{"}, _json("data.json", "a")),
        ({"data.yaml": "a: [\n"}, _yaml("data.yaml", "a")),
        ({"data.json": '{"a": 1}'}, _json("data.json", "a.b")),
        ({"data.json": '{"a": 1}'}, _json("data.json", "a..b")),
        ({}, ExistsSelector(exists="../escape.md")),
    ],
)
def test_an_unusable_artifact_fails_output_validation(
    tmp_path: Path,
    files: dict[str, str],
    selector: LabelSelector | JsonPathSelector | YamlPathSelector | ExistsSelector,
) -> None:
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="utf-8")

    with pytest.raises(OutputValidationError):
        extract_output(tmp_path, selector)


def test_an_artifact_that_is_not_utf8_fails_output_validation(tmp_path: Path) -> None:
    (tmp_path / "report.md").write_bytes(b"\xff\xfe")

    with pytest.raises(OutputValidationError):
        extract_output(tmp_path, _label("report.md", "Ready"))


@pytest.mark.parametrize(
    ("text", "state"),
    [("nodes: [", DraftValidationState.INVALID), (VALID, DraftValidationState.VALID)],
)
def test_an_autosaved_draft_is_labeled_by_validity_and_read_back(
    relay_root: Path, text: str, state: DraftValidationState
) -> None:
    store = _MemoryDrafts()

    draft = autosave_workflow_draft(store, relay_root, "p1", "main", text, "h")

    assert draft["state"] == state.value
    assert read_workflow_document(store, relay_root, "p1", "main").draft == draft


def test_saving_replaces_the_file_and_discards_the_draft(relay_root: Path) -> None:
    store = _MemoryDrafts()
    autosave_workflow_draft(store, relay_root, "p1", "main", "nodes: [", "h")
    base = read_workflow_document(store, relay_root, "p1", "main").base_hash
    updated = "version: 1\nname: Updated\nnodes: {}\n"

    save_workflow_document(store, relay_root, "p1", "main", updated, base)

    assert (relay_root / "workflows" / "main.yaml").read_text(encoding="utf-8") == updated
    assert store.get_draft("p1", "main") is None


def test_a_nested_key_with_an_explicit_suffix_is_read(relay_root: Path) -> None:
    document = read_workflow_document(_MemoryDrafts(), relay_root, "p1", "nested/child.yml")

    assert document.yaml == VALID


def test_saving_over_a_changed_file_is_refused(relay_root: Path) -> None:
    with pytest.raises(PermissionFlowError):
        save_workflow_document(_MemoryDrafts(), relay_root, "p1", "main", VALID, "0" * 64)


def test_saving_invalid_text_is_refused(relay_root: Path) -> None:
    store = _MemoryDrafts()
    base = read_workflow_document(store, relay_root, "p1", "main").base_hash

    with pytest.raises(WorkflowValidationError):
        save_workflow_document(store, relay_root, "p1", "main", "nodes: [", base)


@pytest.mark.parametrize("key", ["missing", "nested/absent.yaml", "main.yaml/extra"])
def test_an_unknown_workflow_key_does_not_exist(relay_root: Path, key: str) -> None:
    with pytest.raises(ProjectDiscoveryError):
        read_workflow_document(_MemoryDrafts(), relay_root, "p1", key)


def test_a_key_cannot_follow_a_link_outside_the_workflow_root(
    relay_root: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.yaml"
    outside.write_text(VALID, encoding="utf-8")
    symlink_or_skip(relay_root / "workflows" / "linked.yaml", outside)

    with pytest.raises(ProjectDiscoveryError):
        read_workflow_document(_MemoryDrafts(), relay_root, "p1", "linked")


def test_a_failed_replacement_is_reported_without_leaving_a_temporary_file(
    relay_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _MemoryDrafts()
    base = read_workflow_document(store, relay_root, "p1", "main").base_hash

    def disk_full(source: object, target: object) -> None:
        del source, target
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "replace", disk_full)

    with pytest.raises(WorkflowValidationError):
        save_workflow_document(store, relay_root, "p1", "main", VALID, base)
    assert sorted(path.name for path in (relay_root / "workflows").iterdir()) == [
        "main.yaml",
        "nested",
    ]


@pytest.mark.parametrize(
    "operation",
    ["read", "save"],
)
def test_a_workflow_file_that_is_not_utf8_cannot_be_read_or_saved(
    relay_root: Path, operation: str
) -> None:
    (relay_root / "workflows" / "main.yaml").write_bytes(b"\xff\xfe")

    with pytest.raises(WorkflowValidationError):
        if operation == "read":
            read_workflow_document(_MemoryDrafts(), relay_root, "p1", "main")
        else:
            save_workflow_document(_MemoryDrafts(), relay_root, "p1", "main", VALID, "0" * 64)
