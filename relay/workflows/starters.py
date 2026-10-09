"""Copy the approved starter sources into an owner's editable workflow folder."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import tempfile

from relay.errors import PermissionFlowError, WorkflowValidationError
from relay.manage import MigrationLock
from relay.paths import data_dir, safe_resolve

from .editor import (
    WorkflowDocument,
    WorkflowEditorStore,
    _atomic_create,
    _require_portable_names,
    read_workflow_document,
)
from .loader import load_workflow_text, workflow_key_parts
from .validation import validate_loaded_workflow

STARTER_ROOT = Path(__file__).with_name("starters")


@dataclass(frozen=True, slots=True)
class Starter:
    """A fixed bundle; the chosen model remains an explicit launch input."""

    id: str
    name: str
    description: str
    jobs: tuple[str, ...]
    prompts: tuple[str, ...]


STARTERS = (
    Starter(
        "ask-agent",
        "Ask an agent",
        "Ask a question about this repository.",
        ("Ask",),
        ("ask-agent.md",),
    ),
    Starter(
        "plan-approve-implement",
        "Plan, approve, implement",
        "Read a plan and approve the change before implementation.",
        ("Plan", "Approval", "Implement"),
        ("plan.md", "implement.md"),
    ),
    Starter(
        "implement-and-test",
        "Implement and test",
        "Make a change, then run pytest or npm test.",
        ("Implement", "Choose tests", "pytest / npm test"),
        ("implement.md",),
    ),
    Starter(
        "review-branch",
        "Review my branch",
        "Review this branch and save findings in REVIEW.md.",
        ("Review",),
        ("review-branch.md",),
    ),
    Starter(
        "fix-tests",
        "Fix until tests pass",
        "Fix failures with at most two repair rounds using pytest.",
        ("Implement", "Tests", "Fix → Verify, up to twice"),
        ("implement.md", "fix-tests.md"),
    ),
    Starter(
        "write-docs",
        "Write docs for a change",
        "Update documentation from the current code.",
        ("Write docs",),
        ("write-docs.md",),
    ),
)


def _sources(starter: Starter, key: str) -> tuple[tuple[str, str], ...]:
    return (
        (f"workflows/{key}", (STARTER_ROOT / f"{starter.id}.yaml").read_text(encoding="utf-8")),
        *(
            (f"prompts/{name}", (STARTER_ROOT / name).read_text(encoding="utf-8"))
            for name in starter.prompts
        ),
    )


def starter_inventory() -> list[dict[str, object]]:
    """Return gallery metadata and schema-defined inputs from the same sources."""
    records: list[dict[str, object]] = []
    for starter in STARTERS:
        source = STARTER_ROOT / f"{starter.id}.yaml"
        definition = load_workflow_text(
            source.read_text(encoding="utf-8"), source=source
        ).definition
        records.append(
            {
                "id": starter.id,
                "name": starter.name,
                "description": starter.description,
                "jobs": list(starter.jobs),
                "required_agents": "One compatible coding agent",
                "inputs": {
                    key: item.model_dump(mode="json") for key, item in definition.inputs.items()
                },
            }
        )
    from .library import inventory

    return [*records, *inventory()]


def _require_matching_prompt(path: Path, text: str) -> None:
    if path.read_bytes() != text.encode("utf-8"):
        message = "The template's instructions changed while it was being copied."
        raise PermissionFlowError(message, next_action="Reload and choose another workflow.")


def create_starter_workflow(
    store: WorkflowEditorStore,
    relay_root: Path,
    project_id: str,
    workflow_key: str,
    starter_id: str,
) -> WorkflowDocument:
    if starter_id.startswith("owner:"):
        from .library import instantiate

        return instantiate(store, relay_root, project_id, workflow_key, starter_id)
    """Serialize shared prompt creation and rollback across browser requests."""
    filename = sha256(project_id.encode("utf-8")).hexdigest()
    with MigrationLock(
        data_dir() / "workflow-source-locks" / f"{filename}.lock",
        timeout=0,
        purpose="workflow sources",
    ):
        return _copy_starter_workflow(store, relay_root, project_id, workflow_key, starter_id)


def _copy_starter_workflow(
    store: WorkflowEditorStore,
    relay_root: Path,
    project_id: str,
    workflow_key: str,
    starter_id: str,
) -> WorkflowDocument:
    """Validate the whole bundle before publishing any file; never replace owner bytes."""
    starter = next((item for item in STARTERS if item.id == starter_id), None)
    if starter is None:
        message = "Choose one of the available starter workflows."
        raise WorkflowValidationError(message)
    parts = workflow_key_parts(workflow_key)
    _require_portable_names(parts)
    key = "/".join(parts)
    sources = _sources(starter, key)
    with tempfile.TemporaryDirectory(prefix="relay-starter-") as directory:
        scratch = Path(directory)
        for relative, text in sources:
            path = scratch / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="")
        source = scratch / sources[0][0]
        validate_loaded_workflow(load_workflow_text(sources[0][1], source=source), scratch)

    targets = [(safe_resolve(relay_root, relative), text) for relative, text in sources]
    for index, (path, text) in enumerate(targets):
        if path.exists() and (
            index == 0 or not path.is_file() or path.read_bytes() != text.encode("utf-8")
        ):
            message = f"File {path.name!r} already exists with owner content."
            raise PermissionFlowError(
                message,
                next_action="Choose another workflow or keep the existing instructions.",
            )
    created: list[tuple[Path, str]] = []
    try:
        # Publish the workflow last, so an inventory cannot expose missing prompts.
        for index, (path, text) in enumerate((*targets[1:], targets[0])):
            if index == len(targets) - 1 or not path.exists():
                _atomic_create(path, text)
                created.append((path, text))
            else:
                _require_matching_prompt(path, text)
        return read_workflow_document(store, relay_root, project_id, key)
    except Exception:
        for path, text in reversed(created):
            # Never remove an owner's concurrent edit during rollback.
            with suppress(OSError):
                if path.read_bytes() == text.encode("utf-8"):
                    path.unlink()
        raise
