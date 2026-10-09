"""Framework-free project registration, relinking, and blank initialization."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import tempfile
from typing import Protocol

from relay.errors import GitError, ProjectRelinkError
from relay.vcs.git import run_git

from .discovery import git_root
from .identity import ProjectIdentity, canonical_path, identify_project

_BLANK_WORKFLOW = (
    "name: Blank workflow\non: workflow_dispatch\njobs:\n"
    "  main:\n    steps:\n      - run: echo Ready\n"
)
INITIAL_PROJECT_FILES = (
    ("workflows/workflow.yaml", _BLANK_WORKFLOW),
    ("prompts/prompt.md", ""),
)


@dataclass(frozen=True, slots=True)
class ProjectRecord:
    """Project fields returned to application and interface layers."""

    id: str
    canonical_path: str
    display_name: str
    git_root: str


@dataclass(frozen=True, slots=True)
class ProjectLaunchSource:
    """Current Git source shown before the immutable launch capture."""

    branch: str | None
    commit: str | None


def project_launch_source(repository: Path) -> ProjectLaunchSource:
    branch = run_git(repository, ["symbolic-ref", "--quiet", "--short", "HEAD"], check=False)
    head = run_git(repository, ["rev-parse", "--verify", "--quiet", "HEAD"], check=False)
    if branch.returncode not in {0, 1} or head.returncode not in {0, 1}:
        message = "Relay could not read this project's Git source."
        raise GitError(message, context={"project": str(repository)})
    return ProjectLaunchSource(
        branch.stdout.strip() if branch.returncode == 0 else None,
        head.stdout.strip() if head.returncode == 0 else None,
    )


@dataclass(frozen=True, slots=True)
class InitializationResult:
    """Outcome of an idempotent blank-project initialization."""

    relay_root: Path
    created: bool


class ProjectStore(Protocol):
    """Persistence port required by project application services."""

    def register(self, identity: ProjectIdentity) -> ProjectRecord: ...

    def list_projects(self) -> list[ProjectRecord]: ...

    def relink(self, old_path: str, identity: ProjectIdentity) -> ProjectRecord: ...


def initialize_project(start: Path | None = None) -> InitializationResult:
    """Create the two-file blank surface atomically at the Git root."""
    repository = git_root(start)
    target = repository / ".relay"
    if target.exists():
        return InitializationResult(target, created=False)

    temporary = Path(tempfile.mkdtemp(prefix=".relay-init-", dir=repository))
    try:
        workflows = temporary / "workflows"
        prompts = temporary / "prompts"
        workflows.mkdir()
        prompts.mkdir()
        for relative, text in INITIAL_PROJECT_FILES:
            (temporary / relative).write_text(text, encoding="utf-8")
        try:
            temporary.replace(target)
        except FileExistsError:
            return InitializationResult(target, created=False)
        return InitializationResult(target, created=True)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def register_current_project(store: ProjectStore, start: Path | None = None) -> ProjectRecord:
    """Discover and persist the current project's canonical identity."""
    return store.register(identify_project(start))


def list_registered_projects(store: ProjectStore) -> list[ProjectRecord]:
    """Return projects in repository-defined recent-use order."""
    return store.list_projects()


def relink_project(store: ProjectStore, old_path: Path, new_path: Path) -> ProjectRecord:
    """Validate the new Git location before recording an explicit move."""
    new_identity = identify_project(new_path)
    old = canonical_path(old_path)
    if old == new_identity.canonical_path:
        message = "The old and new project paths resolve to the same location."
        raise ProjectRelinkError(message)
    return store.relink(old, new_identity)
