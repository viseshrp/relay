"""Run complete Python coverage with isolated serial and parallel integration lanes."""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Callable
import json
import math
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from types import TracebackType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
_OWNER_MARKER = ".relay-python-reports.json"
_SCRATCH_MARKER = ".relay-pytest-root.json"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return {
            "collection_errors": [f"Cannot read {path.name}: {error}"],
            "collected": [],
            "reports": [],
        }
    if not isinstance(value, dict):
        return {
            "collection_errors": [f"Invalid report {path.name}"],
            "collected": [],
            "reports": [],
        }
    return value


def _report_shape_error(report: dict[str, Any]) -> str | None:
    collected = report.get("collected")
    errors = report.get("collection_errors")
    phases = report.get("reports")
    if (
        not isinstance(collected, list)
        or not isinstance(errors, list)
        or not isinstance(phases, list)
    ):
        return "collected, collection_errors, and reports must be lists"
    if any(not isinstance(error, str) for error in errors):
        return "collection_errors must contain strings"
    for item in collected:
        if not isinstance(item, dict) or not isinstance(item.get("nodeid"), str):
            return "collected test identities must be strings"
        if not isinstance(item.get("skip_reasons", []), list) or any(
            not isinstance(reason, str) for reason in item.get("skip_reasons", [])
        ):
            return "declared skip reasons must be lists of strings"
    for phase in phases:
        if not isinstance(phase, dict) or not isinstance(phase.get("nodeid"), str):
            return "execution test identities must be strings"
        if phase.get("phase") not in ("setup", "call", "teardown"):
            return "execution reports must identify setup, call, or teardown"
        if phase.get("outcome") not in ("passed", "failed", "skipped"):
            return "execution reports contain an invalid outcome"
        duration = phase.get("seconds")
        if not isinstance(duration, (float, int)) or not math.isfinite(duration) or duration < 0:
            return "execution durations must be finite nonnegative numbers"
        if not isinstance(phase.get("skip_reason"), str):
            return "execution skip reasons must be strings"
    return None


def _read_report(path: Path) -> dict[str, Any]:
    report = _read_json(path)
    if error := _report_shape_error(report):
        return {
            "collection_errors": [f"Invalid report {path.name}: {error}"],
            "collected": [],
            "reports": [],
        }
    return report


def validate_reports(inventory: dict[str, Any], lanes: list[dict[str, Any]]) -> list[str]:
    """Fail closed for incomplete, duplicated, or silently skipped test execution."""
    errors = [str(error) for report in [inventory, *lanes] for error in report["collection_errors"]]
    expected = {item["nodeid"]: item for item in inventory["collected"]}
    if not expected:
        errors.append("The complete test inventory is empty")
    if len(expected) != len(inventory["collected"]):
        errors.append("The complete inventory contains duplicate test identities")
    selected = Counter(item["nodeid"] for lane in lanes for item in lane["collected"])
    completed = Counter(
        report["nodeid"]
        for lane in lanes
        for report in lane["reports"]
        if report["phase"] == "teardown"
    )
    for label, actual in (("selected", selected), ("completed", completed)):
        missing = sorted(expected.keys() - actual.keys())
        extra = sorted(actual.keys() - expected.keys())
        duplicates = sorted(nodeid for nodeid, count in actual.items() if count != 1)
        if missing:
            errors.append(f"Tests missing from {label}: {missing}")
        if extra:
            errors.append(f"Unexpected tests {label}: {extra}")
        if duplicates:
            errors.append(f"Duplicate tests {label}: {duplicates}")
    phases: dict[str, dict[str, str]] = {}
    for lane in lanes:
        for metadata in ("checkout_sha", "requested_paths"):
            if lane.get(metadata) != inventory.get(metadata):
                errors.append(f"Execution {metadata} differs from the complete inventory")
        for report in lane["reports"]:
            phases.setdefault(report["nodeid"], {})[report["phase"]] = report["outcome"]
    for nodeid, outcomes in phases.items():
        if "setup" not in outcomes or (
            outcomes.get("setup") == "passed" and "call" not in outcomes
        ):
            errors.append(f"Incomplete execution phases: {nodeid}")
    for lane in lanes:
        for report in lane["reports"]:
            if report["outcome"] == "failed":
                errors.append(f"Failed {report['phase']}: {report['nodeid']}")
            if report["outcome"] != "skipped":
                continue
            reason = report["skip_reason"]
            declared = expected.get(report["nodeid"], {}).get("skip_reasons", [])
            symlink_unavailable = reason.startswith("symlinks are unavailable here:") or reason == (
                "Directory symlinks are unavailable for this test account"
            )
            optional_local_node = (
                not os.environ.get("CI")
                and report["nodeid"].split("::")[0].endswith("test_actions_javascript.py")
                and reason
                in {
                    "Node.js 20 is not installed for this optional integration check.",
                    "Node.js 24 is not installed for this optional integration check.",
                }
            )
            if reason not in declared and not symlink_unavailable and not optional_local_node:
                errors.append(f"Unexplained skip: {report['nodeid']}: {reason}")
    return errors


def _execute(command: list[str], environment: dict[str, str]) -> tuple[int, float]:
    started = time.perf_counter()
    try:
        result = subprocess.run(command, cwd=ROOT, env=environment, check=False)  # noqa: S603
    except OSError as error:
        print(f"Cannot start command: {error}", file=sys.stderr)
        return 1, time.perf_counter() - started
    return result.returncode, time.perf_counter() - started


def _checkout_sha() -> str:
    if current := os.environ.get("GITHUB_SHA"):
        return current
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],  # noqa: S607 - fixed read-only Git invocation
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _summary(summary: dict[str, Any]) -> str:
    lines = [
        "## Python test results",
        "",
        f"{summary['test_count']} tests; workers={summary['workers']}; "
        f"elapsed={summary['elapsed_seconds']:.1f}s; exit={summary['exit_code']}.",
        f"Coverage: {'enabled' if summary['coverage_enabled'] else 'disabled'}.",
        "",
        "| Lane | Exit | Seconds |",
        "| --- | ---: | ---: |",
    ]
    for lane in summary["commands"]:
        lines.append(f"| {lane['name']} | {lane['exit_code']} | {lane['seconds']:.1f} |")
    lines.extend(["", "Slowest tests (setup + call + teardown):", ""])
    for nodeid, seconds in summary["slowest"]:
        lines.append(f"- `{nodeid}`: {seconds:.2f}s")
    if summary["errors"]:
        lines.extend(["", "Completeness errors:", ""])
        lines.extend(f"- {error}" for error in summary["errors"])
    return "\n".join(lines) + "\n"


def _prepare_report_dir(reports_dir: Path) -> bool:
    """Only replace generated files in a directory this checkout marked as owned."""
    expected_owner = {"schema_version": 1, "owner": "relay-python-ci", "checkout": str(ROOT)}
    reports_dir.mkdir(parents=True, exist_ok=True)
    marker = reports_dir / _OWNER_MARKER
    if marker.exists():
        if _read_json(marker) != expected_owner:
            print(f"Refusing an unverified report directory: {reports_dir}", file=sys.stderr)
            return False
    elif any(reports_dir.iterdir()):
        print(f"Choose an empty report directory: {reports_dir}", file=sys.stderr)
        return False
    else:
        marker.write_text(json.dumps(expected_owner) + "\n", encoding="utf-8")
    return True


def _publish_summary(
    summary: dict[str, Any], reports_dir: Path, environment: dict[str, str]
) -> None:
    (reports_dir / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    rendered = _summary(summary)
    (reports_dir / "summary.md").write_text(rendered, encoding="utf-8")
    if destination := environment.get("GITHUB_STEP_SUMMARY"):
        with Path(destination).open("a", encoding="utf-8") as stream:
            stream.write(rendered)
    print(rendered)


def _scratch_owner(root: Path) -> dict[str, str]:
    return {"owner": "relay-python-ci", "checkout": str(ROOT), "root": str(root)}


def _new_scratch_root(environment: dict[str, str]) -> Path:
    root = Path(
        tempfile.mkdtemp(prefix="rp-", dir=environment.get("RUNNER_TEMP") or None)
    ).resolve()
    (root / _SCRATCH_MARKER).write_text(json.dumps(_scratch_owner(root)), encoding="utf-8")
    return root


def _remove_scratch_root(root: Path) -> None:
    if _read_json(root / _SCRATCH_MARKER) != _scratch_owner(root):
        message = f"Refusing cleanup of an unverified pytest root: {root}"
        raise OSError(message)

    def remove_readonly(
        function: Callable[..., object],
        path: str,
        exc_info: tuple[type[BaseException], BaseException, TracebackType | None],
    ) -> None:
        error = exc_info[1]
        if function is not os.unlink or not isinstance(error, PermissionError):
            raise error
        mode = Path(path).lstat().st_mode
        if not stat.S_ISREG(mode) or mode & stat.S_IWUSR:
            raise error
        # Git loose objects are read-only on Windows. Only change regular
        # files within this verified allocation, never symlink targets.
        os.chmod(path, mode | stat.S_IWUSR)
        function(path)

    shutil.rmtree(root, onerror=remove_readonly)


def run(
    workers: int,
    reports_dir: Path,
    paths: list[str],
    *,
    legacy_coverage: bool = False,
    coverage_enabled: bool = True,
) -> int:
    reports_dir = reports_dir.resolve()
    if not _prepare_report_dir(reports_dir):
        return 1
    # Never let a previous invocation satisfy this run's completeness checks.
    for name in ("inventory", "serial", "parallel", "full"):
        (reports_dir / f"{name}.json").unlink(missing_ok=True)
        (reports_dir / f"junit-{name}.xml").unlink(missing_ok=True)
    for name in (".coverage", "coverage.xml", "coverage.json", "summary.json"):
        (reports_dir / name).unlink(missing_ok=True)
    for fragment in reports_dir.glob(".coverage.*"):
        if fragment.is_file():
            fragment.unlink()
    environment = dict(os.environ)
    if coverage_enabled:
        environment["COVERAGE_FILE"] = str(reports_dir / ".coverage")
    else:
        for name in (
            "COVERAGE_FILE",
            "COVERAGE_PROCESS_START",
            "COV_CORE_SOURCE",
            "COV_CORE_CONFIG",
            "COV_CORE_DATAFILE",
            "COV_CORE_BRANCH",
        ):
            environment.pop(name, None)
    environment["RELAY_TEST_CHECKOUT_SHA"] = _checkout_sha()
    environment["RELAY_TEST_REQUESTED_PATHS"] = json.dumps(paths)
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(None, [str(ROOT), environment.get("PYTHONPATH")])
    )
    # CI collection and execution cannot inherit a local -k/-m filter or fail-fast.
    environment.pop("PYTEST_ADDOPTS", None)
    base = [
        sys.executable,
        "-m",
        "pytest",
        "-c",
        str(ROOT / "pyproject.toml"),
        "-p",
        "tests.ci_reporting",
        *paths,
    ]
    if not coverage_enabled:
        base.extend(["-p", "no:pytest_cov"])
    commands: list[dict[str, Any]] = []
    started = time.perf_counter()
    try:
        scratch_root = _new_scratch_root(environment)
    except OSError as error:
        _publish_summary(
            {
                "schema_version": 1,
                "workers": workers,
                "paths": paths,
                "checkout_sha": environment["RELAY_TEST_CHECKOUT_SHA"],
                "test_count": 0,
                "commands": [],
                "slowest": [],
                "errors": [f"Cannot create isolated pytest storage: {error}"],
                "elapsed_seconds": time.perf_counter() - started,
                "exit_code": 1,
                "coverage_enabled": coverage_enabled,
                "coverage_reports": [],
            },
            reports_dir,
            environment,
        )
        return 1

    def execute(name: str, arguments: list[str]) -> int:
        code, seconds = _execute(arguments, environment)
        commands.append({"name": name, "exit_code": code, "seconds": seconds})
        return code

    execute(
        "inventory",
        [
            *base,
            "--basetemp",
            str(scratch_root / "i"),
            "--collect-only",
            "-q",
            "--relay-ci-report",
            str(reports_dir / "inventory.json"),
        ],
    )
    names = ["full"] if workers == 0 else ["serial", "parallel"]
    for index, name in enumerate(names):
        arguments = [
            *base,
            "--basetemp",
            str(scratch_root / name[0]),
            "-o",
            "junit_logging=all",
            "-o",
            "junit_log_passing_tests=false",
            "--relay-ci-report",
            str(reports_dir / f"{name}.json"),
            f"--junitxml={reports_dir / f'junit-{name}.xml'}",
        ]
        if coverage_enabled:
            arguments.extend(["--cov", f"--cov-config={ROOT / 'pyproject.toml'}", "--cov-report="])
            if index:
                arguments.append("--cov-append")
        if name == "serial":
            arguments.extend(["-m", "serial_integration"])
        elif name == "parallel":
            arguments.extend(
                [
                    "-m",
                    "not serial_integration",
                    "-n",
                    str(workers),
                    "--dist=worksteal",
                    "--max-worker-restart=0",
                ]
            )
        execute(name, arguments)

    inventory = _read_report(reports_dir / "inventory.json")
    lanes = [_read_report(reports_dir / f"{name}.json") for name in names]
    errors = validate_reports(inventory, lanes)
    for command, lane in zip(commands[1:], lanes, strict=True):
        if command["exit_code"] == 5 and not lane["collected"] and not lane["collection_errors"]:
            command["expected_empty_lane"] = True
    if coverage_enabled:
        for format_name in ("xml", "json"):
            execute(
                f"coverage-{format_name}",
                [
                    sys.executable,
                    "-m",
                    "coverage",
                    format_name,
                    "-o",
                    str(reports_dir / f"coverage.{format_name}"),
                ],
            )
        coverage_report = _read_json(reports_dir / "coverage.json")
        meta = coverage_report.get("meta")
        totals = coverage_report.get("totals")
        if not isinstance(meta, dict) or meta.get("branch_coverage") is not True:
            errors.append("Coverage report is missing branch instrumentation")
        if (
            not isinstance(totals, dict)
            or not isinstance(totals.get("covered_lines"), int)
            or totals["covered_lines"] <= 0
        ):
            errors.append("Coverage report contains no executed Relay source lines")
    durations: dict[str, float] = {}
    for lane in lanes:
        for report in lane["reports"]:
            durations[report["nodeid"]] = durations.get(report["nodeid"], 0.0) + report["seconds"]
    exit_code = next(
        (
            command["exit_code"]
            for command in commands
            if command["exit_code"] and not command.get("expected_empty_lane")
        ),
        0,
    )
    if errors and not exit_code:
        exit_code = 1
    if not exit_code:
        try:
            _remove_scratch_root(scratch_root)
        except OSError as error:
            errors.append(f"Cannot clean isolated pytest storage: {error}")
            exit_code = 1
    summary = {
        "schema_version": 1,
        "workers": workers,
        "paths": paths,
        "checkout_sha": environment["RELAY_TEST_CHECKOUT_SHA"],
        "test_count": len(inventory["collected"]),
        "commands": commands,
        "errors": errors,
        "slowest": sorted(durations.items(), key=lambda entry: entry[1], reverse=True)[:20],
        "elapsed_seconds": time.perf_counter() - started,
        "exit_code": exit_code,
        "temporary_root": str(scratch_root),
        "temporary_root_retained": scratch_root.exists(),
        "coverage_enabled": coverage_enabled,
        "coverage_reports": ["coverage.xml", "coverage.json"] if coverage_enabled else [],
    }
    _publish_summary(summary, reports_dir, environment)
    if (
        legacy_coverage
        and coverage_enabled
        and not os.environ.get("RELAY_TEST_REPORT_DIR")
        and (reports_dir / "coverage.xml").is_file()
    ):
        shutil.copyfile(reports_dir / "coverage.xml", ROOT / "coverage.xml")
    return exit_code if exit_code >= 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    coverage_default = os.environ.get("RELAY_TEST_COVERAGE", "true").strip().casefold()
    if coverage_default not in {"true", "false"}:
        parser.error("RELAY_TEST_COVERAGE must be true or false")
    parser.add_argument(
        "--coverage",
        action=argparse.BooleanOptionalAction,
        default=coverage_default == "true",
        help="Collect branch coverage (default: true, or RELAY_TEST_COVERAGE).",
    )
    parser.add_argument("--workers", type=int, default=os.environ.get("RELAY_TEST_WORKERS", "0"))
    parser.add_argument(
        "--reports-dir",
        type=Path,
        default=os.environ.get("RELAY_TEST_REPORT_DIR", str(ROOT / ".pytest_cache" / "ci-python")),
    )
    parser.add_argument(
        "--legacy-coverage",
        action="store_true",
        help="Also write the legacy root coverage.xml for local tox.",
    )
    parser.add_argument("paths", nargs="*", default=["tests"])
    arguments = parser.parse_args()
    if arguments.workers < 0:
        parser.error("--workers must be zero or positive")
    return run(
        arguments.workers,
        arguments.reports_dir,
        arguments.paths or ["tests"],
        legacy_coverage=arguments.legacy_coverage,
        coverage_enabled=arguments.coverage,
    )


if __name__ == "__main__":
    raise SystemExit(main())
