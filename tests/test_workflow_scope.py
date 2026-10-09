"""Runtime scope paths: parsing, rendering, siblings, and ancestry."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial

import pytest

from relay.errors import WorkflowValidationError
from relay.workflows.scope import (
    ScopeSegment,
    enclosing_scope,
    loop_iteration_scope,
    node_scope,
    parse_scope_path,
    render_scope_path,
    scope_is_ancestor,
    sibling_scope,
)


def test_parsing_and_rendering_round_trip_a_nested_scope() -> None:
    segments = parse_scope_path("root.build#2.verify.check")

    assert segments == (ScopeSegment("build", 2), ScopeSegment("verify"), ScopeSegment("check"))
    assert render_scope_path(segments) == "root.build#2.verify.check"


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
        ("root.loop#1", "check", "root.loop#1.check"),
    ],
)
def test_a_node_scope_appends_to_its_parent(
    parent: str | None, node_id: str, expected: str
) -> None:
    assert node_scope(parent, node_id) == expected


@pytest.mark.parametrize(
    ("parent", "node_id", "iteration", "expected"),
    [
        (None, "loop", 2, "root.loop#2"),
        ("root.outer#1", "inner", 1, "root.outer#1.inner#1"),
    ],
)
def test_a_loop_iteration_scope_appends_its_one_based_index(
    parent: str | None, node_id: str, iteration: int, expected: str
) -> None:
    assert loop_iteration_scope(parent, node_id, iteration) == expected


@pytest.mark.parametrize(
    "build",
    [partial(loop_iteration_scope, None, "loop", 0), partial(node_scope, None, "1Bad")],
)
def test_scopes_reject_a_zero_iteration_or_an_invalid_node_id(build: Callable[[], str]) -> None:
    with pytest.raises(WorkflowValidationError):
        build()


def test_a_sibling_scope_replaces_the_last_segment() -> None:
    assert sibling_scope("root.loop#2.verify.check", "format") == "root.loop#2.verify.format"


@pytest.mark.parametrize(
    ("path", "expected"),
    [("root.build", None), ("root.loop#2", "root"), ("root.loop#2.check", "root.loop#2")],
)
def test_the_enclosing_scope_drops_the_last_segment(path: str, expected: str | None) -> None:
    assert enclosing_scope(path) == expected


@pytest.mark.parametrize(
    ("ancestor", "descendant", "expected"),
    [
        ("root.build", "root.build#2.check", True),
        ("root.build#2", "root.build#2.check", True),
        ("root.build#1", "root.build#2.check", False),
        ("root.other", "root.build#2.check", False),
        ("root.build#2.check", "root.build", False),
    ],
)
def test_scope_ancestry_matches_concrete_iterations(
    ancestor: str, descendant: str, expected: bool
) -> None:
    assert scope_is_ancestor(ancestor, descendant) is expected
