"""Bounded recovery of unstarted delivery, leased controls, and lost workers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Protocol

from .control import ControlRecovery

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AttemptRecovery:
    """Attempt rows reconciled from heartbeat and shutdown evidence."""

    interrupted: int
    worker_lost: int


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    """One bounded pass, suitable for diagnostics and startup evidence."""

    dispatches_enqueued: int
    dispatch_enqueue_failures: int
    human_controls_applied: int
    human_waits_expired: int
    controls: ControlRecovery
    attempts: AttemptRecovery


class ReconcileStore(Protocol):
    def orphaned_dispatch_tokens(self) -> tuple[str, ...]: ...

    def mark_dispatch_enqueued(self, claim_token: str) -> None: ...

    def recover_control_claims(self) -> ControlRecovery: ...

    def resolve_human_wait_controls(self) -> int: ...

    def expire_human_waits(self) -> int: ...

    def reap_stale_attempts(self, *, orderly_shutdown: bool) -> AttemptRecovery: ...


def reconcile_once(
    store: ReconcileStore,
    enqueue: Callable[[str], object],
    *,
    orderly_shutdown: bool,
) -> ReconcileResult:
    """Repair only claims for which no attempt ever began."""
    enqueued = 0
    failures = 0
    for token in store.orphaned_dispatch_tokens():
        try:
            enqueue(token)
            store.mark_dispatch_enqueued(token)
            enqueued += 1
        except Exception:
            failures += 1
            LOGGER.exception("Dispatch reconciliation enqueue failed", extra={"claim_token": token})
    human_controls = store.resolve_human_wait_controls()
    expired_waits = store.expire_human_waits()
    controls = store.recover_control_claims()
    attempts = store.reap_stale_attempts(orderly_shutdown=orderly_shutdown)
    return ReconcileResult(enqueued, failures, human_controls, expired_waits, controls, attempts)


__all__ = [
    "AttemptRecovery",
    "ReconcileResult",
    "ReconcileStore",
    "reconcile_once",
]
