"""Unambiguous runtime scope-path construction and parsing."""

from __future__ import annotations

from dataclasses import dataclass
import re

from relay.errors import WorkflowValidationError

ROOT_SCOPE = "root"


@dataclass(frozen=True, slots=True)
class ScopeSegment:
    """One job, step, matrix variant, or reusable-call segment."""

    node_id: str

    def render(self) -> str:
        return self.node_id


def _validate_node_id(node_id: str) -> None:
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", node_id) is None:
        message = f"Scope node id {node_id!r} is invalid."
        raise WorkflowValidationError(message)


def parse_scope_path(path: str) -> tuple[ScopeSegment, ...]:
    """Parse `root.build.iteration_2.verify.check` into typed segments."""
    parts = path.split(".")
    if len(parts) < 2 or parts[0] != ROOT_SCOPE:
        message = f"Scope path {path!r} must begin with 'root.'."
        raise WorkflowValidationError(message)
    segments = []
    for part in parts[1:]:
        _validate_node_id(part)
        segments.append(ScopeSegment(part))
    return tuple(segments)


def render_scope_path(segments: tuple[ScopeSegment, ...]) -> str:
    """Render typed segments beneath the fixed `root` namespace."""
    if not segments:
        message = "A node scope must contain at least one segment."
        raise WorkflowValidationError(message)
    return ".".join((ROOT_SCOPE, *(segment.render() for segment in segments)))


def node_scope(parent: str | None, node_id: str) -> str:
    """Append a node to a parent scope; `None` creates `root.<node>`."""
    _validate_node_id(node_id)
    if parent is None or parent == ROOT_SCOPE:
        return f"{ROOT_SCOPE}.{node_id}"
    parse_scope_path(parent)
    return f"{parent}.{node_id}"


def sibling_scope(current: str, sibling_id: str) -> str:
    """Resolve `needs.<id>` within the current node's enclosing scope."""
    segments = parse_scope_path(current)
    parent = segments[:-1]
    _validate_node_id(sibling_id)
    return render_scope_path((*parent, ScopeSegment(sibling_id)))


def enclosing_scope(path: str) -> str | None:
    """Return direct enclosing scope, with top-level nodes represented by null."""
    segments = parse_scope_path(path)
    if len(segments) == 1:
        return None
    return render_scope_path(segments[:-1])


def scope_is_ancestor(ancestor: str, descendant: str) -> bool:
    """Match exact segment ancestry, including concrete matrix and loop instances."""
    parent_segments = parse_scope_path(ancestor)
    child_segments = parse_scope_path(descendant)
    return (
        len(parent_segments) <= len(child_segments)
        and parent_segments == child_segments[: len(parent_segments)]
    )


__all__ = [
    "ROOT_SCOPE",
    "ScopeSegment",
    "enclosing_scope",
    "node_scope",
    "parse_scope_path",
    "render_scope_path",
    "scope_is_ancestor",
    "sibling_scope",
]
