"""Closest-match suggestions for misspelled names in validation messages."""

from __future__ import annotations

from collections.abc import Iterable
from difflib import get_close_matches


def closest(name: str, candidates: Iterable[str]) -> str | None:
    """Return the single nearest candidate, ignoring case, or None."""
    options = {item.lower(): item for item in candidates}
    match = get_close_matches(name.lower(), sorted(options), n=1, cutoff=0.6)
    return options[match[0]] if match else None
