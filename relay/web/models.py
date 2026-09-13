"""Django models for Relay's durable local source of truth."""

from __future__ import annotations

from typing import ClassVar
import uuid

from django.db import models
from django.utils import timezone


class RelayModel(models.Model):
    """Typed abstract base exposing Django's default manager."""

    objects: ClassVar[models.Manager] = models.Manager()

    class Meta:
        abstract = True


class RunStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    PAUSED_WAIT = "paused_wait", "Paused for input"
    CANCELING = "canceling", "Canceling"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    CANCELED = "canceled", "Canceled"
    INTERRUPTED = "interrupted", "Interrupted"


class WorktreeState(models.TextChoices):
    NONE = "none", "None"
    CREATED = "created", "Created"
    REMOVED = "removed", "Removed"
    CLEANUP_FAILED = "cleanup_failed", "Cleanup failed"


class CleanupPolicy(models.TextChoices):
    CLEAN_ON_SUCCESS = "clean_on_success", "Clean on success"
    RETAIN = "retain", "Retain"


class NodeStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    READY = "ready", "Ready"
    DISPATCHED = "dispatched", "Dispatched"
    RUNNING = "running", "Running"
    WAITING = "waiting", "Waiting"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    SKIPPED = "skipped", "Skipped"
    CANCELED = "canceled", "Canceled"


class NodeType(models.TextChoices):
    AGENT = "agent", "Agent"
    COMMAND = "command", "Command"
    HUMAN_WAIT = "human_wait", "Human wait"
    CONDITION = "condition", "Condition"
    LOOP = "loop", "Loop"
    SUBWORKFLOW = "subworkflow", "Subworkflow"


class AttemptStatus(models.TextChoices):
    CREATED = "created", "Created"
    RUNNING = "running", "Running"
    WAITING = "waiting", "Waiting"
    TERMINAL = "terminal", "Terminal"


class DriverKind(models.TextChoices):
    ACP = "acp", "ACP"
    ANTIGRAVITY = "antigravity", "Antigravity"


class AttemptStopReason(models.TextChoices):
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"
    OUTPUT_INVALID = "output_invalid", "Output invalid"
    TIMEOUT = "timeout", "Timeout"
    SOFT_DENIED = "soft_denied", "Soft denied"
    CANCELED = "canceled", "Canceled"
    WORKER_LOST = "worker_lost", "Worker lost"
    INTERRUPTED = "interrupted", "Interrupted"


class DispatchState(models.TextChoices):
    DISPATCHED = "dispatched", "Dispatched"
    CLAIMED = "claimed", "Claimed"
    CONSUMED = "consumed", "Consumed"


class DraftValidationState(models.TextChoices):
    VALID = "valid", "Valid"
    INVALID = "invalid", "Invalid"
    UNCHECKED = "unchecked", "Unchecked"


class EventSource(models.TextChoices):
    RUN = "run", "Run"
    NODE = "node", "Node"
    ATTEMPT = "attempt", "Attempt"
    AGENT = "agent", "Agent"
    COMMAND = "command", "Command"
    SYSTEM = "system", "System"


class EventSensitivity(models.TextChoices):
    NORMAL = "normal", "Normal"
    REDACTED = "redacted", "Redacted"


class PreservationState(models.TextChoices):
    PENDING = "pending", "Pending"
    PRESERVED = "preserved", "Preserved"
    FAILED = "failed", "Failed"


class InteractionKind(models.TextChoices):
    PERMISSION = "permission", "Permission"
    ELICITATION = "elicitation", "Elicitation"
    WAIT = "wait", "Wait"


class InteractionStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    ANSWERED = "answered", "Answered"
    EXPIRED = "expired", "Expired"
    DISCARDED = "discarded", "Discarded"


class ControlKind(models.TextChoices):
    PERMISSION_ANSWER = "permission_answer", "Permission answer"
    ELICITATION_ANSWER = "elicitation_answer", "Elicitation answer"
    WAIT_ANSWER = "wait_answer", "Wait answer"
    CANCEL = "cancel", "Cancel"


class ControlState(models.TextChoices):
    PENDING = "pending", "Pending"
    CLAIMED = "claimed", "Claimed"
    APPLIED = "applied", "Applied"
    STALE = "stale", "Stale"
    INVALID = "invalid", "Invalid"


class LockMode(models.TextChoices):
    READ = "read", "Read"
    WRITE = "write", "Write"


class Installation(RelayModel):
    """Singleton installation state; the owner flag is created transactionally."""

    id: models.PositiveSmallIntegerField = models.PositiveSmallIntegerField(
        primary_key=True, default=1, editable=False
    )
    owner_created: models.BooleanField = models.BooleanField(default=False)
    settings: models.JSONField = models.JSONField(default=dict)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)


class Instance(RelayModel):
    """The sole live supervisor lease, replaced only after heartbeat expiry."""

    id: models.UUIDField = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    singleton_key: models.PositiveSmallIntegerField = models.PositiveSmallIntegerField(
        default=1, unique=True, editable=False
    )
    pid: models.PositiveIntegerField = models.PositiveIntegerField()
    host: models.TextField = models.TextField()
    started_at: models.DateTimeField = models.DateTimeField(default=timezone.now)
    heartbeat_at: models.DateTimeField = models.DateTimeField(default=timezone.now)
    shutdown_requested: models.BooleanField = models.BooleanField(default=False)


class Project(RelayModel):
    """A repository identified by its canonical filesystem path."""

    id: models.UUIDField = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    canonical_path: models.TextField = models.TextField(unique=True)
    display_name: models.TextField = models.TextField()
    git_root: models.TextField = models.TextField()
    last_opened_at: models.DateTimeField = models.DateTimeField(null=True, blank=True)


class ProjectRelink(RelayModel):
    """Append-only audit evidence for an explicit project move."""

    project: models.ForeignKey = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="relinks"
    )
    old_path: models.TextField = models.TextField()
    new_path: models.TextField = models.TextField()
    at: models.DateTimeField = models.DateTimeField(default=timezone.now)


class WorkflowDraft(RelayModel):
    """Latest recovery YAML for one tracked workflow."""

    project: models.ForeignKey = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="workflow_drafts"
    )
    workflow_key: models.TextField = models.TextField()
    recovery_yaml: models.TextField = models.TextField()
    base_file_hash: models.CharField = models.CharField(max_length=64)
    validation_state: models.CharField = models.CharField(
        max_length=16,
        choices=DraftValidationState.choices,
        default=DraftValidationState.UNCHECKED,
    )
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=("project", "workflow_key"), name="relay_unique_workflow_draft"
            )
        ]


class EditorLease(RelayModel):
    """Renewable single-editor lease for one workflow."""

    project: models.ForeignKey = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="editor_leases"
    )
    workflow_key: models.TextField = models.TextField()
    holder: models.TextField = models.TextField()
    acquired_at: models.DateTimeField = models.DateTimeField(default=timezone.now)
    expires_at: models.DateTimeField = models.DateTimeField()

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=("project", "workflow_key"), name="relay_unique_editor_lease"
            )
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=("expires_at",), name="relay_lease_expiry_idx")
        ]


class Run(RelayModel):
    """One immutable-input workflow execution and its mutable status."""

    id: models.UUIDField = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project: models.ForeignKey = models.ForeignKey(
        Project, on_delete=models.PROTECT, related_name="runs"
    )
    workflow_key: models.TextField = models.TextField()
    status: models.CharField = models.CharField(
        max_length=16, choices=RunStatus.choices, default=RunStatus.PENDING
    )
    source_commit: models.CharField = models.CharField(max_length=40)
    run_branch: models.TextField = models.TextField(unique=True)
    worktree_path: models.TextField = models.TextField(unique=True)
    worktree_state: models.CharField = models.CharField(
        max_length=16, choices=WorktreeState.choices, default=WorktreeState.NONE
    )
    cleanup_policy: models.CharField = models.CharField(
        max_length=20,
        choices=CleanupPolicy.choices,
        default=CleanupPolicy.CLEAN_ON_SUCCESS,
    )
    launcher: models.TextField = models.TextField()
    started_at: models.DateTimeField = models.DateTimeField(null=True, blank=True)
    ended_at: models.DateTimeField = models.DateTimeField(null=True, blank=True)
    failure_code: models.TextField = models.TextField(null=True, blank=True)
    failure_summary: models.TextField = models.TextField(null=True, blank=True)
    entry_point: models.TextField = models.TextField(null=True, blank=True)
    recorded_head: models.CharField = models.CharField(max_length=40)

    class Meta:
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=("project", "status"), name="relay_run_project_status_idx")
        ]


class RunSnapshot(RelayModel):
    """Write-once workflow, prompt, input, route, and version evidence."""

    run: models.OneToOneField = models.OneToOneField(
        Run, on_delete=models.CASCADE, related_name="snapshot", primary_key=True
    )
    workflow_yaml: models.TextField = models.TextField()
    subworkflows: models.JSONField = models.JSONField(default=dict)
    resolved_prompts: models.JSONField = models.JSONField(default=list)
    typed_inputs: models.JSONField = models.JSONField(default=dict)
    route_table: models.JSONField = models.JSONField(default=dict)
    default_model: models.TextField = models.TextField(blank=True)
    agent_prefs: models.JSONField = models.JSONField(default=list)
    relay_version: models.TextField = models.TextField()
    runtime_versions: models.JSONField = models.JSONField(default=dict)
    hashes: models.JSONField = models.JSONField(default=dict)
    created_at: models.DateTimeField = models.DateTimeField(default=timezone.now)


class NodeRun(RelayModel):
    """One materialized node at an unambiguous runtime scope path."""

    run: models.ForeignKey = models.ForeignKey(
        Run, on_delete=models.CASCADE, related_name="node_runs"
    )
    scope_path: models.TextField = models.TextField()
    parent_scope_path: models.TextField = models.TextField(null=True, blank=True)
    node_id: models.TextField = models.TextField()
    node_type: models.CharField = models.CharField(max_length=16, choices=NodeType.choices)
    frozen_def: models.JSONField = models.JSONField(default=dict)
    status: models.CharField = models.CharField(
        max_length=16, choices=NodeStatus.choices, default=NodeStatus.PENDING
    )
    writes: models.BooleanField = models.BooleanField(default=False)
    selected_branch: models.TextField = models.TextField(null=True, blank=True)
    loop_index: models.PositiveIntegerField = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=("run", "scope_path"), name="relay_unique_node_scope")
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=("run", "status"), name="relay_node_run_status_idx"),
            models.Index(fields=("run", "parent_scope_path"), name="relay_node_parent_idx"),
        ]


class NodeAttempt(RelayModel):
    """One fail-fast execution try; interrupted recovery creates another row."""

    node_run: models.ForeignKey = models.ForeignKey(
        NodeRun, on_delete=models.CASCADE, related_name="attempts"
    )
    attempt_number: models.PositiveIntegerField = models.PositiveIntegerField()
    status: models.CharField = models.CharField(
        max_length=16, choices=AttemptStatus.choices, default=AttemptStatus.CREATED
    )
    worker_id: models.TextField = models.TextField()
    process_pid: models.PositiveIntegerField = models.PositiveIntegerField(null=True, blank=True)
    acp_session_id: models.TextField = models.TextField(null=True, blank=True)
    driver_kind: models.CharField = models.CharField(
        max_length=16, choices=DriverKind.choices, null=True, blank=True
    )
    agent_id: models.TextField = models.TextField(blank=True)
    agent_version: models.TextField = models.TextField(blank=True)
    model_value: models.TextField = models.TextField(blank=True)
    config_ids: models.JSONField = models.JSONField(default=dict)
    starting_head: models.CharField = models.CharField(max_length=40)
    ending_head: models.CharField = models.CharField(max_length=40, null=True, blank=True)
    started_at: models.DateTimeField = models.DateTimeField(null=True, blank=True)
    ended_at: models.DateTimeField = models.DateTimeField(null=True, blank=True)
    stop_reason: models.CharField = models.CharField(
        max_length=16, choices=AttemptStopReason.choices, null=True, blank=True
    )
    exit_code: models.IntegerField = models.IntegerField(null=True, blank=True)
    error_code: models.TextField = models.TextField(null=True, blank=True)
    heartbeat_at: models.DateTimeField = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=("node_run", "attempt_number"), name="relay_unique_node_attempt"
            )
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=("status", "heartbeat_at"), name="relay_attempt_heartbeat_idx")
        ]


class DispatchClaim(RelayModel):
    """Durable dispatch intent claimed atomically with attempt creation."""

    node_run: models.ForeignKey = models.ForeignKey(
        NodeRun, on_delete=models.CASCADE, related_name="dispatch_claims"
    )
    attempt: models.ForeignKey = models.ForeignKey(
        NodeAttempt,
        on_delete=models.SET_NULL,
        related_name="dispatch_claims",
        null=True,
        blank=True,
    )
    claim_token: models.CharField = models.CharField(max_length=32, unique=True)
    state: models.CharField = models.CharField(
        max_length=16, choices=DispatchState.choices, default=DispatchState.DISPATCHED
    )
    claim_owner: models.TextField = models.TextField(null=True, blank=True)
    enqueued_at: models.DateTimeField = models.DateTimeField(null=True, blank=True)
    claimed_at: models.DateTimeField = models.DateTimeField(null=True, blank=True)
    consumed_at: models.DateTimeField = models.DateTimeField(null=True, blank=True)
    created_at: models.DateTimeField = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=("state", "created_at"), name="relay_dispatch_state_idx")
        ]


class RunEvent(RelayModel):
    """Append-only event whose global primary key is the SSE replay cursor."""

    id: models.BigAutoField = models.BigAutoField(primary_key=True)
    run: models.ForeignKey = models.ForeignKey(Run, on_delete=models.CASCADE, related_name="events")
    node_run: models.ForeignKey = models.ForeignKey(
        NodeRun,
        on_delete=models.SET_NULL,
        related_name="events",
        null=True,
        blank=True,
    )
    attempt: models.ForeignKey = models.ForeignKey(
        NodeAttempt,
        on_delete=models.SET_NULL,
        related_name="events",
        null=True,
        blank=True,
    )
    ts: models.DateTimeField = models.DateTimeField(default=timezone.now)
    type: models.TextField = models.TextField()
    version: models.PositiveSmallIntegerField = models.PositiveSmallIntegerField(default=1)
    source: models.CharField = models.CharField(max_length=16, choices=EventSource.choices)
    payload: models.JSONField = models.JSONField(default=dict)
    sensitivity: models.CharField = models.CharField(
        max_length=16,
        choices=EventSensitivity.choices,
        default=EventSensitivity.NORMAL,
    )

    class Meta:
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=("run", "id"), name="relay_event_run_id_idx")
        ]


class Artifact(RelayModel):
    """Metadata for centrally preserved bytes from one attempt."""

    attempt: models.ForeignKey = models.ForeignKey(
        NodeAttempt, on_delete=models.CASCADE, related_name="artifacts"
    )
    declared_name: models.TextField = models.TextField()
    source_path: models.TextField = models.TextField()
    retained_path: models.TextField = models.TextField()
    sha256: models.CharField = models.CharField(max_length=64)
    media_type: models.TextField = models.TextField()
    bytes: models.BigIntegerField = models.BigIntegerField()
    preservation_state: models.CharField = models.CharField(
        max_length=16,
        choices=PreservationState.choices,
        default=PreservationState.PENDING,
    )


class HumanInteraction(RelayModel):
    """Permission, elicitation, or wait tied to one exact attempt."""

    run: models.ForeignKey = models.ForeignKey(
        Run, on_delete=models.CASCADE, related_name="interactions"
    )
    node_run: models.ForeignKey = models.ForeignKey(
        NodeRun, on_delete=models.CASCADE, related_name="interactions"
    )
    attempt: models.ForeignKey = models.ForeignKey(
        NodeAttempt, on_delete=models.CASCADE, related_name="interactions"
    )
    kind: models.CharField = models.CharField(max_length=16, choices=InteractionKind.choices)
    request_payload: models.JSONField = models.JSONField(default=dict)
    response_payload: models.JSONField = models.JSONField(null=True, blank=True)
    status: models.CharField = models.CharField(
        max_length=16,
        choices=InteractionStatus.choices,
        default=InteractionStatus.PENDING,
    )
    deadline: models.DateTimeField = models.DateTimeField(null=True, blank=True)
    created_at: models.DateTimeField = models.DateTimeField(default=timezone.now)
    answered_at: models.DateTimeField = models.DateTimeField(null=True, blank=True)


class ControlRequest(RelayModel):
    """Durable browser-to-worker request correlated to an exact attempt."""

    attempt: models.ForeignKey = models.ForeignKey(
        NodeAttempt, on_delete=models.CASCADE, related_name="control_requests"
    )
    kind: models.CharField = models.CharField(max_length=24, choices=ControlKind.choices)
    idempotency_key: models.TextField = models.TextField()
    payload: models.JSONField = models.JSONField(default=dict)
    state: models.CharField = models.CharField(
        max_length=16, choices=ControlState.choices, default=ControlState.PENDING
    )
    claim_owner: models.TextField = models.TextField(null=True, blank=True)
    created_at: models.DateTimeField = models.DateTimeField(default=timezone.now)
    claimed_at: models.DateTimeField = models.DateTimeField(null=True, blank=True)
    claim_heartbeat_at: models.DateTimeField = models.DateTimeField(null=True, blank=True)
    applied_at: models.DateTimeField = models.DateTimeField(null=True, blank=True)
    expires_at: models.DateTimeField = models.DateTimeField()

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=("attempt", "idempotency_key"), name="relay_unique_control_request"
            )
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=("state", "expires_at"), name="relay_control_expiry_idx")
        ]


class AgentModelObservation(RelayModel):
    """Advisory model inventory; launch authorization always probes again."""

    agent_id: models.TextField = models.TextField()
    model_value: models.TextField = models.TextField()
    model_name: models.TextField = models.TextField()
    config_id: models.TextField = models.TextField()
    agent_version: models.TextField = models.TextField()
    observed_at: models.DateTimeField = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=("agent_id", "observed_at"), name="relay_agent_observed_idx")
        ]


class RunLock(RelayModel):
    """A reader or writer admission lease tied to one live attempt."""

    run: models.ForeignKey = models.ForeignKey(Run, on_delete=models.CASCADE, related_name="locks")
    attempt: models.OneToOneField = models.OneToOneField(
        NodeAttempt, on_delete=models.CASCADE, related_name="run_lock"
    )
    mode: models.CharField = models.CharField(max_length=8, choices=LockMode.choices)
    starting_head: models.CharField = models.CharField(max_length=40)
    recorded_head: models.CharField = models.CharField(max_length=40)
    acquired_at: models.DateTimeField = models.DateTimeField(default=timezone.now)
    heartbeat_at: models.DateTimeField = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=("run", "mode"), name="relay_run_lock_mode_idx")
        ]
