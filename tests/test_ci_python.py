"""Native tox/pytest execution must retain every test and every failure."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

from scripts.verify_python_tests import verify

ROOT = Path(__file__).resolve().parents[1]


def _reports(directory: Path, *, skipped: str = "") -> None:
    items = [
        {
            "nodeid": "test_a",
            "serial_integration": True,
            "skip_reasons": [skipped] if skipped else [],
        },
        {"nodeid": "test_b", "serial_integration": False, "skip_reasons": []},
    ]
    (directory / "inventory.json").write_text(
        json.dumps({"checkout_sha": "head", "collected": items}), encoding="utf-8"
    )
    for lane, item in zip(("serial", "parallel"), items, strict=True):
        tree = ET.Element("testsuites")
        suite = ET.SubElement(tree, "testsuite", tests="1")
        case = ET.SubElement(suite, "testcase", name=item["nodeid"])
        properties = ET.SubElement(case, "properties")
        for name, value in (("relay_nodeid", item["nodeid"]), ("relay_checkout", "head")):
            ET.SubElement(properties, "property", name=name, value=value)
        if skipped and lane == "serial":
            ET.SubElement(case, "skipped", message=skipped)
        ET.ElementTree(tree).write(directory / f"junit-{lane}.xml")


@pytest.mark.parametrize(
    "damage",
    ["missing", "duplicate", "collection", "skip", "failed", "sha", "wrong lane", "malformed"],
)
def test_native_junit_rejects_incomplete_or_unexplained_execution(
    tmp_path: Path, damage: str
) -> None:
    _reports(tmp_path)
    path = tmp_path / "junit-parallel.xml"
    tree = ET.parse(path)  # noqa: S314 - generated test report
    case = tree.find(".//testcase")
    assert case is not None
    if damage == "missing":
        path.unlink()
    elif damage == "malformed":
        path.write_text("<broken>", encoding="utf-8")
    else:
        if damage == "duplicate":
            tree.find("testsuite").append(case)
        elif damage in {"collection", "failed"}:
            ET.SubElement(case, "error" if damage == "collection" else "failure")
        elif damage == "skip":
            ET.SubElement(case, "skipped", message="temporarily disabled")
        elif damage == "sha":
            case.find("./properties/property[@name='relay_checkout']").set("value", "wrong")
        elif damage == "wrong lane":
            case.find("./properties/property[@name='relay_nodeid']").set("value", "test_a")
        tree.write(path)
    with pytest.raises((ValueError, OSError, ET.ParseError)):
        verify(tmp_path)


def test_native_junit_preserves_declared_platform_skips(tmp_path: Path) -> None:
    _reports(tmp_path, skipped="Windows-only behavior")
    verify(tmp_path)


@pytest.mark.parametrize("coverage", [False, True])
@pytest.mark.parametrize("failed_serial", [False, True])
def test_native_tox_runs_both_lanes_and_preserves_failure(
    tmp_path: Path, coverage: bool, failed_serial: bool
) -> None:
    # Exercise stock tox and the real locked runner using cached dependencies.
    configuration = (ROOT / "tox.toml").read_text(encoding="utf-8")
    configuration = configuration.replace(
        "[env_run_base]", "[env_run_base]\nbase_python = " + json.dumps([sys.executable])
    )
    config = tmp_path / "tox.toml"
    config.write_text(configuration, encoding="utf-8")
    (tmp_path / "conftest.py").write_text(
        "from pathlib import Path\nimport pytest\n"
        "ROOT = Path(__file__).resolve().parent\n"
        "class CollectionBoundary:\n"
        "    @pytest.hookimpl(tryfirst=True)\n"
        "    def pytest_collect_directory(self, path: Path, parent: pytest.Collector) -> None:\n"
        "        if not path.is_relative_to(ROOT):\n"
        "            raise AssertionError(\n"
        "                f'Probe collection escaped its owned directory: {path}'\n"
        "            )\n"
        "def pytest_configure(config: pytest.Config) -> None:\n"
        "    config.pluginmanager.register(CollectionBoundary(), 'owned-collection-boundary')\n",
        encoding="utf-8",
    )
    probe = tmp_path / "test_native_probe.py"
    finished = tmp_path / "parallel-ran"
    probe.write_text(
        "import pytest\nfrom pathlib import Path\nfrom relay.errors import RelayError\n"
        "@pytest.mark.serial_integration\ndef test_serial():\n"
        f"    assert {not failed_serial!r}\n"
        "def test_parallel():\n"
        f"    Path({str(finished)!r}).write_text('ran')\n"
        "    assert RelayError('probe').message == 'probe'\n",
        encoding="utf-8",
    )
    temporary = tmp_path / "tox owned with spaces"
    environment = {
        **os.environ,
        "RELAY_TEST_COVERAGE": str(coverage).lower(),
        "RELAY_TEST_WORKERS": "2",
        "RELAY_TEST_TEMP_DIR": str(temporary),
        "PYTEST_ADDOPTS": "-k never_select",
        "GITHUB_ACTIONS": "false",
        "UV_OFFLINE": "true",
    }
    result = subprocess.run(  # noqa: S603 - run stock tox against our disposable probe
        [
            sys.executable,
            "-m",
            "tox",
            "-c",
            str(config),
            "--root",
            str(ROOT),
            "--workdir",
            str(tmp_path / "tox"),
            "-e",
            "py",
            "--",
            str(probe),
            "-c",
            str(ROOT / "pyproject.toml"),
            "--rootdir",
            str(tmp_path),
            "--confcutdir",
            str(tmp_path),
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=90,
    )
    assert (result.returncode == 0) is not failed_serial, result.stdout + result.stderr
    assert finished.read_text() == "ran"
    reports = temporary / "reports"
    assert (reports / "junit-serial.xml").is_file()
    assert (reports / "junit-parallel.xml").is_file()
    assert (reports / "coverage.xml").is_file() is coverage
    if failed_serial:
        with pytest.raises(ValueError, match="Failed Python execution"):
            verify(reports)
    else:
        verify(reports)


def _run_probe(tmp_path: Path, probe: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - execute our isolated pytest probe
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "tests.ci_reporting",
            "-c",
            str(ROOT / "pyproject.toml"),
            "--rootdir",
            str(tmp_path),
            "--confcutdir",
            str(tmp_path),
            str(probe),
            "--basetemp",
            str(tmp_path / "scratch"),
            f"--junitxml={tmp_path / 'junit.xml'}",
            "-o",
            "junit_logging=all",
            "-o",
            "junit_log_passing_tests=false",
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT), "PYTEST_ADDOPTS": ""},
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


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
    result = _run_probe(tmp_path, probe)
    assert result.returncode == 1, result.stdout + result.stderr
    junit = ET.parse(tmp_path / "junit.xml")  # noqa: S314 - XML generated solely by this probe
    cases = {case.attrib["name"]: case for case in junit.findall(".//testcase")}
    assert "PASS_OUTPUT_UNCHANGED" not in ET.tostring(cases["test_passing"], encoding="unicode")
    assert "relay-invalid-probe-command" in ET.tostring(cases["test_failing"], encoding="unicode")


def test_diagnostic_fixture_preserves_shared_patch_and_temporary_cleanup_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    probe = tmp_path / "test_cleanup_probe.py"
    probe.write_text(
        "import os, pytest\n"
        "original_scandir = os.scandir\n"
        "@pytest.fixture\n"
        "def tmp_path(tmp_path_factory):\n"
        "    path = tmp_path_factory.mktemp('cleanup-probe')\n"
        "    yield path\n"
        "    assert os.scandir is original_scandir, 'filesystem patch outlived test cleanup'\n"
        "def test_cleanup(tmp_path, monkeypatch):\n"
        "    def entries(path):\n"
        "        return original_scandir(path)\n"
        "    monkeypatch.setattr(os, 'scandir', entries)\n"
        "    assert os.scandir is entries\n",
        encoding="utf-8",
    )
    result = _run_probe(tmp_path, probe)
    assert result.returncode == 0, result.stdout + result.stderr
