"""Shared commands and environment layers stay explicit and frozen at launch."""

from __future__ import annotations

import json

from django.test import Client
from pydantic import ValidationError
import pytest

from relay.errors import ConfigError
from relay.execution.preflight import load_launch_workflow
from relay.owner_settings import effective_config, read_settings, revision, save_settings
from relay.web.models import NodeRun, Run, RunEvent, RunSnapshot
from relay.web.settings_repository import DjangoSettingsStore
from relay.web.views import actions
from relay.workflows.defaults import apply_workflow_defaults, validate_defaults
from relay.workflows.schema import CommandNode, LoopNode, WorkflowDefinition
from tests.support import PYTHON, InlineEngine, RelayProject, answer_wait
from tests.test_web_api import client as client
from tests.test_web_api import owner as owner
from tests.test_web_api import post
from tests.test_web_api import served as served


def save_defaults(values: dict[str, object]) -> None:
    save_settings({"workflow_defaults": values}, str(read_settings()["revision"]))


@pytest.mark.parametrize(
    "values",
    [
        {"commands": {"Bad-name": ["git"]}},
        {"commands": {"test": []}},
        {"commands": {"test": [""]}},
        {"commands": {"test": ["git", "\x00"]}},
        {"commands": {"test": "git status"}},
        {"env": {"": "value"}},
        {"env": {"BAD=NAME": "value"}},
        {"env": {"BAD\x00NAME": "value"}},
        {"env": {"NAME": "bad\x00value"}},
        {"env": {"NAME": 1}},
    ],
)
def test_invalid_commands_and_variables_preserve_saved_bytes(values: dict[str, object]) -> None:
    save_defaults({"commands": {"test": ["git", "status"]}, "env": {"MODE": "test"}})
    before = read_settings()
    with pytest.raises(ConfigError):
        save_defaults(values)
    assert read_settings() == before


@pytest.mark.parametrize("env", [{"A=B": "x"}, {"A": "\x00"}, {"A": False}])
def test_workflow_and_job_variables_reject_invalid_process_values(env: object) -> None:
    with pytest.raises(ValidationError):
        WorkflowDefinition.model_validate(
            {"version": 1, "name": "Invalid", "nodes": {}, "env": env}
        )
    with pytest.raises(ValidationError):
        CommandNode.model_validate({"type": "command", "run": ["git"], "env": env})


@pytest.mark.parametrize("empty", [False, True])
def test_project_maps_replace_global_maps_and_reset_to_current_globals(
    project: RelayProject, empty: bool
) -> None:
    save_defaults(
        {
            "commands": {"test": ["git", "status"], "lint": ["git", "diff"]},
            "env": {"GLOBAL": "value", "MODE": "global"},
        }
    )
    store = DjangoSettingsStore()
    commands = {} if empty else {"test": ["git", "log"]}
    env = {} if empty else {"MODE": "project"}
    store.save_project_defaults(
        project.project_id, {"workflow_defaults": {"commands": commands, "env": env}}, revision({})
    )
    resolved = effective_config(store, project.project_id).workflow_defaults
    assert resolved.commands == commands
    assert resolved.env == env
    save_defaults({"commands": {"build": ["git", "show"]}, "env": {"MODE": "new global"}})
    assert effective_config(store, project.project_id).workflow_defaults.env == env
    current = store.project_defaults(project.project_id)
    store.save_project_defaults(project.project_id, {}, revision(current))
    assert effective_config(store, project.project_id).workflow_defaults.commands == {
        "build": ["git", "show"]
    }
    assert effective_config(store, project.project_id).workflow_defaults.env == {
        "MODE": "new global"
    }


@pytest.mark.parametrize("inherit", [False, True])
def test_defaults_resolve_explicit_commands_loops_and_child_environment(
    project: RelayProject, inherit: bool
) -> None:
    source = (
        "version: 1\nname: Parent\n"
        f"inherit_env: {str(inherit).lower()}\nenv: {{MODE: workflow, PARENT: present}}\n"
        "nodes:\n"
        "  direct: {type: command, run: [git, status], env: {MODE: job}}\n"
        "  isolated: {type: command, run: {command: test}, inherit_env: false, "
        "env: {ONLY: local}}\n"
        "  repeat:\n    type: loop\n    max_iterations: 1\n    exhausted: direct\n"
        "    body:\n      work: {type: command, run: {command: test}}\n"
        "  nested: {type: subworkflow, workflow: child}\n"
    )
    project.write_workflow("parent", source)
    project.write_workflow(
        "child",
        "version: 1\nname: Child\nenv: {CHILD: present}\nnodes:\n"
        "  work: {type: command, run: {command: test}}\n",
    )
    loaded = apply_workflow_defaults(
        load_launch_workflow(project.relay_root, "parent"),
        validate_defaults(
            {
                "commands": {"test": ["git", "log", "--oneline"]},
                "env": {"GLOBAL": "present", "MODE": "global"},
            }
        ),
        (),
        None,
    )
    nodes = loaded.root.definition.nodes
    direct = nodes["direct"]
    isolated = nodes["isolated"]
    repeat = nodes["repeat"]
    assert isinstance(direct, CommandNode)
    assert isinstance(isolated, CommandNode)
    assert isinstance(repeat, LoopNode)
    expected = {"GLOBAL": "present"} if inherit else {}
    assert direct.run == ["git", "status"]
    assert direct.env == {**expected, "PARENT": "present", "MODE": "job"}
    assert isolated.run == ["git", "log", "--oneline"]
    assert isolated.env == {"ONLY": "local"}
    inner = repeat.body["work"]
    assert isinstance(inner, CommandNode)
    assert inner.env == {**expected, "PARENT": "present", "MODE": "workflow"}
    child = loaded.subworkflows["child.yaml"].definition.nodes["work"]
    assert isinstance(child, CommandNode)
    assert child.env == {"GLOBAL": "present", "MODE": "global", "CHILD": "present"}
    assert loaded.root.text == source


def test_missing_shared_command_rejects_launch_before_creating_run(
    owner: Client, served: RelayProject
) -> None:
    served.write_workflow(
        "missing",
        "version: 1\nname: Missing\nnodes:\n  work: {type: command, run: {command: test}}\n",
    )
    response = post(owner, "/api/runs", {"workflow_key": "missing", "inputs": {}})
    assert response.status_code == 422
    assert response.json()["code"] == "workflow_validation_error"
    assert "test" in response.json()["message"]
    assert not Run.objects.exists()


def test_launch_freezes_literal_arguments_and_environment_through_child_dispatch(
    owner: Client, served: RelayProject, engine: InlineEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = (
        "import json, os, sys; print(json.dumps([sys.argv[1:], "
        "os.environ['RELAY_TEST_MODE'], os.environ['RELAY_TEST_BASE']]))"
    )
    arguments = [PYTHON, "-c", script, "a b", "$(not-a-shell)", "semi;colon", ""]
    monkeypatch.setenv("RELAY_TEST_BASE", "worker")
    save_defaults({"commands": {"test": arguments}, "env": {"RELAY_TEST_MODE": "global"}})
    source = (
        "version: 1\nname: Frozen\nnodes:\n  wait: {type: human_wait, prompt: Continue}\n"
        "  child: {type: subworkflow, workflow: child, needs: [wait]}\n"
    )
    child = (
        "version: 1\nname: Child\nenv: {RELAY_TEST_MODE: workflow}\nnodes:\n"
        "  work: {type: command, run: {command: test}, env: {RELAY_TEST_MODE: job}}\n"
    )
    served.write_workflow("parent", source)
    served.write_workflow("child", child)
    monkeypatch.setattr(actions, "_enqueue_claim", engine.tokens.append)
    response = post(
        owner, "/api/runs", {"workflow_key": "parent", "inputs": {}, "cleanup_policy": "retain"}
    )
    assert response.status_code == 201, response.json()
    run_id = response.json()["run_id"]
    captured = RunSnapshot.objects.get(run_id=run_id)
    assert captured.workflow_yaml == source
    assert captured.subworkflows["child.yaml"]["yaml"] == child
    assert captured.launch_defaults["workflow_defaults"]["commands"]["test"] == arguments
    engine.drain(run_id)
    save_defaults(
        {"commands": {"test": ["missing-program"]}, "env": {"RELAY_TEST_MODE": "changed"}}
    )
    answer_wait(engine, run_id)
    assert Run.objects.get(pk=run_id).status == "succeeded"
    frozen = NodeRun.objects.get(run_id=run_id, scope_path="root.child.work").frozen_def
    assert frozen["run"] == arguments
    assert frozen["env"] == {"RELAY_TEST_MODE": "job"}
    output = "".join(
        str(event.payload["chunk"])
        for event in RunEvent.objects.filter(run_id=run_id, type="command.stdout").order_by("id")
    )
    assert json.loads(output) == [arguments[3:], "job", "worker"]


def test_shared_command_and_environment_apply_to_repair_roles(project: RelayProject) -> None:
    project.write_workflow(
        "repairs",
        "version: 1\nname: Repairs\nenv: {MODE: workflow}\nnodes:\n"
        "  review: {type: command, run: [git, status], "
        "outputs: {ready: {exists: REVIEW.md}}}\n"
        "repairs:\n  review:\n    accepted_output: ready\n    accepted_value: true\n"
        "    fix: {type: command, run: {command: fix}, env: {MODE: fixer}}\n"
        "    verify: {type: command, run: {command: verify}, inherit_env: false, "
        "outputs: {ready: {exists: REVIEW.md}}}\n",
    )
    loaded = apply_workflow_defaults(
        load_launch_workflow(project.relay_root, "repairs"),
        validate_defaults(
            {
                "commands": {"fix": ["git", "diff"], "verify": ["git", "status"]},
                "env": {"GLOBAL": "present"},
            }
        ),
        (),
        None,
    )
    loop = loaded.root.definition.nodes["relay_repair_review"]
    assert isinstance(loop, LoopNode)
    fix = loop.body["fix"]
    verify = loop.body["verify"]
    assert isinstance(fix, CommandNode)
    assert isinstance(verify, CommandNode)
    assert fix.run == ["git", "diff"]
    assert fix.env == {"GLOBAL": "present", "MODE": "fixer"}
    assert verify.run == ["git", "status"]
    assert verify.env == {}


@pytest.mark.parametrize(
    "reference", [{"command": "Bad-name"}, {"command": "test", "shell": "bash"}, {"command": 1}]
)
def test_shared_references_reject_unknown_fields_and_invalid_names(reference: object) -> None:
    with pytest.raises(ValidationError):
        CommandNode.model_validate({"type": "command", "run": reference})


def test_unresolved_captured_command_fails_with_a_relay_error(
    project: RelayProject, engine: InlineEngine
) -> None:
    project.write_workflow(
        "corrupt",
        "version: 1\nname: Captured\nnodes:\n  work: {type: command, run: [git, status]}\n",
    )
    run_id = engine.launch(project, "corrupt")
    node = NodeRun.objects.get(run_id=run_id, scope_path="root.work")
    node.frozen_def = {**node.frozen_def, "run": {"command": "unresolved"}}
    node.save(update_fields=["frozen_def"])
    engine.drain(run_id)
    assert Run.objects.get(pk=run_id).status == "failed"
    event = RunEvent.objects.get(run_id=run_id, type="attempt.ended")
    assert event.payload["error_code"] == "node_execution_error"
    assert (
        event.payload["error_message"]
        == "The shared command was not resolved in the captured workflow."
    )
