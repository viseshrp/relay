"""Round-trip YAML loading with schema-version and recursion gates."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError
from ruamel.yaml import YAML

from relay.constants import SCHEMA_VERSION
from relay.errors import PathSafetyError, SchemaVersionError, WorkflowValidationError
from relay.paths import safe_resolve

from .repairs import compile_repairs
from .schema import LoopNode, NodeDefinition, SubworkflowNode, WorkflowDefinition


@dataclass(frozen=True, slots=True)
class LoadedWorkflow:
    """Validated workflow paired with its exact source bytes and parsed tree."""

    path: Path
    text: str
    document: Mapping[str, object]
    definition: WorkflowDefinition


def _yaml() -> YAML:
    parser = YAML(typ="rt")
    parser.allow_duplicate_keys = False
    return parser


def _validation_message(error: ValidationError) -> str:
    """A missing name -> ``Workflow validation failed:\n- name: Field required``."""
    issues = []
    for item in error.errors(include_url=False, include_context=False):
        location = ".".join(str(part) for part in item["loc"]) or "workflow"
        issues.append(f"{location}: {item['msg']}")
    return "Workflow validation failed:\n- " + "\n- ".join(issues)


def load_workflow(path: Path) -> LoadedWorkflow:
    """Load one UTF-8 workflow without changing its round-trip YAML shape."""
    resolved = path.resolve()
    try:
        text = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        message = f"Workflow {resolved} could not be read as UTF-8."
        raise WorkflowValidationError(message, context={"workflow": str(resolved)}) from None
    return load_workflow_text(text, source=resolved)


def load_workflow_text(text: str, *, source: Path | None = None) -> LoadedWorkflow:
    """Validate workflow YAML supplied by the editor or a stored snapshot."""
    display = source or Path("<memory>")
    try:
        document = _yaml().load(text)
    except Exception:
        message = f"Workflow {display} is not valid YAML."
        raise WorkflowValidationError(message, context={"workflow": str(display)}) from None
    if not isinstance(document, Mapping):
        message = f"Workflow {display} must contain a YAML mapping at the top level."
        raise WorkflowValidationError(message, context={"workflow": str(display)})

    if "jobs" in document and "nodes" not in document and "version" not in document:
        from .actions.compiler import definition as compile_actions
        from .actions.language import load as load_actions

        actions = load_actions(text, source=display)
        return LoadedWorkflow(display, text, actions.document, compile_actions(actions))

    version = document.get("version")
    if isinstance(version, int) and not isinstance(version, bool) and version != SCHEMA_VERSION:
        message = f"Workflow schema version {version} is not supported by this Relay build."
        raise SchemaVersionError(
            message,
            context={"workflow": str(display)},
            next_action=(
                f"Migrate the workflow to schema version {SCHEMA_VERSION} before loading it."
            ),
        )
    try:
        definition = WorkflowDefinition.model_validate(document)
    except ValidationError as error:
        raise WorkflowValidationError(
            _validation_message(error), context={"workflow": str(display)}
        ) from None
    return LoadedWorkflow(display, text, document, compile_repairs(definition))


def subworkflow_nodes(nodes: Mapping[str, NodeDefinition]) -> Iterable[SubworkflowNode]:
    """Yield child references in insertion order, including references in loops."""
    for node in nodes.values():
        if isinstance(node, SubworkflowNode):
            yield node
        elif isinstance(node, LoopNode):
            yield from subworkflow_nodes(node.body)


def workflow_key_parts(workflow_key: str) -> tuple[str, ...]:
    """Parse a relative POSIX key: `review` -> (`review.yaml`,),
    `nested/review.yml` -> (`nested`, `review.yml`); reject `nested\\review`.
    """
    parts = workflow_key.split("/")
    if not workflow_key or "\\" in workflow_key or any(part in {"", ".", ".."} for part in parts):
        message = f"Workflow key {workflow_key!r} is not a relative POSIX key."
        raise WorkflowValidationError(message, context={"workflow": workflow_key})
    suffix = Path(parts[-1]).suffix
    if suffix == "":
        parts[-1] = f"{parts[-1]}.yaml"
    elif suffix not in {".yaml", ".yml"}:
        message = f"Workflow key {workflow_key!r} must name a YAML file."
        raise WorkflowValidationError(message, context={"workflow": workflow_key})
    return tuple(parts)


def resolve_workflow_path(workflows_root: Path, reference: str) -> Path:
    """Resolve `review` to `review.yaml`, or preserve `nested/review.yml`."""
    relative = Path(*workflow_key_parts(reference))
    try:
        resolved = safe_resolve(workflows_root, relative)
    except PathSafetyError:
        message = f"Subworkflow reference {reference!r} escapes .relay/workflows."
        raise WorkflowValidationError(message, context={"workflow": reference}) from None
    if resolved.suffix not in {".yaml", ".yml"}:
        message = f"Subworkflow reference {reference!r} must name a YAML file."
        raise WorkflowValidationError(message, context={"workflow": reference})
    return resolved


def load_workflow_tree(root: LoadedWorkflow, workflows_root: Path) -> dict[str, LoadedWorkflow]:
    """Load each transitive child once and reject recursive references."""
    resolved_root = workflows_root.resolve()
    loaded = {}

    def visit(workflow: LoadedWorkflow, stack: tuple[Path, ...]) -> None:
        for reference in subworkflow_nodes(workflow.definition.nodes):
            child_path = resolve_workflow_path(resolved_root, reference.workflow)
            if child_path in stack:
                chain = " -> ".join(path.name for path in (*stack, child_path))
                message = f"Recursive subworkflow reference detected: {chain}."
                raise WorkflowValidationError(message, context={"workflow": reference.workflow})
            key = child_path.relative_to(resolved_root).as_posix()
            child = loaded.get(key)
            if child is None:
                if not child_path.is_file():
                    message = f"Subworkflow {reference.workflow!r} does not exist."
                    raise WorkflowValidationError(message, context={"workflow": reference.workflow})
                child = load_workflow(child_path)
                loaded[key] = child
                visit(child, (*stack, child_path))

    visit(root, (root.path.resolve(),))
    return loaded


__all__ = [
    "LoadedWorkflow",
    "load_workflow",
    "load_workflow_text",
    "load_workflow_tree",
    "resolve_workflow_path",
    "subworkflow_nodes",
]
