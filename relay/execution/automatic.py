"""Deterministic recovery instructions for explicitly enabled agent steps."""

from __future__ import annotations

from hashlib import sha256

from relay.constants import DEFAULT_RECOVERY_PROMPT, RETRY_HANDOFF_MAX_BYTES

RECOVERABLE_ERRORS = frozenset(
    {
        "output_validation_error",
        "commit_validation_error",
        "dirty_repository_error",
        "node_timeout",
    }
)
PENDING_RECOVERY_STATES = ("scheduled", "preparing")


def _bounded(value: str, limit: int) -> str:
    return value.encode("utf-8")[:limit].decode("utf-8", errors="ignore")


def recovery_instruction(
    scope_path: str, error_code: str, message: str, evidence_index: str | None = None
) -> tuple[str, str]:
    """Keep error text bounded without changing the original prompt bytes.

    For example, `output_validation_error` with `Missing Created by` becomes
    a separately appended instruction containing that exact error and scope.
    An evidence index path adds a line naming the file that maps the retained
    diff, untracked files, rejected reports, and the untruncated failure.
    """
    # A scope containing 5,000 `é` characters becomes a complete UTF-8 prefix,
    # leaving room for the fixed instruction and failure detail within 8 KiB.
    scope = _bounded(scope_path, RETRY_HANDOFF_MAX_BYTES // 4)
    # A path cut mid-way would point nowhere, so an oversized one is omitted.
    index = (
        f"Evidence index: {evidence_index}\n"
        if evidence_index and len(evidence_index.encode("utf-8")) <= RETRY_HANDOFF_MAX_BYTES // 4
        else ""
    )
    prefix = (
        f"{DEFAULT_RECOVERY_PROMPT}\n\nFailed step: {scope}\nError code: {error_code}\n"
        f"{index}Failure: "
    )
    remaining = max(0, RETRY_HANDOFF_MAX_BYTES - len(prefix.encode("utf-8")))
    detail = _bounded(message, remaining)
    instruction = prefix + detail
    return instruction, sha256(instruction.encode("utf-8")).hexdigest()
