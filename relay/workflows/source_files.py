"""Portable source-file operations shared by editor and bundled publication."""

from __future__ import annotations

from contextlib import suppress
import os
from pathlib import Path
import re
import tempfile
from typing import Protocol

from relay.errors import PermissionFlowError, ProjectDiscoveryError, WorkflowValidationError
from relay.execution.state import DraftValidationState

from .loader import workflow_key_parts

_WINDOWS_DEVICE = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)", re.IGNORECASE)


def _require_portable_names(parts: tuple[str, ...]) -> None:
    """Accept `nested/review.yaml`; reject `NUL.yaml` or `draft:notes.md` on every OS."""
    if any(
        part.endswith((" ", "."))
        or _WINDOWS_DEVICE.match(part)
        or any(character in '<>:"|?*\\' or ord(character) < 32 for character in part)
        for part in parts
    ):
        message = "Choose a file name supported on both Linux and Windows."
        raise WorkflowValidationError(message)


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
        *,
        prompts: dict[str, object] | None = None,
    ) -> dict[str, object]: ...

    def discard_draft(self, project_id: str, workflow_key: str) -> None: ...


def _path(relay_root: Path, workflow_key: str) -> Path:
    root = (relay_root / "workflows").resolve()
    current = root
    parts = workflow_key_parts(workflow_key)
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


def _atomic_create(path: Path, text: str | bytes) -> None:
    """Publish complete UTF-8 bytes without overwriting an owner file."""
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(text.encode("utf-8") if isinstance(text, str) else text)
            stream.flush()
            os.fsync(stream.fileno())
        # A hard link publishes complete bytes atomically and fails if the owner already has a file.
        os.link(temporary, path)
    except FileExistsError:
        message = f"File {path.name!r} already exists."
        raise PermissionFlowError(
            message, next_action="Choose another name or reload that file."
        ) from None
    except OSError:
        message = "Relay could not create the selected file."
        raise WorkflowValidationError(message) from None
    finally:
        if temporary is not None:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)


def _atomic_replace(path: Path, text: str, *, resource: str = "workflow") -> None:
    temporary = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(temporary_name)
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
        if temporary is not None:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)
        message = f"Relay could not atomically save {resource} {path.name!r}."
        raise WorkflowValidationError(message, context={resource: path.name}) from None
