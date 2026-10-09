"""Explicit, reviewed publication of new workflow sources to the owner's Git history."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import TypedDict

from relay.constants import API_MAX_PAGE_BYTES
from relay.errors import PermissionFlowError, WorkflowValidationError
from relay.execution.preflight import launch_source_files, load_launch_workflow
from relay.projects.discovery import git_root
from relay.vcs.cleanliness import execution_status
from relay.vcs.git import git_stdout, run_git


class CommitFile(TypedDict):
    path: str
    hash: str
    text: str


class CommitPreview(TypedDict):
    head: str
    files: list[CommitFile]


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
    for change in changes:
        if change.status != "??" or change.allowed:
            continue
        path = root / change.path
        if path.is_symlink() or not path.is_relative_to(relay_root):
            continue
        relative = path.relative_to(relay_root)
        if relative.parts[0] == "workflows" and path.suffix in {".yaml", ".yml"}:
            other = load_launch_workflow(relay_root, relative.relative_to("workflows").as_posix())
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
    return {"head": git_stdout(repository, ["rev-parse", "HEAD"]), "files": files}


def _require_staged_sources(repository: Path, paths: list[str]) -> None:
    staged = set(git_stdout(repository, ["diff", "--cached", "--name-only"]).splitlines())
    if staged != set(paths):
        message = "Another Git operation changed the index. Workflow files were not committed."
        raise PermissionFlowError(message)


def commit_workflow_sources(
    relay_root: Path, workflow_key: str, head: str, hashes: Mapping[str, str]
) -> str:
    """Commit exactly the confirmed bytes after repeating validation and the index check."""
    preview = preview_workflow_commit(relay_root, workflow_key)
    files = preview["files"]
    current = {item["path"]: item["hash"] for item in files}
    if not current or current != dict(hashes) or preview["head"] != head:
        message = "Workflow files or the branch changed after the preview."
        raise PermissionFlowError(message, next_action="Review a fresh preview before committing.")
    paths = sorted(current)
    repository = relay_root.parent.resolve()
    try:
        run_git(repository, ["add", "--", *paths])
        _require_staged_sources(repository, paths)
        run_git(repository, ["commit", "-m", "Add Relay workflow sources", "--", *paths])
    except Exception:
        # The index was empty before this operation. Restore only our selected paths.
        run_git(repository, ["reset", "--", *paths])
        raise
    return git_stdout(repository, ["rev-parse", "HEAD"])
