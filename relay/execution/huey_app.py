"""Huey dispatch adapter; Relay's database remains the durable source of truth."""

from __future__ import annotations

import logging
import os
from pathlib import Path
import socket
import threading
from typing import Protocol

import django
from huey import SqliteHuey, signals

from relay.constants import DB_BUSY_TIMEOUT_MS, RECONCILE_INTERVAL_SECONDS
from relay.paths import artifacts_dir, data_dir, huey_database_path, shutdown_marker_path

from .reconcile import ReconcileResult, reconcile_once
from .runner import AttemptExecutor, run_claim_token
from .scheduler import SchedulingStore, dispatch_ready_nodes

LOGGER = logging.getLogger(__name__)


class ActiveSchedulingStore(SchedulingStore, Protocol):
    """Scheduler adapter that can enumerate the bounded active-run set."""

    def active_run_ids(self) -> tuple[str, ...]: ...


def _database_path() -> Path:
    override = os.environ.get("RELAY_HUEY_DATABASE_PATH")
    if override is not None:
        path = Path(override)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        return path
    data_dir(create=True)
    return huey_database_path()


huey: SqliteHuey = SqliteHuey(
    "relay",
    filename=str(_database_path()),
    results=False,
    fsync=True,
    journal_mode="wal",
    timeout=DB_BUSY_TIMEOUT_MS / 1_000,
)


def _setup_django() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "relay.web.settings")
    django.setup()


def _executors() -> dict[str, AttemptExecutor]:
    # Imported only in a worker so loading the queue never launches an agent.
    from relay.execution.nodes import node_executors

    return node_executors()


def _worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{threading.get_ident()}"


@huey.task(retries=0)
def run_node_attempt(claim_token: str) -> None:
    """Claim one durable token and run at most one new attempt."""
    _setup_django()
    from relay.web.repositories import DjangoExecutionStore

    store = DjangoExecutionStore()
    run_claim_token(
        store,
        claim_token,
        _worker_id(),
        _executors(),
        artifact_root=artifacts_dir(create=True),
    )
    _advance_active_runs(store)


def enqueue_claim(claim_token: str) -> object:
    """Enqueue only the opaque claim token in Huey's separate database."""
    return run_node_attempt(claim_token)


def _advance_active_runs(store: ActiveSchedulingStore) -> None:
    """Schedule newly eligible work after a durable state change."""
    for run_id in store.active_run_ids():
        dispatch_ready_nodes(store, run_id, enqueue_claim)


def reconcile_dispatch() -> ReconcileResult:
    """Run one bounded repair pass in the consumer process."""
    _setup_django()
    from relay.web.repositories import DjangoExecutionStore

    store = DjangoExecutionStore()
    result = reconcile_once(
        store,
        enqueue_claim,
        orderly_shutdown=shutdown_marker_path().exists(),
    )
    _advance_active_runs(store)
    return result


def reconciliation_loop(stop: threading.Event) -> None:
    """Reconcile at startup and fixed intervals until consumer shutdown."""
    while not stop.is_set():
        try:
            reconcile_dispatch()
        except Exception:
            # Reconciliation is retried at the next bounded interval; attempts are not.
            LOGGER.exception("Relay reconciliation pass failed")
        stop.wait(RECONCILE_INTERVAL_SECONDS)


def _task_claim_token(task: object) -> str | None:
    args = getattr(task, "args", ())
    if not isinstance(args, tuple) or not args or not isinstance(args[0], str):
        return None
    return args[0]


@huey.signal(signals.SIGNAL_INTERRUPTED)
def _task_interrupted(
    signal_name: str,
    task: object,
    *args: object,
    **kwargs: object,
) -> None:
    del signal_name, args, kwargs
    claim_token = _task_claim_token(task)
    if claim_token is None:
        return
    _setup_django()
    from relay.web.repositories import DjangoExecutionStore

    store = DjangoExecutionStore()
    if shutdown_marker_path().exists():
        store.mark_huey_interrupted(claim_token)
    else:
        store.mark_huey_error(claim_token)


@huey.signal(signals.SIGNAL_ERROR)
def _task_error(
    signal_name: str,
    task: object,
    *args: object,
    **kwargs: object,
) -> None:
    del signal_name, args, kwargs
    claim_token = _task_claim_token(task)
    if claim_token is None:
        return
    _setup_django()
    from relay.web.repositories import DjangoExecutionStore

    DjangoExecutionStore().mark_huey_error(claim_token)


@huey.signal(signals.SIGNAL_COMPLETE)
def _task_complete(
    signal_name: str,
    task: object,
    *args: object,
    **kwargs: object,
) -> None:
    del signal_name, args, kwargs
    # Completion is advisory: the task transaction, not this signal, is authoritative.
    LOGGER.debug("Huey task completed", extra={"claim_token": _task_claim_token(task)})


__all__ = [
    "enqueue_claim",
    "huey",
    "reconcile_dispatch",
    "reconciliation_loop",
    "run_node_attempt",
]
