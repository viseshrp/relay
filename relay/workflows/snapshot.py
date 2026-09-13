"""Immutable, write-once launch snapshot construction."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
import platform

from relay import __version__

from .routing import RouteRequirement, serialize_route_table
from .validation import ValidatedWorkflow


@dataclass(frozen=True, slots=True)
class SnapshotBundle:
    """JSON-compatible fields persisted exactly once with a Run."""

    workflow_yaml: str
    subworkflows: dict[str, object]
    resolved_prompts: list[dict[str, str]]
    typed_inputs: dict[str, object]
    route_table: dict[str, dict[str, object]]
    default_model: str
    agent_prefs: list[dict[str, object]]
    relay_version: str
    runtime_versions: dict[str, str]
    hashes: dict[str, str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _digest(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def _package_version(distribution: str) -> str:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return "not-installed"


def build_snapshot(
    workflow: ValidatedWorkflow,
    *,
    typed_inputs: Mapping[str, object],
    routes: Iterable[RouteRequirement],
) -> SnapshotBundle:
    """Capture exact workflow and prompt bytes plus all launch decisions."""
    subworkflows: dict[str, object] = {}
    hashes = {"workflow": _digest(workflow.root.text)}
    agent_prefs: list[dict[str, object]] = [
        {
            "workflow": workflow.root.path.name,
            "agents": list(workflow.root.definition.agents),
        }
    ]
    for key, loaded in workflow.subworkflows.items():
        digest = _digest(loaded.text)
        subworkflows[key] = {"yaml": loaded.text, "sha256": digest}
        hashes[f"subworkflow:{key}"] = digest
        agent_prefs.append({"workflow": key, "agents": list(loaded.definition.agents)})

    prompt_rows = [prompt.to_dict() for prompt in workflow.prompts]
    for index, prompt in enumerate(workflow.prompts):
        hashes[f"prompt:{index}:{prompt.source}:{prompt.reference}"] = prompt.sha256

    runtime_versions = {
        "python": platform.python_version(),
        "pydantic": _package_version("pydantic"),
        "ruamel.yaml": _package_version("ruamel.yaml"),
    }
    return SnapshotBundle(
        workflow_yaml=workflow.root.text,
        subworkflows=subworkflows,
        resolved_prompts=prompt_rows,
        typed_inputs=dict(typed_inputs),
        route_table=serialize_route_table(routes),
        default_model=workflow.root.definition.model or "",
        agent_prefs=agent_prefs,
        relay_version=__version__,
        runtime_versions=runtime_versions,
        hashes=hashes,
    )


__all__ = ["SnapshotBundle", "build_snapshot"]
