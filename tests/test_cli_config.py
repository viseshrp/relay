"""Administration exit codes and owner configuration through public entrypoints."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import json
from pathlib import Path

from click.testing import CliRunner, Result
import pytest

from relay import cli, paths
from relay.config import RelayConfig, load_config
from relay.constants import (
    APPLICATION_LOG_OWNERSHIP_LINE,
    EXIT_ALREADY_INITIALIZED,
    EXIT_DOCTOR_FAILED,
    EXIT_NOT_A_REPOSITORY,
    EXIT_NOTHING_TO_CLEAN,
    EXIT_PROJECT_NOT_FOUND,
    EXIT_SUPERVISOR,
    EXIT_UP_CONFIG,
)
from relay.errors import ConfigError, PermissionFlowError, WorktreeError
from relay.web import static_view, supervisor
from tests.support import FakeAgents, InlineEngine, RelayProject, init_repository


def invoke(*arguments: str, input_text: str | None = None) -> Result:
    return CliRunner().invoke(cli.main, list(arguments), input=input_text)


def report(result: Result) -> dict[str, object]:
    """Parse the final JSON line after Click's optional confirmation prompt."""
    return json.loads(result.output.strip().splitlines()[-1])


def test_init_rejects_a_non_git_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = invoke("init")
    assert (result.exit_code, report(result)["code"]) == (
        EXIT_NOT_A_REPOSITORY,
        "project_discovery_error",
    )


def test_init_creates_the_blank_authoring_surface(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = init_repository(tmp_path / "repo")
    monkeypatch.chdir(repository)
    result = invoke("init")
    assert result.exit_code == 0
    assert (repository / ".relay/workflows/workflow.yaml").is_file()
    assert (repository / ".relay/prompts/prompt.md").is_file()


def test_repeated_init_has_the_already_initialized_exit_code(
    project: RelayProject, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(project.repository)
    assert invoke("init").exit_code == EXIT_ALREADY_INITIALIZED


@dataclass
class SupervisorBoundary:
    """Record the CLI's startup request without launching a long-lived runtime."""

    failure: Exception | None = None
    configurations: list[RelayConfig] = field(default_factory=list)
    browser_requests: list[bool] = field(default_factory=list)

    def run(
        self, config: RelayConfig, *, open_browser: bool, on_ready: Callable[[str], None]
    ) -> None:
        self.configurations.append(config)
        self.browser_requests.append(open_browser)
        if self.failure is not None:
            raise self.failure
        on_ready(f"http://{config.host}:{config.port}/")


@pytest.fixture
def supervisor_boundary(monkeypatch: pytest.MonkeyPatch) -> SupervisorBoundary:
    boundary = SupervisorBoundary()
    monkeypatch.setattr(supervisor, "run_supervisor", boundary.run)
    return boundary


@pytest.mark.parametrize("explicit", ["workers", "host", "port"])
def test_up_overrides_only_explicit_command_options(
    supervisor_boundary: SupervisorBoundary, explicit: str
) -> None:
    saved = {"host": "localhost", "port": 9001, "workers": 3}
    settings = paths.settings_path()
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps(saved), encoding="utf-8")
    overrides = {"workers": "2", "host": "127.0.0.1", "port": "9002"}

    result = invoke("up", "--no-browser", f"--{explicit}", overrides[explicit])

    expected = {
        **saved,
        explicit: int(overrides[explicit]) if explicit != "host" else overrides[explicit],
    }
    assert result.exit_code == 0
    effective = supervisor_boundary.configurations[0]
    assert (effective.host, effective.port, effective.workers) == (
        expected["host"],
        expected["port"],
        expected["workers"],
    )
    assert supervisor_boundary.browser_requests == [False]


@pytest.mark.parametrize(
    ("failure", "exit_code", "code"),
    [
        (ConfigError("bad"), EXIT_UP_CONFIG, "config_error"),
        (WorktreeError("bad"), EXIT_SUPERVISOR, "worktree_error"),
        (RuntimeError("bad"), EXIT_SUPERVISOR, "persistence_error"),
    ],
)
def test_up_maps_runtime_failures_to_administration_exit_codes(
    supervisor_boundary: SupervisorBoundary, failure: Exception, exit_code: int, code: str
) -> None:
    supervisor_boundary.failure = failure
    result = invoke("up", "--no-browser")
    assert (result.exit_code, report(result)["code"]) == (exit_code, code)


def test_project_list_reports_registered_identity(project: RelayProject) -> None:
    result = invoke("project", "list")
    assert result.exit_code == 0
    assert [row["id"] for row in report(result)["projects"]] == [project.project_id]


def test_project_relink_reports_the_preserved_identity(
    project: RelayProject, tmp_path: Path
) -> None:
    moved = tmp_path / "moved"
    project.repository.rename(moved)
    result = invoke("project", "relink", str(project.repository), str(moved))
    assert result.exit_code == 0
    assert report(result)["project"]["id"] == project.project_id


def test_an_unknown_project_relink_has_the_project_not_found_exit_code(
    project: RelayProject, tmp_path: Path
) -> None:
    result = invoke("project", "relink", str(tmp_path / "missing"), str(project.repository))
    assert (result.exit_code, report(result)["code"]) == (
        EXIT_PROJECT_NOT_FOUND,
        "project_relink_error",
    )


@pytest.mark.usefixtures("registry_network")
@pytest.mark.parametrize("ready", [False, True])
def test_doctor_needs_at_least_one_ready_agent(
    project: RelayProject,
    fake_agents: FakeAgents,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ready: bool,
) -> None:
    assets = tmp_path / "static"
    (assets / "assets").mkdir(parents=True)
    (assets / "index.html").write_text("<html></html>", encoding="utf-8")
    (assets / "assets" / "app.js").write_text("export {};", encoding="utf-8")
    monkeypatch.setattr(static_view, "STATIC_ROOT", assets)
    monkeypatch.chdir(project.repository)
    if ready:
        fake_agents.install("codex")

    result = invoke("doctor")

    assert result.exit_code == (0 if ready else EXIT_DOCTOR_FAILED)
    assert report(result)["ok"] is ready
    assert [row["id"] for row in report(result)["agents"] if row["ready"]] == (
        ["codex"] if ready else []
    )


def test_cleanup_without_selection_has_nothing_to_clean() -> None:
    result = invoke("data", "clean")
    assert (result.exit_code, report(result)) == (EXIT_NOTHING_TO_CLEAN, {"deleted": {}})


def test_cleanup_cannot_mix_all_with_individual_categories() -> None:
    result = invoke("data", "clean", "--all", "--runs")
    assert (result.exit_code, report(result)["code"]) == (ConfigError.cli_exit_code, "config_error")


def test_declining_cleanup_aborts_before_mutation() -> None:
    assert invoke("data", "clean", "--runs", input_text="n\n").exit_code == 1


@pytest.fixture
def terminal_project(
    project: RelayProject, engine: InlineEngine, monkeypatch: pytest.MonkeyPatch
) -> RelayProject:
    project.write_workflow(
        "done", "version: 1\nname: Done\nnodes:\n  a: {type: command, run: [git, status]}\n"
    )
    engine.drain(engine.launch(project, "done"))
    monkeypatch.chdir(project.repository)
    return project


@pytest.mark.usefixtures("terminal_project")
def test_runs_cleanup_rejects_retained_git_state() -> None:
    result = invoke("data", "clean", "--runs", input_text="y\n")
    assert (result.exit_code, report(result)["code"]) == (
        PermissionFlowError.cli_exit_code,
        "permission_flow_error",
    )


@pytest.mark.usefixtures("terminal_project")
def test_selected_cleanup_orders_worktrees_and_branches_before_run_records() -> None:
    result = invoke("data", "clean", "--worktrees", "--branches", "--runs", input_text="y\n")
    assert result.exit_code == 0
    deleted = report(result)["deleted"]
    assert (deleted["runs"], deleted["worktrees"], deleted["branches"]) == (1, 1, 1)


def test_all_cleanup_of_an_empty_project_has_nothing_to_clean(
    project: RelayProject, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(project.repository)
    assert invoke("data", "clean", "--all", input_text="y\n").exit_code == EXIT_NOTHING_TO_CLEAN


def test_all_cleanup_preserves_other_tools_logs_in_an_override_directory(
    project: RelayProject, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "shared-logs"
    folder.mkdir()
    monkeypatch.setenv("RELAY_LOG_PATH", str(folder / "app.log"))
    monkeypatch.chdir(project.repository)
    owned = folder / "app-111.log"
    marker = (APPLICATION_LOG_OWNERSHIP_LINE + "\n").encode("ascii")
    owned.write_bytes(marker + b"Relay diagnostics\n")
    foreign = [folder / "app-notes.log", folder / "app-20261002.log"]
    for path in foreign:
        path.write_bytes(b"Other tool diagnostics\n")

    result = invoke("data", "clean", "--all", input_text="y\n")

    assert result.exit_code == 0
    assert owned.read_bytes() == marker
    assert [path.read_bytes() for path in foreign] == [b"Other tool diagnostics\n"] * 2


def test_missing_settings_use_the_defaults(tmp_path: Path) -> None:
    assert load_config(tmp_path / "missing.json") == RelayConfig()


def test_valid_owner_settings_are_preserved_by_serialization(tmp_path: Path) -> None:
    expected = {
        "agent_preferences": ["codex", "cursor"],
        "cleanup_policy": "retain",
        "host": "localhost",
        "port": 8080,
        "workers": 2,
    }
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(expected), encoding="utf-8")
    assert load_config(path).to_dict() == expected


@pytest.mark.parametrize(
    "content",
    [
        "{",
        "[]",
        '{"theme": "dark"}',
        '{"agent_preferences": ["", "x"]}',
        '{"cleanup_policy": "never"}',
        '{"host": "0.0.0.0"}',
        '{"port": true}',
        '{"port": 70000}',
        '{"workers": 0}',
    ],
)
def test_invalid_settings_raise_a_config_error(tmp_path: Path, content: str) -> None:
    path = tmp_path / "settings.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)
