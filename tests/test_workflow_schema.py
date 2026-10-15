"""Typed builtin inputs, constraints, and retained artifact identifiers."""

from __future__ import annotations

from pydantic import BaseModel, ValidationError
import pytest

from relay.workflows.schema import (
    AgentNode,
    EntryArtifact,
    EnumInput,
    NumberConstraints,
    StringConstraints,
)


def _errors(
    model: type[BaseModel], document: dict[str, object]
) -> list[tuple[str, tuple[str | int, ...]]]:
    with pytest.raises(ValidationError) as caught:
        model.model_validate(document)
    return [(error["type"], error["loc"]) for error in caught.value.errors()]


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
    document = {"type": "agent", "auto_retry": "yes"}

    assert _errors(AgentNode, document) == [("bool_type", ("auto_retry",))]
