"""Shared commands and environment layers stay explicit and frozen at launch."""

from __future__ import annotations

import json

from django.test import Client
from pydantic import ValidationError
import pytest

from relay.errors import ConfigError
from relay.owner_settings import effective_config, read_settings, revision, save_settings
from relay.web.models import NodeRun, Run, RunEvent, RunSnapshot
from relay.web.settings_repository import DjangoSettingsStore
from relay.web.views import actions
from relay.workflows.schema import CommandNode, WorkflowDefinition
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
            {"name": "Invalid", "env": env, "jobs": {"main": {"steps": [{"run": "echo ready"}]}}}
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


def test_missing_shared_command_rejects_launch_before_creating_run(
    owner: Client, served: RelayProject
) -> None:
    served.write_workflow(
        "missing",
        "name: Missing\njobs: {work: {steps: [{uses: relay/command@v1, with: {command: test}}]}}\n",
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
        "name: Frozen\n"
        "jobs:\n"
        "  wait:\n"
        "    steps: [{uses: relay/human-wait@v1, with: {prompt: Continue}}]\n"
        "  child: {uses: ./.relay/workflows/child.yaml, needs: wait}\n"
    )
    child = (
        "name: Child\n"
        "on: workflow_call\n"
        "env: {RELAY_TEST_MODE: workflow}\n"
        "jobs:\n"
        "  work:\n"
        "    env: {RELAY_TEST_MODE: job}\n"
        "    steps: [{uses: relay/command@v1, with: {command: test}}]\n"
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
    assert (
        captured.resolved_definition["nodes"]["child"]["sources"][".relay/workflows/child.yaml"]
        == child
    )
    assert captured.launch_defaults["workflow_defaults"]["commands"]["test"] == arguments
    engine.drain(run_id)
    save_defaults(
        {"commands": {"test": ["missing-program"]}, "env": {"RELAY_TEST_MODE": "changed"}}
    )
    answer_wait(engine, run_id)
    assert Run.objects.get(pk=run_id).status == "succeeded"
    frozen = NodeRun.objects.get(run_id=run_id, scope_path="root.child.work.step_1").frozen_def
    assert frozen["step"]["with"] == {"command": "test"}
    assert captured.launch_defaults["workflow_defaults"]["commands"]["test"] == arguments
    assert frozen["job"]["env"] == {"RELAY_TEST_MODE": "job"}
    output = "".join(
        str(event.payload["chunk"])
        for event in RunEvent.objects.filter(run_id=run_id, type="command.stdout").order_by("id")
    )
    assert json.loads(output) == [arguments[3:], "job", "worker"]


@pytest.mark.parametrize(
    "reference", [{"command": "Bad-name"}, {"command": "test", "shell": "bash"}, {"command": 1}]
)
def test_shared_references_reject_unknown_fields_and_invalid_names(reference: object) -> None:
    with pytest.raises(ValidationError):
        CommandNode.model_validate({"type": "command", "run": reference})
