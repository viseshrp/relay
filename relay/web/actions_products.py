"""Persistence adapter for hashed named artifacts and immutable caches."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from hashlib import sha256
import json
from pathlib import Path
import shutil
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from relay.errors import NodeExecutionError, RelayError
from relay.execution.action_products import (
    CACHE_MODES,
    QUOTA,
    cache_mode,
    capture,
    checked_path,
    restore,
    verify,
)
from relay.execution.runner import AttemptContext, ExecutionOutcome, OutcomeKind
from relay.execution.state import EventSource
from relay.workflows.schema import ActionsStepNode


def execute_product(
    context: AttemptContext,
    reference: str,
    inputs: Mapping[str, Any],
    values: Mapping[str, Any],
    node: ActionsStepNode,
) -> ExecutionOutcome:
    from relay.web.models import ActionsArtifact, ActionsCache, Run

    run = Run.objects.get(pk=context.attempt.run_id)
    project_id = str(run.project.pk)
    name = str(inputs.get("name", "artifact"))
    if not name or len(name) > 256 or any(char in name for char in "/\\\x00"):
        message = "Product names must be nonempty and cannot contain path separators."
        raise NodeExecutionError(message)
    if reference == "relay/upload-artifact@v1":
        if ActionsArtifact.objects.filter(run_id=run.pk, name=name).exists():
            message = "Artifact names are immutable within a run."
            raise NodeExecutionError(message)
        try:
            days = int(str(inputs.get("retention-days", "0")))
        except ValueError:
            message = "Artifact retention-days must be an integer."
            raise NodeExecutionError(message) from None
        if not 0 <= days <= 365:
            message = "Artifact retention-days must be between 0 and 365."
            raise NodeExecutionError(message)
        directory, manifest, size, digest = capture(
            context.worktree, str(inputs.get("path", "")).splitlines(), "artifacts", str(run.pk)
        )
        artifact = ActionsArtifact.objects.create(
            run=run,
            attempt_id=context.attempt.attempt_id,
            name=name,
            directory=str(directory),
            manifest=manifest,
            bytes=size,
            digest=digest,
            expires_at=timezone.now() + timedelta(days=days) if days else None,
        )
        return ExecutionOutcome(
            OutcomeKind.SUCCEEDED,
            outputs={"artifact-id": str(artifact.pk), "artifact-digest": digest},
        )
    if reference == "relay/download-artifact@v1":
        source_run = str(inputs.get("run-id", run.pk))
        artifact = ActionsArtifact.objects.filter(
            run_id=source_run, run__project_id=project_id, name=name
        ).first()
        if artifact is None or (artifact.expires_at and artifact.expires_at <= timezone.now()):
            message = "The named artifact is unavailable."
            raise NodeExecutionError(message)
        verify(Path(artifact.directory), artifact.manifest, "artifacts", source_run)
        target = checked_path(context.worktree, str(inputs.get("path", ".")), restore=True)
        restore(Path(artifact.directory), artifact.manifest, target)
        return ExecutionOutcome(OutcomeKind.SUCCEEDED, outputs={"download-path": str(target)})
    key = str(inputs.get("key", ""))
    if not key or len(key) > 512:
        message = "Cache keys must contain 1 to 512 characters."
        raise NodeExecutionError(message)
    patterns = str(inputs.get("path", "")).splitlines()
    version = sha256(json.dumps(patterns).encode()).hexdigest()
    capability = CACHE_MODES[cache_mode(node.workflow, node.job)]
    outputs = {"cache-hit": "false", "cache-primary-key": key, "cache-matched-key": ""}
    if reference != "relay/save-cache@v1" and "read" in capability:
        candidates = ActionsCache.objects.filter(
            project_id=project_id, version=version, namespace="project"
        )
        cache = candidates.filter(key=key).first()
        if cache is None:
            for prefix in [key, *str(inputs.get("restore-keys", "")).splitlines()]:
                cache = candidates.filter(key__startswith=prefix).order_by("-created_at").first()
                if cache:
                    break
        if cache:
            try:
                verify(Path(cache.directory), cache.manifest, "caches", project_id)
                restore(Path(cache.directory), cache.manifest, context.worktree)
            except OSError:
                context.runtime.append_attempt_event(
                    context.attempt.attempt_id,
                    "actions.warning",
                    EventSource.SYSTEM,
                    {"message": "Cache restore failed; continuing without a cache hit."},
                )
            else:
                ActionsCache.objects.filter(pk=cache.pk).update(accessed_at=timezone.now())
                outputs.update(
                    {
                        "cache-hit": "true" if cache.key == key else "false",
                        "cache-matched-key": cache.key,
                    }
                )
    if reference == "relay/cache@v1":
        from relay.execution.action_files import atomic_state, read_state
        from relay.web.actions_repository import job_state_path
        from relay.web.models import NodeRun

        job = NodeRun.objects.get(run_id=run.pk, scope_path=node.state_scope)
        path = job_state_path(str(job.pk))
        state = read_state(path)
        state.setdefault("cache_posts", []).append(
            {"inputs": dict(inputs), "node": node.model_dump(mode="json", by_alias=True)}
        )
        atomic_state(path, state)
    elif reference == "relay/save-cache@v1" and "write" in capability:
        if not ActionsCache.objects.filter(
            project_id=project_id, key=key, version=version, namespace="project"
        ).exists():
            directory, manifest, size, _ = capture(context.worktree, patterns, "caches", project_id)
            try:
                with transaction.atomic():
                    ActionsCache.objects.create(
                        project_id=project_id,
                        key=key,
                        version=version,
                        namespace="project",
                        directory=str(directory),
                        manifest=manifest,
                        bytes=size,
                    )
            except IntegrityError:
                verify(directory, manifest, "caches", project_id)
                shutil.rmtree(directory)
            total = sum(
                ActionsCache.objects.filter(project_id=project_id).values_list("bytes", flat=True)
            )
            for row in ActionsCache.objects.filter(project_id=project_id).order_by(
                "accessed_at", "created_at"
            ):
                if total <= QUOTA:
                    break
                verify(Path(row.directory), row.manifest, "caches", project_id)
                shutil.rmtree(row.directory)
                total -= row.bytes
                row.delete()
    return ExecutionOutcome(OutcomeKind.SUCCEEDED, outputs=outputs)


def expire_artifacts() -> int:
    """Expire optional named products only after verifying ownership and hashes."""
    from .models import ActionsArtifact

    expired = 0
    for artifact in ActionsArtifact.objects.filter(required=False, expires_at__lte=timezone.now())[
        :100
    ]:
        directory = Path(artifact.directory)
        try:
            verify(directory, artifact.manifest, "artifacts", str(artifact.run_id))
            shutil.rmtree(directory)
        except (RelayError, OSError):
            # Keep unverifiable bytes and their record available for owner inspection.
            continue
        artifact.delete()
        expired += 1
    return expired
