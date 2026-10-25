"""Django persistence for owner-approved workflow notes."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
import uuid

from django.db import DatabaseError, models, transaction

from relay.errors import ConfigError, PersistenceError, ProjectDiscoveryError
from relay.workflows.loader import workflow_key_parts
from relay.workflows.notes import NOTES_PER_WORKFLOW_MAX, FrozenNote, NoteDraft

from .models import Run, WorkflowNote


def canonical_workflow_key(workflow_key: str) -> str:
    """`review` and `review.yaml` name the same workflow's notes."""
    return "/".join(workflow_key_parts(workflow_key))


def _created_at(note: WorkflowNote) -> str:
    value = getattr(note, "created_at")  # noqa: B009 - validated Django accessor
    if not isinstance(value, datetime):
        message = "A stored workflow note has an invalid creation time."
        raise PersistenceError(message)
    return value.isoformat()


def _optional_relation(instance: models.Model, name: str) -> str | None:
    """A cleaned-up evidence run leaves its note with no run link."""
    value = getattr(instance, f"{name}_id")
    return str(value) if value is not None else None


def _record(note: WorkflowNote) -> dict[str, object]:
    return {
        "id": str(note.pk),
        "workflow_key": note.workflow_key,
        "cue": note.cue,
        "lesson": note.lesson,
        "evidence": note.evidence,
        "confidence": note.confidence,
        "evidence_run_id": _optional_relation(note, "evidence_run"),
        "archived": note.archived,
        "created_at": _created_at(note),
    }


def _uuid(value: str, resource: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError:
        message = f"The requested {resource} does not exist."
        raise ProjectDiscoveryError(message, context={resource: value}) from None


class DjangoWorkflowNoteStore:
    """Notes are scoped to one project and one canonical workflow key."""

    def list_notes(
        self, project_id: str, workflow_key: str, *, archived: bool = False
    ) -> list[dict[str, object]]:
        key = canonical_workflow_key(workflow_key)
        try:
            rows = WorkflowNote.objects.filter(
                project_id=project_id, workflow_key=key, archived=archived
            ).order_by("created_at", "pk")
            return [_record(row) for row in rows[:NOTES_PER_WORKFLOW_MAX]]
        except DatabaseError:
            message = "Relay could not read workflow notes."
            raise PersistenceError(message, context={"workflow": key}) from None

    def create_note(
        self, project_id: str, workflow_key: str, draft: NoteDraft
    ) -> dict[str, object]:
        key = canonical_workflow_key(workflow_key)
        try:
            with transaction.atomic():
                active = WorkflowNote.objects.filter(
                    project_id=project_id, workflow_key=key, archived=False
                ).count()
                if active >= NOTES_PER_WORKFLOW_MAX:
                    message = f"A workflow can keep at most {NOTES_PER_WORKFLOW_MAX} active notes."
                    raise ConfigError(message, next_action="Archive notes that no longer apply.")
                run = None
                if draft.evidence_run_id is not None:
                    run = Run.objects.filter(
                        pk=_uuid(draft.evidence_run_id, "run"), project_id=project_id
                    ).first()
                    if run is None:
                        message = "The evidence run does not exist in this project."
                        raise ConfigError(message, context={"run": draft.evidence_run_id})
                note = WorkflowNote.objects.create(
                    project_id=project_id,
                    workflow_key=key,
                    cue=draft.cue,
                    lesson=draft.lesson,
                    evidence=draft.evidence,
                    confidence=draft.confidence,
                    evidence_run=run,
                )
                return _record(note)
        except DatabaseError:
            message = "Relay could not save the workflow note."
            raise PersistenceError(message, context={"workflow": key}) from None

    def archive_note(self, project_id: str, workflow_key: str, note_id: str) -> dict[str, object]:
        key = canonical_workflow_key(workflow_key)
        try:
            with transaction.atomic():
                note = (
                    WorkflowNote.objects.select_for_update()
                    .filter(pk=_uuid(note_id, "note"), project_id=project_id, workflow_key=key)
                    .first()
                )
                if note is None:
                    message = "The requested note does not exist."
                    raise ProjectDiscoveryError(message, context={"note": note_id})
                note.archived = True
                note.save(update_fields=("archived",))
                return _record(note)
        except DatabaseError:
            message = "Relay could not archive the workflow note."
            raise PersistenceError(message, context={"note": note_id}) from None

    def launch_notes(
        self, project_id: str, workflow_key: str, note_ids: Sequence[str]
    ) -> tuple[FrozenNote, ...]:
        """Return active notes in the owner's chosen order, or reject the launch."""
        if not note_ids:
            return ()
        key = canonical_workflow_key(workflow_key)
        ids = [_uuid(value, "note") for value in note_ids]
        try:
            rows = {
                str(row.pk): row
                for row in WorkflowNote.objects.filter(
                    pk__in=ids, project_id=project_id, workflow_key=key, archived=False
                )
            }
        except DatabaseError:
            message = "Relay could not read the selected workflow notes."
            raise PersistenceError(message, context={"workflow": key}) from None
        missing = [value for value in ids if value not in rows]
        if missing:
            message = "A selected note is archived or belongs to another workflow."
            raise ConfigError(message, context={"note": missing[0]})
        return tuple(
            FrozenNote(
                id=value,
                cue=rows[value].cue,
                lesson=rows[value].lesson,
                evidence=rows[value].evidence,
                confidence=rows[value].confidence,
            )
            for value in ids
        )


__all__ = ["DjangoWorkflowNoteStore", "canonical_workflow_key"]
