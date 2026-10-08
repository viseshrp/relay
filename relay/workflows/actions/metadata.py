"""Frozen local composite and JavaScript action metadata."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from ruamel.yaml import YAML

from relay.errors import WorkflowValidationError

from .language import (
    IDENTIFIER,
    MAX_YAML_BYTES,
    _expression_check,
    _inspect_tree,
    _issue,
    _mapping,
    _unsupported,
    _validate_type,
)


def load_action(text: str, *, source: Path | None = None) -> dict[str, Any]:
    """Validate metadata without executing an action or probing Node."""
    del source
    if len(text.encode()) > MAX_YAML_BYTES:
        raise _issue("action", "Action metadata exceeds 1 MiB.")
    parser = YAML(typ="rt")
    parser.allow_duplicate_keys = False
    try:
        tree = parser.compose(text)
        if tree is not None:
            _inspect_tree(tree, "action", {}, frozenset(), [0, 0])
        value = _mapping(parser.load(text), "action")
    except WorkflowValidationError:
        raise
    except Exception:
        raise _issue("action", "Invalid action YAML.") from None
    unknown = value.keys() - {
        "name",
        "description",
        "author",
        "inputs",
        "outputs",
        "runs",
        "branding",
    }
    if unknown or any(
        not isinstance(value.get(field), str) or not value[field]
        for field in ("name", "description")
    ):
        raise _issue("action", "Action requires name and description; unknown fields are rejected.")
    for kind in ("inputs", "outputs"):
        records = _mapping(value.get(kind, {}), f"action.{kind}")
        for name, raw in records.items():
            if not isinstance(name, str) or IDENTIFIER.fullmatch(name) is None:
                raise _issue(f"action.{kind}", "Expected a valid input or output identifier.")
            item = _mapping(raw, f"action.{kind}.{name}")
            allowed = (
                {"description", "required", "default", "deprecationMessage"}
                if kind == "inputs"
                else {"description", "value"}
            )
            if item.keys() - allowed:
                raise _issue(f"action.{kind}.{name}", "Unknown metadata field.")
            if "required" in item and not isinstance(item["required"], bool):
                raise _issue(f"action.{kind}.{name}.required", "Expected boolean.")
            for field in ("description", "default", "deprecationMessage", "value"):
                if field in item and not isinstance(item[field], str):
                    raise _issue(f"action.{kind}.{name}.{field}", "Expected string.")
            if not isinstance(item.get("description"), str):
                raise _issue(f"action.{kind}.{name}.description", "Expected string description.")
    if "author" in value and not isinstance(value["author"], str):
        raise _issue("action.author", "Expected string.")
    if "branding" in value:
        branding = _mapping(value["branding"], "action.branding")
        if branding.keys() - {"icon", "color"} or any(
            not isinstance(item, str) for item in branding.values()
        ):
            raise _issue("action.branding", "Use string icon and color fields.")
        if branding.get("color", "white") not in {
            "white",
            "yellow",
            "blue",
            "green",
            "orange",
            "red",
            "purple",
            "gray-dark",
        }:
            raise _issue("action.branding.color", "Unsupported branding color.")
    runs = _mapping(value.get("runs"), "action.runs")
    using = runs.get("using")
    if using == "composite":
        if runs.keys() - {"using", "steps"}:
            raise _issue("action.runs", "Unknown composite metadata field.")
        steps = runs.get("steps")
        if not isinstance(steps, list) or not steps:
            raise _issue("action.runs.steps", "Composite actions require ordered steps.")
        _unsupported({"jobs": {"composite": {"steps": steps}}}, "workflow")
        runs["steps"] = _validate_type("steps", steps, "action.runs.steps", ("inputs",))
        for step in cast(list[Mapping[str, Any]], runs["steps"]):
            from .builtins import CONTRACTS, validate_inputs

            if step.get("uses") in CONTRACTS:
                validate_inputs(str(step["uses"]), step.get("with", {}))
            if "run" in step and "shell" not in step:
                raise _issue("action.runs.steps.shell", "Composite run steps require shell.")
        for name, output in value.get("outputs", {}).items():
            if "value" not in output:
                raise _issue(f"action.outputs.{name}", "Composite outputs require value.")
            _expression_check(
                output["value"],
                "composite-output",
                ("inputs", "steps"),
                f"action.outputs.{name}.value",
            )
    elif using in {"node20", "node24"}:
        if runs.keys() - {"using", "main", "post", "post-if"}:
            raise _issue(
                "action.runs",
                "Local JavaScript pre hooks and unknown fields are unsupported.",
                unsupported=True,
            )
        if not isinstance(runs.get("main"), str) or not runs["main"]:
            raise _issue("action.runs.main", "JavaScript actions require main.")
        for field in ("main", "post"):
            if field in runs and (not isinstance(runs[field], str) or "${{" in runs[field]):
                raise _issue(f"action.runs.{field}", "Use a static local script path.")
        if "post-if" in runs:
            _expression_check(
                runs["post-if"],
                "step-if",
                (
                    "github",
                    "inputs",
                    "env",
                    "job",
                    "runner",
                    "always()",
                    "cancelled()",
                    "success()",
                    "failure()",
                ),
                "action.runs.post-if",
            )
    else:
        raise _issue(
            "action.runs.using",
            "Only composite, node20 and node24 local actions are supported.",
            unsupported=True,
        )
    value["runs"] = runs
    return value


def validate_action_inputs(metadata: Mapping[str, Any], supplied: Mapping[str, Any]) -> None:
    """Reject unknown and missing required input keys before launching local code."""
    declarations = metadata.get("inputs", {})
    if supplied.keys() - declarations.keys() or any(
        item.get("required") and name not in supplied and "default" not in item
        for name, item in declarations.items()
    ):
        raise _issue("action.inputs", "Local action has missing required or unknown inputs.")
