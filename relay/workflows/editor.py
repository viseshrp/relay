"""Application services for recovery drafts, validation, and atomic YAML saves."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Protocol

from relay.constants import API_MAX_PAGE, API_MAX_PAGE_BYTES
from relay.errors import (
    PermissionFlowError,
    ProjectDiscoveryError,
    RelayError,
    WorkflowValidationError,
)
from relay.execution.state import DraftValidationState
from relay.paths import safe_resolve

from .loader import load_workflow_text, resolve_workflow_path, workflow_key_parts
from .schema import AgentNode, CommandNode, ExistsSelector, LoopNode, NodeDefinition
from .validation import validate_loaded_workflow

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


@dataclass(frozen=True, slots=True)
class WorkflowDocument:
    """Current Git-owned YAML plus its optional database recovery draft."""

    yaml: str
    draft: dict[str, object] | None
    base_hash: str


def _digest(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


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


def read_workflow_document(
    store: WorkflowEditorStore,
    relay_root: Path,
    project_id: str,
    workflow_key: str,
) -> WorkflowDocument:
    from .source_bundle import source_lock

    with source_lock(relay_root):
        """Read the saved file and latest recovery draft without merging either."""
        path = _path(relay_root, workflow_key)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            message = f"Workflow {workflow_key!r} could not be read as UTF-8."
            raise WorkflowValidationError(message, context={"workflow": workflow_key}) from None
        return WorkflowDocument(text, store.get_draft(project_id, workflow_key), _digest(text))


def list_workflow_documents(relay_root: Path) -> list[dict[str, str]]:
    """List saved workflows without following directory links outside this project."""
    root = relay_root / "workflows"
    records = []
    for directory, children, files in os.walk(root, followlinks=False):
        children[:] = sorted(
            child for child in children if not (Path(directory) / child).is_symlink()
        )
        for name in sorted(files):
            path = Path(directory) / name
            if path.suffix not in {".yaml", ".yml"} or path.is_symlink():
                continue
            key = path.relative_to(root).as_posix()
            title = path.stem
            # Invalid files remain selectable so the owner can repair them in the editor.
            with suppress(RelayError, OSError, UnicodeError):
                title = load_workflow_text(
                    path.read_text(encoding="utf-8"), source=path
                ).definition.name
            records.append({"key": key, "name": title})
            if len(records) >= API_MAX_PAGE:
                return records
    return records


def create_workflow_document(
    store: WorkflowEditorStore,
    relay_root: Path,
    project_id: str,
    workflow_key: str,
    yaml_text: str | None = None,
    name: str = "New workflow",
) -> WorkflowDocument:
    from .source_bundle import source_lock

    with source_lock(relay_root):
        """Validate and publish a new file without replacing an existing workflow."""
        _require_portable_names(workflow_key_parts(workflow_key))
        path = resolve_workflow_path(relay_root / "workflows", workflow_key)
        text = (
            yaml_text
            if yaml_text is not None
            # JSON quotes preserve a name such as "Review: API" as one YAML scalar.
            else (
                f"name: {json.dumps(name)}\non: workflow_dispatch\njobs:\n"
                "  check:\n    steps:\n      - run: echo Ready\n"
            )
        )
        from .actions.language import load

        load(text, source=path)
        loaded = load_workflow_text(text, source=path)
        validate_loaded_workflow(loaded, relay_root)
        _atomic_create(path, text)
        return read_workflow_document(store, relay_root, project_id, workflow_key)


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


def read_prompt_document(relay_root: Path, reference: str) -> dict[str, str]:
    from .source_bundle import source_lock

    with source_lock(relay_root):
        """Read an editable local prompt within this project's prompts directory."""
        path = safe_resolve(relay_root, reference)
        path = safe_resolve(relay_root / "prompts", path)
        try:
            with path.open("rb") as stream:
                content = stream.read(API_MAX_PAGE_BYTES + 1)
            if len(content) > API_MAX_PAGE_BYTES:
                message = "These instructions exceed the editor's size limit."
                raise WorkflowValidationError(message)
            text = content.decode("utf-8")
        except (OSError, UnicodeError):
            message = "The selected instructions could not be read as UTF-8."
            raise WorkflowValidationError(message) from None
        return {"text": text, "base_hash": _digest(text), "reference": reference}


def save_prompt_document(
    relay_root: Path,
    reference: str,
    text: str,
    base_hash: str | None,
) -> dict[str, str]:
    from .source_bundle import source_lock

    with source_lock(relay_root):
        """Write local instructions only if the owner's loaded bytes still match."""
        path = safe_resolve(relay_root, reference)
        path = safe_resolve(relay_root / "prompts", path)
        if path.exists():
            saved = read_prompt_document(relay_root, reference)
            if base_hash != saved["base_hash"]:
                message = "These instructions changed after you loaded them."
                raise PermissionFlowError(
                    message, next_action="Reload the instructions before saving."
                )
            _atomic_replace(path, text, resource="instructions")
        else:
            if base_hash is not None:
                message = "The instructions file was removed after you loaded it."
                raise PermissionFlowError(message)
            _require_portable_names(path.relative_to(relay_root.resolve()).parts)
            _atomic_create(path, text)
        return read_prompt_document(relay_root, reference)


def workflow_handoff_warnings(nodes: dict[str, NodeDefinition]) -> list[dict[str, str]]:
    """Explain boolean-only outputs, including ones inside a loop body."""
    warnings = []

    def visit(items: dict[str, NodeDefinition], parent: str) -> None:
        for node_id, node in items.items():
            scope = f"{parent}.{node_id}"
            if isinstance(node, (AgentNode, CommandNode)):
                for output_name, selector in node.outputs.items():
                    if isinstance(selector, ExistsSelector):
                        warnings.append(
                            {
                                "scope_path": scope,
                                "output": output_name,
                                "artifact": selector.exists,
                                "message": (
                                    "This output records only whether the file exists. "
                                    "Use label, json_path, or yaml_path to retain a report. "
                                    "A condition can check its verdict before a human review step."
                                ),
                            }
                        )
            if isinstance(node, LoopNode):
                visit(node.body, scope)

    visit(nodes, "root")
    return warnings


def autosave_workflow_draft(
    store: WorkflowEditorStore,
    relay_root: Path,
    project_id: str,
    workflow_key: str,
    yaml_text: str,
    base_hash: str,
    *,
    prompts: dict[str, object] | None = None,
) -> dict[str, object]:
    """Keep invalid editor text recoverable while recording its validation state."""
    path = _path(relay_root, workflow_key)
    state = DraftValidationState.VALID
    try:
        from .actions.language import load

        load(yaml_text, source=path)
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
        **({"prompts": prompts} if prompts is not None else {}),
    )


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


def save_workflow_document(
    store: WorkflowEditorStore,
    relay_root: Path,
    project_id: str,
    workflow_key: str,
    yaml_text: str,
    base_hash: str,
) -> None:
    """Save YAML through the same recoverable publication used by bundled prompts."""
    from .source_bundle import save_source_bundle

    save_source_bundle(store, relay_root, project_id, workflow_key, yaml_text, base_hash, {})


__all__ = [
    "WorkflowDocument",
    "WorkflowEditorStore",
    "autosave_workflow_draft",
    "create_workflow_document",
    "list_workflow_documents",
    "read_prompt_document",
    "read_workflow_document",
    "save_prompt_document",
    "save_workflow_document",
    "workflow_handoff_warnings",
]
