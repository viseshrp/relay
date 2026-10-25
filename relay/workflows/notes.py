"""Owner-approved lessons a workflow can carry into later runs.

A note records when it applies (`cue`), what to do (`lesson`), and what showed
it (`evidence`). A launch may freeze selected notes into its snapshot as one
separate prompt block, so prompt files keep their exact bytes and retries see
the same text.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from hashlib import sha256

from relay.errors import ConfigError, PersistenceError

NOTE_CUE_MAX_CHARS = 500
NOTE_LESSON_MAX_CHARS = 4000
NOTE_EVIDENCE_MAX_CHARS = 2000
NOTES_PER_WORKFLOW_MAX = 100
NOTES_PER_LAUNCH_MAX = 10
NOTE_CONFIDENCE = ("low", "medium", "high")
NOTES_BLOCK_HEADER = "Relay workflow notes (owner-approved lessons from earlier runs):"


@dataclass(frozen=True, slots=True)
class NoteDraft:
    """Validated note fields before persistence assigns identity."""

    cue: str
    lesson: str
    evidence: str
    confidence: str | None = None
    evidence_run_id: str | None = None


@dataclass(frozen=True, slots=True)
class FrozenNote:
    """The exact note text a launch captured."""

    id: str
    cue: str
    lesson: str
    evidence: str
    confidence: str | None


def _text(body: Mapping[str, object], name: str, limit: int) -> str:
    value = body.get(name)
    if not isinstance(value, str) or not value.strip():
        message = f"A workflow note needs a nonempty {name}."
        raise ConfigError(
            message,
            next_action="Describe when the note applies, what to do, and what showed it.",
        )
    value = value.strip()
    if len(value) > limit:
        message = f"A workflow note {name} is limited to {limit} characters."
        raise ConfigError(message)
    return value


def validate_note(body: Mapping[str, object]) -> NoteDraft:
    """Refuse a note unless cue, lesson, and evidence are all present.

    For example, `{"cue": "Tests time out", "lesson": "Run the fast suite
    first", "evidence": "Run #4 timed out in the full suite"}` is accepted;
    the same body without `evidence` is rejected.
    """
    confidence = body.get("confidence")
    if confidence is not None and confidence not in NOTE_CONFIDENCE:
        message = "Note confidence must be low, medium, high, or omitted."
        raise ConfigError(message)
    run_id = body.get("evidence_run_id")
    if run_id is not None and (not isinstance(run_id, str) or not run_id):
        message = "evidence_run_id must be a run ID or omitted."
        raise ConfigError(message)
    return NoteDraft(
        cue=_text(body, "cue", NOTE_CUE_MAX_CHARS),
        lesson=_text(body, "lesson", NOTE_LESSON_MAX_CHARS),
        evidence=_text(body, "evidence", NOTE_EVIDENCE_MAX_CHARS),
        confidence=confidence if isinstance(confidence, str) else None,
        evidence_run_id=run_id if isinstance(run_id, str) else None,
    )


def launch_note_ids(value: object) -> tuple[str, ...]:
    """Accept an optional list of distinct note IDs, up to the launch limit."""
    if value is None:
        return ()
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not item for item in value)
        or len(set(value)) != len(value)
    ):
        message = "notes must be a list of distinct workflow note IDs."
        raise ConfigError(message)
    if len(value) > NOTES_PER_LAUNCH_MAX:
        message = f"A launch can include at most {NOTES_PER_LAUNCH_MAX} workflow notes."
        raise ConfigError(message)
    return tuple(value)


def notes_block(notes: Sequence[FrozenNote]) -> str:
    """Render notes in their chosen order as one plain-text block."""
    lines = [NOTES_BLOCK_HEADER]
    for index, note in enumerate(notes, start=1):
        confidence = f" (confidence: {note.confidence})" if note.confidence else ""
        lines += [
            "",
            f"{index}. When: {note.cue}{confidence}",
            f"   Do: {note.lesson}",
            f"   Because: {note.evidence}",
        ]
    lines += [
        "",
        (
            "Apply a note only when its situation matches this task; the step's own "
            "instructions take precedence."
        ),
    ]
    return "\n".join(lines) + "\n"


def frozen_notes(notes: Sequence[FrozenNote]) -> dict[str, object] | None:
    """Return the snapshot record for selected notes, or `None` for no notes."""
    if not notes:
        return None
    text = notes_block(notes)
    return {
        "notes": [asdict(note) for note in notes],
        "text": text,
        "sha256": sha256(text.encode("utf-8")).hexdigest(),
    }


def frozen_notes_text(launch_defaults: Mapping[str, object]) -> str | None:
    """Read the captured block back, verifying it still matches its hash."""
    record = launch_defaults.get("workflow_notes")
    if record is None:
        return None
    text = record.get("text") if isinstance(record, Mapping) else None
    digest = record.get("sha256") if isinstance(record, Mapping) else None
    if not isinstance(text, str) or digest != sha256(text.encode("utf-8")).hexdigest():
        message = "The captured workflow notes do not match their recorded hash."
        raise PersistenceError(message)
    return text


__all__ = [
    "NOTES_PER_LAUNCH_MAX",
    "NOTES_PER_WORKFLOW_MAX",
    "FrozenNote",
    "NoteDraft",
    "frozen_notes",
    "frozen_notes_text",
    "launch_note_ids",
    "notes_block",
    "validate_note",
]
