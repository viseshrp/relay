"""Pure execution rules: transitions, controls, admission, timing, and dispatch."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import logging

from django.db import connections
import pytest

from relay.errors import (
    DispatchError,
    NodeExecutionError,
    PermissionFlowError,
    PersistenceError,
    WorkflowValidationError,
)
from relay.execution.control import (
    ClaimedControl,
    ControlRecovery,
    ControlResult,
    cancel_stop_reason,
    submit_control,
)
from relay.execution.dispatch import (
    ClaimDisposition,
    ClaimResult,
    defer_dispatch,
    dispatch_node,
    release_admission,
    set_dispatch_notifier,
)
from relay.execution.launch import LaunchRequest, launch_workflow
from relay.execution.locks import decide_admission
from relay.execution.machine import (
    TransitionResult,
    apply_transition,
    transition_control,
    transition_interaction,
    transition_node,
    transition_run,
)
from relay.execution.scheduler import (
    downstream_scope_candidates,
    entry_node_for_scope,
    evaluate_eligibility,
    initial_scope_candidates,
    reachable_node_ids,
)
from relay.execution.state import AttemptStopReason, ControlKind, LockMode, Transition
from relay.execution.timing import attempt_deadline, duration_seconds, remaining_seconds
from relay.web.models import DispatchClaim
from relay.workflows.graph import CompiledGraph, compile_graph
from relay.workflows.loader import load_workflow_text
from relay.workflows.schema import NodeDefinition
from tests.support import Clock, InlineEngine, RelayProject

GUARDED: Mapping[str, NodeDefinition] = load_workflow_text(
    "version: 1\nname: S\nnodes:\n"
    "  a: {type: command, run: [x]}\n"
    '  b: {type: command, run: [x], needs: [a], if: "${{ inputs.go }}"}\n'
    '  c: {type: command, run: [x], needs: [a], if: "${{ inputs.count }}"}\n'
).definition.nodes


def _graph(text: str) -> CompiledGraph:
    nodes = load_workflow_text(f"version: 1\nname: S\nnodes:\n{text}").definition.nodes
    return compile_graph(nodes)


BRANCHING: CompiledGraph = _graph(
    "  a: {type: command, run: [x]}\n"
    "  b: {type: command, run: [x], needs: [a]}\n"
    '  choose:\n    type: condition\n    needs: [b]\n    expr: "${{ True }}"\n'
    '    branches: {"yes": c}\n'
    "  c: {type: command, run: [x], needs: [choose]}\n"
)


@pytest.mark.parametrize(
    ("apply", "action", "status", "event"),
    [
        (transition_run, "worktree_ready", "running", "run.started"),
        (transition_node, "dependencies_satisfied", "ready", "node.ready"),
        (transition_interaction, "deadline", "expired", "expired"),
        (transition_control, "claim", "claimed", "claimed"),
    ],
)
def test_a_transition_moves_to_its_target_and_names_its_event(
    apply: Callable[[str, str], TransitionResult], action: str, status: str, event: str
) -> None:
    result = apply("pending", action)

    assert (result.status, result.event, result.changed) == (status, event, True)


def test_repeating_a_transition_confirms_the_state_without_changing_it() -> None:
    result = transition_run("running", "worktree_ready")

    assert (result.status, result.changed) == ("running", False)


def test_a_transition_the_table_does_not_allow_is_rejected() -> None:
    with pytest.raises(PersistenceError):
        transition_run("succeeded", "owner_cancel")


@pytest.mark.parametrize("current", ["a", None])
def test_a_table_row_without_a_target_is_rejected(current: str | None) -> None:
    table = (Transition(current or "b", "go", "guard", None, "x.go"),)

    with pytest.raises(PersistenceError):
        apply_transition(current, "go", table, subject="x")


@dataclass
class _ControlStore:
    submitted: list[tuple[str, str, str, Mapping[str, object]]] = field(default_factory=list)

    def submit_control(
        self,
        attempt_id: str,
        kind: str,
        idempotency_key: str,
        payload: Mapping[str, object],
        ttl_seconds: float,
    ) -> ControlResult:
        del ttl_seconds
        self.submitted.append((attempt_id, kind, idempotency_key, payload))
        return ControlResult.ACCEPTED

    def claim_next_control(
        self, attempt_id: str, worker_id: str, kinds: tuple[str, ...] | None = None
    ) -> ClaimedControl | None:
        del attempt_id, worker_id, kinds
        return None

    def apply_control(self, request_id: str, worker_id: str) -> bool:
        del request_id, worker_id
        return True

    def recover_control_claims(self) -> ControlRecovery:
        return ControlRecovery(0, 0)


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("", ControlResult.INVALID),
        ("k" * 201, ControlResult.INVALID),
        ("k" * 200, ControlResult.ACCEPTED),
    ],
)
def test_an_idempotency_key_must_have_one_to_200_characters(
    key: str, expected: ControlResult
) -> None:
    assert submit_control(_ControlStore(), "a1", ControlKind.CANCEL, key, {}) is expected


@pytest.mark.parametrize("payload", [{"value": object()}, {"value": "x" * 70_000}])
def test_a_control_payload_must_be_bounded_json(payload: dict[str, object]) -> None:
    with pytest.raises(PermissionFlowError):
        submit_control(_ControlStore(), "a1", ControlKind.CANCEL, "key", payload)


def test_an_accepted_control_is_stored_for_its_attempt() -> None:
    store = _ControlStore()

    submit_control(store, "a1", ControlKind.CANCEL, "key", {"a": 1})

    assert store.submitted == [("a1", "cancel", "key", {"a": 1})]


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ({"reason": "orderly_shutdown"}, AttemptStopReason.INTERRUPTED),
        ({}, AttemptStopReason.CANCELED),
    ],
)
def test_a_cancel_from_shutdown_interrupts_and_any_other_cancels(
    payload: dict[str, object], reason: AttemptStopReason
) -> None:
    control = ClaimedControl("r", "a", "cancel", payload, "k")

    assert cancel_stop_reason(control) is reason


@pytest.mark.parametrize(
    ("writes", "active", "allowed", "mode"),
    [
        (False, [], True, LockMode.READ),
        (False, ["read"], True, LockMode.READ),
        (False, ["write"], False, LockMode.READ),
        (True, [], True, LockMode.WRITE),
        (True, ["read"], False, LockMode.WRITE),
    ],
)
def test_admission_allows_many_readers_or_one_writer(
    writes: bool, active: list[str], allowed: bool, mode: LockMode
) -> None:
    decision = decide_admission(writes, active)

    assert (decision.allowed, decision.mode) == (allowed, mode)


@pytest.mark.parametrize(
    ("value", "seconds"),
    [("250ms", 0.25), ("4s", 4.0), ("3m", 180.0), ("2h", 7200.0), (None, None)],
)
def test_a_duration_converts_to_seconds(value: str | None, seconds: float | None) -> None:
    assert duration_seconds(value) == seconds


@pytest.mark.parametrize("value", ["5x", "m", "1.5s"])
def test_an_invalid_duration_is_rejected(value: str) -> None:
    with pytest.raises(NodeExecutionError):
        duration_seconds(value)


@pytest.mark.parametrize(
    ("timeout", "inherited", "expected"),
    [("10s", None, 110.0), (None, 5.0, 5.0), (None, None, None), ("10s", 104.0, 104.0)],
)
def test_an_attempt_deadline_is_the_earlier_of_its_timeout_and_its_parent(
    clock: Clock,
    timeout: str | None,
    inherited: float | None,
    expected: float | None,
) -> None:
    clock.elapsed = 100.0

    assert attempt_deadline(timeout, inherited) == expected


@pytest.mark.parametrize(("deadline", "remaining"), [(None, None), (99.0, 0.0), (102.5, 2.5)])
def test_remaining_time_never_goes_below_zero(
    clock: Clock, deadline: float | None, remaining: float | None
) -> None:
    clock.elapsed = 100.0

    assert remaining_seconds(deadline) == remaining


@dataclass
class _DispatchStore:
    created: list[str] = field(default_factory=list)
    enqueued: list[str] = field(default_factory=list)

    def create_dispatch(self, node_run_id: str) -> str:
        token = f"token-{node_run_id}"
        self.created.append(token)
        return token

    def mark_dispatch_enqueued(self, claim_token: str) -> None:
        self.enqueued.append(claim_token)

    def claim_dispatch(self, claim_token: str, worker_id: str) -> ClaimResult:
        del claim_token, worker_id
        return ClaimResult(ClaimDisposition.IGNORED)

    def mark_dispatch_consumed(self, claim_token: str) -> None:
        del claim_token


def test_launch_commits_the_claim_before_enqueuing_its_token(
    project: RelayProject, engine: InlineEngine
) -> None:
    project.write_workflow(
        "dispatch",
        "version: 1\nname: Dispatch\nnodes:\n  work: {type: command, run: [git, status]}\n",
    )
    observed = []

    def read_committed_claim(token: str) -> tuple[str, str]:
        try:
            claim = DispatchClaim.objects.get(claim_token=token)
            return str(claim.state), str(claim.node_run.status)
        finally:
            connections.close_all()

    def enqueue(token: str) -> None:
        # A separate connection must see the claim before a consumer can receive it.
        with ThreadPoolExecutor(max_workers=1) as reader:
            observed.append(reader.submit(read_committed_claim, token).result(timeout=10))

    launch_workflow(
        engine.store,
        project.relay_root,
        project.project_id,
        LaunchRequest("dispatch", {}, None, "retain", None, (), "owner"),
        enqueue,
    )

    assert observed == [("dispatched", "dispatched")]


def test_an_enqueue_failure_becomes_a_dispatch_error() -> None:
    def broken(token: str) -> None:
        raise RuntimeError(token)

    with pytest.raises(DispatchError):
        dispatch_node(_DispatchStore(), "n1", broken)


def test_a_relay_error_from_the_queue_is_not_wrapped() -> None:
    def unavailable(token: str) -> None:
        raise PersistenceError(token)

    with pytest.raises(PersistenceError):
        dispatch_node(_DispatchStore(), "n1", unavailable)


def test_releasing_admission_wakes_only_that_runs_deferred_tokens() -> None:
    woken = []
    set_dispatch_notifier(woken.append)
    defer_dispatch("run-a", "t1")
    defer_dispatch("run-b", "t2")

    release_admission("run-a")
    release_admission("run-a")

    assert woken == ["t1"]
    release_admission("run-b")
    assert woken == ["t1", "t2"]


def test_a_failed_wake_up_is_logged_and_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    def failing(token: str) -> None:
        raise RuntimeError(token)

    set_dispatch_notifier(failing)
    defer_dispatch("run-a", "t1")

    with caplog.at_level(logging.ERROR, logger="relay.execution.dispatch"):
        release_admission("run-a")

    assert [
        (record.levelno, getattr(record, "claim_token", None)) for record in caplog.records
    ] == [(logging.ERROR, "t1")]


@pytest.mark.parametrize(
    ("node_id", "statuses", "go", "action"),
    [
        ("b", {"a": "running"}, True, None),
        ("b", {"a": "failed"}, True, "dependencies_unreachable"),
        ("b", {"a": "succeeded"}, True, "dependencies_satisfied"),
        ("b", {"a": "succeeded"}, False, "guard_false"),
    ],
)
def test_eligibility_follows_dependencies_and_guards(
    node_id: str, statuses: dict[str, str], go: bool, action: str | None
) -> None:
    context = {"inputs": {"go": go, "count": 1}, "needs": {}, "run": {}, "loop": {}}

    assert evaluate_eligibility(GUARDED[node_id], statuses, context).action == action


def test_a_guard_that_is_not_boolean_is_rejected() -> None:
    context = {"inputs": {"go": True, "count": 1}, "needs": {}, "run": {}, "loop": {}}

    with pytest.raises(WorkflowValidationError):
        evaluate_eligibility(GUARDED["c"], {"a": "succeeded"}, context)


@pytest.mark.parametrize(
    ("parent", "expected"), [(None, ("root.a",)), ("root.loop#1", ("root.loop#1.a",))]
)
def test_initial_candidates_are_the_root_nodes_in_scope(
    parent: str | None, expected: tuple[str, ...]
) -> None:
    assert initial_scope_candidates(BRANCHING, parent) == expected


def test_downstream_candidates_are_the_direct_dependents() -> None:
    assert downstream_scope_candidates(BRANCHING, None, "a") == ("root.b",)


def test_reachable_nodes_follow_data_and_control_edges() -> None:
    assert reachable_node_ids("b", BRANCHING, BRANCHING.control_downstream) == {"b", "choose", "c"}


@pytest.mark.parametrize(
    ("entry_point", "parent", "expected"),
    [
        (None, None, None),
        ("b", None, "b"),
        ("root.loop#2.check", None, "loop"),
        ("root.loop#2.check", "root.loop#2", "check"),
        ("root.loop#2.inner#1.x", "root.loop#2", "inner"),
        ("root.other.x", "root.loop#2", None),
    ],
)
def test_an_entry_point_selects_one_direct_child_per_scope(
    entry_point: str | None, parent: str | None, expected: str | None
) -> None:
    assert entry_node_for_scope(entry_point, parent) == expected
