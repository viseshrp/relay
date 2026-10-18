"""Public input contracts for Relay's versioned local action adapters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import re
from typing import Any, Literal

from relay.errors import WorkflowValidationError

from .suggest import closest

BUILTIN_REFERENCE = re.compile(r"relay/([a-z][a-z-]*)@v([1-9][0-9]*)")


@dataclass(frozen=True, slots=True)
class BuiltinAction:
    """One major version of a built-in action and its inputs."""

    name: str
    major: int
    allowed: frozenset[str]
    required: frozenset[str]
    status: Literal["current", "deprecated"] = "current"

    @property
    def reference(self) -> str:
        return f"relay/{self.name}@v{self.major}"


BUILTIN_ACTIONS: tuple[BuiltinAction, ...] = (
    BuiltinAction(
        "agent",
        1,
        frozenset(
            {
                "agent",
                "agents",
                "model",
                "effort",
                "prompt-files",
                "prompt",
                "report",
                "selector",
                "format",
                "field",
                "label",
                "auto-retry",
                "retry-limit",
            }
        ),
        frozenset(),
    ),
    BuiltinAction("command", 1, frozenset({"argv", "command"}), frozenset()),
    BuiltinAction(
        "human-wait", 1, frozenset({"prompt", "timeout-minutes", "options"}), frozenset({"prompt"})
    ),
    BuiltinAction(
        "loop",
        1,
        frozenset({"workflow", "inputs", "max-iterations", "until-output", "equals"}),
        frozenset({"workflow", "max-iterations"}),
    ),
    BuiltinAction(
        "validate-report",
        1,
        frozenset({"path", "report", "selector", "format", "field", "label"}),
        frozenset(),
    ),
    BuiltinAction(
        "validate-input",
        1,
        frozenset({"value", "type", "constraints"}),
        frozenset({"value", "type"}),
    ),
    BuiltinAction(
        "upload-artifact", 1, frozenset({"name", "path", "retention-days"}), frozenset({"path"})
    ),
    BuiltinAction(
        "download-artifact", 1, frozenset({"name", "path", "run-id"}), frozenset({"name"})
    ),
    BuiltinAction(
        "cache", 1, frozenset({"key", "path", "restore-keys"}), frozenset({"key", "path"})
    ),
    BuiltinAction(
        "restore-cache", 1, frozenset({"key", "path", "restore-keys"}), frozenset({"key", "path"})
    ),
    BuiltinAction("save-cache", 1, frozenset({"key", "path"}), frozenset({"key", "path"})),
)
_BY_REFERENCE: dict[str, BuiltinAction] = {action.reference: action for action in BUILTIN_ACTIONS}


def parse_builtin(reference: object) -> tuple[str, int] | None:
    """Split relay/<name>@v<major>; None for any other value."""
    if not isinstance(reference, str):
        return None
    match = BUILTIN_REFERENCE.fullmatch(reference)
    return (match[1], int(match[2])) if match else None


def builtin(reference: object) -> BuiltinAction | None:
    """The registered version a reference names, if Relay has it."""
    if not isinstance(reference, str):
        return None
    return _BY_REFERENCE.get(reference)


def is_builtin(reference: object, name: str) -> bool:
    """True for any version of one action, registered or not."""
    parsed = parse_builtin(reference)
    return parsed is not None and parsed[0] == name


def builtin_references(name: str) -> tuple[str, ...]:
    """Every registered version of one action, oldest first."""
    versions = sorted(
        (action for action in BUILTIN_ACTIONS if action.name == name),
        key=lambda action: action.major,
    )
    return tuple(action.reference for action in versions)


def current_builtin(name: str) -> BuiltinAction:
    """The current version of one action; KeyError if unknown."""
    for action in BUILTIN_ACTIONS:
        if action.name == name and action.status == "current":
            return action
    raise KeyError(name)


def validate_inputs(reference: str, inputs: Mapping[str, Any]) -> None:
    action = builtin(reference)
    if action is None:
        raise KeyError(reference)
    unknown = sorted(inputs.keys() - action.allowed)
    missing = sorted(action.required - inputs.keys())
    if unknown or missing:
        sentences = []
        if unknown:
            noun = "input" if len(unknown) == 1 else "inputs"
            sentence = f"{reference} does not accept {noun} {', '.join(unknown)}."
            suggestion = closest(unknown[0], action.allowed) if len(unknown) == 1 else None
            sentences.append(sentence + (f" Did you mean {suggestion}?" if suggestion else ""))
        if missing:
            noun = "input" if len(missing) == 1 else "inputs"
            sentences.append(f"{reference} requires {noun} {', '.join(missing)}.")
        raise WorkflowValidationError(" ".join(sentences))
    if action.name == "command" and len({"argv", "command"} & inputs.keys()) != 1:
        message = f"{reference} requires exactly one of argv or command."
        raise WorkflowValidationError(message)
    if action.name == "validate-report" and not ({"path", "report", "selector"} & inputs.keys()):
        message = f"{reference} requires path, report, or selector."
        raise WorkflowValidationError(message)
    if action.name == "loop":
        maximum = inputs["max-iterations"]
        if isinstance(maximum, bool) or str(maximum) not in {str(i) for i in range(1, 101)}:
            message = "Loop max-iterations must be a literal integer between 1 and 100."
            raise WorkflowValidationError(message)
    if (
        action.name == "agent"
        and "retry-limit" in inputs
        and (
            isinstance(inputs["retry-limit"], bool) or str(inputs["retry-limit"]) not in {"1", "2"}
        )
    ):
        message = "Agent retry-limit must be a literal integer between 1 and 2."
        raise WorkflowValidationError(message)
    if action.name == "human-wait" and "options" in inputs:
        value = inputs["options"]
        if "${{" not in str(value):
            human_wait_options(value)
    format_name = inputs.get("format")
    if (
        format_name is not None
        and "${{" not in str(format_name)
        and format_name not in {"exists", "label", "json", "yaml"}
    ):
        message = "Report format must be exists, label, json, or yaml."
        raise WorkflowValidationError(message)


def human_wait_options(value: object) -> list[str]:
    """Validate bounded answer labels without interpreting the owner's prose."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            value = None
    if (
        not isinstance(value, list)
        or not 1 <= len(value) <= 10
        or any(not isinstance(item, str) or not item.strip() or len(item) > 256 for item in value)
        or len(set(value)) != len(value)
    ):
        message = "Human wait options must be 1-10 distinct, nonempty answer strings."
        raise WorkflowValidationError(message)
    return value
