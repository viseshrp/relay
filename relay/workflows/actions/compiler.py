"""Translate validated Actions sources to Relay's internal execution records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from hashlib import sha256
import json
from typing import TYPE_CHECKING, Any, cast

from relay.errors import WorkflowValidationError
from relay.workflows.schema import (
    ActionsJobNode,
    AgentNode,
    AgentOptions,
    BooleanInput,
    EnumConstraints,
    EnumInput,
    GlobalPrompt,
    LocalPrompt,
    NumberInput,
    StringInput,
    WorkflowDefinition,
)

from . import expressions
from .language import (
    ActionsDocument,
    expand_matrix,
    input_definitions,
    load,
    source_bytes,
    topological_jobs,
)

if TYPE_CHECKING:
    from relay.workflows.validation import ValidatedWorkflow


def definition(
    document: ActionsDocument, sources: Mapping[str, str] | None = None
) -> WorkflowDefinition:
    value = document.value
    inputs = {}
    for name, raw in input_definitions(value).items():
        kind = raw.get("type", "string")
        common = {"description": raw.get("description", ""), "required": raw.get("required", False)}
        if "default" in raw:
            common["default"] = raw["default"]
        if kind == "boolean":
            inputs[name] = BooleanInput(type="boolean", **common)
        elif kind == "number":
            inputs[name] = NumberInput(type="number", **common)
        elif kind == "choice":
            inputs[name] = EnumInput(
                type="enum", constraints=EnumConstraints(values=raw["options"]), **common
            )
        else:
            inputs[name] = StringInput(type="string", **common)
    jobs = value["jobs"]
    nodes = {}
    for job_id in topological_jobs(jobs):
        job = jobs[job_id]
        needs = job.get("needs", [])
        needs = [needs] if isinstance(needs, str) else needs
        nodes[job_id] = ActionsJobNode(
            job_id=job_id,
            job=job,
            workflow=value,
            needs=needs,
            sources=dict(sources or {}),
            coordinator="matrix" in job.get("strategy", {}) or "uses" in job,
            timeout=_timeout(job.get("timeout-minutes"), default=360),
        )
    return WorkflowDefinition(
        version=1,
        name=str(value.get("name") or document.source.as_posix()),
        inputs=inputs,
        nodes=nodes,
        actions=value,
    )


def _timeout(value: object, *, default: int | None = None) -> str | None:
    if value is None:
        return f"{default * 60}s" if default is not None else None
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 < value <= 360:
        return f"{int(float(value) * 60_000)}ms"
    if isinstance(value, str) and "${{" in value:
        return None
    message = "timeout-minutes must be greater than zero and at most 360."
    raise WorkflowValidationError(message)


def bind_agent(step: Mapping[str, Any], values: Mapping[str, Any]) -> AgentNode:
    raw = step.get("with", {})
    route_values = {name: values.get(name, {}) for name in ("inputs", "vars", "matrix", "github")}
    route = {}
    for field in ("agent", "agents", "model", "effort", "prompt-files"):
        if field in raw:
            if isinstance(raw[field], str):
                for segment in expressions.segments(raw[field]):
                    if segment[0]:
                        tree = expressions.parse(segment[1])

                        def check(item: object) -> None:
                            if not isinstance(item, tuple) or not item:
                                return
                            if (
                                item[0] == "index"
                                and item[1] == ("context", "inputs")
                                and item[2][0] == "literal"
                                and isinstance(item[2][1], str)
                                and item[2][1] not in values.get("_dynamic_inputs", set())
                            ):
                                return
                            if item[0] == "context" and str(item[1]).lower() not in route_values:
                                message = (
                                    "Agent routing must use launch-static inputs, vars, github, "
                                    "or a static matrix."
                                )
                                raise WorkflowValidationError(message)
                            if (
                                item[0] == "context"
                                and str(item[1]).lower() == "inputs"
                                and values.get("_dynamic_inputs")
                            ):
                                message = (
                                    "Runtime-derived reusable/action inputs "
                                    "cannot choose an agent route."
                                )
                                raise WorkflowValidationError(message)
                            if (
                                item[0] == "context"
                                and str(item[1]).lower() == "matrix"
                                and values.get("_dynamic_matrix")
                            ):
                                message = "A dynamic matrix cannot choose an agent route."
                                raise WorkflowValidationError(message)
                            for child in item[1:]:
                                check(child)

                        check(tree)
            route[field] = expressions.interpolate(raw[field], route_values)
    agents = route.get("agents", route.get("agent", []))
    if isinstance(agents, str):
        agents = json.loads(agents) if agents.startswith("[") else [agents] if agents else []
    if not isinstance(agents, list) or any(not isinstance(item, str) for item in agents):
        message = "relay/agent agents must be a JSON list of exact provider ids."
        raise WorkflowValidationError(message)
    model = route.get("model")
    if model is not None and (not isinstance(model, str) or not model):
        message = "relay/agent model must be an exact, nonempty model value."
        raise WorkflowValidationError(message)
    prompts = []
    for reference in str(route.get("prompt-files", "")).splitlines():
        if reference.strip():
            prompts.append(
                GlobalPrompt(global_=reference[7:])
                if reference.startswith("global:")
                else LocalPrompt(local=reference.strip().removeprefix(".relay/"))
            )
    effort = route.get("effort")
    if effort is not None and not isinstance(effort, str):
        message = "relay/agent effort must be an exact provider value or null."
        raise WorkflowValidationError(message)
    options = (
        {agent: AgentOptions(effort=effort or None) for agent in agents}
        if "effort" in route
        else {}
    )
    return AgentNode(
        type="agent",
        writes=False,
        allow_no_commit=True,
        agents=agents,
        model=model,
        prompts=prompts,
        agent_options=options,
        auto_retry=raw.get("auto-retry", True) not in (False, "false"),
    )


def bind_routes(workflow: ValidatedWorkflow, values: Mapping[str, Any]) -> ValidatedWorkflow:
    """Resolve routes only from launch-static data; dynamic matrices cannot invent them."""
    if not workflow.root.definition.actions:
        return workflow
    sources = cast(ActionsJobNode, next(iter(workflow.root.definition.nodes.values()))).sources
    nodes = {}

    def dynamic(raw: object, context: Mapping[str, Any]) -> bool:
        if isinstance(raw, Mapping):
            return any(dynamic(item, context) for item in raw.values())
        if not isinstance(raw, str):
            return False
        for enabled, text in expressions.segments(raw):
            if not enabled:
                continue
            tree = expressions.parse(text)

            def depends(item: object) -> bool:
                if not isinstance(item, tuple) or not item:
                    return False
                if (
                    item[0] == "index"
                    and item[1] == ("context", "inputs")
                    and item[2][0] == "literal"
                    and isinstance(item[2][1], str)
                ):
                    return item[2][1] in context.get("_dynamic_inputs", set())
                if item[0] == "context":
                    name = str(item[1]).lower()
                    return (
                        name not in {"inputs", "vars", "matrix", "github"}
                        or (name == "matrix" and bool(context.get("_dynamic_matrix")))
                        or (name == "inputs" and bool(context.get("_dynamic_inputs")))
                    )
                return any(depends(child) for child in item[1:])

            if depends(tree):
                return True
        return False

    def call_inputs(
        value: Mapping[str, Any], supplied: Mapping[str, Any], context: Mapping[str, Any]
    ) -> tuple[dict[str, Any], set[str]]:
        from .language import resolve_inputs

        declarations = input_definitions(value, "workflow_call")
        resolved = {}
        deferred: set[str] = set()
        for key, raw in supplied.items():
            if dynamic(raw, context):
                deferred.add(key)
                declaration = declarations.get(key, {})
                resolved[key] = declaration.get(
                    "default", {"boolean": False, "number": 0}.get(declaration.get("type"), "")
                )
            else:
                resolved[key] = expressions.interpolate(raw, context)
        return resolve_inputs(value, resolved, event="workflow_call"), deferred

    def visit_steps(
        steps: Sequence[Mapping[str, Any]],
        context: Mapping[str, Any],
        prefix: str,
        bindings: dict[str, AgentNode],
    ) -> None:
        for index, step in enumerate(steps):
            step_id = str(step.get("id") or f"step_{index + 1}")
            scope = f"{prefix}.{step_id}" if prefix else step_id
            reference = step.get("uses", "")
            if reference == "relay/agent@v1":
                bindings[scope] = bind_agent(step, context)
            elif reference == "relay/loop@v1":
                raw = step.get("with", {})
                child = load(sources[str(raw["workflow"]).removeprefix("./")])
                deferred = dynamic(raw.get("inputs", "{}"), context)
                supplied = (
                    dict.fromkeys(
                        input_definitions(child.value, "workflow_call"), "${{ needs.deferred }}"
                    )
                    if deferred
                    else json.loads(str(expressions.interpolate(raw.get("inputs", "{}"), context)))
                )
                child_inputs, deferred = call_inputs(child.value, supplied, context)
                for iteration in range(int(str(raw.get("max-iterations", 1)))):
                    visit_workflow(
                        child.value,
                        {**context, "inputs": child_inputs, "_dynamic_inputs": deferred},
                        f"{scope}.iteration_{iteration + 1}",
                        bindings,
                    )
            elif isinstance(reference, str) and reference.startswith("./"):
                from .metadata import load_action

                path = reference.removeprefix("./").rstrip("/")
                text = sources.get(f"{path}/action.yml", sources.get(f"{path}/action.yaml"))
                if text:
                    action = load_action(text)
                    if action["runs"]["using"] == "composite":
                        action_inputs = {
                            name: item.get("default", "")
                            for name, item in action.get("inputs", {}).items()
                        }
                        deferred = set()
                        for name, raw in step.get("with", {}).items():
                            if dynamic(raw, context):
                                deferred.add(name)
                                action_inputs[name] = ""
                            else:
                                action_inputs[name] = expressions.interpolate(raw, context)
                        visit_steps(
                            action["runs"]["steps"],
                            {**context, "inputs": action_inputs, "_dynamic_inputs": deferred},
                            scope,
                            bindings,
                        )

    def visit_workflow(
        value: Mapping[str, Any],
        context: Mapping[str, Any],
        prefix: str,
        bindings: dict[str, AgentNode],
    ) -> None:

        for job_id, job in value["jobs"].items():
            scope = f"{prefix}.{job_id}" if prefix else job_id
            matrix = job.get("strategy", {}).get("matrix")
            try:
                resolved = expressions.interpolate(matrix, context) if matrix is not None else None
            except WorkflowValidationError:
                resolved = None
            dynamic = matrix is not None and not isinstance(resolved, Mapping)
            variants = expand_matrix(resolved) if isinstance(resolved, Mapping) else [{}]
            for index, variant in enumerate(variants):
                branch = (
                    f"{scope}.dynamic"
                    if dynamic
                    else f"{scope}.variant_{index + 1}"
                    if matrix is not None
                    else scope
                )
                child_context = {**context, "matrix": variant, "_dynamic_matrix": dynamic}
                if "uses" in job:
                    child = load(sources[job["uses"].removeprefix("./")])
                    child_inputs, deferred = call_inputs(
                        child.value, job.get("with", {}), child_context
                    )
                    visit_workflow(
                        child.value,
                        {**child_context, "inputs": child_inputs, "_dynamic_inputs": deferred},
                        branch,
                        bindings,
                    )
                else:
                    visit_steps(job.get("steps", []), child_context, branch, bindings)

    all_bindings: dict[str, AgentNode] = {}
    visit_workflow(workflow.root.definition.actions, values, "", all_bindings)
    for key, raw_node in workflow.root.definition.nodes.items():
        if not isinstance(raw_node, ActionsJobNode):
            continue
        bindings = {
            name.removeprefix(key + "."): agent
            for name, agent in all_bindings.items()
            if name.startswith(key + ".")
        }
        nodes[key] = raw_node.model_copy(update={"sources": sources, "bound_agents": bindings})
    root = replace(
        workflow.root, definition=workflow.root.definition.model_copy(update={"nodes": nodes})
    )
    return replace(workflow, root=root)


def sources_hashes(sources: Mapping[str, str]) -> dict[str, str]:
    result = {}
    for key, value in sources.items():
        content, mode = source_bytes(value)
        result[f"source:{key}"] = sha256(content).hexdigest()
        result[f"mode:{key}"] = sha256(str(mode).encode()).hexdigest()
    return result


def validate_commands(
    value: Mapping[str, Any], sources: Mapping[str, str], commands: Mapping[str, Sequence[str]]
) -> None:
    """Reject missing literal command names before creating a run."""
    documents = [value]
    for path, text in sources.items():
        if path.startswith(".relay/workflows/"):
            documents.append(load(text).value)
        elif path.endswith(("/action.yml", "/action.yaml")):
            from .metadata import load_action

            action = load_action(text)
            if action["runs"]["using"] == "composite":
                documents.append({"jobs": {"action": {"steps": action["runs"]["steps"]}}})
    for document in documents:
        for job in document.get("jobs", {}).values():
            for step in job.get("steps", []):
                name = step.get("with", {}).get("command")
                if (
                    step.get("uses") == "relay/command@v1"
                    and isinstance(name, str)
                    and "${{" not in name
                    and name not in commands
                ):
                    message = f"Shared command {name!r} is not configured for this project."
                    raise WorkflowValidationError(message)
