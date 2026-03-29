from relay.worker.retry import backoff_seconds, can_retry


def test_backoff_progression() -> None:
    assert [backoff_seconds(value) for value in range(1, 6)] == [5, 10, 20, 40, 80]


def test_retry_limit_logic() -> None:
    assert can_retry(1, 5) is True
    assert can_retry(6, 5) is False
