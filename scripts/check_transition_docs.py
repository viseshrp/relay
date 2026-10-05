"""Fail when documented execution transitions differ from the engine tables."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from relay.execution.state import (
    CONTROL_TRANSITIONS,
    INTERACTION_TRANSITIONS,
    NODE_TRANSITIONS,
    RUN_TRANSITIONS,
    ChoiceEnum,
    Transition,
)

DOC_PATH = Path("docs/execution.md")
TABLES: dict[str, Sequence[Transition]] = {
    "run": RUN_TRANSITIONS,
    "node": NODE_TRANSITIONS,
    "interaction": INTERACTION_TRANSITIONS,
    "control": CONTROL_TRANSITIONS,
}


def _text(value: str | ChoiceEnum | None) -> str:
    if isinstance(value, ChoiceEnum):
        return value.value
    return value if value is not None else "(start)"


def _expected_rows(transitions: Sequence[Transition]) -> list[str]:
    return [
        "| "
        + " | ".join(
            (
                f"`{_text(item.source)}`",
                f"`{item.action}`",
                f"`{item.guard}`",
                f"`{_text(item.target)}`",
                f"`{item.event}`",
            )
        )
        + " |"
        for item in transitions
    ]


def _documented_rows(document: str, name: str) -> list[str]:
    start = f"<!-- relay-transitions:{name}:start -->"
    end = f"<!-- relay-transitions:{name}:end -->"
    if start not in document or end not in document:
        message = f"Missing transition markers for {name}."
        raise SystemExit(message)
    body = document.split(start, 1)[1].split(end, 1)[0]
    lines = [line.strip() for line in body.splitlines() if line.strip().startswith("|")]
    return lines[2:]


def main() -> None:
    document = DOC_PATH.read_text(encoding="utf-8")
    mismatches = [
        name
        for name, transitions in TABLES.items()
        if _documented_rows(document, name) != _expected_rows(transitions)
    ]
    if mismatches:
        message = "Transition documentation differs for: " + ", ".join(mismatches)
        raise SystemExit(message)


if __name__ == "__main__":
    main()
