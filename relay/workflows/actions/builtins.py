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
# The named shells a run step can choose; any other shell is a command with {0}.
SHELLS = ("bash", "sh", "pwsh", "powershell", "cmd", "python")
SHELL_HINT = (
    f"Use {', '.join(SHELLS[:-1])}, or {SHELLS[-1]}, "
    "or a command that contains {0} for the script path."
)


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


def parse_list_input(value: object, field: str) -> list[str]:
    """Read a JSON array of strings or one non-blank value per line."""
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            items = json.loads(text)
        except ValueError:
            items = None
        if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
            message = f"{field}: Write a JSON array of strings or one value per line."
            raise WorkflowValidationError(message)
        return items
    return [line.strip() for line in text.splitlines() if line.strip()]


def _literal_list(inputs: Mapping[str, Any], field: str) -> list[str] | None:
    """A list input written literally; None when absent or an expression."""
    value = inputs.get(field)
    if not isinstance(value, str) or "${{" in value:
        return None
    try:
        return parse_list_input(value, field)
    except WorkflowValidationError as error:
        error.context.setdefault("field", f"with.{field}")
        raise


def _input_error(field: str, message: str) -> WorkflowValidationError:
    return WorkflowValidationError(f"{field}: {message}", context={"field": f"with.{field}"})


def validate_inputs(reference: str, inputs: Mapping[str, Any]) -> None:
    """Check one built-in step's inputs; literal values are checked as they will run.

    An error about one input carries its field relative to the step, such as
    with.argv, so the step validator can point at that line.
    """
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
    if action.name == "command" and (argv := _literal_list(inputs, "argv")) is not None:
        text = str(inputs["argv"]).strip()
        if not argv:
            raise _input_error("argv", "Add the program to run.")
        if (
            len(argv) == 1
            and not text.startswith("[")
            and len(text.splitlines()) == 1
            and any(character.isspace() for character in argv[0])
        ):
            raise _input_error(
                "argv",
                f'"{argv[0]}" is a single argument. Put each argument on its own line, '
                "or use a JSON array.",
            )
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
    if action.name == "agent":
        from relay.agents.profiles import PROFILES

        for field in ("agent", "agents"):
            unknown = [item for item in _literal_list(inputs, field) or [] if item not in PROFILES]
            if unknown:
                raise _input_error(
                    field, f"Unknown agent {unknown[0]}. Use one of {', '.join(sorted(PROFILES))}."
                )
    if action.name == "human-wait" and "options" in inputs:
        value = inputs["options"]
        if "${{" not in str(value):
            try:
                human_wait_options(value)
            except WorkflowValidationError as error:
                error.context.setdefault("field", "with.options")
                raise
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
        value = parse_list_input(value, "options")
    if (
        not isinstance(value, list)
        or not 1 <= len(value) <= 10
        or any(not isinstance(item, str) or not item.strip() or len(item) > 256 for item in value)
        or len(set(value)) != len(value)
    ):
        message = "Human wait options must be 1-10 distinct, nonempty answer strings."
        raise WorkflowValidationError(message)
    return value
