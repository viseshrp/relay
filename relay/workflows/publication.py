"""Explicit, reviewed publication of new workflow sources to the owner's Git history."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import logging
from pathlib import Path
from typing import TypedDict

from relay.constants import API_MAX_PAGE_BYTES
from relay.errors import PermissionFlowError, RelayError, WorkflowValidationError
from relay.execution.preflight import launch_source_files, load_launch_workflow
from relay.projects.discovery import git_root
from relay.vcs.cleanliness import execution_status
from relay.vcs.git import git_stdout, run_git, run_git_bytes

LOGGER = logging.getLogger(__name__)


class CommitFile(TypedDict):
    path: str
    hash: str
    text: str


class CommitPreview(TypedDict):
    head: str
    files: list[CommitFile]
    notices: list[str]


def preview_workflow_commit(relay_root: Path, workflow_key: str) -> CommitPreview:
    """Show complete, bounded untracked sources; code and root reports are never candidates."""
    repository = relay_root.parent.resolve()
    root = git_root(repository)
    workflow = load_launch_workflow(relay_root, workflow_key)
    changes = execution_status(
        repository,
        snapshot_files=launch_source_files(workflow, repository),
        allow_initial_surface=True,
    )
    if any(change.status != "??" and change.status[0] != " " for change in changes):
        message = (
            "The Git index has changes. Commit or set those aside before committing workflow files."
        )
        raise PermissionFlowError(message)
    sources = set(launch_source_files(workflow, repository))
    candidates = []
    notices = []
    for change in changes:
        if change.status != "??" or change.allowed:
            continue
        path = root / change.path
        if path.is_symlink() or not path.is_relative_to(relay_root):
            continue
        relative = path.relative_to(relay_root)
        if relative.parts[0] == "workflows" and path.suffix in {".yaml", ".yml"}:
            try:
                other = load_launch_workflow(
                    relay_root, relative.relative_to("workflows").as_posix()
                )
            except RelayError as error:
                notices.append(f"Skipped {change.path}: {error.message}")
                continue
            sources.update(launch_source_files(other, repository))
        if relative.parts[0] in {"workflows", "prompts"}:
            candidates.append(change.path)
    files: list[CommitFile] = []
    remaining = API_MAX_PAGE_BYTES // 2
    for name in candidates:
        if name not in sources:
            continue
        path = root / name
        if not path.resolve().is_relative_to(relay_root.resolve()) or any(
            parent.is_symlink() for parent in path.parents if parent.is_relative_to(relay_root)
        ):
            message = "Linked workflow sources cannot be committed from Relay."
            raise WorkflowValidationError(message)
        raw = path.read_bytes()
        if len(raw) > remaining:
            message = (
                "These workflow sources exceed the commit preview limit. Commit them with Git."
            )
            raise WorkflowValidationError(message)
        remaining -= len(raw)
        files.append({"path": name, "hash": sha256(raw).hexdigest(), "text": raw.decode("utf-8")})
    return {
        "head": git_stdout(repository, ["rev-parse", "HEAD"]),
        "files": files,
        "notices": notices,
    }


def _require_staged_sources(repository: Path, blobs: Mapping[str, str]) -> None:
    staged = set(git_stdout(repository, ["diff", "--cached", "--name-only"]).splitlines())
    if staged != set(blobs) or any(
        git_stdout(repository, ["rev-parse", f":{path}"]) != expected
        for path, expected in blobs.items()
    ):
        message = "Another Git operation changed the index. Workflow files were not committed."
        raise PermissionFlowError(message)


def commit_workflow_sources(
    relay_root: Path, workflow_key: str, head: str, hashes: Mapping[str, str]
) -> str:
    """Commit confirmed sources after Git clean conversion and repeated index checks."""
    preview = preview_workflow_commit(relay_root, workflow_key)
    files = preview["files"]
    current = {item["path"]: item["hash"] for item in files}
    if not current or current != dict(hashes) or preview["head"] != head:
        message = "Workflow files or the branch changed after the preview."
        raise PermissionFlowError(message, next_action="Review a fresh preview before committing.")
    paths = sorted(current)
    repository = relay_root.parent.resolve()
    # Git's clean conversion can normalize CRLF or apply repository attributes.
    # Feed the reviewed bytes, so a later worktree edit cannot redefine consent.
    blobs = {
        item["path"]: run_git_bytes(
            repository,
            ["hash-object", f"--path={item['path']}", "--stdin"],
            input_bytes=item["text"].encode("utf-8"),
        )
        .stdout.decode("ascii")
        .strip()
        for item in files
    }
    try:
        run_git(repository, ["add", "--", *paths])
        _require_staged_sources(repository, blobs)
        run_git(repository, ["commit", "-m", "Add Relay workflow sources"])
    except Exception:
        # The index was empty before this operation. Restore only our selected paths.
        try:
            run_git(repository, ["reset", "--", *paths])
        except Exception:
            LOGGER.exception(
                "Workflow source index cleanup failed", extra={"project": str(repository)}
            )
        raise
    return git_stdout(repository, ["rev-parse", "HEAD"])
