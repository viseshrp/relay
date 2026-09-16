"""Cross-field workflow validation and typed launch-input resolution."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from pydantic import Field, TypeAdapter, ValidationError

from relay.constants import MAX_EXPANDED_NODES
from relay.errors import PromptResolutionError, WorkflowValidationError

from .graph import CompiledGraph, compile_graph
from .loader import LoadedWorkflow, load_workflow_tree, resolve_workflow_path
from .prompts import ResolvedPrompt, iter_agent_nodes, resolve_prompt
from .schema import (
    NODE_ID_PATTERN,
    AgentNode,
    BooleanInput,
    CommandNode,
    EnumInput,
    InputDefinition,
    IntegerInput,
    LoopNode,
    NodeDefinition,
    NumberInput,
    StringInput,
    SubworkflowNode,
    WorkflowDefinition,
)
from .scope import parse_scope_path


@dataclass(frozen=True, slots=True)
class ValidatedWorkflow:
    """Validated root, dependency indexes, children, and resolved prompts."""

    root: LoadedWorkflow
    graph: CompiledGraph
    subworkflows: Mapping[str, LoadedWorkflow]
    subworkflow_graphs: Mapping[str, CompiledGraph]
    prompts: tuple[ResolvedPrompt, ...]


def _issue_text(issues: Iterable[str]) -> str:
    return "Workflow validation failed:\n- " + "\n- ".join(issues)


def _pattern_adapter(pattern: str) -> TypeAdapter[str]:
    """Compile through Pydantic's linear-time Rust regex engine."""
    try:
        return TypeAdapter(Annotated[str, Field(pattern=pattern)])
    except Exception:
        message = f"Input pattern {pattern!r} is not in Pydantic's RE2-compatible subset."
        raise WorkflowValidationError(message) from None


def _definition_issues(definition: WorkflowDefinition, *, label: str) -> list[str]:
    issues: list[str] = []
    for input_id, item in definition.inputs.items():
        if isinstance(item, StringInput) and item.constraints.pattern is not None:
            try:
                _pattern_adapter(item.constraints.pattern)
            except WorkflowValidationError as error:
                issues.append(f"{label}.inputs.{input_id}: {error.message}")
    for entry in definition.entrypoints:
        scope = entry.scope_path
        if NODE_ID_PATTERN.fullmatch(scope) is not None:
            top_id = scope
        else:
            try:
                top_id = parse_scope_path(scope)[0].node_id
            except WorkflowValidationError as error:
                issues.append(f"{label}.entrypoints: {error.message}")
                continue
        if top_id not in definition.nodes:
            issues.append(f"{label}.entrypoints references unknown node {scope!r}")
        for input_id in entry.inputs:
            if input_id not in definition.inputs:
                issues.append(f"{label}.entrypoints references unknown input {input_id!r}")
    return issues


def _walk_nodes(nodes: Mapping[str, NodeDefinition]) -> Iterable[SubworkflowNode]:
    for node in nodes.values():
        if isinstance(node, SubworkflowNode):
            yield node
        elif isinstance(node, LoopNode):
            yield from _walk_nodes(node.body)


def _declared_outputs(definition: WorkflowDefinition) -> set[str]:
    outputs: set[str] = set()
    for node_id, node in definition.nodes.items():
        if isinstance(node, (AgentNode, CommandNode, SubworkflowNode)):
            outputs.update(f"{node_id}.{name}" for name in node.outputs)
    return outputs


def _subworkflow_io_issues(
    definition: WorkflowDefinition,
    workflows_root: Path,
    subworkflows: Mapping[str, LoadedWorkflow],
    *,
    label: str,
) -> list[str]:
    issues: list[str] = []
    for node in _walk_nodes(definition.nodes):
        path = resolve_workflow_path(workflows_root, node.workflow)
        key = path.relative_to(workflows_root.resolve()).as_posix()
        child = subworkflows.get(key)
        if child is None:
            continue
        unknown_inputs = node.inputs.keys() - child.definition.inputs.keys()
        for input_id in sorted(unknown_inputs):
            issues.append(f"{label} subworkflow {node.workflow!r} has unknown input {input_id!r}")
        for input_id, item in child.definition.inputs.items():
            if item.required and item.default is None and input_id not in node.inputs:
                issues.append(f"{label} subworkflow {node.workflow!r} requires input {input_id!r}")
        child_outputs = _declared_outputs(child.definition)
        for output_name, child_selector in node.outputs.items():
            if child_selector not in child_outputs:
                issues.append(
                    f"{label} output {output_name!r} references unknown child output "
                    f"{child_selector!r}"
                )
    return issues


def _expanded_node_count(
    nodes: Mapping[str, NodeDefinition],
    workflows_root: Path,
    subworkflows: Mapping[str, LoadedWorkflow],
) -> int:
    """Count the largest materialized graph, stopping above the fixed ceiling."""
    total = 0
    for node in nodes.values():
        total += 1
        if isinstance(node, LoopNode):
            nested = _expanded_node_count(node.body, workflows_root, subworkflows)
            total += node.max_iterations * nested
        elif isinstance(node, SubworkflowNode):
            path = resolve_workflow_path(workflows_root, node.workflow)
            key = path.relative_to(workflows_root.resolve()).as_posix()
            child = subworkflows.get(key)
            if child is not None:
                total += _expanded_node_count(child.definition.nodes, workflows_root, subworkflows)
        if total > MAX_EXPANDED_NODES:
            return total
    return total


def _resolved_prompts(
    workflows: Iterable[LoadedWorkflow], relay_root: Path, issues: list[str]
) -> list[ResolvedPrompt]:
    prompts: list[ResolvedPrompt] = []
    for workflow in workflows:
        for node in iter_agent_nodes(workflow.definition.nodes):
            for reference in node.prompts:
                try:
                    prompts.append(resolve_prompt(reference, relay_root))
                except PromptResolutionError as error:
                    issues.append(f"{workflow.path.name}: {error.message}")
    return prompts


def validate_loaded_workflow(root: LoadedWorkflow, relay_root: Path) -> ValidatedWorkflow:
    """Validate root and transitive workflows, aggregating independent issues."""
    workflows_root = (relay_root / "workflows").resolve()
    subworkflows = load_workflow_tree(root, workflows_root)
    issues = _definition_issues(root.definition, label=root.path.name)
    try:
        graph = compile_graph(root.definition.nodes)
    except WorkflowValidationError as error:
        issues.append(error.message)
        graph = CompiledGraph({}, (), {}, {}, {})

    subworkflow_graphs: dict[str, CompiledGraph] = {}
    for key, workflow in subworkflows.items():
        issues.extend(_definition_issues(workflow.definition, label=key))
        try:
            subworkflow_graphs[key] = compile_graph(workflow.definition.nodes, location=key)
        except WorkflowValidationError as error:
            issues.append(error.message)
    issues.extend(
        _subworkflow_io_issues(root.definition, workflows_root, subworkflows, label=root.path.name)
    )
    for key, workflow in subworkflows.items():
        issues.extend(
            _subworkflow_io_issues(workflow.definition, workflows_root, subworkflows, label=key)
        )
    expanded = _expanded_node_count(root.definition.nodes, workflows_root, subworkflows)
    if expanded > MAX_EXPANDED_NODES:
        issues.append(f"expanded workflow has {expanded} nodes; limit is {MAX_EXPANDED_NODES}")
    prompts = _resolved_prompts((root, *subworkflows.values()), relay_root, issues)
    if issues:
        raise WorkflowValidationError(_issue_text(issues), context={"workflow": str(root.path)})
    return ValidatedWorkflow(
        root=root,
        graph=graph,
        subworkflows=subworkflows,
        subworkflow_graphs=subworkflow_graphs,
        prompts=tuple(prompts),
    )


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
    definition: WorkflowDefinition, supplied: Mapping[str, object]
) -> dict[str, object]:
    """Apply defaults and validate every launch input without coercion."""
    issues: list[str] = []
    unknown = supplied.keys() - definition.inputs.keys()
    issues.extend(f"unknown launch input {name!r}" for name in sorted(unknown))
    resolved: dict[str, object] = {}
    for input_id, item in definition.inputs.items():
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
