"""YAML loading and workflow path boundaries on every supported platform."""

from __future__ import annotations

from pathlib import Path

import pytest

from relay.errors import WorkflowValidationError
from relay.workflows.loader import (
    load_workflow,
    load_workflow_text,
    resolve_workflow_path,
    workflow_key_parts,
)
from tests.support import symlink_or_skip


def _write(root: Path, name: str, text: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ("jobs: [", WorkflowValidationError),
        ("- a\n- b\n", WorkflowValidationError),
        ("jobs: {work: {steps: invalid}}\n", WorkflowValidationError),
        ("name: Missing jobs\n", WorkflowValidationError),
        ("name: a\nname: b\njobs: {}\n", WorkflowValidationError),
    ],
)
def test_an_invalid_document_is_rejected(text: str, error: type[Exception]) -> None:
    with pytest.raises(error):
        load_workflow_text(text)


def test_a_workflow_file_is_read_as_utf8(tmp_path: Path) -> None:
    path = _write(
        tmp_path, "workflow.yaml", "name: Ünïcode\njobs: {main: {steps: [{run: echo ready}]}}\n"
    )

    assert load_workflow(path).definition.name == "Ünïcode"


def test_a_file_that_is_not_utf8_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yaml"
    path.write_bytes(b"\xff\xfe")

    with pytest.raises(WorkflowValidationError):
        load_workflow(path)


@pytest.mark.parametrize(
    ("key", "parts"),
    [
        ("review", ("review.yaml",)),
        ("nested/review.yml", ("nested", "review.yml")),
        ("nested/review.yaml", ("nested", "review.yaml")),
    ],
)
def test_a_workflow_key_maps_to_a_relative_yaml_path(key: str, parts: tuple[str, ...]) -> None:
    assert workflow_key_parts(key) == parts


@pytest.mark.parametrize("key", ["", "nested\\review", "../x", "a//b", "./a", "notes.txt"])
def test_an_invalid_workflow_key_is_rejected_on_every_platform(key: str) -> None:
    with pytest.raises(WorkflowValidationError):
        workflow_key_parts(key)


def test_a_subworkflow_link_outside_the_workflow_root_is_rejected(tmp_path: Path) -> None:
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    outside = _write(
        tmp_path, "outside.yaml", "jobs: {main: {steps: [{run: print(1), shell: python}]}}\n"
    )
    symlink_or_skip(workflows / "link.yaml", outside)

    with pytest.raises(WorkflowValidationError):
        resolve_workflow_path(workflows, "link")


def test_a_yaml_key_that_resolves_to_another_suffix_is_rejected(tmp_path: Path) -> None:
    workflows = tmp_path / "workflows"
    notes = _write(workflows, "notes.txt", "not a workflow")
    symlink_or_skip(workflows / "alias.yaml", notes)

    with pytest.raises(WorkflowValidationError):
        resolve_workflow_path(workflows, "alias")
