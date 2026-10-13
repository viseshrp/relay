"""Collect identities and phase timings for serial and xdist CI runs."""

from __future__ import annotations

from collections import Counter
import json
import os
from pathlib import Path
import time
from typing import Any

import pytest

_SERIAL_MODULES = {
    "test_sqlite_reliability.py",
    "test_supervisor_recovery.py",
    "test_worker_handoff.py",
    "test_worker_heartbeats.py",
}
_BURST_TEST = "test_forty_concurrent_launches_across_projects_have_complete_sqlite_records"
_TIMED_TESTS = {
    _BURST_TEST,
    "test_coordinator_contention_logs_the_database_cause_but_keeps_the_public_error_generic",
}


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--relay-ci-report", help="Write Relay's collection and execution report.")


def pytest_configure(config: pytest.Config) -> None:
    if config.getoption("--relay-ci-report") and not hasattr(config, "workerinput"):
        config.pluginmanager.register(CiRecorder(config), "relay-ci-recorder")


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Keep deliberately timed contention and orphan ownership tests alone."""
    for item in items:
        if item.path.name in _SERIAL_MODULES or getattr(item, "originalname", None) in _TIMED_TESTS:
            item.add_marker(pytest.mark.serial_integration)


def _skip_reasons(item: pytest.Item) -> list[str]:
    reasons = []
    for marker in item.iter_markers():
        if marker.name == "skip":
            reasons.append(str(marker.kwargs.get("reason", marker.args[0] if marker.args else "")))
        elif marker.name == "skipif":
            conditions = marker.args or (marker.kwargs.get("condition", False),)
            # Repository skipif conditions are evaluated booleans. A string expression
            # cannot authorize a skip here without an explicit reviewed baseline.
            if any(not isinstance(condition, str) and bool(condition) for condition in conditions):
                reasons.append(str(marker.kwargs.get("reason", "")))
    return reasons


class CiRecorder:
    """Record in the controller; xdist forwards reports from isolated workers."""

    config: pytest.Config
    started: float
    collected: list[dict[str, Any]]
    reports: list[dict[str, Any]]
    collection_errors: list[str]
    collection_seconds: float

    def __init__(self, config: pytest.Config) -> None:
        self.config = config
        self.started = time.perf_counter()
        self.collected = []
        self.reports = []
        self.collection_errors = []
        self.collection_seconds = 0.0

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        self.collected = [
            {
                "nodeid": item.nodeid,
                "skip_reasons": _skip_reasons(item),
                "serial_integration": bool(item.get_closest_marker("serial_integration")),
            }
            for item in session.items
        ]
        self.collection_seconds = time.perf_counter() - self.started

    @pytest.hookimpl(optionalhook=True)
    def pytest_xdist_node_collection_finished(self, node: Any, ids: list[str]) -> None:
        del node
        if self.collected and [item["nodeid"] for item in self.collected] != ids:
            self.collection_errors.append("xdist workers collected different test identities")
        self.collected = [{"nodeid": nodeid} for nodeid in ids]
        self.collection_seconds = time.perf_counter() - self.started

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        if report.failed or report.skipped:
            self.collection_errors.append(f"{report.nodeid}: {report.longrepr}")

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        reason = ""
        if report.skipped:
            reason = str(
                report.longrepr[2] if isinstance(report.longrepr, tuple) else report.longrepr
            )
            reason = reason.removeprefix("Skipped: ")
        self.reports.append(
            {
                "nodeid": report.nodeid,
                "phase": report.when,
                "outcome": report.outcome,
                "seconds": report.duration,
                "skip_reason": reason,
                "worker": getattr(report, "worker_id", "main"),
            }
        )

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        del session
        completed = Counter(
            report["nodeid"] for report in self.reports if report["phase"] == "teardown"
        )
        result = {
            "schema_version": 1,
            "checkout_sha": os.environ.get("RELAY_TEST_CHECKOUT_SHA", ""),
            "requested_paths": json.loads(os.environ.get("RELAY_TEST_REQUESTED_PATHS", "[]")),
            "exit_code": int(exitstatus),
            "collected": self.collected,
            "collection_errors": self.collection_errors,
            "collection_seconds": self.collection_seconds,
            "elapsed_seconds": time.perf_counter() - self.started,
            "completed": dict(completed),
            "reports": self.reports,
        }
        destination = Path(self.config.getoption("--relay-ci-report"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
