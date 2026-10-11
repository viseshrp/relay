"""Deterministic, test-server-only records for visual and boundary regressions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from django.db.models import Q
import yaml

from relay.web.models import (
    Artifact,
    HumanInteraction,
    NodeAttempt,
    NodeRun,
    Project,
    Run,
    RunEvent,
    RunSnapshot,
)
from relay.workflows.schema import ActionsJobNode, ActionsStepNode
from tests.support import create_project, git

PREFIX = "relay/ui-fixture/"
WHEN = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)


def clear_ui_fixtures() -> None:
    """Delete only records carrying this disposable server fixture's namespace."""
    projects = Project.objects.filter(canonical_path__contains="/ui-fixture/project-")
    Run.objects.filter(Q(run_branch__startswith=PREFIX) | Q(project__in=projects)).delete()
    projects.delete()


def seed_ui_fixture(root: Path, *, worst: bool) -> dict[str, object]:
    """Toggle between a compact demo and the audit's hostile display values."""
    clear_ui_fixtures()
    names = (
        ["a-very-long-project-name-" * 3, "王秀英-客户端", "نور-الهدى", "j"] if worst else ["Demo"]
    )
    projects = []
    for index, name in enumerate(names):
        project = (
            create_project(root / "ui-fixture" / f"project-{index}")
            if not (root / "ui-fixture" / f"project-{index}" / ".git").exists()
            else None
        )
        if project is None:
            from relay.projects.service import register_current_project
            from relay.web.repositories import DjangoProjectStore

            record = register_current_project(
                DjangoProjectStore(), root / "ui-fixture" / f"project-{index}"
            )
            project_id, repository = record.id, Path(record.canonical_path)
        else:
            project_id, repository = project.project_id, project.repository
        Project.objects.filter(pk=project_id).update(display_name=name[:72])
        projects.append((project_id, repository))
    project_id, repository = projects[0]
    job_ids = (
        ["job_" + "x" * 86] + [f"check_{index:02}" for index in range(1, 41)]
        if worst
        else ["build", "test"]
    )
    jobs = {
        job_id: {
            "name": f"Check {index + 1}" + (" · 王秀英 نور 👩‍💻 " * 12 if worst else ""),
            "steps": [{"id": "verify", "name": "Verify output", "run": "echo 'Completed check'"}],
        }
        for index, job_id in enumerate(job_ids)
    }
    workflow = {
        "name": "Visual <script> ** &amp; workflow" if worst else "Demo workflow",
        "on": "workflow_dispatch",
        "jobs": jobs,
    }
    text = yaml.safe_dump(workflow, sort_keys=False, allow_unicode=True)
    source = repository / ".relay/workflows/visual.yaml"
    source.write_text(text, encoding="utf-8")
    if git(repository, "status", "--porcelain", "--", ".relay/workflows/visual.yaml"):
        git(repository, "add", "--", ".relay/workflows/visual.yaml")
        git(repository, "commit", "-m", "Save isolated UI fixture workflow")
    head = git(repository, "rev-parse", "HEAD")
    title = (
        ("Ticket owner@example.test 王秀英 نور 👩‍💻 ** &amp; <script> " * 60)[:2000]
        if worst
        else "Verify the release candidate"
    )

    def run_record(index: int, status: str, *, waiting: bool = False) -> Run:
        run_id = uuid5(NAMESPACE_URL, f"relay-ui-fixture-{index}")
        run = Run.objects.create(
            id=run_id,
            project_id=project_id,
            workflow_key="visual.yaml",
            number=index,
            title=title if index == 1 else f"Release check {index}",
            status=status,
            source_branch="feat/release-candidate",
            source_commit=head,
            recorded_head=head,
            run_branch=f"{PREFIX}{index}",
            worktree_path=str(root / "ui-fixture" / "runs" / str(run_id)),
            launcher="local",
            created_at=WHEN,
            started_at=None if status == "pending" else WHEN,
            ended_at=WHEN + timedelta(hours=67, minutes=11, seconds=36)
            if status in {"failed", "succeeded", "canceled"}
            else None,
            dispatch_paused_seconds=3600 if index == 1 else 0,
            failure_code="command_failed" if index == 1 else None,
            actions_state={
                "display_names": {f"root.{key}": value["name"] for key, value in jobs.items()}
            },
        )
        RunSnapshot.objects.create(
            run=run,
            workflow_yaml=text,
            relay_version="test-fixture",
            semantics_revision="relay-local-1",
        )
        if waiting:
            node = NodeRun.objects.create(
                run=run,
                node_id="approval",
                scope_path="root.approval",
                node_type="human_wait",
                status="waiting",
                frozen_def={
                    "type": "human_wait",
                    "prompt": "Approve the release?",
                    "deadline": "10d",
                },
            )
            attempt = NodeAttempt.objects.create(
                node_run=node,
                attempt_number=1,
                status="waiting",
                worker_id="test-fixture",
                starting_head=head,
                started_at=WHEN,
            )
            HumanInteraction.objects.create(
                run=run,
                node_run=node,
                attempt=attempt,
                kind="wait",
                request_payload={
                    "prompt": "Approve the release?",
                    "options": ["Approve", "Request changes"],
                    "deadline_source": "step",
                },
                deadline=WHEN + timedelta(days=10),
            )
        return run

    main = run_record(1, "failed")
    for index, (job_id, job) in enumerate(jobs.items()):
        scope = f"root.{job_id}"
        status = "failed" if index == 0 else "succeeded"
        node = NodeRun.objects.create(
            run=main,
            node_id=job_id,
            scope_path=scope,
            node_type="actions_job",
            status=status,
            frozen_def=ActionsJobNode(job_id=job_id, job=job, workflow=workflow).model_dump(
                mode="json"
            ),
        )
        NodeAttempt.objects.create(
            node_run=node,
            attempt_number=1,
            status=status,
            worker_id="test-fixture",
            starting_head=head,
            started_at=WHEN,
            ended_at=main.ended_at,
        )
        step = NodeRun.objects.create(
            run=main,
            node_id="verify",
            scope_path=f"{scope}.verify",
            parent_scope_path=scope,
            node_type="actions_step",
            status=status,
            frozen_def=ActionsStepNode(
                job_id=job_id,
                step_id="verify",
                step=job["steps"][0],
                job=job,
                workflow=workflow,
                index=0,
            ).model_dump(mode="json"),
        )
        attempt = NodeAttempt.objects.create(
            node_run=step,
            attempt_number=1,
            status=status,
            worker_id="test-fixture",
            starting_head=head,
            started_at=WHEN,
            ended_at=main.ended_at,
            stop_reason="failed" if index == 0 else "completed",
            exit_code=3 if index == 0 else 0,
        )
        line_count = 20_000 if worst and index == 0 else 3
        RunEvent.objects.bulk_create(
            [
                RunEvent(
                    run=main,
                    node_run=step,
                    attempt=attempt,
                    type="command.stdout",
                    source="node",
                    ts=WHEN,
                    payload={
                        "scope_path": step.scope_path,
                        "attempt_number": 1,
                        "chunk": "".join(
                            f"{line:05} Check output\n"
                            for line in range(start, min(start + 100, line_count))
                        ),
                    },
                )
                for start in range(0, line_count, 100)
            ]
        )
        RunEvent.objects.create(
            run=main,
            node_run=node,
            type="attempt.ended",
            source="node",
            ts=WHEN,
            payload={"scope_path": scope, "status": status},
        )
        for kind in ("commits", "worktree_diff"):
            Artifact.objects.create(
                attempt=attempt,
                declared_name=kind,
                source_path=kind,
                retained_path=str(root / "ui-fixture" / "empty"),
                sha256=sha256(b"").hexdigest(),
                bytes=0,
                media_type="text/plain",
                preservation_state="preserved",
            )
    approval = run_record(2, "paused_wait", waiting=True)
    run_record(3, "succeeded")
    run_record(4, "canceled")
    running = run_record(5, "running")
    NodeRun.objects.create(
        run=running,
        node_id=job_ids[0],
        scope_path=f"root.{job_ids[0]}",
        node_type="actions_job",
        status="running",
        frozen_def=ActionsJobNode(
            job_id=job_ids[0], job=jobs[job_ids[0]], workflow=workflow
        ).model_dump(mode="json"),
    )
    RunEvent.objects.create(
        run=running,
        type="artifact.preserved",
        source="run",
        ts=WHEN,
        payload={},
    )
    for index in range(6, 155 if worst else 7):
        run_record(index, "pending")
    Project.objects.filter(pk=project_id).update(next_run_number=155 if worst else 7)
    return {
        "project": str(project_id),
        "run": str(main.pk),
        "approval": str(approval.pk),
        "running": str(running.pk),
        "job": f"root.{job_ids[0]}",
        "workflow": "visual.yaml",
        "worst": worst,
    }
