"""Unambiguous runtime scope-path construction and parsing."""

from __future__ import annotations

from dataclasses import dataclass

from relay.errors import WorkflowValidationError

from .schema import NODE_ID_PATTERN

ROOT_SCOPE = "root"


@dataclass(frozen=True, slots=True)
class ScopeSegment:
    """One node or one-based loop-iteration segment."""

    node_id: str
    iteration: int | None = None

    def render(self) -> str:
        return self.node_id if self.iteration is None else f"{self.node_id}#{self.iteration}"


def _validate_node_id(node_id: str) -> None:
    if NODE_ID_PATTERN.fullmatch(node_id) is None:
        message = f"Scope node id {node_id!r} is invalid."
        raise WorkflowValidationError(message)


def parse_scope_path(path: str) -> tuple[ScopeSegment, ...]:
    """Parse `root.loop#2.verify.check` into typed segments."""
    parts = path.split(".")
    if len(parts) < 2 or parts[0] != ROOT_SCOPE:
        message = f"Scope path {path!r} must begin with 'root.'."
        raise WorkflowValidationError(message)
    segments: list[ScopeSegment] = []
    for part in parts[1:]:
        if "#" in part:
            node_id, separator, raw_iteration = part.partition("#")
            if not separator or not raw_iteration.isdigit() or int(raw_iteration) < 1:
                message = f"Loop scope segment {part!r} is invalid."
                raise WorkflowValidationError(message)
            _validate_node_id(node_id)
            segments.append(ScopeSegment(node_id, int(raw_iteration)))
        else:
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


def loop_iteration_scope(parent: str | None, loop_id: str, iteration: int) -> str:
    """Create a one-based loop instance such as `root.build#2`."""
    _validate_node_id(loop_id)
    if iteration < 1:
        message = "Loop scope iterations are one-based."
        raise WorkflowValidationError(message)
    prefix = ROOT_SCOPE if parent is None else parent
    if prefix != ROOT_SCOPE:
        parse_scope_path(prefix)
    return f"{prefix}.{loop_id}#{iteration}"


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
        return ROOT_SCOPE if segments[0].iteration is not None else None
    return render_scope_path(segments[:-1])


def scope_is_ancestor(ancestor: str, descendant: str) -> bool:
    """Match structural parents across concrete loop-iteration segments.

    For example, ``root.build`` contains ``root.build#2.check`` while
    ``root.build#1`` does not contain ``root.build#2.check``.
    """
    parent_segments = parse_scope_path(ancestor)
    child_segments = parse_scope_path(descendant)
    if len(parent_segments) > len(child_segments):
        return False
    return all(
        parent.node_id == child.node_id
        and (parent.iteration is None or parent.iteration == child.iteration)
        for parent, child in zip(
            parent_segments,
            child_segments[: len(parent_segments)],
            strict=True,
        )
    )


__all__ = [
    "ROOT_SCOPE",
    "ScopeSegment",
    "enclosing_scope",
    "loop_iteration_scope",
    "node_scope",
    "parse_scope_path",
    "render_scope_path",
    "scope_is_ancestor",
    "sibling_scope",
]
