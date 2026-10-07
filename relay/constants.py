"""Stable Relay limits, identifiers, and public exit codes."""

from http import HTTPStatus
from typing import Final

APP_NAME: Final = "relay"
SCHEMA_VERSION: Final = 1
RUN_BRANCH_PREFIX: Final = "relay/run/"
# Root-level workflow documents remain owner files, even when a run produces them.
WORKFLOW_DOCUMENT_NAMES: Final = frozenset(
    {
        "DRAFT_PLAN.md",
        "INITIAL_OPUS_PLANNING_PROMPT.md",
        "FEATURE_SPEC_AND_PLAN.md",
        "EXECUTION_PROMPT.md",
        "PLAN_CRITIQUE.md",
        "OPUS_PLAN_REVISION_REQUEST.md",
        "PLAN_REVISION_SUMMARY.md",
        "PLAN_REVISION_VERIFICATION.md",
        "REVIEW.md",
        "WALKTHROUGH.md",
        "REVIEW_FIX_PROMPT.md",
        "REVIEW_FIX_VERIFICATION.md",
        "FOLLOWUP.md",
        "TEST_AUDIT.md",
        "E2E_VERIFICATION.md",
        "PLAN_CHECKPOINT.json",
        "REVIEW_CHECKPOINT.json",
        "AUDIT_CHECKPOINT.json",
        "E2E_CHECKPOINT.json",
    }
)

EXIT_ALREADY_INITIALIZED: Final = 2
EXIT_NOT_A_REPOSITORY: Final = 3
EXIT_UP_CONFIG: Final = 4
EXIT_SUPERVISOR: Final = 5
EXIT_DOCTOR_FAILED: Final = 6
EXIT_PROJECT_NOT_FOUND: Final = 7
EXIT_NOTHING_TO_CLEAN: Final = 8
EXIT_RELAY_ERROR: Final = 1
EXIT_CONFIG_ERROR: Final = 20
EXIT_PROJECT_DISCOVERY_ERROR: Final = 21
EXIT_PROJECT_RELINK_ERROR: Final = 22
EXIT_SCHEMA_VERSION_ERROR: Final = 23
EXIT_WORKFLOW_VALIDATION_ERROR: Final = 24
EXIT_PROMPT_RESOLUTION_ERROR: Final = 25
EXIT_PATH_SAFETY_ERROR: Final = 26
EXIT_DIRTY_REPOSITORY_ERROR: Final = 27
EXIT_GIT_ERROR: Final = 28
EXIT_MODEL_ERROR: Final = 29
EXIT_AGENT_ERROR: Final = 30
EXIT_PERMISSION_FLOW_ERROR: Final = 31
EXIT_NODE_EXECUTION_ERROR: Final = 32
EXIT_ARTIFACT_PRESERVATION_ERROR: Final = 33
EXIT_CANCELLATION_ERROR: Final = 34
EXIT_DISPATCH_ERROR: Final = 35
EXIT_PERSISTENCE_ERROR: Final = 36

HTTP_BAD_REQUEST: Final = HTTPStatus.BAD_REQUEST
HTTP_NOT_FOUND: Final = HTTPStatus.NOT_FOUND
HTTP_CONFLICT: Final = HTTPStatus.CONFLICT
HTTP_UNPROCESSABLE_CONTENT: Final = HTTPStatus.UNPROCESSABLE_ENTITY
HTTP_INTERNAL_SERVER_ERROR: Final = HTTPStatus.INTERNAL_SERVER_ERROR
HTTP_BAD_GATEWAY: Final = HTTPStatus.BAD_GATEWAY
HTTP_SERVICE_UNAVAILABLE: Final = HTTPStatus.SERVICE_UNAVAILABLE

MAX_LOOP_ITERATIONS: Final = 100
DEFAULT_REPAIR_ROUNDS: Final = 4
REPAIR_NODE_PREFIX: Final = "relay_repair_"
DEFAULT_FIX_INSTRUCTION: Final = (
    "Repair only the issues identified by the rejected review or verification "
    "for this stage. Read its reports and retained evidence before acting. "
    "Preserve completed work, original scope, and required checks. Do not weaken "
    "acceptance criteria or rewrite a rejected verdict as a pass. Follow the "
    "configured instructions and report genuine blockers."
)
DEFAULT_VERIFY_INSTRUCTION: Final = (
    "Independently verify the repairs against the rejected findings, the original "
    "scope, and fresh evidence. Write the configured verification report and "
    "acceptance output. Keep failed verdicts accurate; a successful agent turn "
    "does not establish that the work passed verification."
)
MAX_AUTOMATIC_RETRIES: Final = 2
MAX_EXPANDED_NODES: Final = 10_000
API_MAX_PAGE: Final = 200
API_MAX_PAGE_BYTES: Final = 1_048_576
# Leave room for JSON escaping and metadata around a review document or Git diff.
REVIEW_PREVIEW_MAX_BYTES: Final = API_MAX_PAGE_BYTES // 4
# Run notices stay small even when an agent streams a long final message.
RUN_PROBLEM_TEXT_MAX_CHARS: Final = 4_096
RUN_PROBLEM_MESSAGE_MAX_EVENTS: Final = 16
PROVIDER_USAGE_WINDOW_MAX_CHARS: Final = 64
SSE_MAX_BATCH: Final = 100
SSE_MAX_FRAME_BYTES: Final = 65_536
EVENT_MAX_PAYLOAD_BYTES: Final = 65_536
# Leave room for JSON escaping and route metadata in the durable rerun event.
RETRY_HANDOFF_MAX_BYTES: Final = EVENT_MAX_PAYLOAD_BYTES // 8
DEFAULT_RETRY_HANDOFF_PROMPT: Final = (
    "Continue the failed step in this existing Relay run. Read the files and "
    "reports already in the worktree, and inspect unfinished work before acting. "
    "Follow the original step instructions and its declared outputs. Preserve "
    "completed work and successful stages. Finish the remaining work for this "
    "step and report fresh verification evidence. Use the current Relay agent "
    "and exact model for report provenance."
)
DEFAULT_UNSTARTED_HANDOFF_PROMPT: Final = (
    "Perform this unstarted step in the existing Relay run. Read the existing "
    "files and retained upstream reports before acting. Follow this step's "
    "captured instructions and declared outputs. Preserve completed stages "
    "and committed work rather than repeating them. Report fresh verification "
    "evidence and identify any missing evidence. Use the current Relay agent "
    "and exact model for report provenance."
)
DEFAULT_RECOVERY_PROMPT: Final = (
    "Recover only this failed step. Follow its original instructions and scope. "
    "Read the retained evidence and existing reports before acting. Fix the "
    "supplied error and preserve completed work. Do not start new feature work, "
    "change models or permissions, weaken checks, invent evidence, or turn "
    "failing verdicts into passes. Report genuine blockers when the original "
    "scope cannot resolve them."
)
CONTROL_PAYLOAD_MAX_BYTES: Final = 65_536
CONTROL_IDEMPOTENCY_KEY_MAX_CHARS: Final = 200
RECONCILE_MAX_ITEMS: Final = 200
DATABASE_INTEGER_MAX: Final = (1 << 63) - 1

DB_BUSY_TIMEOUT_MS: Final = 5_000
SECRET_KEY_TOKEN_BYTES: Final = 48
APPLICATION_LOG_MAX_BYTES: Final = 5_000_000
APPLICATION_LOG_BACKUP_COUNT: Final = 3
APPLICATION_LOG_RETAINED_PROCESSES: Final = 3
# First line of every Relay log file; retention and cleanup change only files that start with it.
APPLICATION_LOG_OWNERSHIP_LINE: Final = "Relay process log"
WINDOWS_PROCESS_QUERY_LIMITED_INFORMATION: Final = 0x1000
WINDOWS_PROCESS_STILL_ACTIVE: Final = 259
WINDOWS_ERROR_INVALID_PARAMETER: Final = 87
LOOPBACK_HOSTS: Final = frozenset({"127.0.0.1", "localhost", "::1"})
REGISTRY_CACHE_TTL_SECONDS: Final = 86_400
REGISTRY_FETCH_TIMEOUT_SECONDS: Final = 10.0
AGENT_PROBE_TIMEOUT_SECONDS: Final = 30.0
AGENT_EVENT_QUEUE_MAX_ITEMS: Final = 100
AGENT_STREAM_LINE_MAX_BYTES: Final = API_MAX_PAGE_BYTES
PROCESS_STREAM_CHUNK_BYTES: Final = 8_192
RECONCILE_INTERVAL_SECONDS: Final = 5.0
DISPATCH_ORPHAN_AFTER_SECONDS: Final = 30.0
CONTROL_POLL_INTERVAL_SECONDS: Final = 0.25
CONTROL_REQUEST_TTL_SECONDS: Final = 300.0
CONTROL_CLAIM_STALE_AFTER_SECONDS: Final = 30.0
ATTEMPT_HEARTBEAT_INTERVAL_SECONDS: Final = 5.0
ATTEMPT_STALE_AFTER_SECONDS: Final = 30.0
INSTANCE_HEARTBEAT_INTERVAL_SECONDS: Final = 5.0
INSTANCE_STALE_AFTER_SECONDS: Final = 30.0
EDITOR_LEASE_TTL_SECONDS: Final = 60.0
SSE_POLL_INTERVAL_SECONDS: Final = 0.5
SHUTDOWN_TIMEOUT_SECONDS: Final = 15.0
CANCELLATION_GRACE_SECONDS: Final = 10.0
PROCESS_EXIT_GRACE_SECONDS: Final = 2.0
PROCESS_EXIT_POLL_SECONDS: Final = 0.05
PROCESS_IDENTITY_MAX_CHARS: Final = 256
# Protocol cancel, OS grace, bounded tree-kill command, and final process wait.
AGENT_STOP_TIMEOUT_SECONDS: Final = (CANCELLATION_GRACE_SECONDS * 2) + (
    PROCESS_EXIT_GRACE_SECONDS * 2
)
# Stdin avoids command-line limits; bound the composed UTF-8 input independently.
ANTIGRAVITY_PROMPT_MAX_BYTES: Final = 1_048_576
WINDOWS_COMMAND_MAX_CHARS: Final = 32_767
WINDOWS_BATCH_COMMAND_MAX_CHARS: Final = 8_191
MIGRATION_LOCK_WAIT_SECONDS: Final = 15.0
MIGRATION_LOCK_POLL_SECONDS: Final = 0.1
CLEANUP_BACKOFF_SECONDS: Final = (0.05, 0.2, 0.8)

DEFAULT_HOST: Final = "127.0.0.1"
DEFAULT_PORT: Final = 7845
DEFAULT_WORKERS: Final = 1
DEFAULT_ANTIGRAVITY_PRINT_TIMEOUT_SECONDS: Final = 300
