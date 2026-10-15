"""Load current jobs/steps workflows and resolve their project-owned paths."""

from __future__ import annotations

from pathlib import Path

from relay.errors import PathSafetyError, WorkflowValidationError
from relay.paths import safe_resolve

from .records import LoadedWorkflow
from .source_text import read_source


def load_workflow(path: Path) -> LoadedWorkflow:
    """Load one UTF-8 workflow without changing its round-trip YAML shape."""
    resolved = path.resolve()
    try:
        text = read_source(resolved).raw_text
    except (OSError, UnicodeError):
        message = f"Workflow {resolved} could not be read as UTF-8."
        raise WorkflowValidationError(message, context={"workflow": str(resolved)}) from None
    return load_workflow_text(text, source=resolved)


def load_workflow_text(text: str, *, source: Path | None = None) -> LoadedWorkflow:
    """Compile the single supported workflow language without format fallbacks."""
    from .actions.compiler import definition
    from .actions.language import load

    display = source or Path("<memory>")
    document = load(text, source=display)
    return LoadedWorkflow(display, text, document.document, definition(document))


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
        message = f"Workflow reference {reference!r} escapes .relay/workflows."
        raise WorkflowValidationError(message, context={"workflow": reference}) from None
    if resolved.suffix not in {".yaml", ".yml"}:
        message = f"Workflow reference {reference!r} must name a YAML file."
        raise WorkflowValidationError(message, context={"workflow": reference})
    return resolved


__all__ = [
    "LoadedWorkflow",
    "load_workflow",
    "load_workflow_text",
    "resolve_workflow_path",
]
