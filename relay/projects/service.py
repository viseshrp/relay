"""Framework-free project registration, relinking, and blank initialization."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import tempfile
from typing import Protocol

from relay.constants import SCHEMA_VERSION
from relay.errors import ProjectRelinkError

from .discovery import git_root
from .identity import ProjectIdentity, canonical_path, identify_project

_BLANK_WORKFLOW = f"version: {SCHEMA_VERSION}\nname: Blank workflow\nnodes: {{}}\n"


@dataclass(frozen=True, slots=True)
class ProjectRecord:
    """Project fields returned to application and interface layers."""

    id: str
    canonical_path: str
    display_name: str
    git_root: str


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
        (workflows / "workflow.yaml").write_text(_BLANK_WORKFLOW, encoding="utf-8")
        (prompts / "prompt.md").write_text("", encoding="utf-8")
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
