"""Keep Relay-specific inventory and diagnostics around native pytest reports."""

from __future__ import annotations

from collections.abc import Generator, Iterator
import json
from pathlib import Path
import subprocess
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
_GIT_DIAGNOSTICS = pytest.StashKey[list[str]]()


@pytest.fixture(autouse=True)
def failed_git_diagnostics(request: pytest.FixtureRequest) -> Iterator[None]:
    """Retain real Git stderr without changing calls or exposing passing output."""
    diagnostics: list[str] = []
    request.node.stash[_GIT_DIAGNOSTICS] = diagnostics
    original = subprocess.run

    def execute(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        result = original(*args, **kwargs)
        argv = args[0] if args else kwargs.get("args")
        if (
            result.returncode
            and isinstance(argv, (list, tuple))
            and argv
            and isinstance(argv[0], str)
            and argv[0].replace("\\", "/").rsplit("/", 1)[-1].casefold() in {"git", "git.exe"}
        ):
            stderr = result.stderr or ""
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
            diagnostics.append(
                json.dumps(
                    {
                        "argv": [str(argument)[:256] for argument in argv[:32]],
                        "returncode": result.returncode,
                        "stderr": str(stderr)[:4096],
                    }
                )
            )
            del diagnostics[:-8]
        return result

    # Requesting the shared monkeypatch fixture here would initialize it before
    # tmp_path and leave test filesystem patches active during tmp_path cleanup.
    with pytest.MonkeyPatch.context() as diagnostic_patch:
        diagnostic_patch.setattr(subprocess, "run", execute)
        yield


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    del call
    report = yield
    if report.failed and (diagnostics := item.stash.get(_GIT_DIAGNOSTICS, [])):
        report.sections.append(("Captured stderr failed Git commands", "\n".join(diagnostics)))
    return report


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--relay-ci-report", help="Write the collected test inventory.")


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


_CHECKOUT_SHA = subprocess.check_output(
    ["git", "rev-parse", "HEAD"],  # noqa: S607 - fixed, read-only Git command
    cwd=Path(__file__).resolve().parents[1],
    text=True,
).strip()


def pytest_collection_finish(session: pytest.Session) -> None:
    if destination := session.config.getoption("--relay-ci-report"):
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "checkout_sha": _CHECKOUT_SHA,
                    "collected": [
                        {
                            "nodeid": item.nodeid,
                            "skip_reasons": _skip_reasons(item),
                            "serial_integration": bool(
                                item.get_closest_marker("serial_integration")
                            ),
                        }
                        for item in session.items
                    ],
                }
            ),
            encoding="utf-8",
        )


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    # JUnit remains the result format, including setup/teardown failures.
    for entry in (("relay_nodeid", report.nodeid), ("relay_checkout", _CHECKOUT_SHA)):
        if entry not in report.user_properties:
            report.user_properties.append(entry)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    # Focused tox runs can legitimately leave one lane empty. The separate
    # inventory validator rejects an empty overall suite or missing execution.
    if exitstatus == pytest.ExitCode.NO_TESTS_COLLECTED and session.config.option.markexpr in (
        "serial_integration",
        "not serial_integration",
    ):
        session.exitstatus = 0
