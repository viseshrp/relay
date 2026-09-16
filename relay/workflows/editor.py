"""Application services for recovery drafts, validation, and atomic YAML saves."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import tempfile
from typing import Protocol

from relay.errors import (
    PermissionFlowError,
    ProjectDiscoveryError,
    RelayError,
    WorkflowValidationError,
)
from relay.execution.state import DraftValidationState

from .loader import load_workflow_text
from .validation import validate_loaded_workflow


class WorkflowEditorStore(Protocol):
    """Mutable database state surrounding a Git-owned workflow file."""

    def get_draft(self, project_id: str, workflow_key: str) -> dict[str, object] | None: ...

    def save_draft(
        self,
        project_id: str,
        workflow_key: str,
        yaml_text: str,
        base_hash: str,
        validation_state: DraftValidationState,
    ) -> dict[str, object]: ...

    def discard_draft(self, project_id: str, workflow_key: str) -> None: ...


@dataclass(frozen=True, slots=True)
class WorkflowDocument:
    """Current Git-owned YAML plus its optional database recovery draft."""

    yaml: str
    draft: dict[str, object] | None
    base_hash: str


def _digest(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def _workflow_key_parts(workflow_key: str) -> tuple[str, ...]:
    """Normalize a POSIX workflow key without constructing a filesystem path.

    For example, ``review`` becomes ``("review.yaml",)`` and
    ``nested/review.yml`` remains ``("nested", "review.yml")``.
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


def _path(relay_root: Path, workflow_key: str) -> Path:
    root = (relay_root / "workflows").resolve()
    current = root
    parts = _workflow_key_parts(workflow_key)
    for index, part in enumerate(parts):
        try:
            child = next((item for item in current.iterdir() if item.name == part), None)
        except OSError:
            child = None
        if child is None:
            break
        try:
            resolved = child.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, RuntimeError, ValueError):
            break
        if index < len(parts) - 1 and not resolved.is_dir():
            break
        current = resolved
    else:
        if current.is_file():
            return current
    message = f"Workflow {workflow_key!r} does not exist."
    raise ProjectDiscoveryError(message, context={"workflow": workflow_key})


def read_workflow_document(
    store: WorkflowEditorStore,
    relay_root: Path,
    project_id: str,
    workflow_key: str,
) -> WorkflowDocument:
    """Read the saved file and latest recovery draft without merging either."""
    path = _path(relay_root, workflow_key)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        message = f"Workflow {workflow_key!r} could not be read as UTF-8."
        raise WorkflowValidationError(message, context={"workflow": workflow_key}) from None
    return WorkflowDocument(text, store.get_draft(project_id, workflow_key), _digest(text))


def autosave_workflow_draft(
    store: WorkflowEditorStore,
    relay_root: Path,
    project_id: str,
    workflow_key: str,
    yaml_text: str,
    base_hash: str,
) -> dict[str, object]:
    """Keep invalid editor text recoverable while recording its validation state."""
    path = _path(relay_root, workflow_key)
    state = DraftValidationState.VALID
    try:
        loaded = load_workflow_text(yaml_text, source=path)
        validate_loaded_workflow(loaded, relay_root)
    except RelayError:
        state = DraftValidationState.INVALID
    return store.save_draft(
        project_id,
        workflow_key,
        yaml_text,
        base_hash,
        state,
    )


def _atomic_replace(path: Path, text: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    except OSError:
        temporary.unlink(missing_ok=True)
        message = f"Relay could not atomically save workflow {path.name!r}."
        raise WorkflowValidationError(message, context={"workflow": path.name}) from None


def save_workflow_document(
    store: WorkflowEditorStore,
    relay_root: Path,
    project_id: str,
    workflow_key: str,
    yaml_text: str,
    base_hash: str,
) -> None:
    """Reject stale bases, validate the complete tree, then replace one YAML file."""
    path = _path(relay_root, workflow_key)
    try:
        saved = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        message = f"Workflow {workflow_key!r} could not be read as UTF-8."
        raise WorkflowValidationError(message, context={"workflow": workflow_key}) from None
    if _digest(saved) != base_hash:
        message = "The workflow changed after this editor loaded it."
        raise PermissionFlowError(
            message,
            context={"workflow": workflow_key},
            next_action="Reload the saved file and reconcile the recovery draft before saving.",
        )
    loaded = load_workflow_text(yaml_text, source=path)
    validate_loaded_workflow(loaded, relay_root)
    _atomic_replace(path, yaml_text)
    store.discard_draft(project_id, workflow_key)


__all__ = [
    "WorkflowDocument",
    "WorkflowEditorStore",
    "autosave_workflow_draft",
    "read_workflow_document",
    "save_workflow_document",
]
