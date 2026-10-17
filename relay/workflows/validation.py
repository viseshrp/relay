"""Cross-field workflow validation and typed launch-input resolution."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Annotated

from pydantic import Field, TypeAdapter, ValidationError

from relay.errors import WorkflowValidationError

from .graph import compile_graph
from .records import LoadedWorkflow, ValidatedWorkflow
from .schema import (
    BooleanInput,
    EnumInput,
    InputDefinition,
    IntegerInput,
    NumberInput,
    StringInput,
)


def _issue_text(issues: Iterable[str]) -> str:
    """[``unknown input 'x'``] -> ``Workflow validation failed:\n- unknown input 'x'``."""
    return "Workflow validation failed:\n- " + "\n- ".join(issues)


def _pattern_adapter(pattern: str) -> TypeAdapter[str]:
    """Compile through Pydantic's linear-time Rust regex engine."""
    try:
        return TypeAdapter(Annotated[str, Field(pattern=pattern)])
    except Exception:
        message = f"Input pattern {pattern!r} is not in Pydantic's RE2-compatible subset."
        raise WorkflowValidationError(message) from None


def validate_loaded_workflow(root: LoadedWorkflow, relay_root: Path) -> ValidatedWorkflow:
    """Capture current workflow sources and compile their job dependencies."""
    from dataclasses import replace

    from .actions.compiler import definition
    from .actions.language import capture_sources, load

    document = load(root.text, source=root.path)
    captured = capture_sources(document, relay_root.parent)
    root = replace(root, definition=definition(document, captured))
    return ValidatedWorkflow(root, compile_graph(root.definition.nodes), ())


def _input_value(item: InputDefinition, value: object, input_id: str) -> object:
    if isinstance(item, StringInput):
        if not isinstance(value, str):
            message = "must be a string"
            raise TypeError(message)
        constraints = item.constraints
        if constraints.min_length is not None and len(value) < constraints.min_length:
            message = f"must contain at least {constraints.min_length} characters"
            raise ValueError(message)
        if constraints.max_length is not None and len(value) > constraints.max_length:
            message = f"must contain at most {constraints.max_length} characters"
            raise ValueError(message)
        if constraints.pattern is not None:
            try:
                _pattern_adapter(constraints.pattern).validate_python(value)
            except (ValidationError, WorkflowValidationError):
                message = "does not match the declared pattern"
                raise ValueError(message) from None
        return value
    if isinstance(item, IntegerInput):
        if not isinstance(value, int) or isinstance(value, bool):
            message = "must be an integer"
            raise TypeError(message)
    elif isinstance(item, NumberInput):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            message = "must be a number"
            raise TypeError(message)
    elif isinstance(item, BooleanInput):
        if not isinstance(value, bool):
            message = "must be a boolean"
            raise TypeError(message)
        return value
    elif isinstance(item, EnumInput):
        if value not in item.constraints.values:
            message = "must be one of the declared enum values"
            raise ValueError(message)
        return value
    else:
        message = f"input {input_id!r} has an unsupported type"
        raise TypeError(message)

    bounds = item.constraints
    if bounds.min is not None and value < bounds.min:
        message = f"must be at least {bounds.min}"
        raise ValueError(message)
    if bounds.max is not None and value > bounds.max:
        message = f"must be at most {bounds.max}"
        raise ValueError(message)
    return value


def resolve_inputs(
    inputs: Mapping[str, InputDefinition], supplied: Mapping[str, object]
) -> dict[str, object]:
    """Apply defaults and validate every launch input without coercion."""
    issues = []
    unknown = supplied.keys() - inputs.keys()
    issues.extend(f"unknown launch input {name!r}" for name in sorted(unknown))
    resolved = {}
    for input_id, item in inputs.items():
        if input_id in supplied:
            value = supplied[input_id]
        elif item.default is not None:
            value = item.default
        elif item.required:
            issues.append(f"required launch input {input_id!r} is missing")
            continue
        else:
            value = None
        if value is None and not item.required:
            resolved[input_id] = None
            continue
        try:
            resolved[input_id] = _input_value(item, value, input_id)
        except (TypeError, ValueError) as error:
            issues.append(f"input {input_id!r} {error}")
    if issues:
        raise WorkflowValidationError(_issue_text(issues))
    return resolved


__all__ = ["ValidatedWorkflow", "resolve_inputs", "validate_loaded_workflow"]
