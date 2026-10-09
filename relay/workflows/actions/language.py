"""Relay's local workflow language, inspired by Actions jobs and expressions.

Only Relay-owned schema definitions are accepted. Validation never launches a
process, looks up a credential, or changes workflow sources.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
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
BUILTINS = frozenset(
    {
        "relay/agent@v1",
        "relay/command@v1",
        "relay/human-wait@v1",
        "relay/loop@v1",
        "relay/validate-report@v1",
        "relay/validate-input@v1",
        "relay/upload-artifact@v1",
        "relay/download-artifact@v1",
        "relay/cache@v1",
        "relay/restore-cache@v1",
        "relay/save-cache@v1",
    }
)
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


def _unknown_field(path: str) -> WorkflowValidationError:
    hints = {
        "runs-on": "Relay runs on this computer. Remove runs-on; select an agent in the step.",
        "permissions": "Authentication belongs to your installed tools. Remove permissions.",
        "container": "Use a local script or command instead of a container.",
        "services": "Start required services outside Relay before running this workflow.",
        "max-parallel": "Local matrix jobs run serially. Remove max-parallel.",
        "timeout": "Use timeout-minutes with a number, for example timeout-minutes: 10.",
        "nodes": "Use jobs with ordered steps for a new workflow.",
        "agents": "Select agent or agents in with on a relay/agent@v1 step.",
    }
    hint = hints.get(path.rsplit(".", 1)[-1])
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
            if key.value in names:
                message = f"{path}.{key.value}"
                raise _issue(message, "Duplicate YAML key.")
            names.add(key.value)
            _inspect_tree(child, f"{path}.{key.value}", locations, parents, counts, depth + 1)
    elif isinstance(node, SequenceNode):
        for index, child in enumerate(node.value):
            _inspect_tree(child, f"{path}[{index}]", locations, parents, counts, depth + 1)


@lru_cache(maxsize=1)
def language_definitions() -> dict[str, Any]:
    """The same curated schema is authoritative for validation and discovery."""
    return json.loads(Path(__file__).with_name("schema.json").read_text(encoding="utf-8"))[
        "definitions"
    ]


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
                raise _issue(path, error.message) from None
    return found


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
                else "regular-step"
                if name == "steps-item" and "uses" in value
                else "run-step"
                if name == "steps-item" and "run" in value
                else None
            )
            if variant:
                return _validate_type(variant, value, path, contexts)
        raise errors[0]
    if "mapping" in base:
        record = _mapping(value, path)
        definition = cast(dict[str, Any], base["mapping"])
        properties = cast(dict[str, Any], definition.get("properties", {}))
        result = {}
        if "loose-key-type" not in definition:
            for key in record.keys() - properties.keys():
                raise _unknown_field(f"{path}.{key}")
        for key, descriptor in properties.items():
            if isinstance(descriptor, Mapping) and descriptor.get("required") and key not in record:
                message = f"{path}.{key}"
                raise _issue(message, "Required field is missing.")
        for key, item in record.items():
            descriptor = properties.get(key)
            if descriptor is None:
                if "loose-key-type" not in definition:
                    message = f"{path}.{key}"
                    raise _unknown_field(message)
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
            raise _issue(path, "Expected a scalar string.")
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
            raise _issue(path, f"Expected one of {', '.join(allowed)}.")
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


def validate_steps(steps: object, path: str) -> None:
    """Every ordered-step container uses the same local execution contract."""
    if not isinstance(steps, list) or not steps:
        message = path
        raise _issue(message, "A job must contain ordered steps.")
    ids = set()
    for index, raw_step in enumerate(steps):
        step = _mapping(raw_step, f"{path}[{index}]")
        step_id = step.get("id")
        if step_id is not None:
            if IDENTIFIER.fullmatch(str(step_id)) is None or step_id in ids:
                message = f"{path}[{index}].id"
                raise _issue(message, "Invalid or duplicate step id.")
            ids.add(step_id)
        reference = step.get("uses")
        if (
            reference is not None
            and reference not in BUILTINS
            and (not str(reference).startswith("./.relay/actions/") or "${{" in str(reference))
        ):
            message = f"{path}[{index}].uses"
            raise _issue(
                message,
                "Only frozen local and versioned relay actions are supported.",
                unsupported=True,
            )
        _validate_timeout(step.get("timeout-minutes"), f"{path}[{index}]")
        if reference in BUILTINS:
            from .builtins import validate_inputs

            validate_inputs(reference, _mapping(step.get("with", {}), f"{path}[{index}].with"))
        elif "with" in step:
            _mapping(step["with"], f"{path}[{index}].with")


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
            raise _issue(message, "This event has no local Relay adapter.", unsupported=True)
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
        if event == "workflow_dispatch" and len(declared) > 25:
            message = "on.workflow_dispatch.inputs"
            raise _issue(message, "At most 25 dispatch inputs are supported.")
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
    for job_id, raw in jobs.items():
        if IDENTIFIER.fullmatch(job_id) is None:
            message = f"jobs.{job_id}"
            raise _issue(message, "Invalid job identifier.")
        job = _mapping(raw, f"jobs.{job_id}")
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
                expand_matrix(matrix)
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


def expand_matrix(matrix: Mapping[str, Any]) -> list[dict[str, Any]]:
    axes = {key: value for key, value in matrix.items() if key not in {"include", "exclude"}}
    originals: list[dict[str, Any]] = [{}] if axes else []
    for key, values in axes.items():
        if not isinstance(values, list) or not values:
            message = f"strategy.matrix.{key}"
            raise _issue(message, "A matrix axis must be a nonempty sequence.")
        originals = [{**row, key: value} for row in originals for value in values]
        if len(originals) > 256:
            message = "strategy.matrix"
            raise _issue(message, "Matrix exceeds 256 job variants.")
    excluded = matrix.get("exclude", [])
    includes = matrix.get("include", [])
    if not isinstance(excluded, list) or not isinstance(includes, list):
        message = "strategy.matrix"
        raise _issue(message, "Include and exclude must be sequences of mappings.")
    for item in [*excluded, *includes]:
        if not isinstance(item, Mapping):
            message = "strategy.matrix"
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
        message = "strategy.matrix"
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
    except WorkflowValidationError:
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


def _locate(error: WorkflowValidationError, locations: Mapping[str, tuple[int, int]]) -> None:
    field = str(error.context.get("field", "workflow"))
    location = locations.get(field) or locations.get("workflow." + field)
    while location is None and "." in field:
        field = field.rsplit(".", 1)[0]
        location = locations.get(field) or locations.get("workflow." + field)
    location = location or locations.get("workflow")
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
            if "one-of" in base:
                variant = (
                    "workflow-job"
                    if name == "job" and isinstance(value, Mapping) and "uses" in value
                    else "job-factory"
                    if name == "job" and isinstance(value, Mapping)
                    else "regular-step"
                    if name == "steps-item" and isinstance(value, Mapping) and "uses" in value
                    else "run-step"
                    if name == "steps-item" and isinstance(value, Mapping) and "run" in value
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
                for key, descriptor in properties.items():
                    if (
                        isinstance(descriptor, Mapping)
                        and descriptor.get("required")
                        and key not in value
                    ):
                        issues.append(_issue(f"{path}.{key}", "Required field is missing."))
                for key, item in value.items():
                    descriptor = properties.get(key)
                    if descriptor is None and "loose-key-type" not in mapping:
                        issues.append(_unknown_field(f"{path}.{key}"))
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
                    validate_steps([step], f"jobs.{job_id}.steps")
                except (WorkflowValidationError, TypeError, ValueError) as error:
                    if isinstance(error, WorkflowValidationError):
                        path = f"workflow.jobs.{job_id}.steps[{index}]"
                        error.context["field"] = str(error.context.get("field", path)).replace(
                            "steps[0]", f"steps[{index}]"
                        )
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
        for job in value.get("jobs", {}).values():
            if "uses" in job:
                capture(job["uses"], workflow=True, depth=depth)
            for step in job.get("steps", []):
                reference = step.get("uses", "")
                if reference.startswith("./"):
                    capture(reference, workflow=False, depth=depth)
                    from .metadata import load_action, validate_action_inputs

                    prefix = reference.removeprefix("./").rstrip("/")
                    metadata = result.get(
                        prefix + "/action.yml", result.get(prefix + "/action.yaml")
                    )
                    if metadata is not None:
                        validate_action_inputs(load_action(metadata), step.get("with", {}))
                if reference == "relay/loop@v1":
                    target = step.get("with", {}).get("workflow")
                    if not isinstance(target, str) or not target.startswith("./.relay/workflows/"):
                        message = "with.workflow"
                        raise _issue(message, "Loop requires a static reusable workflow.")
                    capture(target, workflow=True, depth=depth)

    visit(document.value, 1)
    return result


def capture_script(path: Path, project_root: Path, result: dict[str, str]) -> None:
    if not path.is_file() or path.stat().st_size > 10 * MAX_YAML_BYTES:
        message = "runs"
        raise _issue(message, "Action script is missing or too large.")
    try:
        raw = path.read_bytes()
        try:
            content = raw.decode("utf-8")
        except UnicodeError:
            content = "\x00binary:" + base64.b64encode(raw).decode("ascii")
        key = path.relative_to(project_root.resolve()).as_posix()
        if key not in result and (content.startswith("\x00") or path.stat().st_mode & 0o111):
            content = f"\x00asset:{path.stat().st_mode & 0o777:03o}:" + base64.b64encode(
                raw
            ).decode("ascii")
        if key not in result:
            result[key] = content
    except OSError:
        message = "runs"
        raise _issue(message, "Action sources could not be read.") from None


def source_bytes(content: str) -> tuple[bytes, int]:
    """Decode a frozen asset without confusing UTF-8 bytes with an encoding tag."""
    if content.startswith("\x00asset:"):
        _, mode, value = content.split(":", 2)
        return base64.b64decode(value, validate=True), int(mode, 8) & 0o777
    if content.startswith("\x00binary:"):
        return base64.b64decode(content[8:], validate=True), 0o600
    return content.encode("utf-8"), 0o600


def support_manifest() -> dict[str, Any]:
    from .builtins import CONTRACTS

    return {
        "dialect": DIALECT,
        "upstream_commit": UPSTREAM,
        "workflow_directory": ".relay/workflows",
        "job_execution": "serial",
        "definitions": language_definitions(),
        "builtins": sorted(BUILTINS),
        "builtin_inputs": {
            name: {"allowed": sorted(allowed), "required": sorted(required)}
            for name, (allowed, required) in CONTRACTS.items()
        },
        "events": sorted(EVENTS),
        "cache_modes": sorted(CACHE_MODES),
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
