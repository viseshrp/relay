"""Cross-file validation, typed launch inputs, prompts, routes, and snapshots."""

from __future__ import annotations

from pathlib import Path

import pytest

from relay import paths
from relay.errors import PromptResolutionError, WorkflowValidationError
from relay.workflows.loader import load_workflow, load_workflow_text
from relay.workflows.prompts import resolve_prompt
from relay.workflows.routing import (
    RouteEntry,
    RouteRequirement,
    compile_route_requirements,
    effective_agent_order,
    serialize_route_table,
)
from relay.workflows.schema import GlobalPrompt, LocalPrompt, WorkflowDefinition
from relay.workflows.snapshot import build_snapshot
from relay.workflows.validation import (
    ValidatedWorkflow,
    resolve_inputs,
    validate_loaded_workflow,
)
from tests.support import symlink_or_skip


def _relay_root(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / ".relay"
    (root / "workflows").mkdir(parents=True)
    (root / "prompts").mkdir()
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def _validate(root: Path, key: str = "workflows/main.yaml") -> ValidatedWorkflow:
    return validate_loaded_workflow(load_workflow(root / key), root)


def _inputs_definition() -> WorkflowDefinition:
    return load_workflow_text(
        "version: 1\nname: Inputs\nnodes: {}\ninputs:\n"
        "  name: {type: string, required: true, constraints: {min_length: 2, max_length: 4, "
        "pattern: '^[a-z]+$'}}\n"
        "  count: {type: integer, default: 2, constraints: {min: 1, max: 3}}\n"
        "  ratio: {type: number, constraints: {min: 0.5, max: 1.5}}\n"
        "  flag: {type: boolean}\n"
        "  mode: {type: enum, default: a, constraints: {values: [a, b]}}\n"
        "  note: {type: string}\n"
    ).definition


ROUTED_TREE: dict[str, str] = {
    "workflows/main.yaml": (
        "version: 1\nname: Main\nmodel: base\nagents: [cursor, claude]\nnodes:\n"
        "  review:\n    type: agent\n    agents: [codex, cursor]\n"
        "    permission_profile: auto_approve\n"
        "  repeat:\n    type: loop\n    max_iterations: 2\n    exhausted: review\n"
        "    body:\n      fix:\n        type: agent\n        model: special\n"
        "  child:\n    type: subworkflow\n    workflow: child\n"
    ),
    "workflows/child.yaml": (
        "version: 1\nname: Child\nmodel: cm\nagents: [copilot]\nnodes:\n  deep: {type: agent}\n"
    ),
}


def test_a_valid_tree_resolves_its_prompts_children_and_graphs(tmp_path: Path) -> None:
    (paths.global_prompts_dir(create=True) / "shared.md").write_text("global", encoding="utf-8")
    root = _relay_root(
        tmp_path,
        {
            "prompts/review.md": "local",
            "workflows/main.yaml": (
                "version: 1\nname: Main\nmodel: m1\nagents: [codex]\nnodes:\n"
                "  review:\n    type: agent\n    prompts:\n"
                "      - local: prompts/review.md\n      - global: shared.md\n"
                "  child:\n    type: subworkflow\n    workflow: child\n"
                "    inputs: {target: relay}\n    outputs: {ready: check.ready}\n"
            ),
            "workflows/child.yaml": (
                "version: 1\nname: Child\ninputs:\n  target: {type: string, required: true}\n"
                "nodes:\n  check:\n    type: command\n    run: [git, status]\n"
                "    outputs:\n      ready: {exists: report.md}\n"
            ),
        },
    )

    validated = _validate(root)

    assert [prompt.content for prompt in validated.prompts] == ["local", "global"]
    assert validated.subworkflow_graphs["child.yaml"].topological_order == ("check",)
    assert validated.graph.topological_order == ("review", "child")


def test_independent_issues_are_reported_together(tmp_path: Path) -> None:
    root = _relay_root(
        tmp_path,
        {
            "workflows/main.yaml": (
                "version: 1\nname: Main\ninputs:\n"
                "  slug: {type: string, constraints: {pattern: '(?=x)'}}\n"
                "entrypoints:\n  - scope_path: root.\n  - scope_path: ghost\n"
                "    inputs: [nothing]\n"
                "nodes:\n"
                "  review:\n    type: agent\n    prompts: [{local: prompts/missing.md}]\n"
                "  child:\n    type: subworkflow\n    workflow: child\n"
                "    inputs: {extra: 1}\n    outputs: {ready: check.absent}\n"
                "  loop_a:\n    type: command\n    needs: [loop_b]\n    run: [x]\n"
                "  loop_b:\n    type: command\n    needs: [loop_a]\n    run: [x]\n"
            ),
            "workflows/child.yaml": (
                "version: 1\nname: Child\ninputs:\n  target: {type: string, required: true}\n"
                "nodes:\n  check:\n    type: command\n    needs: [nope]\n    run: [x]\n"
            ),
        },
    )

    with pytest.raises(WorkflowValidationError) as caught:
        _validate(root)

    for defect in (
        "RE2-compatible",
        "Scope node id",
        "unknown node 'ghost'",
        "unknown input 'nothing'",
        "dependency cycle detected at root",
        "unknown node 'nope'",
        "unknown input 'extra'",
        "requires input 'target'",
        "unknown child output 'check.absent'",
        "prompts/missing.md",
    ):
        assert defect in caught.value.message


def test_the_expansion_limit_counts_nested_loops_and_children(tmp_path: Path) -> None:
    root = _relay_root(
        tmp_path,
        {
            "workflows/main.yaml": (
                "version: 1\nname: Main\nnodes:\n"
                "  outer:\n    type: loop\n    max_iterations: 100\n    exhausted: done\n"
                "    body:\n      inner:\n        type: loop\n        max_iterations: 100\n"
                "        exhausted: step\n        body:\n"
                "          call:\n            type: subworkflow\n            workflow: child\n"
                "      step:\n        type: command\n        run: [x]\n"
                "  done:\n    type: command\n    needs: [outer]\n    run: [x]\n"
            ),
            "workflows/child.yaml": (
                "version: 1\nname: Child\nnodes:\n  a: {type: command, run: [x]}\n"
            ),
        },
    )

    with pytest.raises(WorkflowValidationError):
        _validate(root)


def test_launch_inputs_receive_defaults_without_coercion() -> None:
    resolved = resolve_inputs(_inputs_definition(), {"name": "abc", "ratio": 1, "flag": False})

    assert resolved == {
        "name": "abc",
        "count": 2,
        "ratio": 1,
        "flag": False,
        "mode": "a",
        "note": None,
    }


@pytest.mark.parametrize(
    "supplied",
    [
        {},
        {"name": "abc", "bogus": 1},
        {"name": 5},
        {"name": "a"},
        {"name": "abcdef"},
        {"name": "AB1"},
        {"name": "abc", "count": "2"},
        {"name": "abc", "count": True},
        {"name": "abc", "count": 0},
        {"name": "abc", "count": 4},
        {"name": "abc", "ratio": "1"},
        {"name": "abc", "flag": 1},
        {"name": "abc", "mode": "c"},
    ],
)
def test_an_invalid_launch_input_is_rejected(supplied: dict[str, object]) -> None:
    with pytest.raises(WorkflowValidationError):
        resolve_inputs(_inputs_definition(), supplied)


def test_a_local_prompt_resolves_to_its_text_and_digest(tmp_path: Path) -> None:
    root = _relay_root(tmp_path, {"prompts/a.md": "text"})

    resolved = resolve_prompt(LocalPrompt(local="prompts/a.md"), root)

    assert resolved.to_dict()["content"] == "text"
    assert resolved.sha256 == "982d9e3eb996f559e633f4d194def3761d909f5a3b647d1a851fead67c32c9d1"


@pytest.mark.parametrize(
    "reference",
    [
        LocalPrompt(local="../outside.md"),
        GlobalPrompt.model_validate({"global": "none.md"}),
        LocalPrompt(local="prompts/bad.md"),
    ],
)
def test_an_unsafe_missing_or_unreadable_prompt_is_rejected(
    tmp_path: Path, reference: LocalPrompt | GlobalPrompt
) -> None:
    root = _relay_root(tmp_path, {})
    (root / "prompts" / "bad.md").write_bytes(b"\xff\xfe")

    with pytest.raises(PromptResolutionError):
        resolve_prompt(reference, root)


def test_a_prompt_link_outside_the_relay_root_is_rejected(tmp_path: Path) -> None:
    root = _relay_root(tmp_path, {})
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    symlink_or_skip(root / "prompts" / "link.md", outside)

    with pytest.raises(PromptResolutionError):
        resolve_prompt(LocalPrompt(local="prompts/link.md"), root)


def test_routes_cover_loop_iterations_and_children(tmp_path: Path) -> None:
    validated = _validate(_relay_root(tmp_path, ROUTED_TREE))

    routes = compile_route_requirements(validated, owner_agents=["codex", "copilot"])

    assert {
        route.scope_path: (route.model_value, route.effective_agent_order) for route in routes
    } == {
        "root.review": ("base", ("codex", "cursor", "claude", "copilot")),
        "root.repeat#1.fix": ("special", ("cursor", "claude", "codex", "copilot")),
        "root.repeat#2.fix": ("special", ("cursor", "claude", "codex", "copilot")),
        "root.child.deep": ("cm", ("copilot", "codex")),
    }


def test_a_route_carries_the_permission_profile_without_serializing_it(tmp_path: Path) -> None:
    validated = _validate(_relay_root(tmp_path, ROUTED_TREE))

    review = next(
        route
        for route in compile_route_requirements(validated)
        if route.scope_path == "root.review"
    )

    assert review.permission_profile == "auto_approve"
    assert "permission_profile" not in review.to_dict()


def test_a_launch_model_replaces_inherited_models_but_not_a_nodes_own(tmp_path: Path) -> None:
    validated = _validate(_relay_root(tmp_path, ROUTED_TREE))

    routes = compile_route_requirements(validated, launch_model="override")

    assert {route.scope_path: route.model_value for route in routes} == {
        "root.review": "override",
        "root.repeat#1.fix": "special",
        "root.repeat#2.fix": "special",
        "root.child.deep": "override",
    }


@pytest.mark.parametrize(
    "workflow",
    [
        "version: 1\nname: M\nagents: [codex]\nnodes:\n  a: {type: agent}\n",
        "version: 1\nname: M\nmodel: m\nnodes:\n  a: {type: agent}\n",
    ],
)
def test_an_agent_node_needs_a_model_and_a_candidate(tmp_path: Path, workflow: str) -> None:
    validated = _validate(_relay_root(tmp_path, {"workflows/main.yaml": workflow}))

    with pytest.raises(WorkflowValidationError):
        compile_route_requirements(validated)


def test_the_route_table_serializes_requirements_and_selections() -> None:
    entries = [
        RouteRequirement("root.a", "m", ("codex",)),
        RouteEntry("root.b", "m", ("codex", "cursor"), selected_agent="cursor"),
    ]

    assert serialize_route_table(entries) == {
        "root.a": {"model_value": "m", "effective_agent_order": ["codex"]},
        "root.b": {
            "model_value": "m",
            "effective_agent_order": ["codex", "cursor"],
            "selected_agent": "cursor",
        },
    }


def test_agent_order_concatenates_preferences_without_duplicates() -> None:
    assert effective_agent_order(["a", "b"], ["b", "c"], ["a"]) == ("a", "b", "c")


def test_a_snapshot_captures_exact_text_hashes_inputs_and_preferences(tmp_path: Path) -> None:
    root = _relay_root(
        tmp_path,
        {
            "prompts/a.md": "prompt",
            "workflows/main.yaml": (
                "version: 1\nname: Main\nmodel: m\nagents: [codex]\nnodes:\n"
                "  review:\n    type: agent\n    prompts: [{local: prompts/a.md}]\n"
                "  child:\n    type: subworkflow\n    workflow: child\n"
            ),
            "workflows/child.yaml": "version: 1\nname: Child\nagents: [cursor]\nnodes: {}\n",
        },
    )
    validated = _validate(root)

    data = build_snapshot(validated, typed_inputs={"x": 1}, routes=[]).to_dict()

    assert data["workflow_yaml"] == validated.root.text
    assert data["default_model"] == "m"
    assert data["typed_inputs"] == {"x": 1}
    assert "subworkflow:child.yaml" in data["hashes"]
    assert data["agent_prefs"][1] == {"workflow": "child.yaml", "agents": ["cursor"]}
