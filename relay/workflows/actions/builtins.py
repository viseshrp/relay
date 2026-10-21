"""Public input contracts for Relay's versioned local action adapters."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import json
import re
from typing import Any, Literal

from relay.errors import WorkflowValidationError

from .suggest import closest

ALLOWED_PATHS_MAX = 100
ALLOWED_PATH_MAX_CHARS = 1024

BUILTIN_REFERENCE = re.compile(r"relay/([a-z][a-z-]*)@v([1-9][0-9]*)")
# The named shells a run step can choose; any other shell is a command with {0}.
SHELLS = ("bash", "sh", "pwsh", "powershell", "cmd", "python")
SHELL_HINT = (
    f"Use {', '.join(SHELLS[:-1])}, or {SHELLS[-1]}, "
    "or a command that contains {0} for the script path."
)


# Formats an agent or validate-report step can read a report in.
REPORT_FORMATS = ("exists", "label", "json", "yaml")
_REPORT_FORMAT = (
    "How to read the report: label (the default), json, yaml, or exists, which only checks "
    "that the file is there."
)
_REPORT_FIELD = (
    "Dotted key to read from a json or yaml report, such as result.status. Defaults to value."
)
_REPORT_LABEL = (
    "Label to look for in a label report: the text after the first line that starts with "
    "'<label>: ' becomes the value. Defaults to Ready."
)
_CACHE_PATH = (
    "Files and folders to cache, as patterns relative to the job's working copy, one per line."
)
_RESTORE_KEYS = (
    "Fallback key prefixes, one per line, tried in order when key has no exact match. "
    "The newest matching entry is restored."
)


# Converts the previous major version's `with` inputs to this version's. It
# returns the new inputs and one sentence per input it changed or dropped, and
# raises WorkflowValidationError when it cannot convert them safely.
Upgrade = Callable[[Mapping[str, object]], tuple[dict[str, object], tuple[str, ...]]]


@dataclass(frozen=True, slots=True)
class BuiltinAction:
    """One major version of a built-in action, its inputs, and their help text.

    A deprecated version names the Relay release that deprecated it in
    deprecated_in. The version after it sets upgrade.
    """

    name: str
    major: int
    allowed: frozenset[str]
    required: frozenset[str]
    status: Literal["current", "deprecated"] = "current"
    summary: str = ""
    descriptions: Mapping[str, str] = field(default_factory=dict)
    values: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    deprecated_in: str = ""
    upgrade: Upgrade | None = None

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
                "allowed-paths",
            }
        ),
        frozenset(),
        summary="Ask an installed coding agent to do work in the job's working copy.",
        descriptions={
            "agent": (
                "One installed agent to run the step, by ID, such as codex or claude. "
                "Use agents instead to give agents to try in order."
            ),
            "agents": (
                "Agents to try in order, as a JSON array or one per line. "
                "The first available agent runs the step."
            ),
            "model": (
                "Exact model value for the agent, matched with case. Without it, your saved "
                "default model applies; the run stops rather than switch to another model."
            ),
            "effort": (
                "Exact reasoning effort value for the chosen model. Leave it out to use your "
                "saved setting; an empty value keeps the agent's own default."
            ),
            "prompt-files": (
                "Instruction files sent before prompt, one per line, under .relay/ or "
                "global:NAME for your global prompts. Their text is fixed when the run starts."
            ),
            "prompt": (
                "Instructions sent to the agent after any prompt files. "
                "Expressions such as ${{ inputs.task }} are filled in at launch."
            ),
            "report": (
                "File the agent must write in the job's working copy. Relay reads it as format "
                "says, and the step fails if it is missing or does not match."
            ),
            "selector": (
                "Full report check as a JSON object using exists, label, json_path, or "
                "yaml_path. Use it instead of report, format, field, and label."
            ),
            "format": _REPORT_FORMAT,
            "field": _REPORT_FIELD,
            "label": _REPORT_LABEL,
            "auto-retry": (
                "true lets Relay retry this step after a report, protocol, or time-limit "
                "failure; false never retries it. Without it, the run's recovery setting decides."
            ),
            "retry-limit": (
                "Most automatic retries for this step, 1 or 2, used with auto-retry: true. "
                "Retries already used are not reset by a restart."
            ),
            "allowed-paths": (
                "Paths the agent may change, one pattern per line relative to the project "
                "folder, such as docs/** or src/*.py. Any other change fails the step."
            ),
        },
        values={"format": REPORT_FORMATS, "auto-retry": ("true", "false")},
    ),
    BuiltinAction(
        "command",
        1,
        frozenset({"argv", "command"}),
        frozenset(),
        summary="Run a program with exact arguments in the job's working copy, without a shell.",
        descriptions={
            "argv": (
                "Program and arguments, as a JSON array or one argument per line. "
                "Arguments are passed exactly; no shell is involved."
            ),
            "command": (
                "Name of a command saved in Relay's settings, used instead of argv. "
                "Its saved arguments are fixed when the run starts."
            ),
        },
    ),
    BuiltinAction(
        "human-wait",
        1,
        frozenset({"prompt", "timeout-minutes", "options"}),
        frozenset({"prompt"}),
        summary="Pause the job until you answer a question in Relay.",
        descriptions={
            "prompt": (
                "Question shown to you while the job waits. It can use expressions; "
                "your answer becomes steps.<id>.outputs.answer."
            ),
            "timeout-minutes": (
                "Minutes to wait for an answer before the step fails. "
                "Without it, the job's time limit applies."
            ),
            "options": (
                "Answer buttons, as a JSON array or one per line. "
                "Without options the answer is free text."
            ),
        },
    ),
    BuiltinAction(
        "loop",
        1,
        frozenset({"workflow", "inputs", "max-iterations", "until-output", "equals"}),
        frozenset({"workflow", "max-iterations"}),
        summary=(
            "Run a local workflow again and again until one of its outputs has a chosen value "
            "or the limit is reached."
        ),
        descriptions={
            "workflow": (
                "Workflow file to repeat, such as ./.relay/workflows/fix.yaml. "
                "It must declare on: workflow_call."
            ),
            "inputs": (
                'Inputs passed to each repetition, as a JSON object such as {"target": "tests"}. '
                "Defaults to none."
            ),
            "max-iterations": (
                "Most repetitions to run, a whole number from 1 to 100. "
                "If until-output never matches, the loop fails after the last one."
            ),
            "until-output": (
                "Output of the repeated workflow to check after each repetition. The loop stops "
                "when it matches equals; without until-output, the workflow runs once."
            ),
            "equals": "Value that until-output must have to stop the loop. Defaults to true.",
        },
    ),
    BuiltinAction(
        "validate-report",
        1,
        frozenset({"path", "report", "selector", "format", "field", "label"}),
        frozenset(),
        summary="Check a report file in the job's working copy and export a value read from it.",
        descriptions={
            "path": (
                "Report file to check, relative to the job's working copy. "
                "You can use report instead."
            ),
            "report": (
                "Report file to check, relative to the job's working copy. "
                "Same as path; report is used when both are set."
            ),
            "selector": (
                "Full report check as a JSON object using exists, label, json_path, or "
                "yaml_path. Use it instead of path, format, field, and label."
            ),
            "format": _REPORT_FORMAT,
            "field": _REPORT_FIELD,
            "label": _REPORT_LABEL,
        },
        values={"format": REPORT_FORMATS},
    ),
    BuiltinAction(
        "validate-input",
        1,
        frozenset({"value", "type", "constraints"}),
        frozenset({"value", "type"}),
        summary=(
            "Check that a value has the expected type and limits; the step fails when it does not."
        ),
        descriptions={
            "value": (
                "Value to check, usually an expression such as ${{ inputs.count }}. "
                "It is exported unchanged as the value output."
            ),
            "type": (
                "Kind of value expected: string (the default), integer, number, boolean, or enum."
            ),
            "constraints": (
                "Limits as a JSON object: min_length, max_length, or pattern for a string, "
                "min or max for a number, and values for an enum."
            ),
        },
        values={"type": ("string", "integer", "number", "boolean", "enum")},
    ),
    BuiltinAction(
        "upload-artifact",
        1,
        frozenset({"name", "path", "retention-days"}),
        frozenset({"path"}),
        summary="Save files from the job's working copy as a named artifact of this run.",
        descriptions={
            "name": (
                "Artifact name, unique within the run and without slashes. Defaults to artifact."
            ),
            "path": (
                "Files to save, as glob patterns relative to the job's working copy, one per line."
            ),
            "retention-days": (
                "Days to keep the artifact, from 0 to 365. Defaults to 0, which keeps it with no "
                "expiry."
            ),
        },
    ),
    BuiltinAction(
        "download-artifact",
        1,
        frozenset({"name", "path", "run-id"}),
        frozenset({"name"}),
        summary=(
            "Copy a saved artifact from this run, or an earlier run of the same project, "
            "into the job's working copy."
        ),
        descriptions={
            "name": "Name of the artifact to copy.",
            "path": (
                "Folder in the job's working copy to copy the files into. "
                "Defaults to the top of the working copy."
            ),
            "run-id": (
                "ID of the run that saved the artifact, in the same project. "
                "Defaults to the current run."
            ),
        },
    ),
    BuiltinAction(
        "cache",
        1,
        frozenset({"key", "path", "restore-keys"}),
        frozenset({"key", "path"}),
        summary=(
            "Restore files from the project cache, and save them under key when the job succeeds."
        ),
        descriptions={
            "key": (
                "Exact name for the cached files, up to 512 characters. Saved entries never "
                "change, so include a hash of the files they depend on."
            ),
            "path": _CACHE_PATH,
            "restore-keys": _RESTORE_KEYS,
        },
    ),
    BuiltinAction(
        "restore-cache",
        1,
        frozenset({"key", "path", "restore-keys"}),
        frozenset({"key", "path"}),
        summary="Restore files from the project cache without saving them later.",
        descriptions={
            "key": (
                "Exact name of the cached files to restore. "
                "When nothing matches it, restore-keys are tried."
            ),
            "path": _CACHE_PATH,
            "restore-keys": _RESTORE_KEYS,
        },
    ),
    BuiltinAction(
        "save-cache",
        1,
        frozenset({"key", "path"}),
        frozenset({"key", "path"}),
        summary="Save files from the job's working copy to the project cache under a key.",
        descriptions={
            "key": (
                "Exact name for the saved files, up to 512 characters. "
                "An entry that already has this key is not replaced."
            ),
            "path": _CACHE_PATH,
        },
    ),
)
_BY_REFERENCE: dict[str, BuiltinAction] = {action.reference: action for action in BUILTIN_ACTIONS}
# Versions removed after their deprecation period: reference -> (the Relay
# release that removed it, its replacement). Relay never runs the replacement
# in their place.
REMOVED_BUILTINS: dict[str, tuple[str, str]] = {}


def registered_builtins() -> tuple[BuiltinAction, ...]:
    """Every registered version, current and deprecated, in registry order."""
    return BUILTIN_ACTIONS


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
    """Every registered or removed version of one action, oldest first.

    Removed versions stay listed so persisted rows from older runs keep their
    meaning; builtin() still returns None for them.
    """
    majors = {action.major: action.reference for action in BUILTIN_ACTIONS if action.name == name}
    for reference in REMOVED_BUILTINS:
        parsed = parse_builtin(reference)
        if parsed is not None and parsed[0] == name:
            majors.setdefault(parsed[1], reference)
    return tuple(majors[major] for major in sorted(majors))


def current_builtin(name: str) -> BuiltinAction:
    """The current version of one action; KeyError if unknown."""
    for action in BUILTIN_ACTIONS:
        if action.name == name and action.status == "current":
            return action
    raise KeyError(name)


def removed_builtin(reference: object) -> tuple[str, str] | None:
    """The release that removed a reference and its replacement, if it was removed."""
    return REMOVED_BUILTINS.get(reference) if isinstance(reference, str) else None


def newer_versions(reference: object) -> tuple[BuiltinAction, ...]:
    """The versions after a deprecated or removed reference, up to the current one.

    Each one's upgrade converts the inputs of the version before it. A current,
    unknown, or local reference has none.
    """
    parsed = parse_builtin(reference)
    action = builtin(reference)
    older = (
        action.status == "deprecated"
        if action is not None
        else removed_builtin(reference) is not None
    )
    if parsed is None or not older:
        return ()
    name, major = parsed
    last = current_builtin(name).major
    return tuple(
        sorted(
            (item for item in BUILTIN_ACTIONS if item.name == name and major < item.major <= last),
            key=lambda item: item.major,
        )
    )


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
    if action.name == "agent" and "allowed-paths" in inputs:
        try:
            parse_allowed_paths(inputs["allowed-paths"])
        except WorkflowValidationError as error:
            error.context.setdefault("field", "with.allowed-paths")
            raise
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
        and format_name not in REPORT_FORMATS
    ):
        message = "Report format must be exists, label, json, or yaml."
        raise WorkflowValidationError(message)


def parse_allowed_paths(value: object) -> tuple[str, ...]:
    """Validate one literal pattern per line, relative to the project folder.

    For example, `docs/**` allows any file below `docs/`, `src/*.py` allows
    Python files directly in `src/`, and `README.md` allows only that file.
    """
    if not isinstance(value, str) or "${{" in value:
        message = "allowed-paths must be a literal list of path patterns, one per line."
        raise WorkflowValidationError(message)
    patterns = tuple(line.strip() for line in value.splitlines() if line.strip())
    if not patterns or len(patterns) > ALLOWED_PATHS_MAX:
        message = f"allowed-paths must list between 1 and {ALLOWED_PATHS_MAX} patterns."
        raise WorkflowValidationError(message)
    for pattern in patterns:
        parts = pattern.split("/")
        if (
            len(pattern) > ALLOWED_PATH_MAX_CHARS
            or "\\" in pattern
            or pattern.startswith("/")
            or re.match(r"^[A-Za-z]:", pattern)
            or any(part in {"", ".", ".."} for part in parts[:-1])
            or parts[-1] in {".", ".."}
        ):
            message = (
                f"allowed-paths pattern {pattern!r} must be a relative POSIX path "
                "without '.', '..', or backslashes."
            )
            raise WorkflowValidationError(message)
    return patterns


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
