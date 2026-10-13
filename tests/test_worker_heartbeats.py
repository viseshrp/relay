"""Real lock contention, nested coordination and database-only retry budgets."""

from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
import threading
import time

from django.db import OperationalError, connection, connections, transaction
import pytest

from relay.agents.models import AgentExecutionContext
from relay.execution.heartbeat import HeartbeatCoordinator
from relay.execution.nodes import node_executors
from relay.execution.state import EventSensitivity, EventSource
from relay.web.db_retry import retry_database_busy
from relay.web.models import NodeAttempt, NodeRun, Project, Run, RunLock
from tests.sqlite_support import SqliteWriteProbe, hold_write_lock
from tests.support import Clock, FakeAgents, InlineEngine, RegistryNetwork, RelayProject


def test_nested_registrations_renew_once_in_one_transaction(
    agent_context: AgentExecutionContext, clock: Clock
) -> None:
    claim = agent_context.attempt.attempt
    store = agent_context.attempt.runtime
    coordinator = HeartbeatCoordinator(store, fatal=lambda: pytest.fail("worker stopped"))
    owners = [(claim.attempt_id, claim.worker_id)]
    for level in range(4):
        node = NodeRun.objects.create(
            run_id=claim.run_id,
            scope_path=f"root.parent_{level}",
            node_id=f"parent_{level}",
            node_type="subworkflow",
            status="running",
            frozen_def={},
        )
        parent = NodeAttempt.objects.create(
            node_run=node,
            attempt_number=1,
            worker_id=claim.worker_id,
            status="running",
            starting_head=claim.starting_head,
        )
        owners.append((str(parent.pk), claim.worker_id))
    clock.advance(5)
    with ExitStack() as stack:
        for depth in range(5):
            stack.enter_context(coordinator.register(tuple(owners[: depth + 1])))
        with SqliteWriteProbe() as probe:
            coordinator.renew()
    assert probe.transactions == 1
    assert probe.empty_transactions == 0
    assert probe.autocommit_writes == 0
    assert NodeAttempt.objects.filter(heartbeat_at=clock.now()).count() == 5
    assert RunLock.objects.filter(attempt_id=claim.attempt_id, heartbeat_at=clock.now()).exists()
    with SqliteWriteProbe() as probe:
        coordinator.renew()
    assert probe.transactions == 0


def test_database_retry_has_one_total_budget_and_restores_connection(
    project: RelayProject,
) -> None:
    calls = 0

    def write() -> None:
        nonlocal calls
        calls += 1
        with transaction.atomic():
            Project.objects.filter(pk=project.project_id).update(display_name="bad")

    started = time.monotonic()
    with hold_write_lock(Path(connection.settings_dict["NAME"])), pytest.raises(OperationalError):
        retry_database_busy(write, budget=0.08)()
    assert 0.07 <= time.monotonic() - started < 1
    assert calls >= 1
    assert not connection.in_atomic_block
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA busy_timeout")
        assert cursor.fetchone() == (15000,)
    assert Project.objects.get(pk=project.project_id).display_name != "bad"


def test_database_retry_does_not_replay_non_busy_errors() -> None:
    calls = 0

    def fail() -> None:
        nonlocal calls
        calls += 1
        message = "constraint failed"
        raise OperationalError(message)

    with pytest.raises(OperationalError, match="constraint"):
        retry_database_busy(fail)()
    assert calls == 1


def test_quiet_five_level_agent_survives_a_write_lock_beyond_five_seconds(
    project: RelayProject,
    tmp_path: Path,
    fake_agents: FakeAgents,
    registry_network: RegistryNetwork,
    database_threads: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del registry_network, database_threads
    from relay.web.repositories import DjangoExecutionStore

    release = tmp_path / "release-agent"
    fake_agents.install("codex", mode=f"quiet-until:{release}")
    for level in range(5):
        node = (
            f"{{type: subworkflow, workflow: nested_{level + 1}}}"
            if level < 4
            else "{type: agent, prompts: [{local: prompts/prompt.md}], writes: false}"
        )
        project.write_workflow(
            f"nested_{level}",
            f"version: 1\nname: Nested\nagents: [codex]\nmodel: m1\nnodes:\n  work: {node}\n",
        )
    engine = InlineEngine(node_executors(), tmp_path / "artifacts")
    run_id = engine.launch(project, "nested_0")
    ready = threading.Event()
    renewing = threading.Event()
    recovered = threading.Event()
    probe = SqliteWriteProbe()
    append = DjangoExecutionStore.append_attempt_event
    renew = DjangoExecutionStore.renew_attempts
    renew_once = DjangoExecutionStore._renew_attempts

    def observe(
        self: DjangoExecutionStore,
        attempt_id: str,
        event_type: str,
        source: EventSource,
        payload: Mapping[str, object],
        *,
        sensitivity: EventSensitivity = EventSensitivity.NORMAL,
    ) -> None:
        append(self, attempt_id, event_type, source, payload, sensitivity=sensitivity)
        if event_type == "agent.message":
            ready.set()

    def renew_with_short_wait(
        self: DjangoExecutionStore, owners: tuple[tuple[str, str], ...]
    ) -> None:
        # Force retries on the coordinator's connection. Provider execution
        # and shutdown retain their normal configured SQLite busy timeout.
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA busy_timeout=50")
        renew(self, owners)

    def renewing_attempts(self: DjangoExecutionStore, owners: tuple[tuple[str, str], ...]) -> None:
        # Observe every real retry, including a renewal already in progress
        # when the test clears its readiness signal and acquires the writer.
        renewing.set()
        renew_once(self, owners)
        if probe.first_busy.is_set():
            recovered.set()

    monkeypatch.setattr(DjangoExecutionStore, "append_attempt_event", observe)
    monkeypatch.setattr(DjangoExecutionStore, "renew_attempts", renew_with_short_wait)
    monkeypatch.setattr(DjangoExecutionStore, "_renew_attempts", renewing_attempts)
    monkeypatch.setattr("relay.execution.heartbeat.ATTEMPT_HEARTBEAT_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr("relay.agents.acp_driver.ATTEMPT_HEARTBEAT_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr("relay.agents.acp_driver.CONTROL_POLL_INTERVAL_SECONDS", 0.05)

    def execute() -> None:
        try:
            engine.drain(run_id)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(execute)
        try:
            assert ready.wait(15), "fake agent did not reach its quiet gate"
            assert NodeAttempt.objects.filter(status="running").count() == 5
            renewing.clear()
            with (
                probe,
                hold_write_lock(Path(connection.settings_dict["NAME"])),
            ):
                assert renewing.wait(2), "coordinator did not try renewing"
                assert probe.first_busy.wait(2), "renewal never encountered the held writer"
                elapsed = threading.Event()
                timer = threading.Timer(5.05, elapsed.set)
                timer.start()
                try:
                    assert elapsed.wait(6)
                    assert not future.done()
                finally:
                    timer.cancel()
            # Keep the provider quiet until the contended renewal commits.
            # This explicitly verifies recovery before finishing the agent.
            assert recovered.wait(2), "renewal did not recover after writer release"
            assert not future.done()
        finally:
            release.touch()
        future.result(timeout=15)
    assert Run.objects.get(pk=run_id).status == "succeeded"
    assert NodeAttempt.objects.filter(status="terminal", stop_reason="completed").count() == 5


def test_a_rolled_back_busy_transaction_retries_until_the_gate_opens(
    project: RelayProject,
) -> None:
    failed = threading.Event()
    calls = 0

    def write() -> None:
        nonlocal calls
        calls += 1
        try:
            with transaction.atomic():
                Project.objects.filter(pk=project.project_id).update(display_name="retried")
        except OperationalError:
            failed.set()
            raise

    def worker() -> None:
        try:
            with connection.cursor() as cursor:
                cursor.execute("PRAGMA busy_timeout=10")
            retry_database_busy(write, budget=1)()
        finally:
            connections.close_all()

    with SqliteWriteProbe() as probe, ThreadPoolExecutor(max_workers=1) as executor:
        with hold_write_lock(Path(connection.settings_dict["NAME"])):
            future = executor.submit(worker)
            assert failed.wait(1), "real SQLite transaction never encountered the gate"
        future.result(timeout=2)
    assert calls > 1
    assert probe.transactions == 1
    assert probe.failed_begins >= 1
    assert Project.objects.get(pk=project.project_id).display_name == "retried"


def test_renewal_exhaustion_stops_the_worker_instead_of_abandoning_renewal(
    agent_context: AgentExecutionContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    stopped = threading.Event()
    claim = agent_context.attempt.attempt
    monkeypatch.setattr("relay.web.repositories.ATTEMPT_STALE_AFTER_SECONDS", 0.08)
    monkeypatch.setattr("relay.execution.heartbeat.ATTEMPT_HEARTBEAT_INTERVAL_SECONDS", 0.01)
    coordinator = HeartbeatCoordinator(agent_context.attempt.runtime, fatal=stopped.set)
    with (
        coordinator.register(((claim.attempt_id, claim.worker_id),)),
        hold_write_lock(Path(connection.settings_dict["NAME"])),
    ):
        coordinator.start()
        try:
            assert stopped.wait(2)
        finally:
            coordinator.stop()
    assert NodeAttempt.objects.get(pk=claim.attempt_id).status == "running"


def test_streaming_step_lock_profile(
    project: RelayProject,
    tmp_path: Path,
    fake_agents: FakeAgents,
    registry_network: RegistryNetwork,
    request: pytest.FixtureRequest,
) -> None:
    """Profile real ACP output and nested execution without provider accounts."""
    import json

    from relay.web.models import RunEvent

    del registry_network
    fake_agents.install("codex", mode="stream-200")
    project.write_workflow(
        "stream-child",
        "version: 1\nname: Stream\nagents: [codex]\nmodel: m1\nnodes:\n"
        "  agent: {type: agent, prompts: [{local: prompts/prompt.md}], writes: false}\n",
    )
    project.write_workflow(
        "stream-parent",
        "version: 1\nname: Parent\nagents: [codex]\nmodel: m1\nnodes:\n"
        "  child: {type: subworkflow, workflow: stream-child}\n",
    )
    engine = InlineEngine(node_executors(), tmp_path / "artifacts")
    run_id = engine.launch(project, "stream-parent")
    with SqliteWriteProbe() as probe:
        engine.drain(run_id)
    report = probe.report()
    request.node.add_report_section("call", "SQLite streaming measurements", json.dumps(report))
    request.node.user_properties.append(("sqlite_profile", json.dumps(report)))
    request.node.add_report_section(
        "call", "Unexpected SQLite writes", "\n".join(probe.unexpected_writes)
    )
    assert Run.objects.get(pk=run_id).status == "succeeded"
    assert RunEvent.objects.filter(run_id=run_id, type="agent.message").count() >= 200
    assert probe.empty_transactions == probe.autocommit_writes == 0
