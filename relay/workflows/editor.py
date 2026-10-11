"""Application services for recovery drafts, validation, and atomic YAML saves."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path

from relay.constants import API_MAX_PAGE, API_MAX_PAGE_BYTES
from relay.errors import (
    PermissionFlowError,
    RelayError,
    WorkflowValidationError,
)
from relay.execution.state import DraftValidationState
from relay.paths import safe_resolve

from .loader import load_workflow_text, resolve_workflow_path, workflow_key_parts
from .schema import AgentNode, CommandNode, ExistsSelector, LoopNode, NodeDefinition
from .source_files import (
    WorkflowEditorStore,
    _atomic_create,
    _atomic_replace,
    _path,
    _require_portable_names,
)
from .source_text import read_source
from .validation import validate_loaded_workflow


@dataclass(frozen=True, slots=True)
class WorkflowDocument:
    """Current Git-owned YAML plus its optional database recovery draft."""

    yaml: str
    draft: dict[str, object] | None
    base_hash: str


def read_workflow_document(
    store: WorkflowEditorStore,
    relay_root: Path,
    project_id: str,
    workflow_key: str,
) -> WorkflowDocument:
    """Read the saved file and latest recovery draft without merging either."""
    from .source_bundle import source_lock

    with source_lock(relay_root):
        path = _path(relay_root, workflow_key)
        try:
            source = read_source(path, max_bytes=API_MAX_PAGE_BYTES)
        except (OSError, UnicodeError):
            message = f"Workflow {workflow_key!r} could not be read as UTF-8."
            raise WorkflowValidationError(message, context={"workflow": workflow_key}) from None
        return WorkflowDocument(
            source.text, store.get_draft(project_id, workflow_key), source.base_hash
        )


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
            # Invalid files remain selectable so the owner can repair them in the editor.
            try:
                title = load_workflow_text(
                    path.read_text(encoding="utf-8"), source=path
                ).definition.name
            except (RelayError, OSError, UnicodeError):
                title = path.stem
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
    """Validate and publish a new file without replacing an existing workflow."""
    from .source_bundle import source_lock

    with source_lock(relay_root):
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


def read_prompt_document(relay_root: Path, reference: str) -> dict[str, str]:
    """Read an editable local prompt within this project's prompts directory."""
    from .source_bundle import source_lock

    with source_lock(relay_root):
        path = safe_resolve(relay_root, reference)
        path = safe_resolve(relay_root / "prompts", path)
        try:
            source = read_source(path, max_bytes=API_MAX_PAGE_BYTES)
        except (OSError, UnicodeError):
            message = "The selected instructions could not be read as UTF-8."
            raise WorkflowValidationError(message) from None
        return {"text": source.text, "base_hash": source.base_hash, "reference": reference}


def save_prompt_document(
    relay_root: Path,
    reference: str,
    text: str,
    base_hash: str | None,
) -> dict[str, str]:
    """Write local instructions only if the owner's loaded bytes still match."""
    from .source_bundle import source_lock

    with source_lock(relay_root):
        path = safe_resolve(relay_root, reference)
        path = safe_resolve(relay_root / "prompts", path)
        if path.exists():
            saved = read_prompt_document(relay_root, reference)
            if base_hash != saved["base_hash"]:
                message = "These instructions changed after you loaded them."
                raise PermissionFlowError(
                    message, next_action="Reload the instructions before saving."
                )
            _atomic_replace(
                path,
                read_source(path, max_bytes=API_MAX_PAGE_BYTES).replacement(text),
                resource="instructions",
            )
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
