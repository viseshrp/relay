"""Readers-writer admission rules and durable lock lifecycle ports."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from .state import LockMode


@dataclass(frozen=True, slots=True)
class AdmissionDecision:
    """Pure admission result used inside an atomic claim transaction."""

    allowed: bool
    mode: LockMode
    reason: str | None = None


class LockStore(Protocol):
    def heartbeat_attempt_lock(self, attempt_id: str, worker_id: str) -> bool: ...

    def release_attempt_lock(self, attempt_id: str) -> None: ...


def decide_admission(writes: bool, active_modes: Iterable[str]) -> AdmissionDecision:
    """Allow many readers or exactly one exclusive writer."""
    modes = tuple(active_modes)
    requested = LockMode.WRITE if writes else LockMode.READ
    if writes and modes:
        return AdmissionDecision(False, requested, "a reader or writer is active")
    if not writes and LockMode.WRITE.value in modes:
        return AdmissionDecision(False, requested, "a writer is active")
    return AdmissionDecision(True, requested)


__all__ = ["AdmissionDecision", "LockStore", "decide_admission"]
