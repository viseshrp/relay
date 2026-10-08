"""Django adapters for serial Actions execution, separate from legacy policy."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any, cast
import uuid

from django.db import transaction

from relay.errors import PathSafetyError, PersistenceError
from relay.execution.dispatch import release_serial_admission
from relay.execution.resources import AttemptResources, allocate_attempt_resources
from relay.execution.runner import ExecutionOutcome
from relay.execution.state import TERMINAL_NODE_STATUSES, EventSource, NodeType
from relay.paths import data_dir, safe_resolve, worktrees_dir
from relay.vcs.commits import current_head, is_ancestor
from relay.vcs.git import run_git
from relay.vcs.worktree import require_project_worktree

from .models import (
    ActionsJobLease,
    ActionsJobState,
    NodeAttempt,
    NodeRun,
    Project,
    Run,
    RunSnapshot,
)


def claim_job_lease(node: NodeRun) -> bool:
    """Called inside the attempt-claim transaction, before creating any attempt."""
    node_type = cast(str, node.node_type)
    if node_type not in {
        NodeType.ACTIONS_JOB.value,
        NodeType.ACTIONS_STEP.value,
        NodeType.AGENT.value,
        NodeType.COMMAND.value,
    }:
        return True
    lease, _ = ActionsJobLease.objects.select_for_update().get_or_create(pk=1)
    owner_id = lease.node_id
    owner = (
        NodeRun.objects.filter(pk=owner_id).values("run_id", "scope_path", "status").first()
        if owner_id
        else None
    )
    if owner is not None and owner["status"] in {item.value for item in TERMINAL_NODE_STATUSES}:
        if NodeAttempt.objects.filter(
            node_run__run_id=owner["run_id"],
            node_run__scope_path__startswith=owner["scope_path"] + ".",
            status__in=("created", "running"),
        ).exists():
            return False
        ActionsJobLease.objects.filter(pk=1).update(node=None)
        owner = None
    if owner is not None:
        scope = cast(str, node.scope_path)
        return str(owner["run_id"]) == str(cast(Run, node.run).pk) and (
            scope == owner["scope_path"] or scope.startswith(owner["scope_path"] + ".")
        )
    if node_type == NodeType.ACTIONS_STEP.value:
        return False
    if node_type != NodeType.ACTIONS_JOB.value:
        return True  # Historical snapshots retain their original admission policy.
    if NodeAttempt.objects.filter(
        status__in=("running", "waiting"), node_run__node_type__in=("agent", "command")
    ).exists():
        return False
    ActionsJobLease.objects.filter(pk=1).update(node=node)
    return True


def release_job_lease(node: NodeRun) -> None:
    """Release only a terminal owning job; nested children never release it."""
    if cast(str, node.status) not in {item.value for item in TERMINAL_NODE_STATUSES}:
        return
    active_children = NodeAttempt.objects.filter(
        node_run__run=node.run,
        node_run__scope_path__startswith=str(node.scope_path) + ".",
        status__in=("created", "running"),
    ).exists()
    changed = (
        ActionsJobLease.objects.filter(pk=1, node=node).update(node=None)
        if not active_children
        else 0
    )
    if changed:
        transaction.on_commit(release_serial_admission)
    from .models import ActionsQueue

    completed = ActionsQueue.objects.filter(
        run=node.run, scope__in=(node.scope_path, f"workflow:{node.scope_path}"), state="active"
    ).update(state="complete")
    if completed:
        transaction.on_commit(release_serial_admission)
    if cast(str, node.node_type) == "actions_job" and not cast(dict, node.frozen_def).get(
        "coordinator"
    ):
        state = dict(
            Run.objects.values_list("actions_state", flat=True).get(pk=cast(Run, node.run).pk)
        )
        if cast(str, node.outcome) in {"failure", "cancelled"}:
            state["needs_continuation"] = True
            Run.objects.filter(pk=cast(Run, node.run).pk).update(actions_state=state)


def prepare_job_workspace(run_id: str) -> None:
    """Retain a rejected job's checkout, then continue at the last accepted head."""
    record = Run.objects.select_related("project").get(pk=run_id)
    state = cast(dict[str, Any], record.actions_state)
    if not state.get("needs_continuation"):
        return
    repository = Path(cast(str, record.project.git_root))
    primary = safe_resolve(worktrees_dir(), cast(str, record.worktree_path))
    protected = cast(str, record.recorded_head)
    if not is_ancestor(repository, cast(str, record.source_commit), protected):
        message = "The accepted job checkpoint is no longer a descendant of launch."
        raise PersistenceError(message)
    # Every failed job must already have complete evidence before moving its bytes.
    from relay.vcs.cleanliness import execution_changes

    from .models import Artifact

    snapshot = RunSnapshot.objects.get(run=record)
    sources = cast(dict, snapshot.resolved_definition).get("sources", {})
    snapshot_files = frozenset(
        {
            ".relay/workflows/" + str(record.workflow_key),
            *(str(path) for path in sources if str(path).startswith(".relay/")),
        }
    )
    if (
        not state.get("continuation_journal")
        and current_head(primary) == protected
        and not execution_changes(primary, snapshot_files=snapshot_files)
    ):
        state["needs_continuation"] = False
        Run.objects.filter(pk=run_id).update(actions_state=state)
        return

    failures = NodeAttempt.objects.filter(
        node_run__run=record,
        node_run__node_type="actions_job",
        node_run__outcome__in=("failure", "cancelled"),
        status="terminal",
    )
    canceled_scopes = failures.filter(node_run__outcome="cancelled").values_list(
        "node_run__scope_path", flat=True
    )
    attempt_ids = list(failures.values_list("pk", flat=True))
    for scope in canceled_scopes:
        latest_child = (
            NodeAttempt.objects.filter(
                node_run__run=record,
                node_run__scope_path__startswith=scope + ".",
                status="terminal",
                artifacts__preservation_state="preserved",
            )
            .order_by("-ended_at")
            .first()
        )
        if latest_child is not None:
            attempt_ids.append(latest_child.pk)
    from relay.execution.action_products import digest_file
    from relay.execution.resources import _linked

    evidence = list(
        Artifact.objects.filter(attempt_id__in=attempt_ids).values(
            "retained_path", "preservation_state", "sha256", "bytes"
        )
    )
    if not evidence or any(
        item["preservation_state"] != "preserved"
        or _linked(Path(item["retained_path"]))
        or not Path(item["retained_path"]).is_file()
        or Path(item["retained_path"]).stat().st_size != item["bytes"]
        or digest_file(Path(item["retained_path"])) != item["sha256"]
        for item in evidence
    ):
        message = "Incomplete job preservation blocks continuation."
        raise PersistenceError(message)
    journal = state.get("continuation_journal")
    if journal is None:
        require_project_worktree(repository, primary)
        journal = {
            "retained": str(worktrees_dir() / f"{run_id}-failed-{uuid.uuid4()}"),
            "head": current_head(primary),
            "protected": protected,
        }
        with transaction.atomic():
            current = Run.objects.select_for_update().get(pk=run_id)
            latest = dict(current.actions_state)
            latest["continuation_journal"] = journal
            Run.objects.filter(pk=run_id).update(actions_state=latest)
    retained = safe_resolve(worktrees_dir(), journal["retained"])
    head = journal["head"]
    if journal["protected"] != protected:
        message = "The protected head changed during workspace continuation."
        raise PersistenceError(message)
    branch = cast(str, record.run_branch)
    # All commands act on the verified run worktree, never on the owner's checkout.
    if not retained.exists():
        require_project_worktree(repository, primary)
        if current_head(primary) != head:
            message = "The rejected workspace head changed before preservation."
            raise PersistenceError(message)
        run_git(repository, ["worktree", "move", str(primary), str(retained)])
    require_project_worktree(repository, retained)
    if current_head(retained) != head:
        message = "The retained failed workspace head changed."
        raise PersistenceError(message)
    attached = run_git(retained, ["symbolic-ref", "--quiet", "HEAD"], check=False)
    if attached.returncode == 0:
        if attached.stdout.strip() != f"refs/heads/{branch}":
            message = "The retained workspace is attached to an unrelated branch."
            raise PersistenceError(message)
        run_git(retained, ["checkout", "--detach", head])
    ref = run_git(repository, ["rev-parse", "--verify", f"refs/heads/{branch}"]).stdout.strip()
    if ref == head:
        run_git(repository, ["update-ref", f"refs/heads/{branch}", protected, head])
    elif ref != protected:
        message = "The run branch changed outside workspace continuation."
        raise PersistenceError(message)
    if not primary.exists():
        run_git(repository, ["worktree", "add", str(primary), branch])
    require_project_worktree(repository, primary)
    from relay.vcs.cleanliness import require_clean

    require_clean(primary, stage="job continuation")
    if current_head(primary) != protected:
        message = "The continued workspace does not match the protected head."
        raise PersistenceError(message)
    with transaction.atomic():
        current = Run.objects.select_for_update().get(pk=run_id)
        latest = dict(current.actions_state)
        continuations = latest.setdefault("continuations", [])
        if str(retained) not in continuations:
            continuations.append(str(retained))
        latest["needs_continuation"] = False
        latest.pop("continuation_journal", None)
        Run.objects.filter(pk=run_id).update(actions_state=latest)


def job_resources(node_run_id: str, run_id: str, attempt_id: str) -> AttemptResources:
    """Reuse a marked private job allocation across suspended attempts."""
    state = (
        ActionsJobState.objects.filter(pk=node_run_id).values_list("resource", flat=True).first()
    )
    if state:
        root = data_dir() / "resources" / run_id
        directory = safe_resolve(root, state["directory"])
        marker = directory / ".relay-resource-owner.json"
        if directory.is_symlink() or marker.is_symlink() or not marker.is_file():
            message = "The durable job resource ownership is missing."
            raise PathSafetyError(message)
        owner = json.loads(marker.read_text(encoding="utf-8"))
        if owner != {
            "version": 1,
            "run": run_id,
            "attempt": state["attempt"],
            "token": state["token"],
        }:
            message = "The durable job resource ownership changed."
            raise PathSafetyError(message)
        return AttemptResources(directory, run_id, state["attempt"], state["token"])
    resource = allocate_attempt_resources(run_id, attempt_id)
    ActionsJobState.objects.update_or_create(
        node_id=node_run_id,
        defaults={
            "resource": {
                "directory": str(resource.directory),
                "attempt": resource.attempt_id,
                "token": resource.token,
            }
        },
    )
    return resource


def job_state_path(node_run_id: str) -> Path:
    record = NodeRun.objects.get(pk=node_run_id)
    attempt = NodeAttempt.objects.filter(node_run=record).order_by("-attempt_number").first()
    if attempt is None:
        message = "A job has no current attempt."
        raise PersistenceError(message)
    resources = job_resources(str(record.pk), str(record.run_id), str(attempt.pk))
    return resources.directory / "job-state.json"


def execution_context(attempt_id: str) -> dict[str, Any]:
    record = NodeAttempt.objects.select_related("node_run__run__project").get(pk=attempt_id)
    return node_context(record.node_run, cast(int, record.attempt_number))


def node_context(node: NodeRun, attempt_number: int = 1) -> dict[str, Any]:
    """Frozen field contexts are available before claiming an attempt or queue."""
    run = cast(Run, node.run)
    project = cast(Project, run.project)
    snapshot = RunSnapshot.objects.get(run=run)
    launch = cast(dict[str, Any], snapshot.launch_defaults)
    context = cast(dict[str, Any], launch.get("actions_context", {}))
    github = {
        "actor": cast(str, run.launcher),
        "repository": cast(str, project.display_name),
        "repository_owner": "local",
        "workspace": cast(str, run.worktree_path),
        "workflow": cast(str, run.title),
        "workflow_ref": cast(str, run.workflow_key),
        "run_id": str(run.pk),
        "run_number": cast(int, run.number),
        "run_attempt": attempt_number,
        "sha": cast(str, run.source_commit),
        "ref": f"refs/heads/{run.source_branch}" if run.source_branch else "",
        "ref_name": cast(str, run.source_branch) or "",
        "ref_type": "branch",
        "event_name": "workflow_dispatch",
        "event": {
            "inputs": {
                name: "true" if value is True else "false" if value is False else str(value)
                for name, value in cast(dict, snapshot.typed_inputs).items()
            }
        },
        "server_url": "",
        "api_url": "",
        "graphql_url": "",
        "token": "",
        **cast(dict, context.get("github", {})),
    }
    needs = {}
    frozen = cast(dict[str, Any], node.frozen_def)
    parent = cast(str | None, node.parent_scope_path)
    if frozen.get("type") == "actions_step":
        owner = NodeRun.objects.get(run=run, scope_path=frozen["state_scope"])
        frozen = cast(dict[str, Any], owner.frozen_def)
        parent = cast(str | None, owner.parent_scope_path)
    if frozen.get("matrix_index") is not None:
        coordinator = NodeRun.objects.get(run=run, scope_path=parent)
        frozen = cast(dict[str, Any], coordinator.frozen_def)
        parent = cast(str | None, coordinator.parent_scope_path)
    for needed in frozen.get("needs", []):
        dependency = NodeRun.objects.get(run=run, scope_path=f"{parent or 'root'}.{needed}")
        result = cast(str, dependency.conclusion) or {
            "succeeded": "success",
            "failed": "failure",
            "canceled": "cancelled",
            "skipped": "skipped",
        }.get(cast(str, dependency.status), "")
        needs[needed] = {"outputs": cast(dict, dependency.outputs), "result": result}
    return {
        "github": github,
        "inputs": cast(dict, node.scope_inputs) if parent else cast(dict, snapshot.typed_inputs),
        "vars": cast(dict, context.get("vars", {})),
        "needs": needs,
        "_statuses": [item["result"] for item in needs.values()],
        "_cancelled": cast(str, run.status) in {"canceling", "canceled"}
        or any(
            cast(str, node.scope_path) == scope
            or cast(str, node.scope_path).startswith(scope + ".")
            for scope in cast(dict, run.actions_state).get("cancelled_jobs", [])
        ),
        "_run_status": cast(str, run.status),
        "_dispatch_paused": cast(bool, run.dispatch_paused),
        "_launch": launch,
        "_context": context,
    }


def scope_context(run_id: str, scope: str) -> dict[str, Any]:
    node = NodeRun.objects.get(run_id=run_id, scope_path=scope)
    attempt = NodeAttempt.objects.filter(node_run=node).order_by("-attempt_number").first()
    if attempt is None:
        message = "A caller scope has no admitted attempt."
        raise PersistenceError(message)
    values = execution_context(str(attempt.pk))
    frozen = cast(dict[str, Any], node.frozen_def)
    values["inputs"] = frozen.get("caller_inputs") or values["inputs"]
    values["matrix"] = frozen.get("matrix", {})
    values["strategy"] = {"max-parallel": 1}
    return values


def output_budget(attempt_id: str, outputs: Mapping[str, str]) -> None:
    from relay.errors import NodeExecutionError

    size = sum(
        len(key.encode("utf-16-le")) + len(value.encode("utf-16-le"))
        for key, value in outputs.items()
    )
    if size > 1_048_576:
        message = "Job outputs exceed 1 MiB in UTF-16."
        raise NodeExecutionError(message)
    attempt = NodeAttempt.objects.select_related("node_run").get(pk=attempt_id)
    with transaction.atomic():
        run = Run.objects.select_for_update().get(pk=attempt.node_run.run_id)
        state = dict(run.actions_state)
        sizes = dict(state.get("output_sizes", {}))
        sizes[cast(str, attempt.node_run.scope_path)] = size
        if sum(sizes.values()) > 50 * 1_048_576:
            message = "Workflow outputs exceed 50 MiB in UTF-16."
            raise NodeExecutionError(message)
        state["output_sizes"] = sizes
        Run.objects.filter(pk=run.pk).update(actions_state=state)


def scope_node_id(run_id: str, scope: str) -> str:
    return str(NodeRun.objects.values_list("pk", flat=True).get(run_id=run_id, scope_path=scope))


def display_name(attempt_id: str, value: str) -> None:
    from relay.execution.masking import redactor

    record = NodeAttempt.objects.select_related("node_run").get(pk=attempt_id)
    with transaction.atomic():
        run = Run.objects.select_for_update().get(pk=record.node_run.run_id)
        state = dict(run.actions_state)
        state.setdefault("display_names", {})[cast(str, record.node_run.scope_path)] = redactor(
            str(run.pk)
        ).text(value)[:1024]
        Run.objects.filter(pk=run.pk).update(actions_state=state)


def request_human_wait(attempt_id: str, prompt: str, timeout: float | None) -> None:
    from .models import HumanInteraction

    record = NodeAttempt.objects.select_related("node_run__run").get(pk=attempt_id)
    deadline = datetime.now(timezone.utc) + timedelta(seconds=timeout) if timeout else None
    if record.deadline_at is not None:
        deadline = min(deadline, record.deadline_at) if deadline else record.deadline_at
    HumanInteraction.objects.get_or_create(
        attempt=record,
        kind="wait",
        status="pending",
        defaults={
            "run": record.node_run.run,
            "node_run": record.node_run,
            "request_payload": {"prompt": prompt},
            "deadline": deadline,
        },
    )


def settle_stopped_children(run_id: str, scope: str, outcome: ExecutionOutcome) -> None:
    """Settle unstarted descendants before their stopped parent becomes terminal."""
    from relay.execution.machine import transition_node
    from relay.execution.state import EventSource

    from .repositories import _append_event

    with transaction.atomic():
        run = Run.objects.select_for_update().get(pk=run_id)
        for node in NodeRun.objects.filter(
            run=run,
            scope_path__startswith=scope + ".",
            status__in=("pending", "ready", "dispatched"),
        ):
            changed = transition_node(cast(str, node.status), "fail_fast")
            NodeRun.objects.filter(pk=node.pk).update(
                status=changed.status, outcome="cancelled", conclusion="cancelled"
            )
            _append_event(
                run,
                changed.event,
                EventSource.NODE,
                {"scope_path": node.scope_path, "reason": outcome.error_code},
                node=node,
            )


def human_wait_result(
    attempt_id: str, response: Mapping[str, Any], *, failed: bool = False, canceled: bool = False
) -> dict[str, str]:
    from relay.execution.action_files import atomic_state, read_state
    from relay.workflows.actions import expressions

    record = NodeAttempt.objects.select_related("node_run").get(pk=attempt_id)
    frozen = cast(dict[str, Any], record.node_run.frozen_def)
    if frozen.get("type") != "actions_step" or frozen["step"].get("uses") != "relay/human-wait@v1":
        return {}
    path = job_state_path(scope_node_id(str(record.node_run.run_id), frozen["state_scope"]))
    state = read_state(path)
    outputs = {} if failed else {"answer": expressions.string(response.get("value", ""))}
    result = "cancelled" if canceled else "failure" if failed else "success"
    state["steps"][cast(str, record.node_run.scope_path)] = {
        "outputs": outputs,
        "outcome": result,
        "conclusion": result,
    }
    atomic_state(path, state)
    return outputs


def retry_step(node_id: str) -> str:
    """Retry a preserved agent step in its current job, without resetting code."""
    from relay.execution.action_files import atomic_state, read_state
    from relay.execution.action_products import digest_file
    from relay.execution.machine import transition_node
    from relay.execution.resources import _linked

    from .models import Artifact, AutomaticRetry, UsageRetry
    from .repositories import DjangoExecutionStore, _append_event

    node = NodeRun.objects.select_related("run").get(pk=node_id)
    frozen = cast(dict[str, Any], node.frozen_def)
    if node.status != "failed" or not frozen.get("bound_agent"):
        return "none"
    attempt = NodeAttempt.objects.filter(node_run=node).order_by("-attempt_number").first()
    if attempt is None:
        return "none"
    retry = AutomaticRetry.objects.filter(attempt=attempt, state="scheduled").first()
    quota = UsageRetry.objects.filter(attempt=attempt, state="scheduled").first()
    if quota is not None and quota.reset_at and quota.reset_at > datetime.now(timezone.utc):
        return "waiting"
    if retry is None and quota is None:
        return "none"
    if (
        quota is not None
        and NodeAttempt.objects.filter(node_run=node, error_code="agent_usage_limit").count() > 3
    ):
        UsageRetry.objects.filter(pk=quota.pk).update(
            state="blocked", error_message="The step usage-recovery budget is exhausted."
        )
        return "none"
    rows = list(
        Artifact.objects.filter(attempt=attempt).values(
            "retained_path", "sha256", "bytes", "preservation_state"
        )
    )
    if not rows or any(
        item["preservation_state"] != "preserved"
        or _linked(Path(item["retained_path"]))
        or not Path(item["retained_path"]).is_file()
        or Path(item["retained_path"]).stat().st_size != item["bytes"]
        or digest_file(Path(item["retained_path"])) != item["sha256"]
        for item in rows
    ):
        message = "Incomplete step evidence blocks automatic recovery."
        raise PersistenceError(message)
    with transaction.atomic():
        node = NodeRun.objects.select_for_update().get(pk=node_id)
        if node.status != "failed":
            return "none"
        transition = transition_node(cast(str, node.status), "rerun")
        instruction = (
            cast(str, retry.instruction)
            if retry
            else "Continue after the provider-confirmed usage reset."
        )
        NodeRun.objects.filter(pk=node.pk).update(
            status=transition.status,
            recovery_instruction=instruction,
            outputs={},
            outcome="",
            conclusion="",
        )
        if retry:
            AutomaticRetry.objects.filter(pk=retry.pk, state="scheduled").update(state="resumed")
        if quota:
            UsageRetry.objects.filter(pk=quota.pk, state="scheduled").update(state="resumed")
        _append_event(
            cast(Run, node.run),
            "step.recovery_resumed",
            EventSource.SYSTEM,
            {"scope_path": node.scope_path, "source_attempt": str(attempt.pk)},
            node=node,
        )
    path = job_state_path(scope_node_id(str(node.run_id), frozen["state_scope"]))
    state = read_state(path)
    state["steps"].pop(cast(str, node.scope_path), None)
    state.get("anonymous_statuses", {}).pop(cast(str, node.scope_path), None)
    atomic_state(path, state)
    DjangoExecutionStore().release_attempt_lock(str(attempt.pk))
    return "ready"


def node_results(run_id: str, scope: str) -> dict[str, dict[str, Any]]:
    return {
        row["node_id"]: {
            "outcome": row["outcome"] or "skipped",
            "conclusion": row["conclusion"] or "skipped",
            "outputs": row["outputs"],
        }
        for row in NodeRun.objects.filter(run_id=run_id, parent_scope_path=scope).values(
            "node_id", "outcome", "conclusion", "outputs"
        )
    }


def set_matrix_manifest(node_run_id: str, manifest: list[dict[str, Any]]) -> None:
    state, _ = ActionsJobState.objects.get_or_create(node_id=node_run_id)
    if state.matrix_manifest and state.matrix_manifest != manifest:
        message = "A frozen matrix manifest changed."
        raise PersistenceError(message)
    ActionsJobState.objects.filter(pk=node_run_id).update(matrix_manifest=manifest)
    node = NodeRun.objects.get(pk=node_run_id)
    with transaction.atomic():
        run = Run.objects.select_for_update().get(pk=node.run_id)
        state = dict(run.actions_state)
        state.setdefault("matrices", {})[cast(str, node.scope_path)] = manifest
        Run.objects.filter(pk=run.pk).update(actions_state=state)


def frozen_matrix(run_id: str, scope: str) -> list[dict[str, Any]] | None:
    state = Run.objects.values_list("actions_state", flat=True).get(pk=run_id)
    return cast(list[dict[str, Any]] | None, state.get("matrices", {}).get(scope))


def matrix_manifest(run_id: str, scope: str) -> list[dict[str, Any]]:
    parent = scope.rsplit(".", 1)[0]
    return cast(
        list[dict[str, Any]],
        ActionsJobState.objects.filter(node__run_id=run_id, node__scope_path=parent)
        .values_list("matrix_manifest", flat=True)
        .first()
        or [],
    )


def record_skipped(node_run_id: str) -> None:
    NodeRun.objects.filter(pk=node_run_id, status="skipped").update(
        outcome="skipped", conclusion="skipped"
    )


def step_deadline(attempt_id: str, minutes: float) -> datetime:
    if not 0 < minutes <= 360:
        message = "timeout-minutes must be between zero and 360 minutes."
        raise PersistenceError(message)
    with transaction.atomic():
        attempt = NodeAttempt.objects.select_for_update().get(pk=attempt_id)
        deadline = attempt.started_at + timedelta(minutes=minutes)
        if attempt.deadline_at is not None:
            deadline = min(deadline, attempt.deadline_at)
        NodeAttempt.objects.filter(pk=attempt.pk).update(deadline_at=deadline)
    return deadline


def environment_gate(attempt_id: str, environment: str, values: Mapping[str, Any]) -> bool:
    """Gate the exact current job attempt before resolving environment secrets."""
    from relay.workflows.actions.patterns import matches

    from .models import HumanInteraction

    configuration = values["_context"].get("environments", {}).get(environment)
    if configuration is None:
        message = f"Environment {environment!r} is not configured."
        raise PersistenceError(message)
    branches = configuration["branches"]
    if branches and not matches(values["github"]["ref_name"], branches):
        message = "The launch branch is not allowed by this environment."
        raise PersistenceError(message)
    record = NodeAttempt.objects.select_related("node_run__run").get(pk=attempt_id)
    run = record.node_run.run
    with transaction.atomic():
        run = Run.objects.select_for_update().get(pk=run.pk)
        state = dict(run.actions_state)
        gates = state.setdefault("environment_gates", {})
        gate = gates.setdefault(
            attempt_id,
            {
                "environment": environment,
                "started": datetime.now(timezone.utc).isoformat(),
                "approved": False,
            },
        )
        ready = datetime.fromisoformat(gate["started"]) + timedelta(
            minutes=configuration["wait_minutes"]
        )
        approved = gate["approved"] or not configuration["approval_required"]
        Run.objects.filter(pk=run.pk).update(actions_state=state)
        if approved and datetime.now(timezone.utc) >= ready:
            return True
        HumanInteraction.objects.get_or_create(
            attempt=record,
            kind="wait",
            status="pending",
            defaults={
                "run": run,
                "node_run": record.node_run,
                "request_payload": {
                    "prompt": f"Approve environment {environment}",
                    "environment": environment,
                    "ready_at": ready.isoformat(),
                },
                "deadline": record.deadline_at,
            },
        )
    return False


def publish_environment(attempt_id: str, name: str, url: str) -> None:
    """Publish a safe resolved environment URL after its job's steps settle."""
    from urllib.parse import urlsplit

    from relay.execution.masking import redactor

    record = NodeAttempt.objects.select_related("node_run__run").get(pk=attempt_id)
    run_id = str(record.node_run.run_id)
    if not url or redactor(run_id).contains(url):
        return
    try:
        parsed = urlsplit(url)
        safe = parsed.scheme.lower() in {"http", "https"} and bool(parsed.hostname)
    except ValueError:
        return
    if not safe or parsed.username is not None or parsed.password is not None or len(url) > 2048:
        return
    with transaction.atomic():
        run = Run.objects.select_for_update().get(pk=run_id)
        state = dict(run.actions_state)
        state.setdefault("environment_links", {})[record.node_run.scope_path] = {
            "name": name,
            "url": url,
        }
        Run.objects.filter(pk=run_id).update(actions_state=state)


def approve_environment(attempt_id: str) -> bool:
    from relay.execution.dispatch import dispatch_node, notify_dispatch

    from .models import HumanInteraction
    from .repositories import DjangoExecutionStore

    with transaction.atomic():
        record = NodeAttempt.objects.select_related("node_run__run").get(pk=attempt_id)
        if record.status != "waiting" or record.node_run.status != "waiting":
            return False
        run = Run.objects.select_for_update().get(pk=record.node_run.run.pk)
        state = dict(run.actions_state)
        gate = state.get("environment_gates", {}).get(attempt_id)
        if gate is None:
            return False
        gate["approved"] = True
        Run.objects.filter(pk=run.pk).update(actions_state=state)
        HumanInteraction.objects.filter(attempt=record, status="pending").update(status="answered")
        configuration = dict(run.snapshot.launch_defaults)["actions_context"]["environments"][
            gate["environment"]
        ]
        ready = datetime.fromisoformat(gate["started"]) + timedelta(
            minutes=configuration["wait_minutes"]
        )
        if datetime.now(timezone.utc) >= ready:
            transaction.on_commit(
                lambda: dispatch_node(
                    DjangoExecutionStore(), str(record.node_run.pk), notify_dispatch
                )
            )
        transaction.on_commit(
            lambda: DjangoExecutionStore().append_attempt_event(
                attempt_id,
                "environment.approved",
                EventSource.SYSTEM,
                {"environment": gate["environment"]},
            )
        )
    return True
