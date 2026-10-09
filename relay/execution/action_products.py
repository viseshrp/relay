"""Named artifacts and project-local immutable caches for local action steps."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
import json
from pathlib import Path
import shutil
from typing import Any
import uuid

from relay.errors import NodeExecutionError, PathSafetyError
from relay.execution.resources import _linked
from relay.execution.runner import AttemptContext, ExecutionOutcome, OutcomeKind
from relay.paths import data_dir, ensure_private_dir, safe_resolve
from relay.workflows.actions.patterns import select_paths
from relay.workflows.schema import ActionsStepNode

MAX_BYTES = 1024**3
QUOTA = 10 * 1024**3
CACHE_MODES = {"write": {"read", "write"}, "read": {"read"}, "write-only": {"write"}, "none": set()}


def cache_mode(
    workflow: Mapping[str, Any], job: Mapping[str, Any], caller: str | None = None
) -> str:
    capability = CACHE_MODES[str(job.get("cache-mode", workflow.get("cache-mode", "write")))].copy()
    if caller:
        capability &= CACHE_MODES[caller]
    if job.get("_caller_cache_mode"):
        capability &= CACHE_MODES[str(job["_caller_cache_mode"])]
    return next(name for name, values in CACHE_MODES.items() if values == capability)


def checked_path(root: Path, relative: str, *, restore: bool = False) -> Path:
    if relative == ".":
        if _linked(root):
            message = "The workspace root was replaced by a link."
            raise PathSafetyError(message)
        return root
    path = Path(relative)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"..", ".git"} for part in path.parts)
        or (restore and path.parts[0] == ".relay")
    ):
        message = "The artifact or cache path is outside its allowed workspace."
        raise PathSafetyError(message)
    for parent in [
        root,
        *(root.joinpath(*path.parts[:index]) for index in range(1, len(path.parts) + 1)),
    ]:
        if _linked(parent):
            message = "Artifact and cache paths cannot contain links."
            raise PathSafetyError(message)
    return safe_resolve(root, relative)


def digest_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_product_file(source: Path, target: Path, expected_size: int) -> None:
    copied = 0
    with source.open("rb") as reader, target.open("xb") as writer:
        while chunk := reader.read(1024 * 1024):
            copied += len(chunk)
            if copied > expected_size:
                message = "Product source changed during capture."
                raise NodeExecutionError(message)
            writer.write(chunk)
    if copied != expected_size:
        message = "Product source changed during capture."
        raise NodeExecutionError(message)


def capture(
    root: Path, patterns: Sequence[str], kind: str, owner: str
) -> tuple[Path, list[dict[str, Any]], int, str]:
    files = select_paths(root, patterns, files_only=True)
    selected = []
    total = 0
    for path in files:
        relative = path.relative_to(root).as_posix()
        checked_path(root, relative, restore=kind == "caches")
        if relative == ".relay-owner.json":
            message = "The product ownership marker is reserved."
            raise PathSafetyError(message)
        size = path.stat().st_size
        total += size
        if len(selected) >= 10000 or total > MAX_BYTES:
            message = "The artifact or cache exceeds 10000 files or 1 GiB."
            raise NodeExecutionError(message)
        selected.append((relative, size))
    if not selected:
        message = "No artifact or cache files matched."
        raise NodeExecutionError(message)
    base = data_dir() / "actions" / kind
    ensure_private_dir(base)
    directory = base / str(uuid.uuid4())
    ensure_private_dir(directory)
    marker_value = json.dumps({"kind": kind, "owner": owner, "id": directory.name})
    marker = directory / ".relay-owner.json"
    marker.write_text(marker_value, encoding="utf-8")
    manifest = []
    try:
        for relative, size in selected:
            source = checked_path(root, relative, restore=kind == "caches")
            target = checked_path(directory, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            _copy_product_file(source, target, size)
            checked_path(root, relative, restore=kind == "caches")
            manifest.append({"path": relative, "bytes": size, "sha256": digest_file(target)})
    except Exception:
        if (
            not _linked(directory)
            and checked_path(directory, marker.name).read_text("utf-8") == marker_value
        ):
            shutil.rmtree(directory)
        raise
    digest = sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return directory, manifest, total, digest


def verify(directory: Path, manifest: Sequence[Mapping[str, Any]], kind: str, owner: str) -> None:
    base = data_dir() / "actions" / kind
    if directory.parent != base or _linked(base) or _linked(directory):
        message = "Retained product ownership changed."
        raise PathSafetyError(message)
    marker = checked_path(directory, ".relay-owner.json")
    if json.loads(marker.read_text(encoding="utf-8")) != {
        "kind": kind,
        "owner": owner,
        "id": directory.name,
    }:
        message = "Retained product ownership changed."
        raise PathSafetyError(message)
    for item in manifest:
        path = checked_path(directory, item["path"])
        if (
            not path.is_file()
            or path.stat().st_size != item["bytes"]
            or digest_file(path) != item["sha256"]
        ):
            message = "A retained artifact or cache failed integrity verification."
            raise NodeExecutionError(message)


def restore(directory: Path, manifest: Sequence[Mapping[str, Any]], workspace: Path) -> None:
    # Verify every destination before the first mutation.
    for item in manifest:
        checked_path(workspace, item["path"], restore=True)
    for item in manifest:
        target = checked_path(workspace, item["path"], restore=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(checked_path(directory, item["path"]), target)


def execute_product(
    context: AttemptContext,
    reference: str,
    inputs: Mapping[str, Any],
    values: Mapping[str, Any],
    node: ActionsStepNode,
) -> ExecutionOutcome:
    from relay.web.actions_products import execute_product as persist_product

    try:
        return persist_product(context, reference, inputs, values, node)
    except OSError:
        if reference not in {"relay/cache@v1", "relay/restore-cache@v1", "relay/save-cache@v1"}:
            raise
        from relay.execution.state import EventSource

        context.runtime.append_attempt_event(
            context.attempt.attempt_id,
            "actions.warning",
            EventSource.SYSTEM,
            {"message": "Cache filesystem operation failed; continuing without a cache hit."},
        )
        return ExecutionOutcome(OutcomeKind.SUCCEEDED, outputs={"cache-hit": "false"})
