"""Single source of truth for persisted states and allowed transitions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ChoiceEnum(str, Enum):
    """String enum carrying the stable label used by Django and the UI."""

    label: str

    def __new__(cls, value: str, label: str) -> ChoiceEnum:
        member = str.__new__(cls, value)
        member._value_ = value
        member.label = label
        return member

    @classmethod
    def choices(cls) -> tuple[tuple[str, str], ...]:
        return tuple((member.value, member.label) for member in cls)


class RunStatus(ChoiceEnum):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    PAUSED_WAIT = "paused_wait", "Paused for input"
    CANCELING = "canceling", "Canceling"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    CANCELED = "canceled", "Canceled"
    INTERRUPTED = "interrupted", "Interrupted"


class WorktreeState(ChoiceEnum):
    NONE = "none", "None"
    CREATED = "created", "Created"
    REMOVED = "removed", "Removed"
    CLEANUP_FAILED = "cleanup_failed", "Cleanup failed"


class CleanupPolicy(ChoiceEnum):
    CLEAN_ON_SUCCESS = "clean_on_success", "Clean on success"
    RETAIN = "retain", "Retain"


class NodeStatus(ChoiceEnum):
    PENDING = "pending", "Pending"
    READY = "ready", "Ready"
    DISPATCHED = "dispatched", "Dispatched"
    RUNNING = "running", "Running"
    WAITING = "waiting", "Waiting"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    SKIPPED = "skipped", "Skipped"
    CANCELED = "canceled", "Canceled"


class NodeType(ChoiceEnum):
    AGENT = "agent", "Agent"
    COMMAND = "command", "Command"
    HUMAN_WAIT = "human_wait", "Human wait"
    CONDITION = "condition", "Condition"
    LOOP = "loop", "Loop"
    SUBWORKFLOW = "subworkflow", "Subworkflow"


class AttemptStatus(ChoiceEnum):
    CREATED = "created", "Created"
    RUNNING = "running", "Running"
    WAITING = "waiting", "Waiting"
    TERMINAL = "terminal", "Terminal"


class DriverKind(ChoiceEnum):
    ACP = "acp", "ACP"
    ANTIGRAVITY = "antigravity", "Antigravity"


class AttemptStopReason(ChoiceEnum):
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"
    OUTPUT_INVALID = "output_invalid", "Output invalid"
    TIMEOUT = "timeout", "Timeout"
    SOFT_DENIED = "soft_denied", "Soft denied"
    CANCELED = "canceled", "Canceled"
    WORKER_LOST = "worker_lost", "Worker lost"
    INTERRUPTED = "interrupted", "Interrupted"


class DispatchState(ChoiceEnum):
    DISPATCHED = "dispatched", "Dispatched"
    CLAIMED = "claimed", "Claimed"
    CONSUMED = "consumed", "Consumed"


class DraftValidationState(ChoiceEnum):
    VALID = "valid", "Valid"
    INVALID = "invalid", "Invalid"
    UNCHECKED = "unchecked", "Unchecked"


class EventSource(ChoiceEnum):
    RUN = "run", "Run"
    NODE = "node", "Node"
    ATTEMPT = "attempt", "Attempt"
    AGENT = "agent", "Agent"
    COMMAND = "command", "Command"
    SYSTEM = "system", "System"


class EventSensitivity(ChoiceEnum):
    NORMAL = "normal", "Normal"
    REDACTED = "redacted", "Redacted"


class PreservationState(ChoiceEnum):
    PENDING = "pending", "Pending"
    PRESERVED = "preserved", "Preserved"
    FAILED = "failed", "Failed"


class InteractionKind(ChoiceEnum):
    PERMISSION = "permission", "Permission"
    ELICITATION = "elicitation", "Elicitation"
    WAIT = "wait", "Wait"


class InteractionStatus(ChoiceEnum):
    PENDING = "pending", "Pending"
    ANSWERED = "answered", "Answered"
    EXPIRED = "expired", "Expired"
    DISCARDED = "discarded", "Discarded"


class ControlKind(ChoiceEnum):
    PERMISSION_ANSWER = "permission_answer", "Permission answer"
    ELICITATION_ANSWER = "elicitation_answer", "Elicitation answer"
    WAIT_ANSWER = "wait_answer", "Wait answer"
    CANCEL = "cancel", "Cancel"


class ControlState(ChoiceEnum):
    PENDING = "pending", "Pending"
    CLAIMED = "claimed", "Claimed"
    APPLIED = "applied", "Applied"
    STALE = "stale", "Stale"
    INVALID = "invalid", "Invalid"


class LockMode(ChoiceEnum):
    READ = "read", "Read"
    WRITE = "write", "Write"


@dataclass(frozen=True, slots=True)
class Transition:
    """One normative state transition and its public event."""

    source: str | None
    action: str
    guard: str
    target: str
    event: str


RUN_TRANSITIONS: tuple[Transition, ...] = (
    Transition(None, "launch", "preflight_passed", RunStatus.PENDING, "run.created"),
    Transition(
        RunStatus.PENDING,
        "worktree_ready",
        "branch_and_worktree_created",
        RunStatus.RUNNING,
        "run.started",
    ),
    Transition(
        RunStatus.PENDING,
        "worktree_failed",
        "creation_error",
        RunStatus.FAILED,
        "run.failed",
    ),
    Transition(
        RunStatus.RUNNING,
        "node_waiting",
        "one_or_more_nodes_waiting",
        RunStatus.PAUSED_WAIT,
        "run.paused",
    ),
    Transition(
        RunStatus.PAUSED_WAIT,
        "wait_answered",
        "no_waiting_nodes_and_none_failed",
        RunStatus.RUNNING,
        "run.resumed",
    ),
    Transition(
        RunStatus.RUNNING,
        "all_succeeded",
        "all_nodes_terminal_success",
        RunStatus.SUCCEEDED,
        "run.succeeded",
    ),
    Transition(
        RunStatus.RUNNING,
        "node_failed",
        "fail_fast",
        RunStatus.CANCELING,
        "run.failing",
    ),
    Transition(
        RunStatus.PAUSED_WAIT,
        "node_failed",
        "fail_fast",
        RunStatus.CANCELING,
        "run.failing",
    ),
    Transition(
        RunStatus.RUNNING,
        "owner_cancel",
        "owner_requested",
        RunStatus.CANCELING,
        "run.canceling",
    ),
    Transition(
        RunStatus.PAUSED_WAIT,
        "owner_cancel",
        "owner_requested",
        RunStatus.CANCELING,
        "run.canceling",
    ),
    Transition(
        RunStatus.CANCELING,
        "cancel_drain_complete",
        "owner_initiated_and_no_active_attempt",
        RunStatus.CANCELED,
        "run.canceled",
    ),
    Transition(
        RunStatus.CANCELING,
        "failure_drain_complete",
        "failure_initiated_and_no_active_attempt",
        RunStatus.FAILED,
        "run.failed",
    ),
    Transition(
        RunStatus.RUNNING,
        "orderly_shutdown",
        "shutdown_marker_set",
        RunStatus.INTERRUPTED,
        "run.interrupted",
    ),
    Transition(
        RunStatus.PAUSED_WAIT,
        "orderly_shutdown",
        "shutdown_marker_set",
        RunStatus.INTERRUPTED,
        "run.interrupted",
    ),
    Transition(
        RunStatus.CANCELING,
        "orderly_shutdown",
        "shutdown_marker_set",
        RunStatus.INTERRUPTED,
        "run.interrupted",
    ),
    Transition(
        RunStatus.INTERRUPTED,
        "restart_reconcile",
        "snapshot_and_artifacts_valid",
        RunStatus.RUNNING,
        "run.resumed",
    ),
    Transition(
        RunStatus.FAILED,
        "manual_rerun",
        "owner_requested_failed_node",
        RunStatus.RUNNING,
        "run.rerun",
    ),
)

NODE_TRANSITIONS: tuple[Transition, ...] = (
    Transition(None, "create", "always", NodeStatus.PENDING, "node.created"),
    Transition(
        NodeStatus.PENDING,
        "dependencies_satisfied",
        "needs_succeeded_and_guard_true",
        NodeStatus.READY,
        "node.ready",
    ),
    Transition(
        NodeStatus.PENDING,
        "guard_false",
        "if_expression_false",
        NodeStatus.SKIPPED,
        "node.skipped",
    ),
    Transition(
        NodeStatus.PENDING,
        "dependencies_unreachable",
        "upstream_terminal_blocks_needs",
        NodeStatus.SKIPPED,
        "node.skipped",
    ),
    Transition(
        NodeStatus.READY,
        "dispatch",
        "claim_created",
        NodeStatus.DISPATCHED,
        "node.dispatched",
    ),
    Transition(
        NodeStatus.DISPATCHED,
        "attempt_started",
        "claim_won_and_gate_acquired",
        NodeStatus.RUNNING,
        "node.running",
    ),
    Transition(
        NodeStatus.RUNNING,
        "interaction_requested",
        "interaction_created",
        NodeStatus.WAITING,
        "node.waiting",
    ),
    Transition(
        NodeStatus.WAITING,
        "interaction_answered",
        "control_applied",
        NodeStatus.RUNNING,
        "node.running",
    ),
    Transition(
        NodeStatus.WAITING,
        "timeout_routed",
        "on_timeout_declared",
        NodeStatus.SUCCEEDED,
        "node.succeeded",
    ),
    Transition(
        NodeStatus.RUNNING,
        "complete",
        "outputs_and_commit_valid",
        NodeStatus.SUCCEEDED,
        "node.succeeded",
    ),
    Transition(
        NodeStatus.RUNNING,
        "fail",
        "attempt_failed",
        NodeStatus.FAILED,
        "node.failed",
    ),
    Transition(
        NodeStatus.WAITING,
        "fail",
        "timeout_or_worker_lost",
        NodeStatus.FAILED,
        "node.failed",
    ),
    Transition(
        NodeStatus.RUNNING,
        "cancel",
        "run_canceling",
        NodeStatus.CANCELED,
        "node.canceled",
    ),
    Transition(
        NodeStatus.WAITING,
        "cancel",
        "run_canceling",
        NodeStatus.CANCELED,
        "node.canceled",
    ),
    Transition(
        NodeStatus.PENDING,
        "fail_fast",
        "run_canceling",
        NodeStatus.CANCELED,
        "node.canceled",
    ),
    Transition(
        NodeStatus.READY,
        "fail_fast",
        "run_canceling",
        NodeStatus.CANCELED,
        "node.canceled",
    ),
    Transition(
        NodeStatus.DISPATCHED,
        "fail_fast",
        "run_canceling",
        NodeStatus.CANCELED,
        "node.canceled",
    ),
    Transition(
        NodeStatus.RUNNING,
        "interrupt",
        "orderly_shutdown",
        NodeStatus.PENDING,
        "node.interrupted",
    ),
    Transition(
        NodeStatus.WAITING,
        "interrupt",
        "orderly_shutdown",
        NodeStatus.PENDING,
        "node.interrupted",
    ),
    Transition(
        NodeStatus.FAILED,
        "rerun",
        "owner_requested",
        NodeStatus.READY,
        "node.ready",
    ),
    Transition(
        NodeStatus.CANCELED,
        "recompute",
        "canceled_only_by_fail_fast",
        NodeStatus.PENDING,
        "node.pending",
    ),
)

INTERACTION_TRANSITIONS: tuple[Transition, ...] = (
    Transition(None, "request", "current_attempt", InteractionStatus.PENDING, "requested"),
    Transition(
        InteractionStatus.PENDING,
        "answer",
        "matching_control_applied",
        InteractionStatus.ANSWERED,
        "answered",
    ),
    Transition(
        InteractionStatus.PENDING,
        "deadline",
        "deadline_reached",
        InteractionStatus.EXPIRED,
        "expired",
    ),
    Transition(
        InteractionStatus.PENDING,
        "attempt_lost",
        "cancel_shutdown_or_loss",
        InteractionStatus.DISCARDED,
        "discarded",
    ),
)

CONTROL_TRANSITIONS: tuple[Transition, ...] = (
    Transition(None, "post", "authenticated_and_valid", ControlState.PENDING, "accepted"),
    Transition(
        ControlState.PENDING,
        "claim",
        "current_attempt",
        ControlState.CLAIMED,
        "claimed",
    ),
    Transition(
        ControlState.CLAIMED,
        "apply",
        "live_session",
        ControlState.APPLIED,
        "applied",
    ),
    Transition(
        ControlState.CLAIMED,
        "lease_recover",
        "attempt_session_still_live",
        ControlState.PENDING,
        "pending",
    ),
    Transition(
        ControlState.PENDING,
        "supersede",
        "not_current_attempt",
        ControlState.STALE,
        "stale",
    ),
    Transition(
        ControlState.CLAIMED,
        "supersede",
        "not_current_attempt_or_expired",
        ControlState.STALE,
        "stale",
    ),
    Transition(None, "reject", "invalid_payload", ControlState.INVALID, "invalid"),
)

TERMINAL_RUN_STATUSES = frozenset({RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELED})
TERMINAL_NODE_STATUSES = frozenset(
    {NodeStatus.SUCCEEDED, NodeStatus.FAILED, NodeStatus.SKIPPED, NodeStatus.CANCELED}
)
ACTIVE_NODE_STATUSES = frozenset({NodeStatus.DISPATCHED, NodeStatus.RUNNING, NodeStatus.WAITING})

__all__ = [
    "ACTIVE_NODE_STATUSES",
    "CONTROL_TRANSITIONS",
    "INTERACTION_TRANSITIONS",
    "NODE_TRANSITIONS",
    "RUN_TRANSITIONS",
    "TERMINAL_NODE_STATUSES",
    "TERMINAL_RUN_STATUSES",
    "AttemptStatus",
    "AttemptStopReason",
    "ChoiceEnum",
    "CleanupPolicy",
    "ControlKind",
    "ControlState",
    "DispatchState",
    "DraftValidationState",
    "DriverKind",
    "EventSensitivity",
    "EventSource",
    "InteractionKind",
    "InteractionStatus",
    "LockMode",
    "NodeStatus",
    "NodeType",
    "PreservationState",
    "RunStatus",
    "Transition",
    "WorktreeState",
]
