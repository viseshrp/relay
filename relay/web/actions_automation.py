"""Durable local trigger deliveries and named concurrency admission."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, cast

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from relay.errors import ConfigError, RelayError
from relay.execution.dispatch import notify_dispatch, release_serial_admission
from relay.execution.triggers import filter_ref, occurrences
from relay.vcs.git import run_git
from relay.workflows.actions import expressions
from relay.workflows.actions.language import capture_sources, events, load
from relay.workflows.loader import resolve_workflow_path

from .models import (
    ActionsQueue,
    NodeAttempt,
    NodeRun,
    Project,
    Run,
    TriggerDelivery,
    WorkflowTrigger,
)


def activate(
    project_id: str, relay_root: Path, key: str, event: str, enabled: bool, allow_writers: bool
) -> None:
    source = resolve_workflow_path(relay_root / "workflows", key).read_text(encoding="utf-8")
    document = load(source)
    config = events(document.value).get(event)
    if event not in {"schedule", "push", "repository_dispatch", "workflow_run"} or config is None:
        message = "Select an automatic trigger declared by this workflow."
        raise ConfigError(message)
    if enabled and not allow_writers:
        message = "Activation requires explicit authorization for automatic writing jobs."
        raise ConfigError(message)
    cursor: dict[str, Any] = {"at": timezone.now().isoformat(), "refs": {}}
    if event == "push":
        cursor["refs"] = local_refs(relay_root.parent)
    WorkflowTrigger.objects.update_or_create(
        project_id=project_id,
        workflow_key=key,
        event=event,
        defaults={
            "enabled": enabled,
            "allow_writers": allow_writers,
            "source_hash": activation_hash(relay_root, key),
            "config": {"value": config},
            "cursor": cursor,
            "activated_at": timezone.now(),
        },
    )


def activation_hash(relay_root: Path, key: str) -> str:
    from relay.paths import global_prompts_dir
    from relay.workflows.actions.compiler import sources_hashes
    from relay.workflows.actions.patterns import select_paths

    from .actions_bindings import freeze_bindings

    path = resolve_workflow_path(relay_root / "workflows", key)
    text = path.read_bytes().decode("utf-8")
    hashes = {
        "workflow": sha256(text.encode()).hexdigest(),
        **sources_hashes(capture_sources(load(text, source=path), relay_root.parent)),
    }
    project = Project.objects.filter(git_root=str(relay_root.parent.resolve())).first()
    if project:
        hashes["bindings"] = sha256(
            json.dumps(freeze_bindings(str(project.pk)), sort_keys=True).encode()
        ).hexdigest()
    for label, directory in (
        ("local-prompts", relay_root / "prompts"),
        ("global-prompts", global_prompts_dir()),
    ):
        if directory.exists():
            for prompt in select_paths(directory, ["**"], files_only=True):
                if prompt.stat().st_size > 1_048_576:
                    message = "A trigger prompt source exceeds 1 MiB."
                    raise ConfigError(message)
                hashes[f"{label}:{prompt.relative_to(directory).as_posix()}"] = sha256(
                    prompt.read_bytes()
                ).hexdigest()
    return sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()


def local_refs(repository: Path) -> dict[str, str]:
    output = run_git(
        repository, ["for-each-ref", "--format=%(refname) %(objectname)", "refs/heads", "refs/tags"]
    ).stdout
    return dict(line.split(" ", 1) for line in output.splitlines())


def deliver(trigger: WorkflowTrigger, occurrence: str, payload: dict[str, Any]) -> None:
    if len(json.dumps(payload).encode()) > 65535:
        message = "Trigger payloads are limited to 65535 bytes."
        raise ConfigError(message)
    TriggerDelivery.objects.get_or_create(
        trigger=trigger, occurrence=occurrence, defaults={"payload": payload}
    )


def repository_dispatch(
    project_id: str, event_type: str, payload: dict[str, Any], identity: str
) -> None:
    if (
        not event_type
        or len(event_type) > 100
        or len(payload) > 10
        or not identity
        or len(identity) > 200
    ):
        message = "repository_dispatch requires an event type and at most ten payload properties."
        raise ConfigError(message)
    for trigger in WorkflowTrigger.objects.filter(
        project_id=project_id, event="repository_dispatch", enabled=True
    ):
        config = cast(dict, trigger.config)["value"]
        if not config.get("types") or event_type in config["types"]:
            deliver(
                trigger,
                identity,
                {
                    "event_name": "repository_dispatch",
                    "event": {"action": event_type, "client_payload": payload},
                },
            )


def reconcile() -> None:
    """Idempotent observations; missed schedules produce one latest delivery."""
    now = timezone.now()
    for trigger in WorkflowTrigger.objects.filter(enabled=True).select_related("project")[:100]:
        root = Path(cast(str, cast(Project, trigger.project).git_root)) / ".relay"
        config = cast(dict, trigger.config)["value"]
        cursor = dict(trigger.cursor)
        try:
            if trigger.event == "schedule":
                found = [
                    (identity, instant, item)
                    for item in config
                    for identity, instant in occurrences(
                        item, datetime.fromisoformat(cursor["at"]), now
                    )
                ]
                if found:
                    identity, instant, item = max(found, key=lambda item: item[1])
                    deliver(
                        trigger,
                        identity,
                        {
                            "event_name": "schedule",
                            "event": {"schedule": item["cron"]},
                            "scheduled_at": instant.isoformat(),
                        },
                    )
                cursor["at"] = now.isoformat()
            elif trigger.event == "push":
                refs = local_refs(root.parent)
                for reference, head in refs.items():
                    before = cursor.get("refs", {}).get(reference)
                    if head == before:
                        continue
                    difference = (
                        run_git(
                            root.parent, ["diff", "--name-only", before, head]
                        ).stdout.splitlines()
                        if before
                        else run_git(
                            root.parent, ["ls-tree", "-r", "--name-only", head]
                        ).stdout.splitlines()
                    )
                    if filter_ref(config, reference, difference):
                        deliver(
                            trigger,
                            f"{reference}:{before or ''}:{head}",
                            {
                                "event_name": "push",
                                "ref": reference,
                                "ref_name": reference.split("/", 2)[-1],
                                "ref_type": "tag"
                                if reference.startswith("refs/tags/")
                                else "branch",
                                "sha": head,
                                "event": {"before": before, "after": head, "paths": difference},
                            },
                        )
                cursor["refs"] = refs
            elif trigger.event == "workflow_run":
                after = Q(ended_at__gt=datetime.fromisoformat(cursor["at"]))
                if cursor.get("run_id"):
                    after |= Q(
                        ended_at=datetime.fromisoformat(cursor["at"]), pk__gt=cursor["run_id"]
                    )
                settled = list(
                    Run.objects.filter(
                        after,
                        project=trigger.project,
                        status__in=("succeeded", "failed", "canceled"),
                    )
                    .select_related("snapshot")
                    .order_by("ended_at", "pk")[:100]
                )
                for run in settled:
                    cursor["at"] = run.ended_at.isoformat()
                    cursor["run_id"] = str(run.pk)
                    source_context = (
                        dict(run.snapshot.launch_defaults)
                        .get("actions_context", {})
                        .get("relay", {})
                    )
                    chain = source_context.get("chain", [])
                    if (
                        len(chain) >= 3
                        or trigger.workflow_key in chain
                        or trigger.workflow_key == run.workflow_key
                    ):
                        continue
                    if (
                        config.get("workflows")
                        and source_context.get("workflow", run.title) not in config["workflows"]
                        and run.workflow_key not in config["workflows"]
                    ):
                        continue
                    if not filter_ref(config, f"refs/heads/{run.source_branch}", []):
                        continue
                    conclusion = {
                        "succeeded": "success",
                        "failed": "failure",
                        "canceled": "cancelled",
                    }[run.status]
                    if config.get("conclusions") and conclusion not in config["conclusions"]:
                        continue
                    deliver(
                        trigger,
                        str(run.pk),
                        {
                            "event_name": "workflow_run",
                            "chain": [*chain, run.workflow_key],
                            "event": {
                                "workflow_run": {
                                    "id": str(run.pk),
                                    "name": run.title,
                                    "conclusion": conclusion,
                                    "head_branch": run.source_branch,
                                    "head_sha": run.recorded_head,
                                }
                            },
                        },
                    )
                if len(settled) < 100:
                    cursor["at"] = now.isoformat()
                    cursor.pop("run_id", None)
            WorkflowTrigger.objects.filter(pk=trigger.pk).update(cursor=cursor)
        except (RelayError, OSError, ValueError):
            continue
    for delivery in TriggerDelivery.objects.filter(state="pending").select_related(
        "trigger__project"
    )[:100]:
        launch_delivery(delivery)
    from datetime import timedelta

    for uncertain in TriggerDelivery.objects.filter(
        state="launching", created_at__lt=now - timedelta(minutes=5)
    )[:100]:
        recovered = Run.objects.filter(
            snapshot__launch_defaults__actions_context__relay__delivery_id=str(uncertain.pk)
        ).first()
        TriggerDelivery.objects.filter(pk=uncertain.pk, state="launching").update(
            state="launched" if recovered else "blocked",
            run=recovered,
            reason=""
            if recovered
            else "The launch outcome is uncertain. Review the run history before retrying.",
        )
    wake_gates()
    from .actions_products import expire_artifacts

    expire_artifacts()
    terminal = ActionsQueue.objects.filter(
        state="active", run__status__in=("succeeded", "failed", "canceled")
    )
    if terminal.update(state="complete"):
        release_serial_admission()


def launch_delivery(delivery: TriggerDelivery) -> None:
    from relay.execution.launch import LaunchRequest, launch_workflow

    from .repositories import DjangoExecutionStore

    trigger = cast(WorkflowTrigger, delivery.trigger)
    root = Path(cast(str, cast(Project, trigger.project).git_root)) / ".relay"
    # Claim once; an uncertain launch is retained for owner review, never replayed.
    with transaction.atomic():
        current = TriggerDelivery.objects.select_for_update().get(pk=delivery.pk)
        if current.state != "pending" or not trigger.enabled:
            return
        TriggerDelivery.objects.filter(pk=current.pk).update(state="launching")
    try:
        resolve_workflow_path(root / "workflows", cast(str, trigger.workflow_key))
        if activation_hash(root, cast(str, trigger.workflow_key)) != trigger.source_hash:
            message = "The activated workflow source changed; reactivate it after review."
            raise ConfigError(message)
        result = launch_workflow(
            DjangoExecutionStore(),
            root,
            str(cast(Project, trigger.project).pk),
            LaunchRequest(
                cast(str, trigger.workflow_key),
                {},
                None,
                "retain",
                None,
                (),
                "automatic",
                event_context={**cast(dict, delivery.payload), "delivery_id": str(delivery.pk)},
            ),
            notify_dispatch,
        )
        TriggerDelivery.objects.filter(pk=delivery.pk).update(
            state="launched", run_id=result.run_id
        )
    except (RelayError, OSError) as error:
        TriggerDelivery.objects.filter(pk=delivery.pk).update(
            state="blocked", reason=str(error)[:1000]
        )


def wake_gates() -> None:
    from .actions_repository import approve_environment

    for run in Run.objects.filter(status__in=("running", "paused_wait"))[:100]:
        for attempt, gate in dict(run.actions_state).get("environment_gates", {}).items():
            if not NodeAttempt.objects.filter(pk=attempt, status="waiting").exists():
                continue
            environment = dict(run.snapshot.launch_defaults)["actions_context"]["environments"][
                gate["environment"]
            ]
            from datetime import timedelta

            if (
                gate["approved"] or not environment["approval_required"]
            ) and timezone.now() >= datetime.fromisoformat(gate["started"]) + timedelta(
                minutes=environment["wait_minutes"]
            ):
                approve_environment(attempt)
    from relay.execution.dispatch import dispatch_node

    from .models import UsageRetry
    from .repositories import DjangoExecutionStore

    for retry in UsageRetry.objects.filter(
        state="scheduled", reset_at__lte=timezone.now(), run__status__in=("running", "paused_wait")
    ).select_related("attempt__node_run")[:100]:
        scope = cast(str, retry.attempt.node_run.parent_scope_path)
        parent = NodeRun.objects.filter(run=retry.run, scope_path=scope, status="waiting").first()
        if parent:
            dispatch_node(DjangoExecutionStore(), str(parent.pk), notify_dispatch)


def cancel_queue_owner(run_id: str, scope: str, identity: str) -> None:
    from relay.execution.cancellation import request_cancellation
    from relay.execution.machine import transition_node
    from relay.execution.state import EventSource

    from .repositories import DjangoExecutionStore, _append_event

    store = DjangoExecutionStore()
    if scope == "workflow":
        request_cancellation(store, run_id, identity)
        return
    target = scope.removeprefix("workflow:")
    with transaction.atomic():
        run = Run.objects.select_for_update().get(pk=run_id)
        state = dict(run.actions_state)
        cancelled = state.setdefault("cancelled_jobs", [])
        if target not in cancelled:
            cancelled.append(target)
        Run.objects.filter(pk=run.pk).update(actions_state=state)
        for node in NodeRun.objects.filter(run=run).filter(
            Q(scope_path=target) | Q(scope_path__startswith=target + ".")
        ):
            if node.status in {"pending", "ready", "dispatched"}:
                changed = transition_node(cast(str, node.status), "fail_fast")
                NodeRun.objects.filter(pk=node.pk).update(
                    status=changed.status, outcome="cancelled", conclusion="cancelled"
                )
                _append_event(
                    run,
                    changed.event,
                    EventSource.SYSTEM,
                    {"scope_path": node.scope_path, "reason": "concurrency"},
                    node=node,
                )
        attempts = list(
            NodeAttempt.objects.filter(node_run__run=run, status__in=("running", "waiting")).values(
                "id", "node_run__scope_path"
            )
        )
    for attempt in attempts:
        if attempt["node_run__scope_path"] == target or attempt["node_run__scope_path"].startswith(
            target + "."
        ):
            store.submit_control(
                str(attempt["id"]), "cancel", identity, {"reason": "concurrency"}, 600
            )


def admit_queue(node: NodeRun, values: dict[str, Any], *, activate: bool = False) -> bool:
    """Reserve queues before the global lease; activate only after its admission."""
    from .models import ActionsJobLease

    ActionsQueue.objects.filter(
        state="active", run__status__in=("succeeded", "failed", "canceled")
    ).update(state="complete")

    frozen = cast(dict, node.frozen_def)
    workflow, job = frozen.get("workflow", {}), frozen.get("job", {})
    run_id, node_scope = str(cast(Run, node.run).pk), cast(str, node.scope_path)
    workflow_scope = frozen.get("workflow_scope", "root")
    queue_scope = "workflow" if workflow_scope == "root" else "workflow:" + workflow_scope
    configs = [(queue_scope, workflow.get("concurrency"))]
    if "matrix" not in job.get("strategy", {}) or frozen.get("matrix_index") is not None:
        configs.append((node_scope, job.get("concurrency")))
    lease = (
        ActionsJobLease.objects.filter(pk=1, node__run_id=run_id)
        .values_list("node__scope_path", flat=True)
        .first()
    )
    nested = bool(lease and node_scope.startswith(lease + "."))
    groups = []
    reserved = []
    for scope, config in configs:
        if config is None:
            continue
        group = expressions.string(
            expressions.interpolate(config if isinstance(config, str) else config["group"], values)
        ).lower()
        if not group or len(group) > 256 or group in groups:
            message = (
                "Concurrency groups must be bounded and cannot block their own nested workflow."
            )
            raise ConfigError(message)
        groups.append(group)
        mode = config.get("queue", "single") if isinstance(config, dict) else "single"
        cancel = (
            expressions.truthy(
                expressions.interpolate(config.get("cancel-in-progress", False), values)
            )
            if isinstance(config, dict)
            else False
        )
        if mode == "max" and cancel:
            message = "queue: max cannot be combined with cancel-in-progress."
            raise ConfigError(message)
        row, created = ActionsQueue.objects.get_or_create(
            run_id=run_id,
            scope=scope,
            defaults={"group": group, "mode": mode, "cancel_in_progress": cancel},
        )
        if row.group != group:
            message = "A frozen concurrency group changed during resume."
            raise ConfigError(message)
        others = ActionsQueue.objects.filter(group=group, state__in=("pending", "active")).exclude(
            pk=row.pk
        )
        for owner in others.filter(run_id=run_id, state="active").values_list("scope", flat=True):
            ancestor = owner.removeprefix("workflow:")
            if (
                owner == "workflow"
                or node_scope == ancestor
                or node_scope.startswith(ancestor + ".")
            ):
                message = "A nested concurrency group would block its owning workflow or job."
                raise ConfigError(message)
        if created and mode == "single":
            superseded = list(others.filter(state="pending").values_list("run_id", "scope"))
            others.filter(state="pending").update(state="superseded")
            if cancel:
                superseded += list(others.filter(state="active").values_list("run_id", "scope"))
            if superseded:
                transaction.on_commit(
                    lambda owners=tuple(superseded), key=str(row.pk): [
                        cancel_queue_owner(str(identity), owner_scope, f"concurrency:{key}")
                        for identity, owner_scope in owners
                    ]
                )
        if row.state == "superseded":
            return False
        if mode == "max" and others.filter(state="pending").count() >= 100:
            message = "A concurrency queue is limited to 100 waiting jobs or runs."
            raise ConfigError(message)
        if others.filter(state="active").exists() or (
            mode == "max" and not nested and others.filter(created_at__lt=row.created_at).exists()
        ):
            return False
        reserved.append(row.pk)
    if activate:
        ActionsQueue.objects.filter(pk__in=reserved).update(state="active")
    return True
