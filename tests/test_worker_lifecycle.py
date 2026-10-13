"""The consumer owns renewal and reconciliation for its entire lifetime."""

from __future__ import annotations

import logging
import sys
import threading

from django.db import OperationalError
from huey.bin import huey_consumer
import pytest

from relay import manage
from relay.errors import PersistenceError
from relay.execution import heartbeat, huey_app
from relay.web.repositories import DjangoExecutionStore


@pytest.mark.parametrize("consumer_crashes", [False, True])
def test_consumer_exit_stops_renewal_and_reconciliation_and_restores_arguments(
    monkeypatch: pytest.MonkeyPatch, consumer_crashes: bool
) -> None:
    original = sys.argv
    entered = threading.Event()
    stopped = threading.Event()
    coordinators: list[heartbeat.HeartbeatCoordinator] = []

    def reconcile(stop: threading.Event) -> None:
        entered.set()
        if stop.wait(5):
            stopped.set()

    def consume() -> None:
        assert entered.wait(2)
        assert sys.argv == ["relay.manage", "--workers", "1", "relay.execution.huey_app.huey"]
        coordinator = heartbeat._COORDINATOR
        assert coordinator is not None
        assert coordinator._thread.is_alive()
        # Nested execution borrows the consumer's coordinator, including on errors.
        with heartbeat.worker_heartbeats(DjangoExecutionStore()) as nested:
            assert nested is coordinator
        coordinators.append(coordinator)
        if consumer_crashes:
            message = "consumer failed"
            raise RuntimeError(message)

    monkeypatch.setattr(huey_app, "reconciliation_loop", reconcile)
    monkeypatch.setattr(huey_consumer, "consumer_main", consume)
    arguments = ["relay.manage", "run_huey", "--workers", "1"]
    if consumer_crashes:
        with pytest.raises(RuntimeError, match="consumer failed"):
            manage.main(arguments)
    else:
        manage.main(arguments)
    assert stopped.is_set()
    assert sys.argv is original
    assert heartbeat._COORDINATOR is None
    assert len(coordinators) == 1
    assert not coordinators[0]._thread.is_alive()


def test_reconciliation_logs_suppressed_database_failure_and_keeps_running(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    stop = threading.Event()
    calls = 0

    def database_failure() -> None:
        message = "private reconciliation database failure"
        raise OperationalError(message)

    def reconcile() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            try:
                database_failure()
            except OperationalError:
                message = "Relay could not reconcile delivery."
                raise PersistenceError(message) from None
        stop.set()

    monkeypatch.setattr(huey_app, "reconcile_dispatch", reconcile)
    monkeypatch.setattr(huey_app, "RECONCILE_INTERVAL_SECONDS", 0.01)
    with caplog.at_level(logging.WARNING, logger=huey_app.__name__):
        huey_app.reconciliation_loop(stop)
    assert calls == 2
    assert any(
        record.exc_info is not None and isinstance(record.exc_info[1], OperationalError)
        for record in caplog.records
    )
    assert "private reconciliation database failure" in caplog.text
    assert "Relay reconciliation pass failed" in caplog.text
