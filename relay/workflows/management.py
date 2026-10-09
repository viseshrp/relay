"""Lease-protected workflow management that retains shared prompts and run history."""

from __future__ import annotations

from collections.abc import MutableMapping
from hashlib import sha256
from io import StringIO
from pathlib import Path
from typing import Any, cast

from ruamel.yaml import YAML

from relay.errors import PermissionFlowError, RelayError, WorkflowValidationError

from .actions.language import load
from .editor import (
    WorkflowEditorStore,
    _path,
    _require_portable_names,
    list_workflow_documents,
)
from .loader import resolve_workflow_path, workflow_key_parts


def _reject_references(relay_root: Path, key: str) -> None:
    reference = f"./.relay/workflows/{key}"
    for item in list_workflow_documents(relay_root):
        if item["key"] == key:
            continue
        try:
            document = load((relay_root / "workflows" / item["key"]).read_text("utf-8"))
        except (RelayError, OSError, UnicodeError):
            continue
        for job in document.value["jobs"].values():
            if job.get("uses") == reference or any(
                step.get("uses") == "relay/loop@v1"
                and step.get("with", {}).get("workflow") == reference
                for step in job.get("steps", [])
            ):
                message = f"{item['key']} references this workflow."
                raise PermissionFlowError(
                    message,
                    next_action="Update that reference before renaming or deleting this file.",
                )


def manage_workflow_document(
    store: WorkflowEditorStore,
    relay_root: Path,
    project_id: str,
    key: str,
    action: str,
    base_hash: str,
    *,
    new_key: str | None = None,
    name: str | None = None,
) -> str | None:
    path = _path(relay_root, key)
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != base_hash:
        message = "The saved workflow changed after you loaded it."
        raise PermissionFlowError(message, next_action="Reload before managing the workflow.")
    if action == "delete":
        _reject_references(relay_root, key)
        path.unlink()
        return None
    if action not in {"rename", "duplicate"} or not new_key:
        message = "Choose rename, duplicate, or delete, with a new file name when needed."
        raise WorkflowValidationError(message)
    new_key = "/".join(workflow_key_parts(new_key))
    _require_portable_names(workflow_key_parts(new_key))
    destination = resolve_workflow_path(relay_root / "workflows", new_key)
    if action == "rename":
        _reject_references(relay_root, key)
    text = raw.decode("utf-8")
    if name is not None:
        parsed = load(text)
        document = cast(MutableMapping[str, Any], parsed.document)
        document["name"] = name
        output = StringIO()
        YAML(typ="rt").dump(document, output)
        text = output.getvalue()
    if destination == path:
        if action == "duplicate":
            message = "A duplicate needs a different file name."
            raise PermissionFlowError(message)
        from .editor import save_workflow_document

        save_workflow_document(store, relay_root, project_id, key, text, base_hash)
        return key
    from .editor import create_workflow_document

    create_workflow_document(store, relay_root, project_id, new_key, text)
    if action == "rename":
        try:
            path.unlink()
        except OSError:
            destination.unlink()
            raise
    return new_key
