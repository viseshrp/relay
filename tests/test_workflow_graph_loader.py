"""Graph compilation and YAML loading, including subworkflow trees and keys."""

from __future__ import annotations

from pathlib import Path

import pytest

from relay.errors import SchemaVersionError, WorkflowValidationError
from relay.workflows.graph import compile_graph
from relay.workflows.loader import (
    load_workflow,
    load_workflow_text,
    load_workflow_tree,
    resolve_workflow_path,
    subworkflow_nodes,
    workflow_key_parts,
)
from relay.workflows.schema import NodeDefinition
from tests.support import symlink_or_skip


def _nodes(text: str) -> dict[str, NodeDefinition]:
    return dict(load_workflow_text(f"version: 1\nname: Graph\nnodes:\n{text}").definition.nodes)


def _write(root: Path, name: str, text: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_compile_graph_indexes_data_and_control_edges() -> None:
    nodes = _nodes(
        """  build:
    type: command
    run: [git, status]
  choose:
    type: condition
    needs: [build]
    expr: "${{ True }}"
    branches: {"yes": ship, "no": stop}
  ship:
    type: command
    needs: [choose]
    run: [git, log]
  stop:
    type: command
    needs: [choose]
    run: [git, log]
  repeat:
    type: loop
    max_iterations: 2
    until: "${{ loop.index >= 2 }}"
    exhausted: stop
    body:
      inner:
        type: command
        run: [git, status]
"""
    )

    graph = compile_graph(nodes)

    assert graph.topological_order.index("build") < graph.topological_order.index("choose")
    assert graph.downstream["build"] == ("choose",)
    assert graph.dependencies["ship"] == ("choose",)
    assert set(graph.control_downstream["choose"]) == {"ship", "stop"}
    assert graph.activators["stop"] == ("choose", "repeat")
    assert graph.loop_bodies["repeat"].topological_order == ("inner",)


def test_a_branch_back_to_an_upstream_node_is_a_cycle() -> None:
    nodes = _nodes(
        """  build:
    type: command
    run: [git, status]
  choose:
    type: condition
    needs: [build]
    expr: "${{ True }}"
    branches: {"retry": build}
"""
    )

    with pytest.raises(WorkflowValidationError):
        compile_graph(nodes)


@pytest.mark.parametrize(
    "body",
    [
        "  a:\n    type: command\n    needs: [missing]\n    run: [x]\n",
        "  a:\n    type: command\n    run: [x]\n    on_timeout: b\n"
        "  b:\n    type: command\n    run: [x]\n",
        '  a:\n    type: condition\n    expr: "${{ True }}"\n    branches: {x: nowhere}\n',
        "  a:\n    type: command\n    needs: [b]\n    run: [x]\n"
        "  b:\n    type: command\n    needs: [a]\n    run: [x]\n",
        '  a:\n    type: command\n    run: [x]\n    if: "${{ open() }}"\n',
        "  a:\n    type: loop\n    max_iterations: 1\n    exhausted: a\n    until: bad\n"
        "    body:\n      i:\n        type: command\n        needs: [z]\n        run: [x]\n",
    ],
)
def test_an_invalid_graph_is_rejected(body: str) -> None:
    with pytest.raises(WorkflowValidationError):
        compile_graph(_nodes(body))


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ("version: [", WorkflowValidationError),
        ("- a\n- b\n", WorkflowValidationError),
        ("version: 2\nname: x\nnodes: {}\n", SchemaVersionError),
        ("version: 1\nnodes: {}\n", WorkflowValidationError),
        ("version: 1\nname: a\nname: b\nnodes: {}\n", WorkflowValidationError),
    ],
)
def test_an_invalid_document_is_rejected(text: str, error: type[Exception]) -> None:
    with pytest.raises(error):
        load_workflow_text(text)


def test_a_workflow_file_is_read_as_utf8(tmp_path: Path) -> None:
    path = _write(tmp_path, "workflow.yaml", "version: 1\nname: Ünïcode\nnodes: {}\n")

    assert load_workflow(path).definition.name == "Ünïcode"


def test_a_file_that_is_not_utf8_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yaml"
    path.write_bytes(b"\xff\xfe")

    with pytest.raises(WorkflowValidationError):
        load_workflow(path)


@pytest.mark.parametrize(
    ("key", "parts"),
    [
        ("review", ("review.yaml",)),
        ("nested/review.yml", ("nested", "review.yml")),
        ("nested/review.yaml", ("nested", "review.yaml")),
    ],
)
def test_a_workflow_key_maps_to_a_relative_yaml_path(key: str, parts: tuple[str, ...]) -> None:
    assert workflow_key_parts(key) == parts


@pytest.mark.parametrize("key", ["", "nested\\review", "../x", "a//b", "./a", "notes.txt"])
def test_an_invalid_workflow_key_is_rejected_on_every_platform(key: str) -> None:
    with pytest.raises(WorkflowValidationError):
        workflow_key_parts(key)


def test_subworkflow_references_include_those_inside_loops() -> None:
    nodes = _nodes(
        "  one:\n    type: subworkflow\n    workflow: child\n"
        "  loop:\n    type: loop\n    max_iterations: 1\n    exhausted: one\n"
        "    body:\n      two:\n        type: subworkflow\n        workflow: nested/child.yml\n"
    )

    assert [node.workflow for node in subworkflow_nodes(nodes)] == ["child", "nested/child.yml"]


def test_a_tree_loads_each_child_once(tmp_path: Path) -> None:
    workflows = tmp_path / "workflows"
    root_path = _write(
        workflows,
        "root.yaml",
        "version: 1\nname: Root\nnodes:\n"
        "  one:\n    type: subworkflow\n    workflow: child\n"
        "  two:\n    type: subworkflow\n    workflow: child\n"
        "  three:\n    type: subworkflow\n    workflow: nested/child.yml\n",
    )
    _write(workflows, "child.yaml", "version: 1\nname: Child\nnodes: {}\n")
    _write(workflows, "nested/child.yml", "version: 1\nname: Nested\nnodes: {}\n")

    tree = load_workflow_tree(load_workflow(root_path), workflows)

    assert sorted(tree) == ["child.yaml", "nested/child.yml"]


def test_a_recursive_subworkflow_reference_is_rejected(tmp_path: Path) -> None:
    workflows = tmp_path / "workflows"
    root_path = _write(
        workflows,
        "root.yaml",
        "version: 1\nname: Root\nnodes:\n  one:\n    type: subworkflow\n    workflow: child\n",
    )
    _write(
        workflows,
        "child.yaml",
        "version: 1\nname: Child\nnodes:\n  back:\n    type: subworkflow\n    workflow: root\n",
    )

    with pytest.raises(WorkflowValidationError):
        load_workflow_tree(load_workflow(root_path), workflows)


def test_a_missing_subworkflow_is_rejected(tmp_path: Path) -> None:
    workflows = tmp_path / "workflows"
    root_path = _write(
        workflows,
        "root.yaml",
        "version: 1\nname: Root\nnodes:\n  one:\n    type: subworkflow\n    workflow: absent\n",
    )

    with pytest.raises(WorkflowValidationError):
        load_workflow_tree(load_workflow(root_path), workflows)


def test_a_subworkflow_link_outside_the_workflow_root_is_rejected(tmp_path: Path) -> None:
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    outside = _write(tmp_path, "outside.yaml", "version: 1\nname: Out\nnodes: {}\n")
    symlink_or_skip(workflows / "link.yaml", outside)

    with pytest.raises(WorkflowValidationError):
        resolve_workflow_path(workflows, "link")


def test_a_yaml_key_that_resolves_to_another_suffix_is_rejected(tmp_path: Path) -> None:
    workflows = tmp_path / "workflows"
    notes = _write(workflows, "notes.txt", "not a workflow")
    symlink_or_skip(workflows / "alias.yaml", notes)

    with pytest.raises(WorkflowValidationError):
        resolve_workflow_path(workflows, "alias")
