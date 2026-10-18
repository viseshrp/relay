"""Versioned builtins execute through durable attempts and real job state."""

from collections.abc import Callable
import json
from pathlib import Path
import re
import sys
from typing import Any

import pytest
from ruamel.yaml import YAML

from relay.execution.nodes import node_executors
from relay.web.models import NodeRun, Run, RunEvent
from relay.workflows.actions import builtins
from relay.workflows.actions.builtins import (
    BUILTIN_ACTIONS,
    builtin,
    builtin_references,
    current_builtin,
    is_builtin,
    parse_builtin,
)
from tests.support import InlineEngine, RelayProject, answer_wait

ROOT = Path(__file__).resolve().parents[1]

# The input contracts every built-in accepted before the registry existed.
CONTRACTS: dict[str, tuple[set[str], set[str]]] = {
    "relay/agent@v1": (
        {
            "agent",
            "agents",
            "model",
            "effort",
            "prompt-files",
            "prompt",
            "report",
            "selector",
            "format",
            "field",
            "label",
            "auto-retry",
            "retry-limit",
        },
        set(),
    ),
    "relay/command@v1": ({"argv", "command"}, set()),
    "relay/human-wait@v1": ({"prompt", "timeout-minutes", "options"}, {"prompt"}),
    "relay/loop@v1": (
        {"workflow", "inputs", "max-iterations", "until-output", "equals"},
        {"workflow", "max-iterations"},
    ),
    "relay/validate-report@v1": ({"path", "report", "selector", "format", "field", "label"}, set()),
    "relay/validate-input@v1": ({"value", "type", "constraints"}, {"value", "type"}),
    "relay/upload-artifact@v1": ({"name", "path", "retention-days"}, {"path"}),
    "relay/download-artifact@v1": ({"name", "path", "run-id"}, {"name"}),
    "relay/cache@v1": ({"key", "path", "restore-keys"}, {"key", "path"}),
    "relay/restore-cache@v1": ({"key", "path", "restore-keys"}, {"key", "path"}),
    "relay/save-cache@v1": ({"key", "path"}, {"key", "path"}),
}


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


def test_registry_holds_one_current_version_per_action() -> None:
    references = [action.reference for action in BUILTIN_ACTIONS]
    assert references == list(CONTRACTS)
    assert len(set(references)) == len(references) == 11
    for name in {action.name for action in BUILTIN_ACTIONS}:
        current = [a for a in BUILTIN_ACTIONS if a.name == name and a.status == "current"]
        assert len(current) == 1, name
    for action in BUILTIN_ACTIONS:
        allowed, required = CONTRACTS[action.reference]
        assert (set(action.allowed), set(action.required)) == (allowed, required)


@pytest.mark.parametrize(
    "call,expected",
    [
        pytest.param(lambda: builtin("relay/agent@v1").name, "agent", id="builtin-agent"),
        pytest.param(lambda: builtin("relay/agent@v9"), None, id="builtin-unregistered"),
        pytest.param(lambda: builtin(None), None, id="builtin-none"),
        pytest.param(
            lambda: parse_builtin("relay/save-cache@v1"), ("save-cache", 1), id="parse-save-cache"
        ),
        pytest.param(lambda: parse_builtin("relay/agent@v0"), None, id="parse-major-zero"),
        pytest.param(lambda: parse_builtin("relay/agent"), None, id="parse-no-version"),
        pytest.param(lambda: parse_builtin("./.relay/actions/agent"), None, id="parse-local"),
        pytest.param(lambda: is_builtin("relay/agent@v9", "agent"), True, id="is-unregistered"),
        pytest.param(lambda: is_builtin("relay/agent@v1", "loop"), False, id="is-other-name"),
        pytest.param(lambda: is_builtin(None, "agent"), False, id="is-none"),
        pytest.param(
            lambda: builtin_references("agent"), ("relay/agent@v1",), id="references-agent"
        ),
        pytest.param(lambda: current_builtin("loop").reference, "relay/loop@v1", id="current-loop"),
        pytest.param(lambda: current_builtin("missing"), KeyError, id="current-missing"),
    ],
)
def test_builtin_reference_helpers(call: Callable[[], object], expected: object) -> None:
    if expected is KeyError:
        with pytest.raises(KeyError):
            call()
    else:
        assert call() == expected


def test_no_builtin_reference_is_spelled_outside_the_registry() -> None:
    spelled = re.compile(r"@v[0-9]")
    registry = ROOT / "relay" / "workflows" / "actions" / "builtins.py"
    sources = [path for path in (ROOT / "relay").rglob("*.py") if path != registry]
    sources += [
        path for pattern in ("*.ts", "*.tsx") for path in (ROOT / "frontend" / "src").rglob(pattern)
    ]
    found = [
        f"{path.relative_to(ROOT).as_posix()}:{number}: {line.strip()}"
        for path in sorted(sources)
        for number, line in enumerate(path.read_text("utf-8").splitlines(), 1)
        if spelled.search(line)
    ]
    assert not found, "Name built-in actions through the registry:\n" + "\n".join(found)


def test_an_unregistered_version_never_runs(
    project: RelayProject, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "ran"
    argv = [sys.executable, "-c", f"open({str(marker)!r}, 'w').close()"]
    project.write_workflow(
        "unregistered",
        f"""on: workflow_dispatch
jobs:
  main:
    steps:
      - uses: relay/human-wait@v1
        with:
          prompt: Go?
      - id: touch
        uses: relay/command@v1
        with:
          argv: {json.dumps(json.dumps(argv))}
""",
    )
    engine = InlineEngine(node_executors(), tmp_path / "artifacts")
    run_id = engine.launch(project, "unregistered")
    engine.drain(run_id)
    monkeypatch.delitem(builtins._BY_REFERENCE, "relay/command@v1")
    answer_wait(engine, run_id)
    step = NodeRun.objects.get(run_id=run_id, scope_path="root.main.touch")
    assert step.status == "failed"
    assert Run.objects.get(pk=run_id).status == "failed"
    events = json.dumps(
        list(RunEvent.objects.filter(run_id=run_id).values_list("payload", flat=True))
    )
    assert "relay/command@v1 is not included in this Relay version." in events
    assert not marker.exists()
