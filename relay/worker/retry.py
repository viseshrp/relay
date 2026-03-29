from __future__ import annotations


def backoff_seconds(attempt_number: int) -> int:
    return min(5 * (2 ** max(0, attempt_number - 1)), 120)


def can_retry(attempt_number: int, retry_limit: int) -> bool:
    return attempt_number <= retry_limit
