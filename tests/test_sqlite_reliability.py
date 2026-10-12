"""Deterministic contention, read isolation, and public diagnostic boundaries."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from django.db import DatabaseError, OperationalError, connection, connections, transaction
from django.utils import timezone
import pytest

from relay.agents.models import AgentExecutionContext
from relay.execution.huey_app import reconcile_dispatch
from relay.web.db_routing import read_snapshot
from relay.web.models import Project, WorkflowTrigger
from relay.web.repositories import DjangoExecutionStore, DjangoReadStore
from tests.sqlite_support import SqliteWriteProbe, hold_write_lock
from tests.support import RelayProject


def test_lock_gate_and_probe_measure_real_sqlite_waiting(
    project: RelayProject, short_busy_timeout: None
) -> None:
    del short_busy_timeout

    def write() -> None:
        try:
            with transaction.atomic():
                Project.objects.filter(pk=project.project_id).update(display_name="changed")
        finally:
            connections.close_all()

    with (
        SqliteWriteProbe() as probe,
        hold_write_lock(Path(connection.settings_dict["NAME"])),
        ThreadPoolExecutor(max_workers=1) as executor,
        pytest.raises(OperationalError, match="locked"),
    ):
        executor.submit(write).result(timeout=5)
    assert probe.failed_begins == 1
    assert max(probe.lock_waits) >= 0.04
    assert not probe.lock_holds
    with SqliteWriteProbe() as probe:
        write()
    assert probe.transactions == 1
    assert probe.empty_transactions == 0
    assert len(probe.lock_holds) == 1


@pytest.mark.parametrize("read", ["dashboard", "attention"])
def test_monitoring_reads_do_not_reserve_the_writer(
    project: RelayProject, short_busy_timeout: None, read: str
) -> None:
    del project, short_busy_timeout
    store = DjangoReadStore()
    with SqliteWriteProbe() as probe, hold_write_lock(Path(connection.settings_dict["NAME"])):
        if read == "dashboard":
            result = store.dashboard(section=None, cursor=None, limit=200, query_text="")
            assert result["counts"]
        else:
            assert store.attention(None)["waiting_count"] == 0
    assert probe.transactions == 0


def test_job_read_does_not_reserve_the_writer(
    agent_context: AgentExecutionContext, short_busy_timeout: None
) -> None:
    del short_busy_timeout
    claim = agent_context.attempt.attempt
    with SqliteWriteProbe() as probe, hold_write_lock(Path(connection.settings_dict["NAME"])):
        job, _ = DjangoReadStore().run_job(claim.run_id, claim.scope_path, since=0, limit=200)
        assert job["scope_path"] == claim.scope_path
    assert probe.transactions == 0


def test_snapshot_rejects_model_and_raw_writes(project: RelayProject) -> None:
    with read_snapshot(), pytest.raises(DatabaseError, match="forbidden"):
        Project.objects.filter(pk=project.project_id).update(display_name="bad")
    with read_snapshot(), pytest.raises(DatabaseError, match="forbidden"):
        Project.objects.using("default").filter(pk=project.project_id).update(display_name="bad")
    with (
        read_snapshot(),
        connections["snapshot"].cursor() as cursor,
        pytest.raises(DatabaseError, match="readonly"),
    ):
        cursor.execute("CREATE TABLE accidental_write (id INTEGER)")
    assert Project.objects.get(pk=project.project_id).display_name != "bad"


def test_both_connections_share_the_isolated_database_with_full_durability() -> None:
    assert (
        connections["default"].settings_dict["NAME"]
        == connections["snapshot"].settings_dict["NAME"]
    )
    for alias in ("default", "snapshot"):
        with connections[alias].cursor() as cursor:
            cursor.execute("PRAGMA synchronous")
            assert cursor.fetchone() == (2,)
            cursor.execute("PRAGMA busy_timeout")
            assert cursor.fetchone() == (15000,)
            cursor.execute("PRAGMA journal_mode")
            assert cursor.fetchone() == ("wal",)
            cursor.execute("PRAGMA query_only")
            assert cursor.fetchone() == (int(alias == "snapshot"),)


def test_empty_control_poll_takes_no_write_lock(
    agent_context: AgentExecutionContext, short_busy_timeout: None
) -> None:
    del short_busy_timeout
    claim = agent_context.attempt.attempt
    with SqliteWriteProbe() as probe, hold_write_lock(Path(connection.settings_dict["NAME"])):
        assert DjangoExecutionStore().claim_next_control(claim.attempt_id, claim.worker_id) is None
    assert probe.transactions == 0


def test_ownership_checks_survive_a_held_write_lock(
    agent_context: AgentExecutionContext, short_busy_timeout: None
) -> None:
    del short_busy_timeout
    with SqliteWriteProbe() as probe, hold_write_lock(Path(connection.settings_dict["NAME"])):
        assert agent_context.attempt.heartbeat()
    assert probe.transactions == 0
    assert probe.autocommit_writes == 0


def test_idle_reconciliation_has_no_writes() -> None:
    with SqliteWriteProbe() as probe:
        reconcile_dispatch()
    assert probe.transactions == 0
    assert probe.autocommit_writes == 0


@pytest.mark.parametrize("event", ["schedule", "workflow_run", "push", "repository_dispatch"])
def test_idle_activated_triggers_write_nothing(project: RelayProject, event: str) -> None:
    from relay.web.actions_automation import local_refs

    WorkflowTrigger.objects.create(
        project_id=project.project_id,
        workflow_key="idle",
        event=event,
        enabled=True,
        source_hash="0" * 64,
        config={"value": [{"cron": "0 0 1 1 *"}]} if event == "schedule" else {"value": {}},
        cursor={"at": timezone.now().isoformat(), "refs": local_refs(project.repository)},
    )
    with SqliteWriteProbe() as probe:
        reconcile_dispatch()
    assert probe.transactions == 0
    assert probe.autocommit_writes == 0


def test_settling_an_active_run_takes_no_write_lock(
    agent_context: AgentExecutionContext,
    short_busy_timeout: None,
) -> None:
    del short_busy_timeout
    with SqliteWriteProbe() as probe, hold_write_lock(Path(connection.settings_dict["NAME"])):
        DjangoExecutionStore().settle_run(agent_context.attempt.attempt.run_id)
    assert probe.transactions == probe.autocommit_writes == 0
