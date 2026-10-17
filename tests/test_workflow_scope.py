"""Runtime scope paths: parsing, rendering, siblings, and ancestry."""

from __future__ import annotations

import pytest

from relay.errors import WorkflowValidationError
from relay.workflows.scope import (
    ScopeSegment,
    enclosing_scope,
    node_scope,
    parse_scope_path,
    render_scope_path,
    scope_is_ancestor,
    sibling_scope,
)


def test_parsing_and_rendering_round_trip_a_nested_scope() -> None:
    segments = parse_scope_path("root.build.iteration_2.verify.check")

    assert segments == (
        ScopeSegment("build"),
        ScopeSegment("iteration_2"),
        ScopeSegment("verify"),
        ScopeSegment("check"),
    )
    assert render_scope_path(segments) == "root.build.iteration_2.verify.check"


@pytest.mark.parametrize(
    "path",
    ["build", "root", "node.build", "root.build#0", "root.build#x", "root.1Build", "root.b#"],
)
def test_an_invalid_scope_path_is_rejected(path: str) -> None:
    with pytest.raises(WorkflowValidationError):
        parse_scope_path(path)


def test_rendering_requires_a_segment() -> None:
    with pytest.raises(WorkflowValidationError):
        render_scope_path(())


@pytest.mark.parametrize(
    ("parent", "node_id", "expected"),
    [
        (None, "build", "root.build"),
        ("root", "build", "root.build"),
        ("root.loop.iteration_1", "check", "root.loop.iteration_1.check"),
    ],
)
def test_a_node_scope_appends_to_its_parent(
    parent: str | None, node_id: str, expected: str
) -> None:
    assert node_scope(parent, node_id) == expected


def test_scopes_reject_an_invalid_node_id() -> None:
    with pytest.raises(WorkflowValidationError):
        node_scope(None, "1Bad")


def test_a_sibling_scope_replaces_the_last_segment() -> None:
    assert (
        sibling_scope("root.loop.iteration_2.verify.check", "format")
        == "root.loop.iteration_2.verify.format"
    )


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("root.build", None),
        ("root.loop.iteration_2", "root.loop"),
        ("root.loop.iteration_2.check", "root.loop.iteration_2"),
    ],
)
def test_the_enclosing_scope_drops_the_last_segment(path: str, expected: str | None) -> None:
    assert enclosing_scope(path) == expected


@pytest.mark.parametrize(
    ("ancestor", "descendant", "expected"),
    [
        ("root.build", "root.build.iteration_2.check", True),
        ("root.build.iteration_2", "root.build.iteration_2.check", True),
        ("root.build.iteration_1", "root.build.iteration_2.check", False),
        ("root.other", "root.build.iteration_2.check", False),
        ("root.build.iteration_2.check", "root.build", False),
    ],
)
def test_scope_ancestry_matches_concrete_iterations(
    ancestor: str, descendant: str, expected: bool
) -> None:
    assert scope_is_ancestor(ancestor, descendant) is expected
