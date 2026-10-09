"""Transactional persistence adapter for project default overrides."""

from __future__ import annotations

from django.db import DatabaseError, transaction

from relay.errors import PersistenceError, ProjectDiscoveryError, SettingsConflictError
from relay.owner_settings import revision
from relay.web.models import Project


class DjangoSettingsStore:
    def project_defaults(self, project_id: str) -> dict[str, object]:
        try:
            row = Project.objects.filter(pk=project_id).first()
            if row is None:
                message = "The requested project does not exist."
                raise ProjectDiscoveryError(message)
            value = row.defaults
            if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
                message = "Saved project defaults are invalid."
                raise PersistenceError(message)
        except DatabaseError:
            message = "Relay could not read project defaults."
            raise PersistenceError(message) from None
        else:
            return value

    def save_project_defaults(
        self, project_id: str, values: dict[str, object], expected_revision: str
    ) -> None:
        try:
            with transaction.atomic():
                row = Project.objects.select_for_update().filter(pk=project_id).first()
                if row is None:
                    message = "The requested project does not exist."
                    raise ProjectDiscoveryError(message)
                if revision(self.project_defaults(project_id)) != expected_revision:
                    message = "Project defaults changed in another window. Reload before saving."
                    raise SettingsConflictError(message)
                row.defaults = values
                row.save(update_fields=("defaults",))
        except DatabaseError:
            message = "Relay could not save project defaults."
            raise PersistenceError(message) from None

    def storage_usage(self, project_id: str) -> dict[str, object]:
        from dataclasses import asdict
        from pathlib import Path

        from django.db.models import Sum

        from relay.execution.state import RunStatus
        from relay.projects.storage import measure_working_copies
        from relay.vcs.git import git_stdout
        from relay.web.models import Artifact, Run

        try:
            project = Project.objects.filter(pk=project_id).first()
            if project is None:
                message = "The requested project does not exist."
                raise ProjectDiscoveryError(message)
            runs = Run.objects.filter(project=project)
            run_ids = frozenset(str(value) for value in runs.values_list("pk", flat=True))
            paths = tuple(
                str(value) for value in runs.values_list("worktree_path", flat=True)[:1000]
            )
            active = runs.exclude(
                status__in=(
                    RunStatus.SUCCEEDED.value,
                    RunStatus.FAILED.value,
                    RunStatus.CANCELED.value,
                    RunStatus.INTERRUPTED.value,
                )
            ).exists()
            artifacts = Artifact.objects.filter(attempt__node_run__run__project=project)
            retained = artifacts.aggregate(total=Sum("bytes"))["total"]
            if retained is not None and not isinstance(retained, int):
                message = "Saved artifact sizes are invalid."
                raise PersistenceError(message)
            root = project.git_root
            if not isinstance(root, str):
                message = "The project repository path is invalid."
                raise PersistenceError(message)
            refs = git_stdout(
                Path(root),
                [
                    "for-each-ref",
                    "--format=%(refname)",
                    "refs/heads/relay/run/",
                    "refs/relay/attempts/",
                ],
            ).splitlines()
            branches = sum(ref.removeprefix("refs/heads/relay/run/") in run_ids for ref in refs)
            attempt_refs = sum(
                ref.startswith("refs/relay/attempts/")
                and ref.removeprefix("refs/relay/attempts/").split("/")[0] in run_ids
                for ref in refs
            )
            usage = measure_working_copies(paths)
            artifact_count = artifacts.count()
        except DatabaseError:
            message = "Relay could not read project storage usage."
            raise PersistenceError(message) from None
        return {
            "runs": len(run_ids),
            "artifacts": artifact_count,
            "artifact_bytes": retained or 0,
            "working_copies": {
                **asdict(usage),
                "truncated": usage.truncated or len(run_ids) > 1000,
            },
            "branches": branches,
            "attempt_refs": attempt_refs,
            "cleanup_blocked": active,
        }
