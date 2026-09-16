"""Application service for validated, compensated workflow launch."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Protocol

from relay.agents.driver import AgentObservationStore, preflight_routes
from relay.agents.models import ModelObservation
from relay.agents.registry import load_registry
from relay.errors import ArtifactPreservationError, RelayError, WorkflowValidationError
from relay.paths import safe_resolve
from relay.vcs.cleanliness import require_clean
from relay.vcs.commits import current_head
from relay.vcs.worktree import create_primary_worktree
from relay.workflows.loader import LoadedWorkflow, load_workflow, resolve_workflow_path
from relay.workflows.routing import compile_route_requirements
from relay.workflows.schema import LoopNode, NodeDefinition, SubworkflowNode, WorkflowDefinition
from relay.workflows.scope import parse_scope_path
from relay.workflows.snapshot import SnapshotBundle, build_snapshot
from relay.workflows.validation import ValidatedWorkflow, resolve_inputs, validate_loaded_workflow

from .scheduler import SchedulingStore, dispatch_ready_nodes

_HASH_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class LaunchRequest:
    """Owner-selected values accepted by the browser launch surface."""

    workflow_key: str
    inputs: Mapping[str, object]
    model: str | None
    cleanup_policy: str
    entry_point: str | None
    owner_agents: Sequence[str]
    launcher: str


@dataclass(frozen=True, slots=True)
class LaunchResult:
    """Identity of a run whose worktree and initial dispatch are durable."""

    run_id: str


class LaunchStore(SchedulingStore, AgentObservationStore, Protocol):
    """Persistence boundary needed by the launch transaction sequence."""

    def replace_model_observations(
        self,
        agent_id: str,
        observations: tuple[ModelObservation, ...],
    ) -> None: ...

    def create_pending_run(
        self,
        project_id: str,
        request: LaunchRequest,
        source_commit: str,
        snapshot: SnapshotBundle,
        nodes: Mapping[str, NodeDefinition],
    ) -> str: ...

    def mark_run_started(
        self,
        run_id: str,
        branch: str,
        worktree: Path,
        source_commit: str,
    ) -> None: ...

    def mark_run_launch_failed(self, run_id: str, error: RelayError) -> None: ...


def _normalize_entry_point(value: str) -> str:
    normalized = value if value.startswith("root.") else f"root.{value}"
    parse_scope_path(normalized)
    return normalized


def _subworkflow_definition(
    workflow: ValidatedWorkflow,
    reference: str,
) -> WorkflowDefinition:
    workflows_root = workflow.root.path.parent.resolve()
    path = resolve_workflow_path(workflows_root, reference)
    key = path.relative_to(workflows_root).as_posix()
    child = workflow.subworkflows.get(key)
    if child is None:
        message = f"Entrypoint subworkflow {reference!r} is missing from validation."
        raise WorkflowValidationError(message)
    return child.definition


def _validate_entry_scope(workflow: ValidatedWorkflow, scope_path: str) -> None:
    nodes: Mapping[str, NodeDefinition] = workflow.root.definition.nodes
    segments = parse_scope_path(scope_path)
    for index, segment in enumerate(segments):
        node = nodes.get(segment.node_id)
        if node is None:
            message = f"Entrypoint scope {scope_path!r} names an unknown node."
            raise WorkflowValidationError(message)
        final = index == len(segments) - 1
        if final:
            if segment.iteration is not None and not isinstance(node, LoopNode):
                message = f"Entrypoint scope {scope_path!r} uses # on a non-loop node."
                raise WorkflowValidationError(message)
            if (
                isinstance(node, LoopNode)
                and segment.iteration is not None
                and segment.iteration > node.max_iterations
            ):
                message = f"Entrypoint scope {scope_path!r} exceeds the loop bound."
                raise WorkflowValidationError(message)
            return
        if isinstance(node, LoopNode):
            if segment.iteration is None or segment.iteration > node.max_iterations:
                message = f"Entrypoint scope {scope_path!r} has an invalid loop iteration."
                raise WorkflowValidationError(message)
            nodes = node.body
        elif isinstance(node, SubworkflowNode) and segment.iteration is None:
            nodes = _subworkflow_definition(workflow, node.workflow).nodes
        else:
            message = f"Entrypoint scope {scope_path!r} descends through a leaf node."
            raise WorkflowValidationError(message)


def _file_sha256(path: Path) -> str:
    digest = sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(_HASH_CHUNK_BYTES):
                digest.update(chunk)
    except OSError:
        message = f"Entrypoint artifact {path} could not be read."
        raise ArtifactPreservationError(message) from None
    return digest.hexdigest()


def _validate_entry_point(
    workflow: ValidatedWorkflow,
    requested: str | None,
    resolved_inputs: Mapping[str, object],
    repository: Path,
) -> str | None:
    if requested is None:
        return None
    normalized = _normalize_entry_point(requested)
    entries = {
        _normalize_entry_point(item.scope_path): item
        for item in workflow.root.definition.entrypoints
    }
    entry = entries.get(normalized)
    if entry is None:
        message = f"Entrypoint {requested!r} is not declared by this workflow."
        raise WorkflowValidationError(message)
    _validate_entry_scope(workflow, normalized)
    missing_inputs = [
        name
        for name in entry.inputs
        if name not in resolved_inputs or resolved_inputs[name] is None
    ]
    if missing_inputs:
        message = "Entrypoint inputs are missing: " + ", ".join(sorted(missing_inputs)) + "."
        raise WorkflowValidationError(message)
    for name, artifact in entry.artifacts.items():
        path = safe_resolve(repository, artifact.path)
        if not path.is_file():
            message = f"Entrypoint artifact {name!r} does not exist."
            raise ArtifactPreservationError(message, context={"project": str(repository)})
        actual = _file_sha256(path)
        if actual != artifact.sha256:
            message = f"Entrypoint artifact {name!r} does not match its declared SHA-256."
            raise ArtifactPreservationError(message, context={"project": str(repository)})
    return normalized


def launch_workflow(
    store: LaunchStore,
    relay_root: Path,
    project_id: str,
    request: LaunchRequest,
    enqueue: Callable[[str], object],
) -> LaunchResult:
    """Run preflight, persist the snapshot, create isolation, and dispatch roots."""
    workflows_root = relay_root / "workflows"
    workflow_path = resolve_workflow_path(workflows_root, request.workflow_key)
    root: LoadedWorkflow = load_workflow(workflow_path)
    workflow = validate_loaded_workflow(root, relay_root)
    typed_inputs = resolve_inputs(workflow.root.definition, request.inputs)
    repository = relay_root.parent.resolve()
    require_clean(repository, stage="run launch")
    entry_point = _validate_entry_point(
        workflow,
        request.entry_point,
        typed_inputs,
        repository,
    )
    normalized_request = LaunchRequest(
        request.workflow_key,
        typed_inputs,
        request.model,
        request.cleanup_policy,
        entry_point,
        tuple(request.owner_agents),
        request.launcher,
    )
    requirements = compile_route_requirements(
        workflow,
        launch_model=request.model,
        owner_agents=request.owner_agents,
    )
    routes = requirements
    if requirements:
        registry = load_registry()
        routes, _probes = preflight_routes(
            requirements,
            repository,
            registry=registry,
            observation_store=store,
        )
    snapshot = build_snapshot(workflow, typed_inputs=typed_inputs, routes=routes)
    source_commit = current_head(repository)
    run_id = store.create_pending_run(
        project_id,
        normalized_request,
        source_commit,
        snapshot,
        workflow.root.definition.nodes,
    )
    try:
        branch, worktree, resolved_commit = create_primary_worktree(
            repository,
            run_id,
            source_commit,
        )
        store.mark_run_started(run_id, branch, worktree, resolved_commit)
    except RelayError as error:
        store.mark_run_launch_failed(run_id, error)
        raise
    dispatch_ready_nodes(store, run_id, enqueue)
    return LaunchResult(run_id)


__all__ = [
    "LaunchRequest",
    "LaunchResult",
    "LaunchStore",
    "launch_workflow",
]
