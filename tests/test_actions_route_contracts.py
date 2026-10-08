"""Agent routes freeze only launch-static values and exact provider choices."""

from typing import Any

import pytest

from relay.errors import WorkflowValidationError
from relay.workflows.actions.compiler import bind_agent, definition, validate_commands
from relay.workflows.actions.language import load


@pytest.mark.parametrize(
    "field,expression,context,reason",
    [
        ("model", "${{ steps.previous.outputs.model }}", {}, "launch-static"),
        ("model", "${{ secrets.MODEL }}", {}, "launch-static"),
        (
            "agent",
            "${{ inputs.route }}",
            {"inputs": {"route": "codex"}, "_dynamic_inputs": {"route"}},
            "Runtime-derived",
        ),
        (
            "agent",
            "${{ matrix.route }}",
            {"matrix": {"route": "codex"}, "_dynamic_matrix": True},
            "dynamic matrix",
        ),
        ("agents", "${{ true }}", {}, "JSON list"),
        ("agents", '["codex", 1]', {}, "JSON list"),
        ("model", "${{ true }}", {}, "nonempty model"),
        ("model", "", {}, "nonempty model"),
        ("effort", "${{ 3 }}", {}, "provider value"),
    ],
)
def test_invalid_or_runtime_derived_agent_routes_fail_before_selection(
    field: str, expression: str, context: dict[str, Any], reason: str
) -> None:
    with pytest.raises(WorkflowValidationError, match=reason):
        bind_agent({"with": {field: expression}}, context)


def test_static_inputs_can_route_even_when_other_inputs_are_dynamic() -> None:
    route = bind_agent(
        {
            "with": {
                "agent": "${{ inputs.provider }}",
                "model": "${{ vars.MODEL }}",
                "effort": "high",
                "prompt-files": ".relay/prompts/local.md\n\nglobal:common.md",
                "auto-retry": "false",
            }
        },
        {
            "inputs": {"provider": "codex"},
            "vars": {"MODEL": "ExactModel"},
            "_dynamic_inputs": {"runtime"},
        },
    )
    assert route.agents == ["codex"] and route.model == "ExactModel"
    assert route.agent_options["codex"].effort == "high"
    assert not route.auto_retry
    assert [item.model_dump(mode="json", by_alias=True) for item in route.prompts] == [
        {"local": "prompts/local.md"},
        {"global": "common.md"},
    ]
    assert bind_agent({"with": {"agent": ""}}, {}).agents == []


def test_input_compilation_preserves_public_types_defaults_and_topological_order() -> None:
    compiled = definition(
        load("""on:
  workflow_dispatch:
    inputs:
      flag: {type: boolean, default: true}
      count: {type: number, default: 2}
      mode: {type: choice, options: [a, b], default: a}
      target: {type: environment}
jobs:
  second: {needs: first, runs-on: self-hosted, steps: [{run: echo second}]}
  first: {runs-on: self-hosted, timeout-minutes: 1.5, steps: [{run: echo first}]}
""")
    )
    assert list(compiled.nodes) == ["first", "second"]
    assert compiled.nodes["first"].timeout == "90000ms"
    assert {key: item.type for key, item in compiled.inputs.items()} == {
        "flag": "boolean",
        "count": "number",
        "mode": "enum",
        "target": "string",
    }
    assert compiled.inputs["flag"].default is True


@pytest.mark.parametrize("timeout", [361, "12", True])
def test_invalid_literal_job_deadlines_reject_compilation(timeout: object) -> None:
    document = load("jobs: {main: {runs-on: self-hosted, steps: [{run: echo}]}}")
    document.value["jobs"]["main"]["timeout-minutes"] = timeout
    with pytest.raises(WorkflowValidationError, match="at most 360"):
        definition(document)


def test_command_preflight_traverses_reusable_and_composite_sources() -> None:
    sources = {
        ".relay/workflows/child.yaml": (
            "jobs: {main: {runs-on: self-hosted, "
            "steps: [{uses: relay/command@v1, with: {command: checked}}]}}"
        ),
        ".relay/actions/local/action.yaml": (
            "name: Local\ndescription: Preflight\n"
            "runs: {using: composite, steps: [{uses: relay/command@v1, "
            "with: {command: nested}}]}"
        ),
    }
    with pytest.raises(WorkflowValidationError, match="nested"):
        validate_commands({"jobs": {}}, sources, {"checked": ["git", "status"]})
    validate_commands(
        {"jobs": {}}, sources, {"checked": ["git", "status"], "nested": ["git", "log"]}
    )
