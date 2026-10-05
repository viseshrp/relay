"""Workflow version 1 schema: strict fields, typed inputs, and identifier rules."""

from __future__ import annotations

from pydantic import BaseModel, ValidationError
import pytest

from relay.workflows.schema import (
    CommandNode,
    EntryArtifact,
    EnumInput,
    NumberConstraints,
    StringConstraints,
    WorkflowDefinition,
)


def _workflow(**overrides: object) -> dict[str, object]:
    return {
        "version": 1,
        "name": "Example",
        "nodes": {"build": {"type": "command", "run": ["git", "status"]}},
        **overrides,
    }


def _errors(
    model: type[BaseModel], document: dict[str, object]
) -> list[tuple[str, tuple[str | int, ...]]]:
    with pytest.raises(ValidationError) as caught:
        model.model_validate(document)
    return [(error["type"], error["loc"]) for error in caught.value.errors()]


def test_every_node_type_validates() -> None:
    workflow = WorkflowDefinition.model_validate(
        _workflow(
            nodes={
                "review": {
                    "type": "agent",
                    "prompts": [{"local": "prompts/a.md"}, {"global": "b.md"}],
                    "outputs": {
                        "ready": {"label": {"artifact": "report.md", "label": "Ready"}},
                        "present": {"exists": "report.md"},
                        "status": {"json_path": {"artifact": "a.json", "path": "x.y"}},
                        "kind": {"yaml_path": {"artifact": "a.yaml", "path": "x"}},
                    },
                },
                "check": {"type": "command", "run": ["git", "status"], "env": {"A": "1"}},
                "approve": {"type": "human_wait", "prompt": "Go?", "deadline": "15m"},
                "choose": {"type": "condition", "expr": "${{ True }}", "branches": {"a": "x"}},
                "repeat": {
                    "type": "loop",
                    "max_iterations": 2,
                    "exhausted": "check",
                    "body": {"inner": {"type": "command", "run": ["git", "log"]}},
                },
                "child": {"type": "subworkflow", "workflow": "child", "inputs": {"n": 1}},
            }
        )
    )

    assert {node_id: node.type for node_id, node in workflow.nodes.items()} == {
        "review": "agent",
        "check": "command",
        "approve": "human_wait",
        "choose": "condition",
        "repeat": "loop",
        "child": "subworkflow",
    }


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        (_workflow(extra=True), ("extra_forbidden", ("extra",))),
        (
            _workflow(nodes={"a": {"type": "command", "run": "git status"}}),
            ("list_type", ("nodes", "a", "command", "run")),
        ),
        (
            _workflow(nodes={"a": {"type": "command", "run": []}}),
            ("too_short", ("nodes", "a", "command", "run")),
        ),
        (
            _workflow(nodes={"a": {"type": "command", "run": ["x"], "timeout": "5"}}),
            ("value_error", ("nodes", "a", "command", "timeout")),
        ),
        (
            _workflow(nodes={"a": {"type": "human_wait", "prompt": "?", "deadline": "later"}}),
            ("value_error", ("nodes", "a", "human_wait", "deadline")),
        ),
        (
            _workflow(nodes={"a": {"type": "command", "run": ["x"], "needs": ["b", "b"]}}),
            ("value_error", ("nodes", "a", "command", "needs")),
        ),
        (
            _workflow(
                nodes={
                    "a": {
                        "type": "loop",
                        "max_iterations": 101,
                        "exhausted": "x",
                        "body": {"inner": {"type": "command", "run": ["x"]}},
                    }
                }
            ),
            ("less_than_equal", ("nodes", "a", "loop", "max_iterations")),
        ),
    ],
)
def test_an_invalid_field_is_rejected_at_its_location(
    document: dict[str, object], expected: tuple[str, tuple[str | int, ...]]
) -> None:
    assert _errors(WorkflowDefinition, document) == [expected]


@pytest.mark.parametrize(
    "document",
    [
        _workflow(nodes={"Bad-Id": {"type": "command", "run": ["x"]}}),
        _workflow(inputs={"Bad": {"type": "string"}}),
        _workflow(entrypoints=[{"scope_path": "root.a"}, {"scope_path": "root.a"}]),
        _workflow(
            nodes={
                "repeat": {
                    "type": "loop",
                    "max_iterations": 1,
                    "exhausted": "x",
                    "body": {"Bad": {"type": "command", "run": ["x"]}},
                }
            }
        ),
    ],
)
def test_identifiers_and_entry_points_are_checked_across_the_document(
    document: dict[str, object],
) -> None:
    assert _errors(WorkflowDefinition, document) == [("value_error", ())]


def test_typed_inputs_accept_values_within_their_constraints() -> None:
    workflow = WorkflowDefinition.model_validate(
        _workflow(
            inputs={
                "target": {"type": "string", "constraints": {"min_length": 1, "max_length": 4}},
                "count": {"type": "integer", "default": 2, "constraints": {"min": 1, "max": 3}},
                "ratio": {"type": "number", "default": 0.5},
                "flag": {"type": "boolean", "default": True},
                "mode": {"type": "enum", "default": "a", "constraints": {"values": ["a", "b"]}},
            }
        )
    )

    assert {name: item.type for name, item in workflow.inputs.items()} == {
        "target": "string",
        "count": "integer",
        "ratio": "number",
        "flag": "boolean",
        "mode": "enum",
    }


@pytest.mark.parametrize(
    ("model", "values"),
    [
        (StringConstraints, {"min_length": 5, "max_length": 2}),
        (NumberConstraints, {"min": 4, "max": 1}),
    ],
)
def test_constraint_bounds_must_be_ordered(
    model: type[StringConstraints] | type[NumberConstraints], values: dict[str, object]
) -> None:
    assert _errors(model, values) == [("value_error", ())]


def test_enum_values_must_be_unique() -> None:
    document = {"type": "enum", "constraints": {"values": ["a", "a"]}}

    assert _errors(EnumInput, document) == [("value_error", ("constraints", "values"))]


def test_an_enum_default_must_be_one_of_its_values() -> None:
    document = {"type": "enum", "default": "c", "constraints": {"values": ["a", "b"]}}

    assert _errors(EnumInput, document) == [("value_error", ())]


@pytest.mark.parametrize("digest", ["A" * 64, "a" * 63, "g" * 64])
def test_entry_artifact_digests_must_be_64_lowercase_hex_characters(digest: str) -> None:
    document = {"path": "a.md", "sha256": digest}

    assert _errors(EntryArtifact, document) == [("value_error", ("sha256",))]


def test_scalars_are_not_coerced() -> None:
    document = {"type": "command", "run": ["x"], "writes": "yes"}

    assert _errors(CommandNode, document) == [("bool_type", ("writes",))]


@pytest.mark.parametrize("key", ["if", "condition"])
def test_a_field_accepts_its_yaml_alias_or_its_name(key: str) -> None:
    document = _workflow(nodes={"a": {"type": "command", "run": ["x"], key: "${{ True }}"}})

    workflow = WorkflowDefinition.model_validate(document)

    assert workflow.nodes["a"].condition == "${{ True }}"
