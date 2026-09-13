"""Django persistence adapters used by Relay application services."""

from __future__ import annotations

from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone

from relay.errors import PersistenceError, ProjectRelinkError
from relay.projects.identity import ProjectIdentity
from relay.projects.service import ProjectRecord

from .models import Project, ProjectRelink


def _text_field(project: Project, name: str) -> str:
    value = getattr(project, name)
    if not isinstance(value, str):
        message = f"Stored project field {name} is not text."
        raise PersistenceError(message)
    return value


def _set_field(project: Project, name: str, value: object) -> None:
    """Assign through a Django descriptor after application-level validation."""
    setattr(project, name, value)


def _record(project: Project) -> ProjectRecord:
    return ProjectRecord(
        id=str(project.pk),
        canonical_path=_text_field(project, "canonical_path"),
        display_name=_text_field(project, "display_name"),
        git_root=_text_field(project, "git_root"),
    )


def _require_project(project: Project | None, old_path: str) -> Project:
    if project is None:
        message = f"No registered project matches {old_path}."
        raise ProjectRelinkError(message)
    return project


def _reject_duplicate(project: Project, new_path: str) -> None:
    if Project.objects.exclude(pk=project.pk).filter(canonical_path=new_path).exists():
        message = f"A project is already registered at {new_path}."
        raise ProjectRelinkError(message)


class DjangoProjectStore:
    """Short-transaction project storage backed by the central SQLite DB."""

    def register(self, identity: ProjectIdentity) -> ProjectRecord:
        try:
            project, _created = Project.objects.update_or_create(
                canonical_path=identity.canonical_path,
                defaults={
                    "display_name": identity.display_name,
                    "git_root": identity.git_root,
                    "last_opened_at": timezone.now(),
                },
            )
        except DatabaseError:
            message = "Relay could not register the current project."
            raise PersistenceError(message) from None
        return _record(project)

    def list_projects(self) -> list[ProjectRecord]:
        try:
            projects = Project.objects.order_by("-last_opened_at", "display_name")
            return [_record(project) for project in projects]
        except DatabaseError:
            message = "Relay could not list registered projects."
            raise PersistenceError(message) from None

    def relink(self, old_path: str, identity: ProjectIdentity) -> ProjectRecord:
        try:
            with transaction.atomic():
                project = _require_project(
                    Project.objects.select_for_update().filter(canonical_path=old_path).first(),
                    old_path,
                )
                _reject_duplicate(project, identity.canonical_path)
                previous = _text_field(project, "canonical_path")
                _set_field(project, "canonical_path", identity.canonical_path)
                _set_field(project, "display_name", identity.display_name)
                _set_field(project, "git_root", identity.git_root)
                _set_field(project, "last_opened_at", timezone.now())
                project.save(
                    update_fields=(
                        "canonical_path",
                        "display_name",
                        "git_root",
                        "last_opened_at",
                    )
                )
                ProjectRelink.objects.create(
                    project=project,
                    old_path=previous,
                    new_path=identity.canonical_path,
                )
                return _record(project)
        except ProjectRelinkError:
            raise
        except (DatabaseError, IntegrityError):
            message = "Relay could not relink the project."
            raise PersistenceError(message) from None
