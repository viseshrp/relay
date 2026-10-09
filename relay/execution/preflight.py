"""Read the same validated sources and Git rules used by workflow launch."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path

from relay.constants import API_MAX_PAGE, API_MAX_PAGE_BYTES
from relay.projects.discovery import git_root
from relay.vcs.cleanliness import RepositoryChange, execution_status
from relay.workflows.loader import load_workflow, resolve_workflow_path
from relay.workflows.schema import ActionsJobNode
from relay.workflows.validation import ValidatedWorkflow, validate_loaded_workflow


def load_launch_workflow(relay_root: Path, workflow_key: str) -> ValidatedWorkflow:
    path = resolve_workflow_path(relay_root / "workflows", workflow_key)
    return validate_loaded_workflow(load_workflow(path), relay_root)


def launch_source_files(workflow: ValidatedWorkflow, repository: Path) -> frozenset[str]:
    captured = [workflow.root.path, *(item.path for item in workflow.subworkflows.values())]
    captured.extend(Path(prompt.path) for prompt in workflow.prompts if prompt.source == "local")
    for node in workflow.root.definition.nodes.values():
        if isinstance(node, ActionsJobNode):
            captured.extend(repository / key for key in node.sources)
    source_root = git_root(repository)
    return frozenset(path.relative_to(source_root).as_posix() for path in captured)


@dataclass(frozen=True, slots=True)
class LaunchCleanliness:
    """Full counts with a bounded, blocking-first page of file explanations."""

    clean: bool
    blocking_count: int
    allowed_count: int
    files: tuple[RepositoryChange, ...]
    truncated: bool


def inspect_launch_cleanliness(
    relay_root: Path, workflow_key: str, *, merge_on_success: bool = False
) -> LaunchCleanliness:
    workflow = load_launch_workflow(relay_root, workflow_key)
    repository = relay_root.parent.resolve()
    changes = execution_status(
        repository,
        snapshot_files=launch_source_files(workflow, repository),
        allow_initial_surface=True,
    )
    if merge_on_success:
        changes = tuple(
            replace(
                change,
                allowed=False,
                reasons=("A merge requires every changed file to be committed or set aside.",),
            )
            for change in changes
        )
    blocked = [change for change in changes if not change.allowed]
    allowed = [change for change in changes if change.allowed]
    files: list[RepositoryChange] = []
    remaining = API_MAX_PAGE_BYTES // 2
    for change in [*blocked, *allowed]:
        size = len(json.dumps(asdict(change)).encode("utf-8")) + 2
        if len(files) >= API_MAX_PAGE or size > remaining:
            break
        remaining -= size
        files.append(change)
    return LaunchCleanliness(
        clean=not blocked,
        blocking_count=len(blocked),
        allowed_count=len(allowed),
        files=tuple(files),
        truncated=len(files) < len(changes),
    )
