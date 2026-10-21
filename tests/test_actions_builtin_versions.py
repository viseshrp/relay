"""Two versions of one built-in run side by side, update in one click, and retire safely.

Relay ships one version of each built-in action. These tests prove the version
mechanism with a stand-in relay/command@v2 from tests.support.stand_in_versions,
so they do not depend on which action changes first.
"""

from collections.abc import Mapping
import json
from pathlib import Path
import sys

import pytest

from relay.errors import WorkflowValidationError
from relay.execution.nodes import node_executors
from relay.web.models import NodeRun, Run, RunEvent
from relay.workflows.actions.builtins import builtin, builtin_references, is_builtin
from relay.workflows.actions.language import (
    capture_sources,
    deprecated_builtin_warnings,
    load,
    support_manifest,
    workflow_diagnostics,
    workflow_warnings,
)
from relay.workflows.actions.upgrade import upgrade_builtins
from tests.support import (
    InlineEngine,
    RelayProject,
    answer_wait,
    registry_problems,
    stand_in_versions,
)

DEPRECATED = (
    "relay/command@v1 is deprecated and will be removed in a later Relay release. "
    "Use relay/command@v2."
)
REMOVED = (
    "Only frozen local and versioned relay actions are supported. "
    "relay/command@v1 was removed in Relay 0.0.0; use relay/command@v2."
)
STOPPED = (
    "relay/command@v1 was removed in Relay 0.0.0. This run started on an earlier Relay "
    "version; cancel it and launch the workflow again."
)
SOURCE = """\
on: workflow_dispatch
jobs:
  main:
    steps:
      # Print a greeting first.
      - uses: relay/command@v1
        with:
          argv: '["echo","Ready"]'  # exact arguments
      - name: Second
        uses: relay/command@v1
        with: {argv: '["echo","Done"]'}
"""


def _touch_workflow(project: RelayProject, marker: Path) -> None:
    """A workflow that waits for an answer, then runs relay/command@v1 to create marker."""
    argv = [sys.executable, "-c", f"open({str(marker)!r}, 'w').close()"]
    project.write_workflow(
        "versions",
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


def _events(run_id: str) -> str:
    return json.dumps(
        list(RunEvent.objects.filter(run_id=run_id).values_list("payload", flat=True))
    )


@pytest.mark.usefixtures("deprecated_command")
def test_a_deprecated_version_validates_with_a_warning() -> None:
    assert workflow_diagnostics(SOURCE) == []
    first, second = workflow_warnings(load(SOURCE))
    assert first.message == f"jobs.main.steps[0].uses: {DEPRECATED}"
    assert second.message == f"jobs.main.steps[1].uses: {DEPRECATED}"
    assert first.context["deprecated"] == "relay/command@v1"
    assert first.context["severity"] == "warning"
    assert workflow_warnings(load(SOURCE.replace("@v1", "@v2"))) == []


@pytest.mark.usefixtures("deprecated_command")
def test_deprecated_steps_in_action_metadata_name_their_file() -> None:
    metadata = {
        "runs": {"using": "composite", "steps": [{"run": "echo"}, {"uses": "relay/command@v1"}]}
    }
    [warning] = deprecated_builtin_warnings(metadata, ".relay/actions/x/action.yaml: ")
    assert warning.message == f".relay/actions/x/action.yaml: runs.steps[1].uses: {DEPRECATED}"
    assert "line" not in warning.context
    assert deprecated_builtin_warnings({"jobs": {"main": {"steps": "none"}}}, "") == []


@pytest.mark.usefixtures("deprecated_command")
def test_the_manifest_offers_only_the_current_version() -> None:
    manifest = support_manifest()
    assert "relay/command@v2" in manifest["builtins"]
    assert "relay/command@v1" not in manifest["builtins"]
    assert {"relay/command@v1", "relay/command@v2"} <= set(manifest["builtin_inputs"])
    versions = manifest["builtin_versions"]
    assert versions["relay/command@v1"] == {
        "name": "command",
        "major": 1,
        "status": "deprecated",
        "deprecated_in": "0.0.0",
    }
    assert versions["relay/command@v2"]["status"] == "current"
    assert versions["relay/command@v2"]["deprecated_in"] == ""
    assert registry_problems() == []


def test_a_deprecated_version_launches_and_runs(
    project: RelayProject, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "ran"
    _touch_workflow(project, marker)
    stand_in_versions(monkeypatch)
    engine = InlineEngine(node_executors(), tmp_path / "artifacts")
    run_id = engine.launch(project, "versions")
    engine.drain(run_id)
    answer_wait(engine, run_id)
    assert Run.objects.get(pk=run_id).status == "succeeded"
    assert marker.exists()


def test_a_run_paused_before_an_upgrade_finishes_on_its_version(
    project: RelayProject, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "ran"
    _touch_workflow(project, marker)
    engine = InlineEngine(node_executors(), tmp_path / "artifacts")
    run_id = engine.launch(project, "versions")
    engine.drain(run_id)
    stand_in_versions(monkeypatch)
    answer_wait(engine, run_id)
    assert Run.objects.get(pk=run_id).status == "succeeded"
    assert marker.exists()
    step = NodeRun.objects.get(run_id=run_id, scope_path="root.main.touch")
    assert step.frozen_def["step"]["uses"] == "relay/command@v1"


@pytest.mark.usefixtures("deprecated_command")
def test_upgrade_moves_deprecated_steps_and_keeps_comments() -> None:
    result = upgrade_builtins(SOURCE)
    assert result.yaml == SOURCE.replace("@v1", "@v2")
    assert result.changes == (
        "Updated step 1 in job main from relay/command@v1 to relay/command@v2.",
        "Updated step 2 in job main from relay/command@v1 to relay/command@v2.",
    )
    assert result.unresolved == ()


def _named_command(inputs: Mapping[str, object]) -> tuple[dict[str, object], tuple[str, ...]]:
    """A stand-in conversion that replaces a named command and respaces argv."""
    converted = dict(inputs)
    if "${{" in str(converted.get("argv", "")):
        message = "argv uses an expression."
        raise WorkflowValidationError(message)
    if "argv" in converted:
        converted["argv"] = json.dumps(json.loads(str(converted["argv"])))
        return converted, ("Respaced argv.",)
    if converted.pop("command", None) is not None:
        converted["argv"] = '["make", "lint"]'
        return converted, ("Replaced command with argv.",)
    converted["argv"] = '["echo", "Ready"]'
    return converted, ("Added argv.",)


def test_upgrade_applies_each_conversion_and_lists_what_it_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stand_in_versions(monkeypatch, upgrade=_named_command)
    source = """\
jobs:
  main:
    steps:
      - uses: relay/command@v1
        with:
          argv: '["echo","Ready"]'
      - uses: relay/command@v1
        with:
          command: lint  # saved in Settings
          # Keep this note.
      - uses: relay/command@v1
"""
    result = upgrade_builtins(source)
    assert (
        result.yaml
        == """\
jobs:
  main:
    steps:
      - uses: relay/command@v2
        with:
          argv: '["echo", "Ready"]'
      - uses: relay/command@v2
        with:
          # Keep this note.
          argv: '["make", "lint"]'
      - uses: relay/command@v2
        with:
          argv: '["echo", "Ready"]'
"""
    )
    assert result.changes == (
        "Updated step 1 in job main from relay/command@v1 to relay/command@v2.",
        "Respaced argv.",
        "Updated step 2 in job main from relay/command@v1 to relay/command@v2.",
        "Replaced command with argv.",
        "Updated step 3 in job main from relay/command@v1 to relay/command@v2.",
        "Added argv.",
    )
    assert result.unresolved == ()


def test_upgrade_leaves_a_step_it_cannot_convert(monkeypatch: pytest.MonkeyPatch) -> None:
    stand_in_versions(monkeypatch, upgrade=_named_command)
    source = (
        "jobs:\n  main:\n    steps:\n"
        "      - uses: relay/command@v1\n        with: {argv: '${{ inputs.argv }}'}\n"
        "  other:\n    steps:\n      - run: echo Ready\n      - uses: relay/command@v1\n"
        "        with: hello\n"
    )
    result = upgrade_builtins(source)
    assert result.yaml == source
    assert result.changes == ()
    assert result.unresolved == (
        "Step 1 in job main: argv uses an expression. Update it by hand.",
        "Step 2 in job other: Expected a mapping. Update it by hand.",
        "jobs.other.steps[1].with: Expected a mapping.",
    )


def test_upgrade_needs_a_conversion_into_every_newer_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stand_in_versions(monkeypatch, upgrade=None)
    assert registry_problems() == ["relay/command@v1 needs an upgrade into every newer version."]
    source = "jobs: {main: {steps: [{uses: relay/command@v1, with: {argv: '[\"true\"]'}}]}}\n"
    result = upgrade_builtins(source)
    assert result.yaml == source
    assert result.unresolved == (
        "Step 1 in job main: Relay cannot convert the inputs of relay/command@v1 to "
        "relay/command@v2. Update it by hand.",
    )


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(SOURCE, id="current"),
        pytest.param(
            "jobs: {main: {steps: [{run: echo Ready}, {uses: ./.relay/actions/x}]}}\n",
            id="script-and-local",
        ),
        pytest.param("jobs:\n  main:\n    uses: ./.relay/workflows/child.yaml\n", id="reusable"),
    ],
)
def test_upgrade_returns_an_up_to_date_source_unchanged(source: str) -> None:
    result = upgrade_builtins(source)
    assert (result.yaml, result.changes, result.unresolved) == (source, (), ())


@pytest.mark.usefixtures("removed_command")
def test_a_removed_version_names_its_replacement() -> None:
    text = (
        "jobs:\n  main:\n    steps:\n      - uses: relay/command@v1\n"
        "        with: {argv: '[\"true\"]'}\n"
    )
    [issue] = workflow_diagnostics(text)
    assert issue.message == f"jobs.main.steps[0].uses: {REMOVED}"
    assert issue.context["removed"] == "relay/command@v1"
    assert issue.context["line"] == "4"
    with pytest.raises(WorkflowValidationError) as rejected:
        load(text)
    assert rejected.value.context["removed"] == "relay/command@v1"
    assert workflow_diagnostics(text.replace("@v1", "@v2")) == []
    assert registry_problems() == []


@pytest.mark.usefixtures("removed_command")
def test_a_removed_version_in_a_local_action_is_fixed_in_that_file(
    project: RelayProject,
) -> None:
    project.write(
        ".relay/actions/x/action.yaml",
        "name: X\ndescription: Local\nruns:\n  using: composite\n  steps:\n"
        "    - uses: relay/command@v1\n      with: {argv: '[\"true\"]'}\n",
    )
    with pytest.raises(WorkflowValidationError) as rejected:
        capture_sources(
            load("jobs: {main: {steps: [{uses: ./.relay/actions/x}]}}"), project.repository
        )
    assert rejected.value.message.endswith(REMOVED)
    assert rejected.value.context["field"] == "jobs.main.steps[0].uses"
    # The open workflow's update cannot change the action's file.
    assert "removed" not in rejected.value.context


def test_a_paused_run_fails_clearly_when_its_version_was_removed(
    project: RelayProject, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "ran"
    _touch_workflow(project, marker)
    engine = InlineEngine(node_executors(), tmp_path / "artifacts")
    run_id = engine.launch(project, "versions")
    engine.drain(run_id)
    stand_in_versions(monkeypatch, removed=True)
    answer_wait(engine, run_id)
    assert NodeRun.objects.get(run_id=run_id, scope_path="root.main.touch").status == "failed"
    assert Run.objects.get(pk=run_id).status == "failed"
    assert STOPPED in _events(run_id)
    assert not marker.exists()


@pytest.mark.usefixtures("removed_command")
def test_the_upgrader_converts_a_removed_version() -> None:
    result = upgrade_builtins(SOURCE)
    assert result.yaml == SOURCE.replace("@v1", "@v2")
    assert len(result.changes) == 2
    assert result.unresolved == ()
    assert upgrade_builtins("jobs: {main: {steps: [{uses: relay/command@v9}]}}\n").changes == ()
    bare = upgrade_builtins("jobs:\n  main:\n    steps:\n      - uses: relay/command@v1\n")
    assert bare.yaml == "jobs:\n  main:\n    steps:\n      - uses: relay/command@v2\n"
    assert bare.unresolved == ("relay/command@v2 requires exactly one of argv or command.",)


@pytest.mark.usefixtures("removed_command")
def test_removed_references_still_classify_persisted_rows() -> None:
    assert builtin_references("command") == ("relay/command@v1", "relay/command@v2")
    assert builtin_references("agent") == ("relay/agent@v1",)
    assert is_builtin("relay/command@v1", "command")
    assert builtin("relay/command@v1") is None
