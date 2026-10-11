"""Persistence shares launch choices without importing the launch service."""

import os
import subprocess
import sys

import pytest

from relay.execution.launch_request import FrozenLaunchBindings
from relay.web.actions_bindings import freeze_bindings
from relay.web.models import Run, RunSnapshot
from relay.web.repositories import DjangoExecutionStore
from tests.support import InlineEngine, RelayProject


def test_persistence_imports_independently_and_preserves_the_public_request_type() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
import django

django.setup()
from relay.web import repositories

assert "relay.execution.launch" not in sys.modules
from relay.execution.launch import LaunchRequest as public_request
from relay.execution.launch_request import LaunchRequest

assert public_request is LaunchRequest
assert repositories.LaunchRequest is LaunchRequest
""",
        ],
        env={**os.environ, "RELAY_LOGIN_REQUIRED": "true"},
        capture_output=True,
        text=True,
        check=False,
        shell=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_launch_freezes_bindings_through_its_store_before_capturing_the_snapshot(
    project: RelayProject, engine: InlineEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[str] = []

    def capture_bindings(store: DjangoExecutionStore, project_id: str) -> FrozenLaunchBindings:
        del store
        captured.append(project_id)
        return {**freeze_bindings(project_id), "vars": {"SOURCE": "store snapshot"}}

    monkeypatch.setattr(
        DjangoExecutionStore, "freeze_launch_bindings", capture_bindings, raising=False
    )
    project.write_workflow(
        "bindings",
        "run-name: Captured ${{ vars.SOURCE }}\njobs: {check: {steps: [{run: echo Ready}]}}\n",
    )
    run_id = engine.launch(project, "bindings")
    engine.drain(run_id)

    assert captured == [project.project_id]
    run = Run.objects.get(pk=run_id)
    assert run.status == "succeeded" and run.title == "Captured store snapshot"
    snapshot = RunSnapshot.objects.get(run_id=run_id)
    assert snapshot.launch_defaults["actions_context"]["vars"] == {"SOURCE": "store snapshot"}
