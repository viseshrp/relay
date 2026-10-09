"""Versioned builtins execute through durable attempts and real job state."""

import json
from pathlib import Path
from typing import Any

import pytest
from ruamel.yaml import YAML

from relay.execution.nodes import node_executors
from relay.web.models import NodeRun, Run, RunEvent
from tests.support import InlineEngine, RelayProject


def workflow(
    project: RelayProject, steps: list[dict[str, Any]], tmp_path: Path
) -> tuple[str, InlineEngine]:
    from io import StringIO

    value = {"jobs": {"main": {"steps": steps}}}
    stream = StringIO()
    YAML().dump(value, stream)
    project.write_workflow("builtins", stream.getvalue())
    engine = InlineEngine(node_executors(), tmp_path / "artifacts")
    run_id = engine.launch(project, "builtins")
    engine.drain(run_id)
    return run_id, engine


@pytest.mark.parametrize(
    "reference,inputs,reason",
    [
        ("relay/command@v1", {"argv": "not JSON"}, "JSON argument vector"),
        ("relay/command@v1", {"argv": "[]"}, "configured named command"),
        ("relay/command@v1", {"argv": '["git", 1]'}, "configured named command"),
        ("relay/command@v1", {"command": "${{ 'unconfigured' }}"}, "configured named command"),
        ("relay/human-wait@v1", {"prompt": "Continue?", "timeout-minutes": "0"}, "360 minutes"),
        ("relay/human-wait@v1", {"prompt": "Continue?", "timeout-minutes": "361"}, "360 minutes"),
        (
            "relay/validate-input@v1",
            {"value": "ready", "type": "invalid"},
            "constraint declaration",
        ),
        (
            "relay/validate-input@v1",
            {"value": "ready", "type": "string", "constraints": "invalid"},
            "constraint declaration",
        ),
        ("relay/validate-report@v1", {"selector": "invalid"}, "valid JSON"),
        (
            "relay/validate-report@v1",
            {"selector": '{"unsupported": "value"}'},
            "selector is invalid",
        ),
    ],
)
def test_builtin_runtime_errors_settle_the_step_and_keep_failure_evidence(
    project: RelayProject, tmp_path: Path, reference: str, inputs: dict[str, str], reason: str
) -> None:
    run_id, _ = workflow(project, [{"id": "check", "uses": reference, "with": inputs}], tmp_path)
    step = NodeRun.objects.get(run_id=run_id, scope_path="root.main.check")
    assert step.status == "failed" and step.outcome == "failure"
    assert Run.objects.get(pk=run_id).status == "failed"
    events = json.dumps(
        list(RunEvent.objects.filter(run_id=run_id).values_list("payload", flat=True))
    )
    assert reason in events


@pytest.mark.parametrize(
    "kind,value,constraints",
    [
        ("string", "ready", {"min_length": 3}),
        ("integer", "3", {"min": 2, "max": 4}),
        ("number", "0.5", {"min": 0, "max": 1}),
        ("boolean", "true", {}),
        ("enum", '"safe"', {"values": ["safe", "thorough"]}),
    ],
)
def test_validate_input_emits_typed_validation_without_changing_report_bytes(
    project: RelayProject, tmp_path: Path, kind: str, value: str, constraints: dict[str, Any]
) -> None:
    run_id, _ = workflow(
        project,
        [
            {
                "id": "check",
                "uses": "relay/validate-input@v1",
                "with": {"type": kind, "value": value, "constraints": json.dumps(constraints)},
            }
        ],
        tmp_path,
    )
    assert Run.objects.get(pk=run_id).status == "succeeded"
    assert NodeRun.objects.get(run_id=run_id, scope_path="root.main.check").outputs == {
        "value": value,
        "valid": "true",
    }


@pytest.mark.parametrize(
    "format_name,contents,extra,expected",
    [
        ("label", "Ready: yes\n", {"label": "Ready"}, "yes"),
        ("json", '{"nested": {"value": 42}}', {"field": "nested.value"}, "42"),
        ("yaml", "nested: {value: accepted}\n", {"field": "nested.value"}, "accepted"),
        ("exists", "bytes", {}, "true"),
    ],
)
def test_report_formats_retain_handoffs_except_exists(
    project: RelayProject,
    tmp_path: Path,
    format_name: str,
    contents: str,
    extra: dict[str, str],
    expected: object,
) -> None:
    project.write("report.txt", contents)
    project.commit("Provide a disposable report")
    run_id, _ = workflow(
        project,
        [
            {
                "id": "check",
                "uses": "relay/validate-report@v1",
                "with": {"path": "report.txt", "format": format_name, **extra},
            }
        ],
        tmp_path,
    )
    assert Run.objects.get(pk=run_id).status == "succeeded"
    assert NodeRun.objects.get(run_id=run_id, scope_path="root.main.check").outputs == {
        "value": expected
    }


def test_exists_missing_report_returns_false_without_failing(
    project: RelayProject, tmp_path: Path
) -> None:
    run_id, _ = workflow(
        project,
        [
            {
                "id": "check",
                "uses": "relay/validate-report@v1",
                "with": {"path": "missing.txt", "format": "exists"},
            }
        ],
        tmp_path,
    )
    assert Run.objects.get(pk=run_id).status == "succeeded"
    assert NodeRun.objects.get(run_id=run_id, scope_path="root.main.check").outputs == {
        "value": "false"
    }


@pytest.mark.parametrize(
    "until,equals,status,iterations",
    [
        ("", "true", "succeeded", 1),
        ("answer", "yes", "succeeded", 1),
        ("answer", "no", "failed", 2),
    ],
)
def test_loop_terminates_on_declared_output_or_exhausts_its_bound(
    project: RelayProject, tmp_path: Path, until: str, equals: str, status: str, iterations: int
) -> None:
    project.write_workflow(
        "child",
        "jobs: {main: {outputs: {answer: yes}, "
        "steps: [{uses: relay/validate-input@v1, with: {value: ready, type: string}}]}}\n"
        "on: {workflow_call: {outputs: {answer: {value: '${{ jobs.main.outputs.answer }}'}}}}\n",
    )
    inputs = {"workflow": "./.relay/workflows/child.yaml", "max-iterations": "2", "equals": equals}
    if until:
        inputs["until-output"] = until
    run_id, _ = workflow(
        project, [{"id": "repeat", "uses": "relay/loop@v1", "with": inputs}], tmp_path
    )
    assert Run.objects.get(pk=run_id).status == status
    scopes = list(
        NodeRun.objects.filter(
            run_id=run_id, node_type="actions_job", parent_scope_path="root.main.repeat"
        ).values_list("scope_path", flat=True)
    )
    assert len(scopes) == iterations
