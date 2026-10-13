"""One heartbeat coordinator for all active attempts in a worker process."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
import logging
import os
import threading
from typing import Protocol, TypeAlias

from relay.constants import ATTEMPT_HEARTBEAT_INTERVAL_SECONDS
from relay.errors import log_persistence_failure

Owners: TypeAlias = tuple[tuple[str, str], ...]
LOGGER = logging.getLogger(__name__)


class HeartbeatStore(Protocol):
    def renew_attempts(self, owners: Owners) -> None: ...

    def close_heartbeat_connections(self) -> None: ...


class HeartbeatCoordinator:
    store: HeartbeatStore
    _owners: Counter[tuple[str, str]]
    _guard: threading.Lock
    _stop: threading.Event
    _thread: threading.Thread
    _fatal: Callable[[], None]

    def __init__(self, store: HeartbeatStore, *, fatal: Callable[[], None]) -> None:
        self.store = store
        self._owners = Counter()
        self._guard = threading.Lock()
        self._stop = threading.Event()
        self._fatal = fatal
        self._thread = threading.Thread(target=self._run, name="relay-heartbeats", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join()

    @contextmanager
    def register(self, owners: Owners) -> Iterator[None]:
        unique = tuple(dict.fromkeys(owners))
        with self._guard:
            self._owners.update(unique)
        try:
            yield
        finally:
            with self._guard:
                self._owners.subtract(unique)
                self._owners += Counter()  # Remove registrations whose last scope ended.

    def renew(self) -> None:
        with self._guard:
            owners = tuple(self._owners)
        if owners:
            self.store.renew_attempts(owners)

    def _run(self) -> None:
        try:
            while not self._stop.wait(ATTEMPT_HEARTBEAT_INTERVAL_SECONDS):
                self.renew()
        except Exception as error:
            log_persistence_failure(LOGGER, error)
            LOGGER.exception("Worker heartbeat renewal exhausted its budget; stopping worker")
            # The supervisor proves this process and its children exited before
            # releasing workspace admission. Continuing without renewal is unsafe.
            self._fatal()
        finally:
            self.store.close_heartbeat_connections()


_GUARD = threading.RLock()
_COORDINATOR: HeartbeatCoordinator | None = None


def _stop_worker() -> None:
    os._exit(1)


@contextmanager
def worker_heartbeats(store: HeartbeatStore) -> Iterator[HeartbeatCoordinator]:
    """Keep the one coordinator alive for the Huey consumer's full lifetime."""
    global _COORDINATOR
    with _GUARD:
        if _COORDINATOR is not None:
            coordinator = _COORDINATOR
            created = False
        else:
            coordinator = HeartbeatCoordinator(store, fatal=_stop_worker)
            _COORDINATOR = coordinator
            coordinator.start()
            created = True
    try:
        yield coordinator
    finally:
        if created:
            with _GUARD:
                coordinator.stop()
                _COORDINATOR = None


@contextmanager
def heartbeat_registration(store: HeartbeatStore, owners: Owners) -> Iterator[None]:
    """Inline engines also share one coordinator across every nested scope."""
    with worker_heartbeats(store) as coordinator, coordinator.register(owners):
        yield
