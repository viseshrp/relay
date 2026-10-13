"""CI scheduling changes must retain complete execution and publication gates."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any

import pytest
from tox.config.loader.str_convert import StrConvert
import yaml

ROOT = Path(__file__).resolve().parents[1]
_PYTHONS = {"3.10", "3.11", "3.12", "3.13", "3.14"}
_OPERATING_SYSTEMS = {"ubuntu-latest", "macos-latest", "windows-latest"}


@pytest.mark.parametrize("coverage", [False, True])
def test_native_tox_keeps_paths_and_complete_lanes(tmp_path: Path, coverage: bool) -> None:
    temporary = tmp_path / "tox reports with spaces"
    target = tmp_path / "config.json"
    environment = {
        **os.environ,
        "RELAY_TEST_TEMP_DIR": str(temporary),
        "RELAY_TEST_COVERAGE": str(coverage).lower(),
        "RELAY_TEST_WORKERS": "3",
    }
    name = f"py{sys.version_info.major}{sys.version_info.minor}"
    result = subprocess.run(  # noqa: S603 - inspect stock tox's resolved arguments
        [
            sys.executable,
            "-m",
            "tox",
            "config",
            "-c",
            str(ROOT / "tox.toml"),
            "-e",
            name,
            "--format",
            "json",
            "-k",
            "commands",
            "ignore_errors",
            "pass_env",
            "-o",
            str(target),
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    configuration = json.loads(target.read_text(encoding="utf-8"))["env"][name]
    commands = [StrConvert.to_command(command).args for command in configuration["commands"]]
    serial, parallel = commands[1:3]
    assert serial[serial.index("-m", 3) + 1] == "serial_integration"
    assert parallel[parallel.index("-m", 3) + 1] == "not serial_integration"
    assert parallel[parallel.index("-n") + 1] == "3"
    assert "--dist=worksteal" in parallel and "--max-worker-restart=0" in parallel
    for lane, command in (("serial", serial), ("parallel", parallel)):
        assert f"--junitxml={temporary / 'reports' / f'junit-{lane}.xml'}" in command
        assert ("--cov" in command) is coverage
        assert command[-1] == "tests"
    assert configuration["ignore_errors"] is True
    assert "PYTEST_ADDOPTS" not in configuration["pass_env"]
    assert len(commands) == (6 if coverage else 4)


def _load(relative: str) -> dict[str, Any]:
    # BaseLoader preserves GitHub's `on` key and makes scalar handling explicit.
    loader = yaml.BaseLoader((ROOT / relative).read_text(encoding="utf-8"))
    try:
        return loader.get_single_data()
    finally:
        loader.dispose()


def _commands(job: dict[str, Any]) -> list[str]:
    return [step["run"] for step in job["steps"] if "run" in step]


def _assert_complete_python_workflow(workflow: dict[str, Any]) -> None:
    job = workflow["jobs"]["tests"]
    strategy = job["strategy"]
    matrix = strategy["matrix"]
    assert set(matrix["python-version"]) == _PYTHONS
    assert set(matrix["os"]) == _OPERATING_SYSTEMS
    assert len(matrix["python-version"]) * len(matrix["os"]) == 15
    assert not matrix.get("exclude") and not matrix.get("include")
    assert strategy["max-parallel"] == "15"
    assert strategy["fail-fast"] == "false"
    assert job.get("continue-on-error", "false") == "false"
    assert job["runs-on"] == "${{ matrix.os }}"
    assert _commands(job).count("make test") == 1
    for candidate in workflow["jobs"].values():
        for command in _commands(candidate):
            for line in command.splitlines():
                # `python -m pytest` selects a module, rather than a test marker.
                invocation = re.search(r"\b(?:pytest|make\s+test)\b(.*)", line)
                if invocation:
                    assert not re.search(r"(?:^|\s)-(?:k|m)(?:\s|=|$)", invocation[1])


@pytest.mark.parametrize("name", ["main", "release"])
def test_python_workflows_preserve_every_environment_and_reject_test_filters(name: str) -> None:
    workflow = _load(f".github/workflows/{name}.yml")
    _assert_complete_python_workflow(workflow)
    for damage in ("missing-python", "excluded-environment", "test-filter"):
        changed = deepcopy(workflow)
        job = changed["jobs"]["tests"]
        if damage == "missing-python":
            job["strategy"]["matrix"]["python-version"].pop()
        elif damage == "excluded-environment":
            job["strategy"]["matrix"]["exclude"] = [{"os": "windows-latest"}]
        else:
            job["steps"].append({"run": "python -m pytest tests -m unit"})
        with pytest.raises(AssertionError):
            _assert_complete_python_workflow(changed)


@pytest.mark.parametrize("name", ["main", "release"])
def test_only_the_canonical_environment_collects_suite_coverage(name: str) -> None:
    workflow = _load(f".github/workflows/{name}.yml")
    assert workflow["jobs"]["tests"]["env"]["RELAY_TEST_COVERAGE"] == (
        "${{ matrix.python-version == '3.14' && matrix.os == 'ubuntu-latest' "
        "&& 'true' || 'false' }}"
    )
    if name == "main":
        assert workflow["env"]["MAIN_PYTHON_VERSION"] == "3.14"
        upload = next(
            step
            for step in workflow["jobs"]["tests"]["steps"]
            if step.get("uses", "").startswith("codecov/codecov-action@")
        )
        assert upload["if"] == (
            "${{ matrix.python-version == env.MAIN_PYTHON_VERSION "
            "&& matrix.os == 'ubuntu-latest' }}"
        )
        assert upload["with"]["files"] == "${{ runner.temp }}/rp/reports/coverage.xml"


def _assert_shared_test_setup(workflow: dict[str, Any]) -> None:
    steps = workflow["jobs"]["tests"]["steps"]
    setup = [step for step in steps if step.get("uses") == "./.github/actions/setup-test-env"]
    assert len(setup) == 1
    assert setup[0]["with"]["python-version"] == "${{ matrix.python-version }}"


def test_main_and_release_share_both_javascript_action_runtimes() -> None:
    main = _load(".github/workflows/main.yml")
    release = _load(".github/workflows/release.yml")
    for workflow in (main, release):
        _assert_shared_test_setup(workflow)
    action = _load(".github/actions/setup-test-env/action.yml")
    steps = action["runs"]["steps"]
    versions = {
        step["with"]["node-version"].split(".")[0]
        for step in steps
        if step.get("uses", "").startswith("actions/setup-node@")
    }
    assert versions == {"20", "24"}
    commands = "\n".join(_commands(action["runs"]))
    assert "RELAY_TEST_NODE_20=" in commands and "RELAY_TEST_NODE_24=" in commands
    assert "RELAY_TEST_REPORT_DIR=" in commands
    changed = deepcopy(release)
    changed["jobs"]["tests"]["steps"] = [
        step
        for step in changed["jobs"]["tests"]["steps"]
        if step.get("uses") != "./.github/actions/setup-test-env"
    ]
    with pytest.raises(AssertionError):
        _assert_shared_test_setup(changed)


def test_shared_setup_preserves_the_managed_windows_310_runtime() -> None:
    action = _load(".github/actions/setup-test-env/action.yml")
    steps = action["runs"]["steps"]
    selection = steps[0]
    assert selection["env"]["RELAY_REQUESTED_PYTHON"] == "${{ inputs.python-version }}"
    assert '"$RUNNER_OS" == "Windows"' in selection["run"]
    assert '"$RELAY_REQUESTED_PYTHON" == "3.10"' in selection["run"]
    assert "UV_PYTHON_PREFERENCE=only-managed" in selection["run"]
    assert "UV_PYTHON_PREFERENCE=system" in selection["run"]
    setup = steps[1]
    assert setup["uses"] == "./.github/actions/setup-python-env"
    assert setup["with"]["python-version"] == (
        "${{ runner.os == 'Windows' && inputs.python-version == '3.10' "
        "&& '3.10.19' || inputs.python-version }}"
    )
    assert setup["with"]["managed-python"] == (
        "${{ runner.os == 'Windows' && inputs.python-version == '3.10' }}"
    )
    assert "sqlite3.sqlite_version" in steps[2]["run"]


def _assert_main_gates(workflow: dict[str, Any]) -> dict[str, Any]:
    jobs = workflow["jobs"]
    for name in ("publish-to-testpypi", "create-draft-release"):
        assert {"quality", "tests", "browser-tests"} <= set(jobs[name]["needs"])
        assert "always()" not in jobs[name].get("if", "")
    preparation_steps = jobs["frontend-prepare"]["steps"]
    chromium = next(
        index
        for index, step in enumerate(preparation_steps)
        if "playwright install --with-deps chromium" in step.get("run", "")
    )
    build_tests = next(
        index
        for index, step in enumerate(preparation_steps)
        if step.get("run") == "npm --prefix frontend run test:build"
    )
    assert chromium < build_tests, "Real publication tests require Chromium."
    shards = jobs["browser-shards"]
    assert shards["needs"] == "frontend-prepare"
    assert shards["strategy"]["matrix"]["shard"] == ["1", "2", "3", "4"]
    assert shards["strategy"]["fail-fast"] == "false"
    executions = [step for step in shards["steps"] if "npx playwright test" in step.get("run", "")]
    assert len(executions) == 3
    assert "--shard=${{ matrix.shard }}/4" in executions[0]["run"]
    for step in executions:
        assert "--workers=1" in step["run"] and "--retries=0" in step["run"]
        assert "--forbid-only" in step["run"] and "--update-snapshots=none" in step["run"]
        assert step.get("continue-on-error", "false") == "false"
    for step in executions[1:]:
        assert "always()" in step["if"] and "matrix.shard == 4" in step["if"]
        assert "steps.assets.outcome == 'success'" in step["if"]
    aggregate = jobs["browser-tests"]
    assert set(aggregate["needs"]) == {"frontend-prepare", "browser-shards"}
    assert "always()" in aggregate["if"]
    gates = [
        step
        for step in aggregate["steps"]
        if set(step.get("env", {}).values())
        == {"${{ needs.frontend-prepare.result }}", "${{ needs.browser-shards.result }}"}
    ]
    assert len(gates) == 1
    gate = gates[0]
    assert gate["if"] == "always()"
    assert gate.get("continue-on-error", "false") == "false"
    return gate


def test_browser_and_publication_gates_reject_missing_shards_and_upstream_failures(
    tmp_path: Path,
) -> None:
    workflow = _load(".github/workflows/main.yml")
    gate = _assert_main_gates(workflow)
    for damage in ("missing-shard", "missing-publish-gate", "conditional-aggregate"):
        changed = deepcopy(workflow)
        if damage == "missing-shard":
            changed["jobs"]["browser-shards"]["strategy"]["matrix"]["shard"].pop()
        elif damage == "missing-publish-gate":
            changed["jobs"]["create-draft-release"]["needs"].remove("browser-tests")
        else:
            changed["jobs"]["browser-tests"]["if"] = "success()"
        with pytest.raises(AssertionError):
            _assert_main_gates(changed)
    executable = shutil.which("bash")
    assert executable is not None, "CI workflow gate verification requires Bash."
    for preparation, shards in (
        ("success", "success"),
        ("failure", "success"),
        ("success", "failure"),
        ("success", "cancelled"),
        ("skipped", "success"),
    ):
        environment = {**os.environ, "PREPARATION_RESULT": preparation, "SHARD_RESULT": shards}
        result = subprocess.run(  # noqa: S603 - exercise the actual CI gate in scratch storage
            [executable, "-e", "-c", gate["run"]],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            check=False,
            timeout=10,
        )
        assert (result.returncode == 0) == (preparation == shards == "success")


def _assert_visual_refresh(workflow: dict[str, Any]) -> None:
    job = workflow["jobs"]["visual-baselines"]
    assert job["if"] == "inputs.refresh_visual_baselines == true"
    assert "matrix" not in job.get("strategy", {})
    commands = _commands(job)
    assert any("--update-snapshots" in command for command in commands)
    assert "make test-frontend" in commands


def test_visual_refresh_preserves_complete_browser_verification() -> None:
    workflow = _load(".github/workflows/main.yml")
    _assert_visual_refresh(workflow)
    changed = deepcopy(workflow)
    changed["jobs"]["visual-baselines"]["steps"] = [
        step
        for step in changed["jobs"]["visual-baselines"]["steps"]
        if step.get("run") != "make test-frontend"
    ]
    with pytest.raises(AssertionError):
        _assert_visual_refresh(changed)


def _assert_environment_contexts(workflow: dict[str, Any]) -> None:
    for environment in [
        workflow.get("env", {}),
        *(job.get("env", {}) for job in workflow["jobs"].values()),
    ]:
        assert not any(
            re.search(r"\$\{\{[^}]*\brunner(?:\.|\[)", str(value)) for value in environment.values()
        )


@pytest.mark.parametrize("name", ["main", "release"])
def test_runner_context_is_used_only_after_a_job_reaches_its_runner(name: str) -> None:
    workflow = _load(f".github/workflows/{name}.yml")
    _assert_environment_contexts(workflow)
    for location in (workflow, workflow["jobs"]["tests"]):
        changed = deepcopy(workflow)
        target = changed if location is workflow else changed["jobs"]["tests"]
        target.setdefault("env", {})["REPORT_DIR"] = "${{ runner.temp }}/reports"
        with pytest.raises(AssertionError):
            _assert_environment_contexts(changed)


@pytest.mark.skipif(sys.platform != "linux", reason="Browser artifact commands run on Linux CI")
@pytest.mark.parametrize("damage", ["none", "archive", "checkout", "symlink"])
def test_native_browser_artifacts_preserve_bytes_and_reject_damage(
    tmp_path: Path, damage: str
) -> None:
    workflow = _load(".github/workflows/main.yml")
    prepare = next(
        step["run"]
        for step in workflow["jobs"]["frontend-prepare"]["steps"]
        if step["name"] == "Archive and identify the exact browser build"
    )
    check = next(
        step["run"]
        for step in workflow["jobs"]["browser-shards"]["steps"]
        if step.get("id") == "assets"
    )
    root = tmp_path / "repo"
    assets = root / "relay" / "static"
    assets.mkdir(parents=True)
    for name in ("index.html", ".build.json", "app.js.gz"):
        (assets / name).write_bytes(name.encode())
    retained = tmp_path / "owner.txt"
    retained.write_text("retain these bytes", encoding="utf-8")
    if damage == "symlink":
        (assets / "outside").symlink_to(retained)
    temporary = tmp_path / "runner"
    preparation = temporary / "frontend-preparation"
    preparation.mkdir(parents=True)
    environment = {
        **os.environ,
        "RUNNER_TEMP": str(temporary),
        "GITHUB_ENV": str(tmp_path / "github-env"),
        "RELAY_TEST_ASSETS_ROOT": str(tmp_path / "extracted"),
    }
    git = shutil.which("git")
    bash = shutil.which("bash")
    assert git and bash
    subprocess.run([git, "init", str(root)], check=True, capture_output=True)  # noqa: S603
    subprocess.run(  # noqa: S603 - disposable Git fixture
        [
            git,
            "-C",
            str(root),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "--allow-empty",
            "-m",
            "fixture",
        ],
        check=True,
        capture_output=True,
    )
    result = subprocess.run(  # noqa: S603 - actual CI command in disposable storage
        [bash, "-e", "-c", prepare], cwd=root, env=environment, capture_output=True, check=False
    )
    if damage == "symlink":
        assert result.returncode != 0
    else:
        assert result.returncode == 0, result.stderr
        if damage == "archive":
            with (preparation / "assets.tgz").open("ab") as stream:
                stream.write(b"corruption")
        if damage == "checkout":
            (preparation / "assets.commit").write_text("wrong", encoding="utf-8")
        result = subprocess.run(  # noqa: S603 - actual CI command in disposable storage
            [bash, "-e", "-c", check], cwd=root, env=environment, capture_output=True, check=False
        )
        assert (result.returncode == 0) is (damage == "none"), result.stderr
        if damage == "none":
            for name in ("index.html", ".build.json", "app.js.gz"):
                assert (Path(environment["RELAY_TEST_ASSETS_ROOT"]) / name).read_bytes() == (
                    assets / name
                ).read_bytes()
    assert retained.read_text(encoding="utf-8") == "retain these bytes"
