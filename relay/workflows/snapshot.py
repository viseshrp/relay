"""Immutable, write-once launch snapshot construction."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
import platform

from relay import __version__

from .actions.language import DIALECT
from .routing import RouteRequirement, serialize_route_table
from .validation import ValidatedWorkflow


@dataclass(frozen=True, slots=True)
class SnapshotBundle:
    """JSON-compatible fields persisted exactly once with a Run."""

    workflow_yaml: str
    resolved_prompts: list[dict[str, str]]
    typed_inputs: dict[str, object]
    route_table: dict[str, dict[str, object]]
    relay_version: str
    runtime_versions: dict[str, str]
    hashes: dict[str, str]
    launch_defaults: dict[str, object] = field(default_factory=dict)
    semantics_revision: str = DIALECT
    resolved_definition: dict[str, object] = field(default_factory=dict)

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
    launch_defaults: Mapping[str, object] | None = None,
) -> SnapshotBundle:
    """Capture exact workflow and prompt bytes plus all launch decisions."""
    hashes = {"workflow": _digest(workflow.root.text)}
    prompt_rows = [prompt.to_dict() for prompt in workflow.prompts]
    for index, prompt in enumerate(workflow.prompts):
        hashes[f"prompt:{index}:{prompt.source}:{prompt.reference}"] = prompt.sha256

    runtime_versions = {
        "python": platform.python_version(),
        "pydantic": _package_version("pydantic"),
        "ruamel.yaml": _package_version("ruamel.yaml"),
    }
    from .actions.compiler import sources_hashes
    from .actions.language import UPSTREAM

    hashes.update(sources_hashes(next(iter(workflow.root.definition.nodes.values())).sources))
    runtime_versions["actions-language"] = UPSTREAM
    return SnapshotBundle(
        workflow_yaml=workflow.root.text,
        resolved_prompts=prompt_rows,
        typed_inputs=dict(typed_inputs),
        route_table=serialize_route_table(routes),
        relay_version=__version__,
        runtime_versions=runtime_versions,
        hashes=hashes,
        launch_defaults=dict(launch_defaults or {}),
        semantics_revision=DIALECT,
        resolved_definition=(workflow.root.definition.model_dump(mode="json", by_alias=True)),
    )


__all__ = ["SnapshotBundle", "build_snapshot"]
