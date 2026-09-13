"""Durable commit-then-enqueue dispatch and idempotent attempt claims."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
import logging
from typing import Protocol

from relay.errors import DispatchError, RelayError

LOGGER = logging.getLogger(__name__)


class ClaimDisposition(str, Enum):
    """Why a dequeued Huey token did or did not create an attempt."""

    CLAIMED = "claimed"
    BUSY = "busy"
    IGNORED = "ignored"


@dataclass(frozen=True, slots=True)
class ClaimedAttempt:
    """Durable attempt and worktree facts returned by the winning claim."""

    claim_token: str
    attempt_id: str
    attempt_number: int
    worker_id: str
    run_id: str
    node_run_id: str
    project_path: str
    primary_worktree: str
    scope_path: str
    node_id: str
    node_type: str
    frozen_def: Mapping[str, object]
    inputs: Mapping[str, object]
    upstream_outputs: Mapping[str, Mapping[str, object]]
    run_metadata: Mapping[str, object]
    prompt_contents: tuple[str, ...]
    route: Mapping[str, object]
    subworkflows: Mapping[str, object]
    writes: bool
    starting_head: str
    recorded_head: str


@dataclass(frozen=True, slots=True)
class ClaimResult:
    """Atomic claim outcome; `attempt` exists only for the winner."""

    disposition: ClaimDisposition
    attempt: ClaimedAttempt | None = None


class DispatchStore(Protocol):
    """Persistence operations needed by the Huey dispatch adapter."""

    def create_dispatch(self, node_run_id: str) -> str: ...

    def mark_dispatch_enqueued(self, claim_token: str) -> None: ...

    def claim_dispatch(self, claim_token: str, worker_id: str) -> ClaimResult: ...

    def mark_dispatch_consumed(self, claim_token: str) -> None: ...


def dispatch_node(
    store: DispatchStore,
    node_run_id: str,
    enqueue: Callable[[str], object],
) -> str:
    """Commit durable intent, enqueue only the token, then record enqueue time."""
    token = store.create_dispatch(node_run_id)
    try:
        enqueue(token)
        store.mark_dispatch_enqueued(token)
    except RelayError:
        raise
    except Exception:
        LOGGER.exception("Huey enqueue failed", extra={"claim_token": token})
        message = "Relay recorded dispatch intent but could not enqueue it."
        raise DispatchError(
            message,
            context={"node": node_run_id},
            next_action="Keep Relay running; reconciliation will repair unstarted delivery.",
        ) from None
    return token


def claim_node_attempt(store: DispatchStore, claim_token: str, worker_id: str) -> ClaimResult:
    """Atomically claim a token, acquire admission, and create one attempt."""
    return store.claim_dispatch(claim_token, worker_id)


__all__ = [
    "ClaimDisposition",
    "ClaimResult",
    "ClaimedAttempt",
    "DispatchStore",
    "claim_node_attempt",
    "dispatch_node",
]
