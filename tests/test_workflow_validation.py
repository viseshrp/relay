"""Cross-file validation, typed launch inputs, prompts, routes, and snapshots."""

from __future__ import annotations

from pathlib import Path

import pytest

from relay.errors import PromptResolutionError, WorkflowValidationError
from relay.workflows.loader import load_workflow
from relay.workflows.prompts import resolve_prompt
from relay.workflows.routing import (
    RouteEntry,
    RouteRequirement,
    effective_agent_order,
    serialize_route_table,
)
from relay.workflows.schema import (
    BooleanInput,
    EnumConstraints,
    EnumInput,
    GlobalPrompt,
    InputDefinition,
    IntegerInput,
    LocalPrompt,
    NumberConstraints,
    NumberInput,
    StringConstraints,
    StringInput,
)
from relay.workflows.validation import (
    ValidatedWorkflow,
    resolve_inputs,
    validate_loaded_workflow,
)
from tests.support import symlink_or_skip


def _relay_root(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / ".relay"
    (root / "workflows").mkdir(parents=True)
    (root / "prompts").mkdir()
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def _validate(root: Path, key: str = "workflows/main.yaml") -> ValidatedWorkflow:
    return validate_loaded_workflow(load_workflow(root / key), root)


def _inputs_definition() -> dict[str, InputDefinition]:
    return {
        "name": StringInput(
            type="string",
            required=True,
            constraints=StringConstraints(min_length=2, max_length=4, pattern="^[a-z]+$"),
        ),
        "count": IntegerInput(
            type="integer", default=2, constraints=NumberConstraints(min=1, max=3)
        ),
        "ratio": NumberInput(type="number", constraints=NumberConstraints(min=0.5, max=1.5)),
        "flag": BooleanInput(type="boolean"),
        "mode": EnumInput(type="enum", default="a", constraints=EnumConstraints(values=["a", "b"])),
        "note": StringInput(type="string"),
    }


def test_launch_inputs_receive_defaults_without_coercion() -> None:
    resolved = resolve_inputs(_inputs_definition(), {"name": "abc", "ratio": 1, "flag": False})

    assert resolved == {
        "name": "abc",
        "count": 2,
        "ratio": 1,
        "flag": False,
        "mode": "a",
        "note": None,
    }


@pytest.mark.parametrize(
    "supplied",
    [
        {},
        {"name": "abc", "bogus": 1},
        {"name": 5},
        {"name": "a"},
        {"name": "abcdef"},
        {"name": "AB1"},
        {"name": "abc", "count": "2"},
        {"name": "abc", "count": True},
        {"name": "abc", "count": 0},
        {"name": "abc", "count": 4},
        {"name": "abc", "ratio": "1"},
        {"name": "abc", "flag": 1},
        {"name": "abc", "mode": "c"},
    ],
)
def test_an_invalid_launch_input_is_rejected(supplied: dict[str, object]) -> None:
    with pytest.raises(WorkflowValidationError):
        resolve_inputs(_inputs_definition(), supplied)


def test_a_rejected_choice_names_the_allowed_values() -> None:
    with pytest.raises(WorkflowValidationError, match="input 'mode' must be one of a, b"):
        resolve_inputs(_inputs_definition(), {"name": "abc", "mode": "c"})


def test_a_local_prompt_resolves_to_its_text_and_digest(tmp_path: Path) -> None:
    root = _relay_root(tmp_path, {"prompts/a.md": "text"})

    resolved = resolve_prompt(LocalPrompt(local="prompts/a.md"), root)

    assert resolved.to_dict()["content"] == "text"
    assert resolved.sha256 == "982d9e3eb996f559e633f4d194def3761d909f5a3b647d1a851fead67c32c9d1"


@pytest.mark.parametrize(
    "reference",
    [
        LocalPrompt(local="../outside.md"),
        GlobalPrompt.model_validate({"global": "none.md"}),
        LocalPrompt(local="prompts/bad.md"),
    ],
)
def test_an_unsafe_missing_or_unreadable_prompt_is_rejected(
    tmp_path: Path, reference: LocalPrompt | GlobalPrompt
) -> None:
    root = _relay_root(tmp_path, {})
    (root / "prompts" / "bad.md").write_bytes(b"\xff\xfe")

    with pytest.raises(PromptResolutionError):
        resolve_prompt(reference, root)


def test_a_prompt_link_outside_the_relay_root_is_rejected(tmp_path: Path) -> None:
    root = _relay_root(tmp_path, {})
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    symlink_or_skip(root / "prompts" / "link.md", outside)

    with pytest.raises(PromptResolutionError):
        resolve_prompt(LocalPrompt(local="prompts/link.md"), root)


def test_the_route_table_serializes_requirements_and_selections() -> None:
    entries = [
        RouteRequirement("root.a", "m", ("codex",)),
        RouteEntry("root.b", "m", ("codex", "cursor"), selected_agent="cursor"),
    ]

    assert serialize_route_table(entries) == {
        "root.a": {"model_value": "m", "effective_agent_order": ["codex"]},
        "root.b": {
            "model_value": "m",
            "effective_agent_order": ["codex", "cursor"],
            "selected_agent": "cursor",
        },
    }


def test_agent_order_concatenates_preferences_without_duplicates() -> None:
    assert effective_agent_order(["a", "b"], ["b", "c"], ["a"]) == ("a", "b", "c")
