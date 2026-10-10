"""Concurrent SQLite launches retain complete snapshots and diagnostic failures."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from django.db import DatabaseError, connections
import pytest

from relay.errors import PersistenceError
from relay.execution.launch import LaunchRequest, launch_workflow
from relay.web.models import Project, Run, RunSnapshot
from relay.web.repositories import DjangoExecutionStore
from tests.support import RelayProject, create_project

SOURCE = "name: Burst\njobs: {check: {steps: [{run: echo Ready}]}}\n"


def request() -> LaunchRequest:
    return LaunchRequest("check.yaml", {}, None, "retain", None, (), "owner")


def test_snapshot_failure_logs_the_traceback_and_rolls_back_the_launch(
    project: RelayProject, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    project.write_workflow("check", SOURCE)

    def fail_snapshot(**fields: object) -> None:
        del fields
        message = "private database failure"
        raise DatabaseError(message)

    monkeypatch.setattr(RunSnapshot.objects, "create", fail_snapshot)
    with pytest.raises(PersistenceError) as caught:
        launch_workflow(
            DjangoExecutionStore(),
            project.relay_root,
            project.project_id,
            request(),
            lambda _: None,
        )
    assert "private database failure" not in caught.value.message
    assert any(record.exc_info and "pending run" in record.message for record in caplog.records)
    assert Run.objects.count() == RunSnapshot.objects.count() == 0
    assert Project.objects.get(pk=project.project_id).next_run_number == 1


def test_forty_concurrent_launches_across_projects_have_complete_sqlite_records(
    tmp_path: Path,
) -> None:
    projects = [create_project(tmp_path / f"project-{index}") for index in range(8)]
    for project in projects:
        project.write_workflow("check", SOURCE)
    ready = Barrier(8)

    def launch(index: int) -> str:
        try:
            if index < 8:
                ready.wait()
            project = projects[index % 8]
            return launch_workflow(
                DjangoExecutionStore(),
                project.relay_root,
                project.project_id,
                request(),
                lambda _: None,
            ).run_id
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(launch, range(40)))
    assert len(set(ids)) == Run.objects.count() == RunSnapshot.objects.count() == 40
    for project in projects:
        assert set(
            Run.objects.filter(project_id=project.project_id).values_list("number", flat=True)
        ) == set(range(1, 6))
