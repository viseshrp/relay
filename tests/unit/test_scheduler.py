from relay.worker.scheduler import Scheduler


def test_scheduler_capacity() -> None:
    scheduler = Scheduler(concurrency_limit=2)
    assert scheduler.has_capacity(0) is True
    assert scheduler.has_capacity(1) is True
    assert scheduler.has_capacity(2) is False
