"""Bounded delivery and control repair; worker loss belongs to the supervisor."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Protocol

from .control import ControlRecovery

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AttemptRecovery:
    """Compatibility counters; periodic repair cannot recover worker attempts."""

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
    usage_retries_resumed: int = 0
    automatic_retries_resumed: int = 0


class ReconcileStore(Protocol):
    def orphaned_dispatch_tokens(self) -> tuple[str, ...]: ...

    def mark_dispatch_enqueued(self, claim_token: str) -> None: ...

    def recover_control_claims(self) -> ControlRecovery: ...

    def resolve_human_wait_controls(self) -> int: ...

    def expire_human_waits(self) -> int: ...

    def expire_scope_waits(self) -> int: ...

    def resume_usage_retries(self) -> int: ...

    def resume_automatic_retries(self) -> int: ...

    def resume_run_completions(self) -> None: ...


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
    store.expire_scope_waits()
    controls = store.recover_control_claims()
    # Sleep, a clock jump, or lock contention can age a live worker's heartbeat.
    # Only the supervisor may release admission after proving process exit.
    attempts = AttemptRecovery(0, 0)
    usage_retries = 0 if orderly_shutdown else store.resume_usage_retries()
    automatic_retries = 0 if orderly_shutdown else store.resume_automatic_retries()
    if not orderly_shutdown:
        store.resume_run_completions()
    return ReconcileResult(
        enqueued,
        failures,
        human_controls,
        expired_waits,
        controls,
        attempts,
        usage_retries,
        automatic_retries,
    )


__all__ = [
    "AttemptRecovery",
    "ReconcileResult",
    "ReconcileStore",
    "reconcile_once",
]
