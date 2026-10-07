"""Stable run identity and additive, project-scoped history filters."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from relay.web.models import Project, Run, RunSnapshot
from tests.support import InlineEngine, RelayProject, create_project

WORKFLOW = (
    "version: 1\nname: Build and review\nnodes:\n  check: {type: command, run: [git, status]}\n"
)


def test_run_numbers_survive_deletion_and_are_local_to_each_project(
    project: RelayProject, engine: InlineEngine, tmp_path: Path
) -> None:
    project.write_workflow("identity", WORKFLOW)
    first = engine.launch(project, "identity")
    engine.drain(first)
    record = Run.objects.get(pk=first)
    assert record.number == 1
    assert record.title == "Build and review"
    assert record.source_branch == "main"
    assert record.created_at <= RunSnapshot.objects.get(pk=first).created_at
    Run.objects.filter(pk=first).delete()
    project.write_workflow("identity", WORKFLOW.replace("Build and review", "Changed title"))
    second = engine.launch(project, "identity")
    assert Run.objects.get(pk=second).number == 2
    assert Run.objects.get(pk=second).title == "Changed title"
    other = create_project(tmp_path / "other")
    other.write_workflow("identity", WORKFLOW)
    third = engine.launch(other, "identity")
    assert Run.objects.get(pk=third).number == 1
    assert Project.objects.get(pk=project.project_id).next_run_number == 3


def test_migration_numbers_by_snapshot_creation_without_changing_snapshots(
    project: RelayProject, engine: InlineEngine
) -> None:
    project.write_workflow("identity", WORKFLOW)
    first = engine.launch(project, "identity")
    engine.drain(first)
    second = engine.launch(project, "identity")
    engine.drain(second)
    before = list(RunSnapshot.objects.order_by("pk").values("run_id", "workflow_yaml", "hashes"))
    executor = MigrationExecutor(connection)
    executor.migrate([("relay_web", "0009_run_repair_groups")])
    RunSnapshot.objects.filter(pk=first).update(
        created_at=datetime(2026, 1, 2, tzinfo=timezone.utc)
    )
    RunSnapshot.objects.filter(pk=second).update(
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc)
    )
    executor = MigrationExecutor(connection)
    executor.migrate([("relay_web", "0010_run_identity")])
    executor.migrate(executor.loader.graph.leaf_nodes())
    assert Run.objects.get(pk=second).number == 1
    assert Run.objects.get(pk=first).number == 2
    assert Run.objects.get(pk=first).created_at == datetime(2026, 1, 2, tzinfo=timezone.utc)
    assert Project.objects.get(pk=project.project_id).next_run_number == 3
    assert (
        list(RunSnapshot.objects.order_by("pk").values("run_id", "workflow_yaml", "hashes"))
        == before
    )
