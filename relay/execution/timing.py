"""Monotonic attempt deadlines shared by all node executors."""

from __future__ import annotations

import time

from relay.errors import NodeExecutionError

_DURATION_UNITS = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3_600.0}


def duration_seconds(value: str | None) -> float | None:
    """Convert schema-validated `250ms`, `4s`, `3m`, or `2h` to seconds."""
    if value is None:
        return None
    suffix = "ms" if value.endswith("ms") else value[-1]
    number = value[: -len(suffix)]
    try:
        return int(number) * _DURATION_UNITS[suffix]
    except (KeyError, ValueError):
        message = f"Duration {value!r} is not valid."
        raise NodeExecutionError(message) from None


def attempt_deadline(timeout: str | None, inherited: float | None) -> float | None:
    """Return the earlier inherited or node-local monotonic deadline."""
    seconds = duration_seconds(timeout)
    local = time.monotonic() + seconds if seconds is not None else None
    if inherited is None:
        return local
    if local is None:
        return inherited
    return min(inherited, local)


def remaining_seconds(deadline: float | None) -> float | None:
    """Return a nonnegative duration suitable for bounded process waits."""
    return None if deadline is None else max(0.0, deadline - time.monotonic())


__all__ = ["attempt_deadline", "duration_seconds", "remaining_seconds"]
