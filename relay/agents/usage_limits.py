"""Authoritative provider limits, separate from context-token accounting."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import math

from relay.constants import PROVIDER_USAGE_WINDOW_MAX_CHARS


@dataclass(frozen=True, slots=True)
class ProviderUsageLimit:
    """A rejected usage window; an absent reset never authorizes a retry."""

    reset_at: datetime | None = None
    window: str | None = None

    def payload(self) -> dict[str, object]:
        return {
            "reset_at": self.reset_at.isoformat() if self.reset_at is not None else None,
            "window": self.window,
        }


def claude_usage_limit(metadata: object) -> ProviderUsageLimit | None:
    """Read Claude's namespaced SDK metadata, never human-readable limit text."""
    if not isinstance(metadata, Mapping) or metadata.get("private") is True:
        return None
    info = metadata.get("_claude/rateLimit")
    if not isinstance(info, Mapping) or info.get("status") != "rejected":
        return None
    reset = info.get("resetsAt")
    reset_at = None
    if (
        isinstance(reset, (int, float))
        and not isinstance(reset, bool)
        and (not isinstance(reset, float) or math.isfinite(reset))
    ):
        try:
            candidate = datetime.fromtimestamp(reset, tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            pass
        else:
            # A stale timestamp cannot cause an immediate failure/retry loop.
            if candidate > datetime.now(timezone.utc):
                reset_at = candidate
    window = info.get("rateLimitType")
    label = (
        window
        if isinstance(window, str) and len(window) <= PROVIDER_USAGE_WINDOW_MAX_CHARS
        else None
    )
    return ProviderUsageLimit(reset_at, label)
