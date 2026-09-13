"""Durable browser-to-worker control mailbox with leased claims."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
import json
from typing import Protocol

from relay.constants import (
    CONTROL_IDEMPOTENCY_KEY_MAX_CHARS,
    CONTROL_PAYLOAD_MAX_BYTES,
    CONTROL_REQUEST_TTL_SECONDS,
)
from relay.errors import PermissionFlowError

from .state import ControlKind


class ControlResult(str, Enum):
    ACCEPTED = "accepted"
    ALREADY_APPLIED = "already_applied"
    STALE = "stale"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class ClaimedControl:
    """One leased request correlated to the worker's exact attempt."""

    request_id: str
    attempt_id: str
    kind: str
    payload: Mapping[str, object]
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ControlRecovery:
    """Bounded reconciliation counts for observable diagnostics."""

    returned_to_pending: int
    marked_stale: int


class ControlStore(Protocol):
    def submit_control(
        self,
        attempt_id: str,
        kind: str,
        idempotency_key: str,
        payload: Mapping[str, object],
        ttl_seconds: float,
    ) -> ControlResult: ...

    def claim_next_control(
        self,
        attempt_id: str,
        worker_id: str,
        kinds: tuple[str, ...] | None = None,
    ) -> ClaimedControl | None: ...

    def heartbeat_control(self, request_id: str, worker_id: str) -> bool: ...

    def apply_control(self, request_id: str, worker_id: str) -> bool: ...

    def recover_control_claims(self) -> ControlRecovery: ...


def _validate_payload(payload: Mapping[str, object]) -> None:
    try:
        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    except (TypeError, ValueError):
        message = "The control payload must contain JSON-compatible values."
        raise PermissionFlowError(message) from None
    if len(encoded) > CONTROL_PAYLOAD_MAX_BYTES:
        message = "The control payload exceeds Relay's byte limit."
        raise PermissionFlowError(message)


def submit_control(
    store: ControlStore,
    attempt_id: str,
    kind: ControlKind,
    idempotency_key: str,
    payload: Mapping[str, object],
) -> ControlResult:
    """Validate and persist a request; delivery stays with the owning worker."""
    if not idempotency_key or len(idempotency_key) > CONTROL_IDEMPOTENCY_KEY_MAX_CHARS:
        return ControlResult.INVALID
    _validate_payload(payload)
    return store.submit_control(
        attempt_id,
        kind.value,
        idempotency_key,
        payload,
        CONTROL_REQUEST_TTL_SECONDS,
    )


__all__ = [
    "ClaimedControl",
    "ControlRecovery",
    "ControlResult",
    "ControlStore",
    "submit_control",
]
