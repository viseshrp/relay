"""CI rejects dropped execution and still runs the other lane after a failure."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

import pytest

from scripts import run_python_tests as runner


@pytest.fixture(autouse=True)
def isolated_ci_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    """Negative controls must not publish synthetic failures into the real CI summary."""
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)


def _report(nodeids: list[str], *, skip_reason: str = "") -> dict[str, Any]:
    return {
        "collection_errors": [],
        "collected": [{"nodeid": nodeid, "skip_reasons": []} for nodeid in nodeids],
        "reports": [
            {
                "nodeid": nodeid,
                "phase": phase,
                "outcome": "skipped" if skip_reason and phase == "call" else "passed",
                "skip_reason": skip_reason if phase == "call" else "",
                "seconds": 0.1,
            }
            for nodeid in nodeids
            for phase in ("setup", "call", "teardown")
        ],
    }


@pytest.mark.parametrize("damage", ["missing", "duplicate", "collection", "skip", "failed", "sha"])
def test_completeness_rejects_incomplete_or_unexplained_execution(damage: str) -> None:
    inventory = _report(["test_a", "test_b"])
    lane = deepcopy(inventory)
    if damage == "missing":
        lane = _report(["test_a"])
    elif damage == "duplicate":
        lane["reports"].extend(deepcopy(lane["reports"]))
    elif damage == "collection":
        lane["collection_errors"].append("cannot collect test_c")
    elif damage == "skip":
        lane = _report(["test_a", "test_b"], skip_reason="temporarily disabled")
    elif damage == "failed":
        lane["reports"][0]["outcome"] = "failed"
    else:
        lane["checkout_sha"] = "another-checkout"
    assert runner.validate_reports(inventory, [lane])


def test_declared_platform_skip_remains_visible_and_allowed() -> None:
    inventory = _report(["platform_test"])
    inventory["collected"][0]["skip_reasons"] = ["Windows directory junction"]
    lane = _report(["platform_test"], skip_reason="Windows directory junction")
    assert runner.validate_reports(inventory, [lane]) == []


@pytest.mark.parametrize("contents", ["{}", '{"collected": null}', '{"collected": []', "[]"])
def test_malformed_reports_preserve_summary_diagnostics(tmp_path: Path, contents: str) -> None:
    report = tmp_path / "parallel.json"
    report.write_text(contents, encoding="utf-8")
    loaded = runner._read_report(report)
    assert loaded["collection_errors"]
    assert runner.validate_reports(_report(["expected_test"]), [loaded])


def test_teardown_alone_cannot_prove_execution() -> None:
    inventory = _report(["expected_test"])
    lane = deepcopy(inventory)
    lane["reports"] = [phase for phase in lane["reports"] if phase["phase"] == "teardown"]
    assert runner.validate_reports(inventory, [lane]) == [
        "Incomplete execution phases: expected_test"
    ]


@pytest.mark.parametrize("foreign_marker", [False, True])
def test_unverified_report_directory_preserves_existing_bytes(
    tmp_path: Path, foreign_marker: bool
) -> None:
    owner_file = tmp_path / "full.json"
    owner_file.write_bytes(b"owner report bytes\n")
    if foreign_marker:
        (tmp_path / ".relay-python-reports.json").write_text(
            '{"owner": "another tool"}', encoding="utf-8"
        )
    assert runner.run(0, tmp_path, ["tests"]) == 1
    assert owner_file.read_bytes() == b"owner report bytes\n"
    assert not (tmp_path / "summary.json").exists()


def test_owned_reuse_removes_stale_worker_coverage_without_deleting_unrelated_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reports_dir = tmp_path / "reports"
    assert runner._prepare_report_dir(reports_dir)
    fragment = reports_dir / ".coverage.old-worker.1234"
    fragment.write_bytes(b"stale coverage bytes")
    unrelated = reports_dir / "owner-notes.txt"
    unrelated.write_text("retain these bytes", encoding="utf-8")

    def execute(command: list[str], environment: dict[str, str]) -> tuple[int, float]:
        del command, environment
        assert not fragment.exists()
        return 1, 0.1

    monkeypatch.setattr(runner, "_execute", execute)
    assert runner.run(0, reports_dir, ["tests"]) == 1
    assert unrelated.read_text(encoding="utf-8") == "retain these bytes"
    assert (reports_dir / "summary.json").is_file()


@pytest.mark.parametrize("coverage_valid", [False, True])
def test_failed_serial_lane_does_not_prevent_parallel_or_coverage_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, coverage_valid: bool
) -> None:
    reports_dir = tmp_path / "reports"
    names: list[str] = []
    temporary = tmp_path / "short"
    temporary.mkdir()
    owner_file = temporary / "owner.txt"
    owner_file.write_text("retain", encoding="utf-8")
    monkeypatch.setenv("RUNNER_TEMP", str(temporary))
    base_paths: list[Path] = []

    def execute(command: list[str], environment: dict[str, str]) -> tuple[int, float]:
        del environment
        if "--relay-ci-report" in command:
            base_paths.append(Path(command[command.index("--basetemp") + 1]))
            report_path = Path(command[command.index("--relay-ci-report") + 1])
            name = report_path.stem
            names.append(name)
            nodeids = (
                ["timed_test", "parallel_test"]
                if name == "inventory"
                else ["timed_test" if name == "serial" else "parallel_test"]
            )
            report_path.write_text(json.dumps(_report(nodeids)), encoding="utf-8")
            return (1 if name == "serial" else 0), 1.0
        output = Path(command[-1])
        if output.suffix == ".json":
            output.write_text(
                json.dumps(
                    {"meta": {"branch_coverage": coverage_valid}, "totals": {"covered_lines": 3}}
                ),
                encoding="utf-8",
            )
        else:
            output.write_text("<coverage/>", encoding="utf-8")
        return 0, 0.1

    monkeypatch.setattr(runner, "_execute", execute)
    assert runner.run(2, reports_dir, ["tests"]) == 1
    assert names == ["inventory", "serial", "parallel"]
    summary = json.loads((reports_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["commands"][1]["exit_code"] == 1
    assert {path.name for path in base_paths} == {"i", "s", "p"}
    assert len({path.parent for path in base_paths}) == 1
    assert base_paths[0].parent.parent == temporary
    assert summary["temporary_root_retained"] is True
    assert owner_file.read_text(encoding="utf-8") == "retain"
    assert bool(summary["errors"]) is not coverage_valid
    assert (reports_dir / "coverage.json").is_file()
    assert (reports_dir / "summary.md").is_file()


def test_scratch_creation_failure_still_publishes_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: Any, **kwargs: Any) -> str:
        del args, kwargs
        message = "scratch filesystem unavailable"
        raise OSError(message)

    monkeypatch.setattr(runner.tempfile, "mkdtemp", fail)
    reports = tmp_path / "reports"
    assert runner.run(2, reports, ["tests"]) == 1
    summary = json.loads((reports / "summary.json").read_text(encoding="utf-8"))
    assert summary["commands"] == []
    assert "scratch filesystem unavailable" in summary["errors"][0]


@pytest.mark.parametrize("workers", [0, 2])
def test_real_runner_collects_exact_identities_and_combines_branch_coverage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, workers: int
) -> None:
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.setenv("RELAY_TEST_COVERAGE", "false")
    tests = tmp_path / "test_probe.py"
    tests.write_text(
        "import pytest\n"
        "from relay.errors import RelayError\n"
        "@pytest.mark.serial_integration\n"
        "def test_serial():\n"
        "    assert RelayError('serial').message == 'serial'\n"
        "def test_parallel():\n"
        "    assert RelayError('parallel').message == 'parallel'\n",
        encoding="utf-8",
    )
    reports = tmp_path / "reports"
    assert runner.run(workers, reports, [str(tests)], coverage_enabled=True) == 0
    summary = json.loads((reports / "summary.json").read_text(encoding="utf-8"))
    coverage = json.loads((reports / "coverage.json").read_text(encoding="utf-8"))
    assert summary["test_count"] == 2
    assert summary["errors"] == []
    assert summary["coverage_enabled"] is True
    assert summary["temporary_root_retained"] is False
    assert not Path(summary["temporary_root"]).exists()
    assert coverage["meta"]["branch_coverage"] is True
    assert coverage["totals"]["covered_lines"] > 0
    assert len(list(reports.glob("junit-*.xml"))) == (1 if workers == 0 else 2)


@pytest.mark.parametrize("serial_failure", [False, True])
def test_real_no_coverage_cli_runs_every_lane_and_preserves_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, serial_failure: bool
) -> None:
    probe = tmp_path / "test_probe.py"
    probe.write_text(
        "import pytest\n"
        "@pytest.mark.serial_integration\n"
        "def test_serial():\n"
        f"    assert {not serial_failure!r}\n"
        "def test_parallel():\n"
        "    assert True\n",
        encoding="utf-8",
    )
    reports = tmp_path / "reports"
    monkeypatch.setenv("RELAY_TEST_COVERAGE", "false")
    monkeypatch.setattr(
        runner.sys,
        "argv",
        ["run_python_tests.py", "--workers", "2", "--reports-dir", str(reports), str(probe)],
    )
    assert runner.main() == int(serial_failure)
    summary = json.loads((reports / "summary.json").read_text(encoding="utf-8"))
    assert summary["coverage_enabled"] is False
    assert summary["coverage_reports"] == []
    assert summary["test_count"] == 2
    assert [command["name"] for command in summary["commands"]] == [
        "inventory",
        "serial",
        "parallel",
    ]
    assert summary["commands"][-1]["exit_code"] == 0
    assert bool(summary["errors"]) is serial_failure
    assert not list(reports.glob("*coverage*"))
    assert not list(reports.glob(".coverage*"))
    for name in ("serial", "parallel"):
        lane = json.loads((reports / f"{name}.json").read_text(encoding="utf-8"))
        assert len(lane["completed"]) == 1


def test_real_failed_git_diagnostics_retain_stderr_without_publishing_passing_output(
    tmp_path: Path,
) -> None:
    probe = tmp_path / "test_git_probe.py"
    probe.write_text(
        "import shutil, subprocess\n"
        "from relay.errors import RelayError\n"
        "def run_git():\n"
        "    result = subprocess.run([shutil.which('git'), 'relay-invalid-probe-command'], "
        "capture_output=True, text=True, check=False)\n"
        "    assert result.returncode != 0\n"
        "    assert 'relay-invalid-probe-command' in result.stderr\n"
        "    return result\n"
        "def test_passing():\n"
        "    assert run_git().stdout == ''\n"
        "    print('PASS_OUTPUT_UNCHANGED')\n"
        "def test_failing():\n"
        "    run_git()\n"
        "    assert RelayError('probe').message == 'force failure'\n",
        encoding="utf-8",
    )
    reports = tmp_path / "reports"
    assert runner.run(0, reports, [str(probe)]) == 1
    full = json.loads((reports / "full.json").read_text(encoding="utf-8"))
    passing = [row for row in full["reports"] if row["nodeid"].endswith("test_passing")]
    assert passing and all(not row["diagnostics"] for row in passing)
    failed = [row for row in full["reports"] if row["outcome"] == "failed"]
    assert len(failed) == 1
    assert "relay-invalid-probe-command" in failed[0]["diagnostics"][0]
    junit = ET.parse(reports / "junit-full.xml")  # noqa: S314 - XML generated solely by this probe
    cases = {case.attrib["name"]: case for case in junit.findall(".//testcase")}
    assert "PASS_OUTPUT_UNCHANGED" not in ET.tostring(cases["test_passing"], encoding="unicode")
    assert "relay-invalid-probe-command" in ET.tostring(cases["test_failing"], encoding="unicode")
