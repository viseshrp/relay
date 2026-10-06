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
        "agent_protocol_error",
    }
)
PENDING_RECOVERY_STATES = ("scheduled", "preparing")


def recovery_instruction(scope_path: str, error_code: str, message: str) -> tuple[str, str]:
    """Keep error text bounded without changing the original prompt bytes.

    For example, `output_validation_error` with `Missing Created by` becomes
    a separately appended instruction containing that exact error and scope.
    """
    # A scope containing 5,000 `é` characters becomes a complete UTF-8 prefix,
    # leaving room for the fixed instruction and failure detail within 8 KiB.
    scope = scope_path.encode("utf-8")[: RETRY_HANDOFF_MAX_BYTES // 4].decode(
        "utf-8", errors="ignore"
    )
    prefix = (
        f"{DEFAULT_RECOVERY_PROMPT}\n\nFailed step: {scope}\nError code: {error_code}\nFailure: "
    )
    remaining = max(0, RETRY_HANDOFF_MAX_BYTES - len(prefix.encode("utf-8")))
    detail = message.encode("utf-8")[:remaining].decode("utf-8", errors="ignore")
    instruction = prefix + detail
    return instruction, sha256(instruction.encode("utf-8")).hexdigest()
