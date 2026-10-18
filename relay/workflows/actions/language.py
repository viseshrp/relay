"""Relay's local workflow language, inspired by Actions jobs and expressions.

Only Relay-owned schema definitions are accepted. Validation never launches a
process, looks up a credential, or changes workflow sources.
"""

from __future__ import annotations

import base64
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
import json
import math
from pathlib import Path
import re
from typing import Any, cast

from ruamel.yaml import YAML
from ruamel.yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from relay.errors import WorkflowValidationError
from relay.paths import safe_resolve

from . import expressions
from .builtins import BUILTIN_ACTIONS, SHELL_HINT, SHELLS, builtin, current_builtin, is_builtin
from .suggest import closest

DIALECT = "relay-local-1"
UPSTREAM = "4043eda158e16579cc5fb1b0b07a4bce2a76f0b5"
MAX_YAML_BYTES = 1_048_576
MAX_YAML_NODES = 10_000
MAX_ALIASES = 100
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
EVENTS = frozenset(
    {
        "workflow_dispatch",
        "workflow_call",
        "schedule",
        "push",
        "repository_dispatch",
        "workflow_run",
    }
)
CACHE_MODES = frozenset({"read", "write", "write-only", "none"})
EVENTS_HINT = (
    "Relay supports workflow_dispatch, workflow_call, schedule, push, repository_dispatch, "
    "and workflow_run. Pull request and other hosted events have no local equivalent."
)
# Relay's names for the expression properties people bring from other platforms.
PLATFORM_NAMES: dict[str, dict[str, str]] = {
    "github": {
        "sha": "relay.sha",
        "ref": "relay.ref",
        "ref_name": "relay.ref_name",
        "ref_type": "relay.ref_type",
        "event": "relay.event",
        "event_name": "relay.event_name",
        "workspace": "relay.workspace",
        "repository": "relay.repository",
        "actor": "relay.actor",
        "triggering_actor": "relay.actor",
        "workflow": "relay.workflow",
        "workflow_ref": "relay.workflow_ref",
        "run_id": "relay.run_id",
        "run_number": "relay.run_number",
        "run_attempt": "relay.attempt_number",
        "job": "relay.job",
        "action": "relay.action",
        "action_path": "relay.action_path",
    },
    "runner": {"os": "host.os", "arch": "host.arch", "name": "host.name", "temp": "host.temp"},
}
PLATFORM_ROOTS = {"github": "relay", "runner": "host"}
FILE_VARIABLES = re.compile(r"\bGITHUB_(OUTPUT|ENV|PATH|STATE|STEP_SUMMARY)\b")
FILE_VARIABLE_GUIDANCE = {
    "OUTPUT": "Write step outputs to $RELAY_OUTPUT.",
    "ENV": "Set variables for later steps in $RELAY_ENV.",
    "PATH": "Add search paths in $RELAY_PATH.",
    "STATE": "Save action state in $RELAY_STATE.",
    "STEP_SUMMARY": "Write the step summary to $RELAY_STEP_SUMMARY.",
}
_PURE_FUNCTIONS = tuple(
    name
    for name in expressions.FUNCTIONS
    if name not in expressions.STATUS_FUNCTIONS and name != "hashfiles"
)


@dataclass(frozen=True, slots=True)
class ActionsDocument:
    text: str
    source: Path
    document: Mapping[str, Any]
    value: dict[str, Any]
    locations: Mapping[str, tuple[int, int]]


def _issue(path: str, message: str, *, unsupported: bool = False) -> WorkflowValidationError:
    return WorkflowValidationError(
        f"{path}: {message}",
        context={"field": path, **({"feature": "unsupported"} if unsupported else {})},
    )


def _warning(path: str, message: str) -> WorkflowValidationError:
    issue = _issue(path, message)
    issue.context["severity"] = "warning"
    return issue


FIELD_HINTS = {
    "runs-on": (
        "Jobs run on this computer. Remove runs-on. To have an AI agent do the work, "
        f"add a {current_builtin('agent').reference} step."
    ),
    "permissions": "Authentication belongs to your installed tools. Remove permissions.",
    "container": "Use a local script or command instead of a container.",
    "services": "Start required services outside Relay before running this workflow.",
    "max-parallel": "Local matrix jobs run serially. Remove max-parallel.",
    "timeout": "Use timeout-minutes with a number, for example timeout-minutes: 10.",
}


def _unknown_hint(path: str, candidates: Iterable[str]) -> tuple[str | None, str | None]:
    """A fixed hint for an unknown key, or else the closest allowed key."""
    parent, _, key = path.rpartition(".")
    hint = EVENTS_HINT if parent == "workflow.on" else FIELD_HINTS.get(key)
    return (hint, None) if hint else (None, closest(key, candidates))


def _unknown_field(path: str, candidates: Iterable[str] = ()) -> WorkflowValidationError:
    hint, suggestion = _unknown_hint(path, candidates)
    if suggestion:
        hint = f"Did you mean {suggestion}?"
    return _issue(path, "Unknown workflow field." + (f" {hint}" if hint else ""))


def _inspect_tree(
    node: Node,
    path: str,
    locations: dict[str, tuple[int, int]],
    ancestors: frozenset[int],
    counts: list[int],
    depth: int = 0,
) -> None:
    counts[0] += 1
    if counts[0] > MAX_YAML_NODES or depth > 50:
        raise _issue(path, "YAML exceeds the node or depth limit.")
    if id(node) in ancestors:
        raise _issue(path, "Cyclic YAML aliases are not supported.")
    if id(node) in counts[2:]:
        counts[1] += 1
        if counts[1] > MAX_ALIASES:
            raise _issue(path, "YAML exceeds the alias limit.")
    else:
        counts.append(id(node))
    locations[path] = (node.start_mark.line + 1, node.start_mark.column + 1)
    tags = {"str", "int", "float", "bool", "null", "map", "seq"}
    if node.tag not in {f"tag:yaml.org,2002:{tag}" for tag in tags}:
        raise _issue(path, "Custom tags and YAML merge keys are unsupported.", unsupported=True)
    parents = ancestors | {id(node)}
    if isinstance(node, MappingNode):
        names = set()
        for key, child in node.value:
            if not isinstance(key, ScalarNode) or key.tag != "tag:yaml.org,2002:str":
                raise _issue(path, "Mapping keys must be strings.")
            if key.value == "<<":
                raise _issue(path, "YAML merge keys are unsupported.", unsupported=True)
            mark = (key.start_mark.line + 1, key.start_mark.column + 1)
            if key.value in names:
                message = f"{path}.{key.value}"
                locations[message] = mark
                raise _issue(message, "Duplicate YAML key.")
            names.add(key.value)
            _inspect_tree(child, f"{path}.{key.value}", locations, parents, counts, depth + 1)
            if (
                isinstance(child, ScalarNode)
                and child.tag == "tag:yaml.org,2002:null"
                and child.value == ""
            ):
                # An empty value starts at the next token; point at its own key instead.
                locations[f"{path}.{key.value}"] = mark
    elif isinstance(node, SequenceNode):
        for index, child in enumerate(node.value):
            _inspect_tree(child, f"{path}[{index}]", locations, parents, counts, depth + 1)


@lru_cache(maxsize=1)
def _language_schema() -> dict[str, Any]:
    return json.loads(Path(__file__).with_name("schema.json").read_text(encoding="utf-8"))


def language_definitions() -> dict[str, Any]:
    """The same curated schema is authoritative for validation and discovery."""
    return _language_schema()["definitions"]


def language_property_descriptions() -> dict[str, str]:
    """Help text for each "<definition>.<property>" pair, shown by the editor."""
    return _language_schema()["property_descriptions"]


def _mapping(value: object, path: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _issue(path, "Expected a mapping.")
    return {str(key): item for key, item in value.items()}


def _expression_check(value: str, name: str, contexts: Sequence[str], path: str) -> bool:
    fields = [item for item in contexts if "(" not in item]
    functions = [item.partition("(")[0].lower() for item in contexts if "(" in item]
    parts = expressions.segments(value)
    if name in {"job-if", "step-if"} and not any(expr for expr, _ in parts):
        parts = [(True, value)]
    found = False
    for expr, text in parts:
        if expr:
            found = True
            if not contexts:
                raise _issue(path, "Expressions are not available in this field.")
            try:
                tree = expressions.parse(
                    text, contexts=fields, functions=(*_PURE_FUNCTIONS, *functions)
                )
                if name == "run-name":
                    expressions.check_launch_context(tree)
            except WorkflowValidationError as error:
                hint = _expression_hint(error.message, text)
                raise _issue(path, error.message + (f" {hint}" if hint else "")) from None
    return found


def _expression_hint(message: str, text: str) -> str:
    """Guidance appended to a parser message without changing the message itself."""
    if message == "Unexpected expression symbol." and '"' in text:
        return "Strings use single quotes, for example 'main'."
    for root, replacement in PLATFORM_ROOTS.items():
        if message != f"Unrecognized named-value: {root}.":
            continue
        match = re.search(rf"\b{root}\.([A-Za-z_]+)(?:\.([A-Za-z_]+)\.([A-Za-z_]+))?", text)
        prop, middle, last = match.groups() if match else (None, None, None)
        if root == "github" and prop == "event" and middle == "inputs":
            return f"Use inputs.{last}."
        if prop in PLATFORM_NAMES[root]:
            return f"Use {PLATFORM_NAMES[root][prop]}."
        if root == "github" and prop == "token":
            return "Relay does not issue a token; bind a secret instead."
        provided = ", ".join(sorted(expressions.CONTEXT_PROPERTIES[replacement]))
        return f"Use {replacement}, which provides {provided}."
    return ""


def _step_variant(value: Mapping[str, Any]) -> str | None:
    """The step form a mapping is written in, or None when it has neither run nor uses."""
    if "uses" in value:
        return "regular-step"
    if "run" in value:
        return "run-step"
    definitions = language_definitions()
    names = {
        key
        for variant in ("run-step", "regular-step")
        for key in definitions[variant]["mapping"]["properties"]
    }
    for key in value:
        if str(key) not in names:
            suggestion = closest(str(key), names)
            if suggestion in {"run", "uses"}:
                return "run-step" if suggestion == "run" else "regular-step"
    return None


def _step_shape_error(value: object, path: str) -> WorkflowValidationError | None:
    """One error for a step that has both or neither of run and uses."""
    if not isinstance(value, Mapping):
        return None
    if "run" in value and "uses" in value:
        return _issue(path, "A step needs either run or uses, not both.")
    if _step_variant(value) is None:
        return _issue(path, "A step needs run (a script) or uses (an action).")
    return None


def _validate_type(name: str, value: object, path: str, inherited: Sequence[str] = ()) -> object:
    definitions = language_definitions()
    base = definitions.get(name, {name: {}})
    if not isinstance(base, Mapping):
        raise _issue(path, "Invalid language definition.")
    contexts = tuple(dict.fromkeys([*inherited, *cast(Sequence[str], base.get("context", []))]))
    expression = isinstance(value, str) and _expression_check(value, name, contexts, path)
    if expression and value.strip().startswith("${{"):
        parts = expressions.segments(value)
        if len(parts) == 1 and parts[0][0]:
            return value
    if "one-of" in base:
        if name == "steps-item":
            shape = _step_shape_error(value, path)
            if shape is not None:
                raise shape
        errors = []
        variants = cast(list[str], base["one-of"])
        matching = (
            "mapping"
            if isinstance(value, Mapping)
            else "sequence"
            if isinstance(value, list)
            else "boolean"
            if isinstance(value, bool)
            else "number"
            if isinstance(value, (int, float))
            else "null"
            if value is None
            else "string"
        )
        variants = sorted(
            variants, key=lambda variant: matching not in definitions.get(variant, {variant: {}})
        )
        for variant in variants:
            try:
                return _validate_type(variant, value, path, contexts)
            except WorkflowValidationError as error:
                errors.append(error)
        if isinstance(value, Mapping):
            variant = (
                "workflow-job"
                if name == "job" and "uses" in value
                else "job-factory"
                if name == "job"
                else _step_variant(value)
                if name == "steps-item"
                else None
            )
            if variant:
                return _validate_type(variant, value, path, contexts)
        constants = [
            cast(Mapping[str, Any], definitions.get(variant, {})).get("string", {}).get("constant")
            for variant in cast(list[str], base["one-of"])
        ]
        if all(isinstance(constant, str) for constant in constants):
            raise _issue(path, f"Expected one of {', '.join(cast(list[str], constants))}.")
        raise errors[0]
    if "mapping" in base:
        record = _mapping(value, path)
        definition = cast(dict[str, Any], base["mapping"])
        properties = cast(dict[str, Any], definition.get("properties", {}))
        result = {}
        if "loose-key-type" not in definition:
            for key in record.keys() - properties.keys():
                raise _unknown_field(f"{path}.{key}", properties)
        for key, descriptor in properties.items():
            if isinstance(descriptor, Mapping) and descriptor.get("required") and key not in record:
                message = f"{path}.{key}"
                raise _issue(message, "Required field is missing.")
        for key, item in record.items():
            descriptor = properties.get(key)
            if descriptor is None:
                # Unknown keys were rejected above unless this mapping allows loose keys.
                _validate_type(str(definition["loose-key-type"]), key, f"{path}.{key}")
                descriptor = definition["loose-value-type"]
            type_name = descriptor["type"] if isinstance(descriptor, Mapping) else descriptor
            result[key] = _validate_type(str(type_name), item, f"{path}.{key}", contexts)
        return result
    if "sequence" in base:
        if not isinstance(value, list):
            raise _issue(path, "Expected a sequence.")
        descriptor = cast(dict[str, str], base["sequence"])
        return [
            _validate_type(descriptor.get("item-type", "any"), item, f"{path}[{index}]", contexts)
            for index, item in enumerate(value)
        ]
    if "string" in base:
        if isinstance(value, (list, Mapping)):
            hint = (
                ' Write a list as one value per line under "|", or as a JSON array string.'
                if isinstance(value, list) and ".with." in path
                else ""
            )
            raise _issue(path, f"Expected a scalar string.{hint}")
        result = expressions.string(value)
        descriptor = cast(dict[str, Any], base["string"])
        maximum = descriptor.get("max-length")
        if isinstance(maximum, int) and len(result) > maximum:
            raise _issue(path, f"Use at most {maximum} characters.")
        if descriptor.get("require-non-empty") and not result:
            raise _issue(path, "String cannot be empty.")
        allowed = base.get("allowed-values") or (
            [descriptor["constant"]] if "constant" in descriptor else None
        )
        if allowed is not None and result not in allowed:
            hint = f" {EVENTS_HINT}" if name == "local-event" else ""
            raise _issue(path, f"Expected one of {', '.join(allowed)}.{hint}")
        return result
    if "number" in base and (
        isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
    ):
        raise _issue(path, "Expected a finite number.")
    if "boolean" in base and not isinstance(value, bool):
        raise _issue(path, "Expected a boolean.")
    if "null" in base and value is not None:
        raise _issue(path, "Expected null.")
    return value


def _validate_filters(event: str, config: Mapping[str, Any]) -> None:
    from .patterns import pattern_regex

    for prefix in ("branches", "tags", "paths"):
        if prefix in config and f"{prefix}-ignore" in config:
            message = f"on.{event}"
            raise _issue(message, f"{prefix} and {prefix}-ignore are mutually exclusive.")
        for field in (prefix, f"{prefix}-ignore"):
            patterns = config.get(field, [])
            if not isinstance(patterns, list):
                message = f"on.{event}.{field}"
                raise _issue(message, "Expected a sequence of patterns.")
            if patterns and all(str(pattern).startswith("!") for pattern in patterns):
                message = f"on.{event}.{field}"
                raise _issue(message, "Include at least one positive pattern.")
            for pattern in patterns:
                pattern_regex(str(pattern).removeprefix("!"))


def events(workflow: Mapping[str, Any]) -> dict[str, Any]:
    value = workflow.get("on", {})
    if isinstance(value, str):
        return {value: {}}
    if isinstance(value, list):
        return {str(item): {} for item in value}
    return (
        {str(key): item or {} for key, item in value.items()} if isinstance(value, Mapping) else {}
    )


def input_definitions(
    workflow: Mapping[str, Any], event: str = "workflow_dispatch"
) -> dict[str, Any]:
    config = events(workflow).get(event, {})
    return (
        _mapping(config.get("inputs", {}), f"on.{event}.inputs")
        if isinstance(config, Mapping)
        else {}
    )


def resolve_inputs(
    workflow: Mapping[str, Any],
    supplied: Mapping[str, Any],
    *,
    event: str = "workflow_dispatch",
    environments: Sequence[str] | None = None,
) -> dict[str, Any]:
    declared = input_definitions(workflow, event)
    unknown = supplied.keys() - declared.keys()
    if unknown:
        message = "inputs"
        raise _issue(message, f"Unknown input: {sorted(unknown)[0]}.")
    resolved = {}
    for name, raw in declared.items():
        definition = _mapping(raw, f"inputs.{name}")
        kind = definition.get("type", "string")
        fallback = False if kind == "boolean" else 0 if kind == "number" else ""
        value = supplied.get(name, definition.get("default", fallback))
        if definition.get("required") and name not in supplied and "default" not in definition:
            message = f"inputs.{name}"
            raise _issue(message, "Required input is missing.")
        if kind == "boolean" and not isinstance(value, bool):
            message = f"inputs.{name}"
            raise _issue(message, "Expected a boolean.")
        if kind == "number" and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            message = f"inputs.{name}"
            raise _issue(message, "Expected a finite number.")
        if kind in {"string", "choice", "environment"} and not isinstance(value, str):
            message = f"inputs.{name}"
            raise _issue(message, "Expected a string.")
        if kind == "choice" and value not in definition.get("options", []):
            message = f"inputs.{name}"
            raise _issue(message, "Choose a declared option.")
        if kind == "environment" and environments is not None and value not in environments:
            message = f"inputs.{name}"
            raise _issue(message, "Choose a configured environment.")
        resolved[name] = value
    if len(json.dumps(resolved).encode()) > 65_535:
        message = "inputs"
        raise _issue(message, "Inputs exceed 65535 bytes.")
    return resolved


def _uses_guidance(reference: str) -> str:
    """What to write instead of an unsupported uses reference."""
    base = reference.partition("@")[0]
    replacements = {
        "actions/upload-artifact": ("upload-artifact", "name, path, and retention-days"),
        "actions/download-artifact": ("download-artifact", "name and path"),
        "actions/cache": ("cache", "key, path, and restore-keys"),
        "actions/cache/restore": ("restore-cache", "key, path, and restore-keys"),
        "actions/cache/save": ("save-cache", "key and path"),
    }
    if base == "actions/checkout":
        return "Remove this step: jobs already run in a working copy of this repository."
    if base.startswith("actions/setup-"):
        return "Remove this step and use the tool installed on this computer."
    if base in replacements:
        name, inputs = replacements[base]
        return f"Use {current_builtin(name).reference} with the same {inputs} inputs."
    if reference.startswith("docker://"):
        command = current_builtin("command").reference
        return f"Run the program with a run step or {command} instead of a container image."
    if reference.startswith("./.github/actions/"):
        name = base.removeprefix("./.github/actions/").strip("/") or "<name>"
        return f"Move the action to ./.relay/actions/{name} and use that path."
    current = sorted(action.reference for action in BUILTIN_ACTIONS if action.status == "current")
    suggestion = closest(reference, current) if reference.startswith("relay/") else None
    if suggestion:
        return f"Did you mean {suggestion}?"
    return f"Use one of {', '.join(current)}, or a local action under ./.relay/actions/."


def _validate_shell(shell: object, path: str) -> None:
    """A literal shell is a named shell or a command with one {0} placeholder."""
    if (
        isinstance(shell, str)
        and "${{" not in shell
        and shell not in SHELLS
        and shell.count("{0}") != 1
    ):
        message = f"shell: {SHELL_HINT}"
        raise WorkflowValidationError(message, context={"field": path})


def _validate_default_shell(scope: Mapping[str, Any], path: str) -> None:
    defaults = scope.get("defaults")
    run = defaults.get("run") if isinstance(defaults, Mapping) else None
    if isinstance(run, Mapping) and "shell" in run:
        _validate_shell(run["shell"], f"{path}defaults.run.shell")


def validate_steps(steps: object, path: str, start: int = 0) -> None:
    """Every ordered-step container uses the same local execution contract."""
    if not isinstance(steps, list) or not steps:
        message = path
        raise _issue(message, "A job must contain ordered steps.")
    ids = set()
    for offset, raw_step in enumerate(steps):
        here = f"{path}[{offset + start}]"
        step = _mapping(raw_step, here)
        step_id = step.get("id")
        if step_id is not None:
            if IDENTIFIER.fullmatch(str(step_id)) is None or step_id in ids:
                message = f"{here}.id"
                raise _issue(message, "Invalid or duplicate step id.")
            ids.add(step_id)
        reference = step.get("uses")
        if (
            reference is not None
            and builtin(reference) is None
            and (not str(reference).startswith("./.relay/actions/") or "${{" in str(reference))
        ):
            message = f"{here}.uses"
            raise _issue(
                message,
                "Only frozen local and versioned relay actions are supported. "
                + _uses_guidance(str(reference)),
                unsupported=True,
            )
        script = step.get("run")
        found = FILE_VARIABLES.search(script) if isinstance(script, str) else None
        if found:
            message = f"{here}.run"
            raise _issue(
                message,
                f"{found[0]} is not a Relay variable. {FILE_VARIABLE_GUIDANCE[found[1]]}",
            )
        _validate_timeout(step.get("timeout-minutes"), here)
        if "run" in step and "shell" in step:
            _validate_shell(step["shell"], f"{here}.shell")
        if builtin(reference) is not None:
            from .builtins import validate_inputs

            inputs = _mapping(step.get("with", {}), f"{here}.with")
            try:
                validate_inputs(str(reference), inputs)
            except WorkflowValidationError as error:
                # Errors about one input name it relative to the step.
                field = error.context.get("field")
                error.context["field"] = f"{here}.{field}" if field else here
                raise
        elif "with" in step:
            _mapping(step["with"], f"{here}.with")


def _validate_contracts(workflow: dict[str, Any]) -> None:
    from pydantic import ValidationError

    from relay.workflows.schema import EntryPoint, RecoveryPolicy

    for field, model in (("entrypoints", EntryPoint), ("recovery", RecoveryPolicy)):
        values = workflow.get(field, []) if field == "entrypoints" else [workflow.get(field, {})]
        for value in values:
            try:
                parsed = model.model_validate(value)
            except ValidationError:
                raise _issue(
                    field, "Use valid local start points or a bounded recovery policy."
                ) from None
            if isinstance(parsed, EntryPoint):
                scope = parsed.scope_path.removeprefix("root.")
                if scope not in workflow["jobs"]:
                    raise _issue(field, "A start point must name a top-level job.")
    triggers = events(workflow)
    for event, raw in triggers.items():
        if event not in EVENTS:
            message = f"on.{event}"
            raise _issue(
                message, f"This event has no local Relay adapter. {EVENTS_HINT}", unsupported=True
            )
        if isinstance(raw, Mapping):
            _validate_filters(event, raw)
            for field in ("workflows",):
                if isinstance(raw.get(field), str):
                    raw[field] = [raw[field]]
        if event == "schedule":
            from relay.execution.triggers import validate_schedule

            if not isinstance(raw, list) or not raw:
                raise _issue("on.schedule", "Declare at least one local cron schedule.")
            for item in raw:
                validate_schedule(item)
    for event in ("workflow_dispatch", "workflow_call"):
        declared = input_definitions(workflow, event)
        for name, raw in declared.items():
            if IDENTIFIER.fullmatch(name) is None:
                message = f"on.{event}.inputs.{name}"
                raise _issue(message, "Invalid input identifier.")
            item = _mapping(raw, f"on.{event}.inputs.{name}")
            if item.get("type") == "choice" and not item.get("options"):
                message = f"on.{event}.inputs.{name}"
                raise _issue(message, "Choice inputs require options.")
            if "options" in item and item.get("type") != "choice":
                message = f"on.{event}.inputs.{name}.options"
                raise _issue(message, "Only choice inputs have options.")
            if "default" in item:
                resolve_inputs(
                    {"on": {event: {"inputs": {name: item}}}}, {name: item["default"]}, event=event
                )
    jobs = _mapping(workflow["jobs"], "jobs")
    if not jobs:
        message = "jobs"
        raise _issue(message, "A workflow must contain at least one job.")
    _validate_default_shell(workflow, "")
    for job_id, raw in jobs.items():
        if IDENTIFIER.fullmatch(job_id) is None:
            message = f"jobs.{job_id}"
            raise _issue(message, "Invalid job identifier.")
        job = _mapping(raw, f"jobs.{job_id}")
        _validate_default_shell(job, f"jobs.{job_id}.")
        for scope, label in ((workflow, "workflow"), (job, f"jobs.{job_id}")):
            if "env" in scope:
                _mapping(scope["env"], f"{label}.env")
        needs = job.get("needs", [])
        needs = [needs] if isinstance(needs, str) else needs
        if len(needs) != len(set(needs)) or any(item not in jobs for item in needs):
            message = f"jobs.{job_id}.needs"
            raise _issue(message, "Unknown or duplicate job dependency.")
        if "uses" in job:
            _mapping(job.get("with", {}), f"jobs.{job_id}.with")
            reference = str(job["uses"])
            if not reference.startswith("./.relay/workflows/") or "${{" in reference:
                message = f"jobs.{job_id}.uses"
                raise _issue(
                    message,
                    "Use a static local .relay/workflows reference.",
                    unsupported=True,
                )
        else:
            validate_steps(job.get("steps"), f"jobs.{job_id}.steps")
        _validate_timeout(job.get("timeout-minutes"), f"jobs.{job_id}")
        strategy = job.get("strategy", {})
        if isinstance(strategy, Mapping):
            matrix = strategy.get("matrix")
            if isinstance(matrix, Mapping):
                expand_matrix(matrix, f"jobs.{job_id}.strategy.matrix")
        for scope in (workflow, job):
            concurrency = scope.get("concurrency")
            if isinstance(concurrency, Mapping) and (
                concurrency.get("queue", "single") == "max"
                and concurrency.get("cancel-in-progress") is True
            ):
                message = "concurrency"
                raise _issue(message, "queue: max cannot cancel in-progress work.")
    topological_jobs(jobs)


def _validate_timeout(value: object, path: str) -> None:
    if (
        value is not None
        and not isinstance(value, str)
        and (isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= 360)
    ):
        message = f"{path}.timeout-minutes"
        raise _issue(message, "Timeout must be positive and at most 360 minutes.")


def topological_jobs(jobs: Mapping[str, Any]) -> tuple[str, ...]:
    """Stable topological order, using source order whenever several jobs are ready."""
    remaining = dict(jobs)
    done = set()
    result = []
    while remaining:
        selected = None
        for job_id, raw in remaining.items():
            job = cast(Mapping[str, Any], raw)
            needs = job.get("needs", [])
            needs = [needs] if isinstance(needs, str) else needs
            if all(item in done for item in needs):
                selected = job_id
                break
        if selected is None:
            message = "jobs"
            raise _issue(message, "Job dependencies contain a cycle.")
        result.append(selected)
        done.add(selected)
        del remaining[selected]
    return tuple(result)


def expand_matrix(matrix: Mapping[str, Any], path: str = "strategy.matrix") -> list[dict[str, Any]]:
    axes = {key: value for key, value in matrix.items() if key not in {"include", "exclude"}}
    originals: list[dict[str, Any]] = [{}] if axes else []
    for key, values in axes.items():
        if not isinstance(values, list) or not values:
            message = f"{path}.{key}"
            hint = (
                " To build the matrix from an expression, set the whole matrix: "
                "matrix: ${{ fromJSON(...) }}."
                if isinstance(values, str) and "${{" in values
                else ""
            )
            raise _issue(message, f"A matrix axis must be a nonempty sequence.{hint}")
        originals = [{**row, key: value} for row in originals for value in values]
        if len(originals) > 256:
            message = path
            raise _issue(message, "Matrix exceeds 256 job variants.")
    excluded = matrix.get("exclude", [])
    includes = matrix.get("include", [])
    if not isinstance(excluded, list) or not isinstance(includes, list):
        message = path
        raise _issue(message, "Include and exclude must be sequences of mappings.")
    for item in [*excluded, *includes]:
        if not isinstance(item, Mapping):
            message = path
            raise _issue(message, "Include and exclude items must be mappings.")
    originals = [
        row
        for row in originals
        if not any(
            all(key in row and expressions.equal(row[key], value) for key, value in item.items())
            for item in excluded
        )
    ]
    results = deepcopy(originals)
    appended = []
    for item in includes:
        matched = False
        for index, original in enumerate(originals):
            if all(
                key not in axes or expressions.equal(original.get(key), value)
                for key, value in item.items()
            ):
                results[index].update(item)
                matched = True
        if not matched:
            appended.append(dict(item))
    results.extend(appended)
    if not results or len(results) > 256:
        message = path
        raise _issue(message, "Matrix must produce between 1 and 256 variants.")
    return results


def _read_document(text: str) -> tuple[Mapping[str, Any], dict[str, tuple[int, int]]]:
    if len(text.encode("utf-8")) > MAX_YAML_BYTES:
        message = "workflow"
        raise _issue(message, "Workflow exceeds 1 MiB.")
    parser = YAML(typ="rt")
    parser.allow_duplicate_keys = False
    locations: dict[str, tuple[int, int]] = {}
    try:
        tree = parser.compose(text)
        if tree is not None:
            _inspect_tree(tree, "workflow", locations, frozenset(), [0, 0])
        document = parser.load(text)
    except WorkflowValidationError as error:
        _locate(error, locations)
        raise
    except Exception as error:
        mark = getattr(error, "problem_mark", None)
        context = {"line": mark.line + 1, "column": mark.column + 1} if mark else {}
        reason = str(getattr(error, "problem", "Check indentation and quotes."))[:500]
        hint = "Check indentation; use spaces rather than tabs."
        lower = reason.lower()
        if "mapping values" in lower:
            hint = "Quote a value that contains a colon followed by a space."
        elif "expected" in lower and ("," in lower or "]" in lower or "}" in lower):
            hint = "Close each bracket or brace and separate items with commas."
        elif "quoted scalar" in lower:
            hint = "Close the quoted value and check its escape sequences."
        elif "alias" in lower:
            hint = "Define the anchor before referencing it with an alias."
        elif "document" in lower:
            hint = "Keep one workflow document in each file."
        message = f"Invalid YAML document: {reason}. {hint}"
        raise WorkflowValidationError(message, context=context) from None
    _mapping(document, "workflow")
    return cast(Mapping[str, Any], document), locations


def _position(field: str, locations: Mapping[str, tuple[int, int]]) -> tuple[int, int] | None:
    """The line and column of a field, or of its nearest located parent."""
    location = locations.get(field) or locations.get("workflow." + field)
    while location is None and "." in field:
        field = field.rsplit(".", 1)[0]
        location = locations.get(field) or locations.get("workflow." + field)
    return location or locations.get("workflow")


def _locate(error: WorkflowValidationError, locations: Mapping[str, tuple[int, int]]) -> None:
    location = _position(str(error.context.get("field", "workflow")), locations)
    if location:
        error.context.update({"line": str(location[0]), "column": str(location[1])})


def load(text: str, *, source: Path | None = None) -> ActionsDocument:
    source = source or Path("<memory>")
    document, locations = _read_document(text)
    record = _mapping(document, "workflow")
    if "version" in record or "nodes" in record:
        message = "workflow"
        raise _issue(
            message,
            "Workflow sources require a jobs mapping with ordered steps.",
            unsupported=True,
        )
    try:
        value = cast(dict[str, Any], _validate_type("workflow-root", record, "workflow"))
        _validate_contracts(value)
    except WorkflowValidationError as error:
        _locate(error, locations)
        raise
    return ActionsDocument(text, source, document, value, locations)


def workflow_diagnostics(text: str, *, source: Path | None = None) -> list[WorkflowValidationError]:
    """Report independent fields without executing or repairing the supplied source."""
    try:
        document, locations = _read_document(text)
    except WorkflowValidationError as error:
        return [error]
    issues: list[WorkflowValidationError] = []
    definitions = language_definitions()

    def visit(name: str, value: object, path: str, inherited: Sequence[str] = ()) -> None:
        if len(issues) >= 100:
            return
        base = definitions.get(name, {name: {}})
        contexts = tuple(dict.fromkeys([*inherited, *base.get("context", [])]))
        try:
            _validate_type(name, value, path, inherited)
        except WorkflowValidationError as original:
            if name == "steps-item" and _step_shape_error(value, path) is not None:
                issues.append(original)
                return
            if "one-of" in base:
                variant = (
                    "workflow-job"
                    if name == "job" and isinstance(value, Mapping) and "uses" in value
                    else "job-factory"
                    if name == "job" and isinstance(value, Mapping)
                    else _step_variant(value)
                    if name == "steps-item" and isinstance(value, Mapping)
                    else next(
                        (
                            item
                            for item in base["one-of"]
                            if (
                                isinstance(value, Mapping)
                                and "mapping" in definitions.get(item, {})
                            )
                            or (isinstance(value, list) and "sequence" in definitions.get(item, {}))
                        ),
                        None,
                    )
                )
                if variant:
                    visit(variant, value, path, contexts)
                    return
            if "mapping" in base and isinstance(value, Mapping):
                mapping = base["mapping"]
                properties = mapping.get("properties", {})
                unknown = (
                    [f"{path}.{key}" for key in value if key not in properties]
                    if "loose-key-type" not in mapping
                    else []
                )
                issues.extend(_unknown_field(field, properties) for field in unknown)
                # A misspelled key explains the required key it was meant to be.
                suggested = {_unknown_hint(field, properties)[1] for field in unknown}
                for key, descriptor in properties.items():
                    if (
                        isinstance(descriptor, Mapping)
                        and descriptor.get("required")
                        and key not in value
                        and key not in suggested
                    ):
                        issues.append(_issue(f"{path}.{key}", "Required field is missing."))
                for key, item in value.items():
                    descriptor = properties.get(key)
                    if descriptor is None and "loose-key-type" not in mapping:
                        continue
                    descriptor = descriptor or mapping.get("loose-value-type", "any")
                    child = str(
                        descriptor["type"] if isinstance(descriptor, Mapping) else descriptor
                    )
                    visit(child, item, f"{path}.{key}", contexts)
                return
            if "sequence" in base and isinstance(value, list):
                for index, item in enumerate(value):
                    visit(
                        base["sequence"].get("item-type", "any"), item, f"{path}[{index}]", contexts
                    )
                return
            issues.append(original)
        else:
            return

    visit("workflow-root", document, "workflow")
    jobs = document.get("jobs")
    if isinstance(jobs, Mapping):
        for job_id, job in jobs.items():
            if not isinstance(job, Mapping) or not isinstance(job.get("steps"), list):
                continue
            for index, step in enumerate(job["steps"]):
                if not isinstance(step, Mapping):
                    continue
                try:
                    validate_steps([step], f"jobs.{job_id}.steps", start=index)
                except (WorkflowValidationError, TypeError, ValueError) as error:
                    if isinstance(error, WorkflowValidationError):
                        issues.append(error)
    if not issues:
        try:
            load(text, source=source)
        except WorkflowValidationError as error:
            issues.append(error)
    unique: dict[tuple[str, str], WorkflowValidationError] = {}
    for issue in issues[:100]:
        _locate(issue, locations)
        unique[(str(issue.context.get("field", "")), issue.message)] = issue
    return list(unique.values())


@contextmanager
def _reported_at(field: str) -> Iterator[None]:
    """Attribute a source error to the step or job that names the source.

    Nested sources report at the outermost reference, which is the one the
    open document contains.
    """
    try:
        yield
    except WorkflowValidationError as error:
        error.context["field"] = field
        raise


def capture_sources(document: ActionsDocument, project_root: Path) -> dict[str, str]:
    """Freeze transitive local workflows, action metadata, and JavaScript bytes."""
    result = {}
    stack: list[str] = []
    workflows = set()

    def capture(reference: str, *, workflow: bool, depth: int) -> None:
        if depth > 10:
            message = "uses"
            raise _issue(message, "Reusable workflows exceed 10 levels.")
        relative = reference.removeprefix("./")
        path = safe_resolve(project_root, relative)
        if not workflow:
            if not path.is_dir():
                raise _issue(reference, "Local action directory is missing.")
            path = next(
                (path / name for name in ("action.yml", "action.yaml") if (path / name).is_file()),
                path / "action.yml",
            )
        key = path.relative_to(project_root.resolve()).as_posix()
        if key in stack:
            message = "uses"
            raise _issue(message, "Local references contain a cycle.")
        if key in result:
            return
        if not path.is_file() or path.stat().st_size > MAX_YAML_BYTES:
            raise _issue(reference, "Local source is missing or exceeds 1 MiB.")
        try:
            text = path.read_bytes().decode("utf-8")
        except (OSError, UnicodeError):
            raise _issue(reference, "Local source cannot be read as UTF-8.") from None
        result[key] = text
        if sum(len(item.encode()) for item in result.values()) > 10 * MAX_YAML_BYTES:
            message = "uses"
            raise _issue(message, "Captured sources exceed 10 MiB.")
        stack.append(key)
        if workflow:
            workflows.add(key)
            if len(workflows) > 50:
                message = "uses"
                raise _issue(message, "More than 50 unique reusable workflows.")
            child = load(text, source=path)
            if "workflow_call" not in events(child.value):
                raise _issue(reference, "Reusable workflow must declare on.workflow_call.")
            visit(child.value, depth + 1)
        else:
            from .metadata import load_action

            action = load_action(text, source=path)
            runs = action["runs"]
            if runs["using"] == "composite":
                visit({"jobs": {"composite": {"steps": runs["steps"]}}}, depth)
            else:
                for field in ("main", "post"):
                    if field in runs:
                        script = safe_resolve(path.parent, runs[field])
                        capture_script(script, project_root, result)
            from .patterns import select_paths

            for asset in select_paths(path.parent, ["**"], files_only=True):
                capture_script(asset, project_root, result)
            if sum(len(item.encode()) for item in result.values()) > 10 * MAX_YAML_BYTES:
                message = "uses"
                raise _issue(message, "Captured sources exceed 10 MiB.")
        stack.pop()

    def visit(value: Mapping[str, Any], depth: int) -> None:
        for job_id, job in value.get("jobs", {}).items():
            if "uses" in job:
                with _reported_at(f"jobs.{job_id}.uses"):
                    capture(job["uses"], workflow=True, depth=depth)
            for index, step in enumerate(job.get("steps", [])):
                here = f"jobs.{job_id}.steps[{index}]"
                reference = step.get("uses", "")
                if reference.startswith("./"):
                    with _reported_at(f"{here}.uses"):
                        capture(reference, workflow=False, depth=depth)
                        from .metadata import load_action, validate_action_inputs

                        prefix = reference.removeprefix("./").rstrip("/")
                        metadata = result.get(
                            prefix + "/action.yml", result.get(prefix + "/action.yaml")
                        )
                        if metadata is not None:
                            validate_action_inputs(load_action(metadata), step.get("with", {}))
                if is_builtin(reference, "loop"):
                    target = step.get("with", {}).get("workflow")
                    with _reported_at(f"{here}.with.workflow"):
                        if not isinstance(target, str) or not target.startswith(
                            "./.relay/workflows/"
                        ):
                            message = "with.workflow"
                            raise _issue(message, "Loop requires a static reusable workflow.")
                        capture(target, workflow=True, depth=depth)

    visit(document.value, 1)
    return result


def missing_prompt_files(
    document: ActionsDocument, relay_root: Path, drafts: Iterable[Path] = ()
) -> list[WorkflowValidationError]:
    """Report literal agent prompt files that neither exist nor are unsaved drafts.

    References resolve exactly as launch resolves them: local paths under the
    project's .relay folder and global:NAME in the owner's prompt folder.
    """
    from relay.errors import PathSafetyError
    from relay.paths import global_prompts_dir

    pending = {path.resolve() for path in drafts}
    issues = []
    for job_id, job in document.value.get("jobs", {}).items():
        for index, step in enumerate(job.get("steps", [])):
            references = step.get("with", {}).get("prompt-files")
            if not is_builtin(step.get("uses"), "agent") or not isinstance(references, str):
                continue
            for reference in references.splitlines():
                if not reference.strip() or "${{" in reference:
                    continue
                if reference.startswith("global:"):
                    root, value = global_prompts_dir(), reference[7:]
                else:
                    root, value = relay_root, reference.strip().removeprefix(".relay/")
                try:
                    path = safe_resolve(root, value)
                except PathSafetyError:
                    continue  # Launch reports a reference that leaves its folder.
                if path.is_file() or path in pending:
                    continue
                error = WorkflowValidationError(
                    f"Prompt file {reference.strip()} does not exist.",
                    context={"field": f"jobs.{job_id}.steps[{index}].with.prompt-files"},
                )
                _locate(error, document.locations)
                issues.append(error)
    return issues


MAX_WARNINGS = 100
_AGENT_WITHOUT_PROMPT = (
    "This agent step has no prompt or prompt-files, so the agent receives no instructions."
)


def _field_strings(value: object, path: str) -> Iterator[tuple[str, str]]:
    """Every string below one field, with its path."""
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield from _field_strings(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _field_strings(item, f"{path}[{index}]")


def _scoped_strings(
    workflow: Mapping[str, Any],
) -> Iterator[tuple[str, str, bool, str | None, frozenset[str] | None]]:
    """Each string with its path, bare-if flag, job, and the step ids it can read.

    The workflow has already validated, so jobs are mappings and steps, when
    present, are a list of mappings. A step reads the ids of earlier steps in
    its job, a job-level field such as outputs reads every step id in its job,
    and a workflow-level field reads none. Ids are upper-cased because
    expression lookups ignore case.
    """
    for key, value in workflow.items():
        if key != "jobs":
            for path, text in _field_strings(value, key):
                yield path, text, False, None, None
            continue
        for job_id, job in value.items():
            steps = job.get("steps", [])
            ids = [
                expressions.upper(str(step["id"])) if step.get("id") is not None else ""
                for step in steps
            ]
            for job_key, item in job.items():
                if job_key != "steps":
                    path = f"jobs.{job_id}.{job_key}"
                    every = frozenset(filter(None, ids))
                    for here, text in _field_strings(item, path):
                        yield here, text, job_key == "if" and here == path, job_id, every
                    continue
                for index, step in enumerate(steps):
                    earlier = frozenset(filter(None, ids[:index]))
                    for step_key, field in step.items():
                        path = f"jobs.{job_id}.steps[{index}].{step_key}"
                        for here, text in _field_strings(field, path):
                            yield here, text, step_key == "if" and here == path, job_id, earlier


def _named_properties(tree: expressions.Tree) -> Iterator[tuple[str, str]]:
    """Each context.<name> or context['<name>'] access in a parsed expression.

    The walk uses its own stack because long operator chains nest deeply.
    """
    pending = [tree]
    while pending:
        node = pending.pop()
        kind = node[0]
        if kind == "index":
            target, key = node[1], node[2]
            if target[0] == "context" and key[0] == "literal" and isinstance(key[1], str):
                yield str(target[1]), key[1]
            children: Sequence[object] = (target, key)
        elif kind == "call":
            children = node[2]
        elif kind in {"literal", "context", "star"}:
            children = ()
        else:
            children = node[1:]
        pending.extend(
            cast(expressions.Tree, child)
            for child in reversed(children)
            if isinstance(child, tuple) and child
        )


def _expression_references(text: str, *, bare: bool) -> Iterator[tuple[str, str]]:
    """Context properties a string names; a bare if is one whole expression."""
    try:
        parts = expressions.segments(text)
    except WorkflowValidationError:
        return
    if bare and not any(expr for expr, _ in parts):
        parts = [(True, text)]
    for expr, source in parts:
        if not expr:
            continue
        try:
            tree = expressions.parse(source)
        except WorkflowValidationError:
            continue
        yield from _named_properties(tree)


def workflow_warnings(
    document: ActionsDocument,
) -> list[WorkflowValidationError]:
    """Non-blocking findings for a source that already validates.

    Each warning names an input, earlier step, or needed job that cannot supply
    a value, or an agent step without instructions. Warnings appear in source
    order; callers locate them with _locate. Nothing here reads files or
    credentials.
    """
    workflow = document.value
    jobs = cast(Mapping[str, Mapping[str, Any]], workflow["jobs"])
    inputs = {
        expressions.upper(name)
        for event in ("workflow_dispatch", "workflow_call")
        for name in input_definitions(workflow, event)
    }
    needs: dict[str, set[str]] = {}
    for job_id, job in jobs.items():
        declared = job.get("needs", [])
        declared = [declared] if isinstance(declared, str) else declared
        needs[job_id] = {expressions.upper(str(item)) for item in declared}
    found: dict[tuple[str, str], WorkflowValidationError] = {}

    def add(path: str, message: str) -> None:
        if len(found) < MAX_WARNINGS:
            found.setdefault((path, message), _warning(path, message))

    for job_id, job in jobs.items():
        for index, step in enumerate(job.get("steps", [])):
            if not is_builtin(step.get("uses"), "agent"):
                continue
            given = step.get("with", {})
            if not any(
                isinstance(given.get(name), str) and given[name].strip()
                for name in ("prompt", "prompt-files")
            ):
                add(f"jobs.{job_id}.steps[{index}]", _AGENT_WITHOUT_PROMPT)
    for path, text, bare, job_id, step_ids in _scoped_strings(workflow):
        for context, name in _expression_references(text, bare=bare):
            key = expressions.upper(name)
            if context == "inputs" and key not in inputs:
                add(path, f"inputs.{name} is not a declared input. It will be empty at run time.")
            elif context == "steps" and step_ids is not None and key not in step_ids:
                add(
                    path,
                    f"steps.{name} does not name an earlier step in this job. "
                    "It will be empty at run time.",
                )
            elif context == "needs" and job_id is not None and key not in needs[job_id]:
                add(
                    path,
                    f"needs.{name} is not listed in this job's needs. "
                    "It will be empty at run time.",
                )
    return sorted(
        found.values(),
        key=lambda item: _position(str(item.context["field"]), document.locations) or (0, 0),
    )


def referenced_secrets(document: ActionsDocument, *, job: str | None = None) -> set[str]:
    """Secret names the workflow's expressions read by literal name, upper-cased.

    Binding names are upper-case and expression lookups ignore case. With job,
    only that job's fields and the workflow-level fields it inherits count.
    """
    names = set()
    for _, text, bare, job_id, _ in _scoped_strings(document.value):
        if job is not None and job_id not in {None, job}:
            continue
        names.update(
            name.upper()
            for context, name in _expression_references(text, bare=bare)
            if context == "secrets"
        )
    return names


def capture_script(path: Path, project_root: Path, result: dict[str, str]) -> None:
    if not path.is_file() or path.stat().st_size > 10 * MAX_YAML_BYTES:
        message = "runs"
        raise _issue(message, "Action script is missing or too large.")
    try:
        key = path.relative_to(project_root.resolve()).as_posix()
        if key in result:
            return
        raw = path.read_bytes()
        try:
            content = raw.decode("utf-8")
        except UnicodeError:
            content = None
        if content is None or content.startswith("\x00") or path.stat().st_mode & 0o111:
            content = f"\x00asset:{path.stat().st_mode & 0o777:03o}:" + base64.b64encode(
                raw
            ).decode("ascii")
        result[key] = content
    except OSError:
        message = "runs"
        raise _issue(message, "Action sources could not be read.") from None


def source_bytes(content: str) -> tuple[bytes, int]:
    """Decode a frozen asset without confusing UTF-8 bytes with an encoding tag."""
    if content.startswith("\x00asset:"):
        _, mode, value = content.split(":", 2)
        return base64.b64decode(value, validate=True), int(mode, 8) & 0o777
    return content.encode("utf-8"), 0o600


def support_manifest() -> dict[str, Any]:
    return {
        "dialect": DIALECT,
        "upstream_commit": UPSTREAM,
        "workflow_directory": ".relay/workflows",
        "job_execution": "serial",
        "definitions": language_definitions(),
        "builtins": sorted(
            action.reference for action in BUILTIN_ACTIONS if action.status == "current"
        ),
        "property_descriptions": language_property_descriptions(),
        "builtin_inputs": {
            action.reference: {
                "allowed": sorted(action.allowed),
                "required": sorted(action.required),
                "summary": action.summary,
                "descriptions": dict(action.descriptions),
                "values": {key: list(values) for key, values in action.values.items()},
            }
            for action in BUILTIN_ACTIONS
        },
        "builtin_versions": {
            action.reference: {
                "name": action.name,
                "major": action.major,
                "status": action.status,
            }
            for action in BUILTIN_ACTIONS
        },
        "events": sorted(EVENTS),
        "cache_modes": sorted(CACHE_MODES),
        "value_hints": {"shell": list(SHELLS)},
        "platform_names": PLATFORM_NAMES,
        "contexts": sorted(expressions.CONTEXTS),
        "context_properties": {
            key: sorted(value) for key, value in expressions.CONTEXT_PROPERTIES.items()
        },
        "limits": {
            "yaml_bytes": MAX_YAML_BYTES,
            "yaml_nodes": MAX_YAML_NODES,
            "aliases": MAX_ALIASES,
            "expression_length": expressions.MAX_LENGTH,
            "expression_depth": expressions.MAX_DEPTH,
            "matrix_variants": 256,
            "reusable_levels": 10,
            "reusable_files": 50,
            "queued_runs": 100,
        },
        "unsupported": [
            "permissions",
            "container",
            "services",
            "hosted-runners",
            "runs-on",
            "max-parallel",
            "environment.deployment",
            "workflow_run.types",
            "action.branding",
            "action.author",
            "oci-artifact-subjects",
            "remote-actions",
            "parallel",
            "background",
            "wait",
            "wait-all",
            "cancel",
            "snapshot",
            "yaml-merge",
            "custom-tags",
        ],
    }
