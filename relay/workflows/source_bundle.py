"""Recoverable, serialized publication of a workflow and its local prompts."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path
import threading
from typing import TypedDict, cast

from relay.constants import API_MAX_PAGE_BYTES
from relay.errors import PermissionFlowError, WorkflowValidationError
from relay.manage import MigrationLock
from relay.paths import data_dir, safe_resolve

from .editor import (
    WorkflowEditorStore,
    _atomic_create,
    _atomic_replace,
    _path,
    _require_portable_names,
)


class PromptEdit(TypedDict):
    text: str
    base_hash: str | None


_LOCKS: dict[str, threading.RLock] = {}
_GUARD = threading.Lock()
_ACTIVE = threading.local()


def prompt_edits(value: object, relay_root: Path) -> dict[str, PromptEdit]:
    if not isinstance(value, dict) or len(value) > 32:
        message = "Prompt edits must map at most 32 local file names to text and base_hash."
        raise WorkflowValidationError(message)
    result: dict[str, PromptEdit] = {}
    paths: set[Path] = set()
    size = 0
    for reference, edit in value.items():
        if not isinstance(reference, str) or not isinstance(edit, dict):
            message = "Each prompt edit needs a local file name, text, and base_hash."
            raise WorkflowValidationError(message)
        path = safe_resolve(relay_root / "prompts", safe_resolve(relay_root, reference))
        _require_portable_names(path.relative_to(relay_root.resolve()).parts)
        text, base = edit.get("text"), edit.get("base_hash")
        if (
            not isinstance(text, str)
            or (
                base is not None
                and (
                    not isinstance(base, str)
                    or len(base) != 64
                    or any(c not in "0123456789abcdef" for c in base)
                )
            )
            or path in paths
        ):
            message = "Prompt text, base_hash, or duplicate file names are invalid."
            raise WorkflowValidationError(message)
        size += len(text.encode("utf-8"))
        if size > API_MAX_PAGE_BYTES:
            message = "Prompt edits exceed 1 MiB."
            raise WorkflowValidationError(message)
        paths.add(path)
        result[path.relative_to(relay_root.resolve()).as_posix()] = {
            "text": text,
            "base_hash": base,
        }
    return result


def _journal(root: Path) -> Path:
    identity = sha256(str(root.resolve()).encode()).hexdigest()
    return data_dir() / "source-bundles" / f"{identity}.json"


def _require_journal(condition: bool) -> None:
    if not condition:
        raise ValueError


def _read_source(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        with path.open("rb") as stream:
            raw = stream.read(API_MAX_PAGE_BYTES + 1)
        if len(raw) > API_MAX_PAGE_BYTES:
            message = "A source file exceeds 1 MiB."
            raise WorkflowValidationError(message)
        return raw.decode("utf-8")
    except (OSError, UnicodeError):
        message = f"Source {path.name!r} could not be read as UTF-8."
        raise WorkflowValidationError(message) from None


def _recover(root: Path) -> None:
    journal = _journal(root)
    if not journal.exists():
        return
    try:
        with journal.open("rb") as stream:
            raw = stream.read(24 * API_MAX_PAGE_BYTES + 1)
        _require_journal(len(raw) <= 24 * API_MAX_PAGE_BYTES)
        value = json.loads(raw)
        _require_journal(
            value.get("owner") == str(root.resolve()) and isinstance(value.get("files"), dict)
        )
        files = value["files"]
        _require_journal(1 <= len(files) <= 33)
        records = []
        for name, record in files.items():
            _require_journal(
                isinstance(name, str) and name.split("/")[0] in {"workflows", "prompts"}
            )
            path = safe_resolve(root / name.split("/")[0], safe_resolve(root, name))
            old, new = record["old"], record["new"]
            _require_journal(isinstance(new, str) and (old is None or isinstance(old, str)))
            current = _read_source(path)
            if current not in (old, new):
                message = "A source changed while an interrupted save was being recovered."
                raise PermissionFlowError(
                    message, next_action="Reconcile that file before saving again."
                )
            records.append((path, old, new, current))
        if value.get("committed") is not True or not all(
            current == new for _, _, new, current in records
        ):
            for path, old, _, current in reversed(records):
                if current == old:
                    continue
                if old is None:
                    path.unlink(missing_ok=True)
                else:
                    _atomic_replace(path, old, resource="source recovery")
        journal.unlink()
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, AttributeError):
        message = "Relay could not recover an interrupted source save."
        raise WorkflowValidationError(
            message, next_action="Inspect the retained source journal before retrying."
        ) from None


@contextmanager
def source_lock(relay_root: Path) -> Iterator[None]:
    identity = str(relay_root.resolve())
    with _GUARD:
        lock = _LOCKS.setdefault(identity, threading.RLock())
    with lock:
        active = getattr(_ACTIVE, "roots", set())
        if identity in active:
            yield
            return
        journal = _journal(relay_root)
        with MigrationLock(journal.with_suffix(".lock"), timeout=5, purpose="workflow source"):
            _ACTIVE.roots = active | {identity}
            try:
                _recover(relay_root)
                yield
            finally:
                _ACTIVE.roots = active


def save_source_bundle(
    store: WorkflowEditorStore,
    relay_root: Path,
    project_id: str,
    key: str,
    yaml_text: str,
    base_hash: str,
    edits: Mapping[str, PromptEdit],
) -> None:
    from .actions.language import load
    from .loader import load_workflow_text
    from .validation import validate_loaded_workflow

    edits = prompt_edits(dict(edits), relay_root)
    with source_lock(relay_root):
        workflow = _path(relay_root, key)
        changes = {
            reference: (edit["text"], edit["base_hash"]) for reference, edit in edits.items()
        }
        changes[workflow.relative_to(relay_root.resolve()).as_posix()] = (yaml_text, base_hash)
        files: dict[str, dict[str, str | None]] = {}
        previous_size = 0
        for name, (text, expected) in changes.items():
            path = safe_resolve(relay_root, name)
            old = _read_source(path)
            previous_size += len(old.encode()) if old is not None else 0
            if previous_size > 2 * API_MAX_PAGE_BYTES:
                message = "The previous source bundle exceeds 2 MiB."
                raise WorkflowValidationError(message)
            actual = sha256(old.encode()).hexdigest() if old is not None else None
            if actual != expected:
                message = f"{name} changed after this editor loaded it."
                raise PermissionFlowError(
                    message, next_action="Reload and reconcile the changes before saving."
                )
            files[name] = {"old": old, "new": text}
        load(yaml_text, source=workflow)
        journal = _journal(relay_root)
        _atomic_create(journal, json.dumps({"owner": str(relay_root.resolve()), "files": files}))
        try:
            for name, record in files.items():
                if name.startswith("workflows/"):
                    continue
                path = safe_resolve(relay_root, name)
                text = cast(str, record["new"])
                if record["old"] is None:
                    _atomic_create(path, text)
                else:
                    _atomic_replace(path, text, resource="instructions")
            validate_loaded_workflow(load_workflow_text(yaml_text, source=workflow), relay_root)
            _atomic_replace(workflow, yaml_text)
            _atomic_replace(
                journal,
                json.dumps({"owner": str(relay_root.resolve()), "files": files, "committed": True}),
                resource="source journal",
            )
            journal.unlink()
        except BaseException:
            _recover(relay_root)
            raise
        store.discard_draft(project_id, key)
