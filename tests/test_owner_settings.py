"""Global defaults, project inheritance, safe saves, and immutable launches."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path

from django.db import DatabaseError
from django.test import Client, override_settings
import pytest

from relay.config import load_config
from relay.errors import ConfigError, PersistenceError, ProjectDiscoveryError, SettingsConflictError
from relay.execution.preflight import load_launch_workflow
from relay.execution.scheduler import dispatch_ready_nodes
from relay.owner_settings import effective_config, read_settings, save_settings
from relay.paths import settings_path, worktrees_dir
from relay.projects.storage import measure_working_copies
from relay.web.models import Artifact, HumanInteraction, NodeRun, Project, Run, RunSnapshot
from relay.web.settings_repository import DjangoSettingsStore
from relay.web.views import actions
from relay.workflows.defaults import apply_workflow_defaults, validate_defaults
from tests.support import FakeAgents, InlineEngine, RelayProject, create_project
from tests.test_web_api import client as client
from tests.test_web_api import finished_run as finished_run
from tests.test_web_api import owner as owner
from tests.test_web_api import post
from tests.test_web_api import served as served
from tests.test_web_api import waiting_run as waiting_run


def save_global(values: dict[str, object]) -> None:
    current = read_settings()
    save_settings(values, str(current["revision"]))


def test_global_save_is_atomic_private_and_rejects_stale_edits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = read_settings()
    save_settings(
        {"port": 8081, "workflow_defaults": {"model": "ExactModel"}}, str(current["revision"])
    )
    path = settings_path()
    before = path.read_bytes()
    assert load_config().workflow_defaults.model == "ExactModel"
    with pytest.raises(SettingsConflictError):
        save_settings({"port": 8082}, str(current["revision"]))
    assert path.read_bytes() == before

    def fail_replace(source: object, destination: object) -> None:
        del source, destination
        message = "private filesystem failure"
        raise OSError(message)

    monkeypatch.setattr("relay.owner_settings.os.replace", fail_replace)
    with pytest.raises(PersistenceError, match="Previous settings remain"):
        save_settings({"port": 8082}, str(read_settings()["revision"]))
    assert path.read_bytes() == before
    assert list(path.parent.glob(".settings-*")) == []


@pytest.mark.parametrize(
    "values",
    [
        {"model": ""},
        {"providers": {"unknown": {"model": "m1"}}},
        {"providers": {"codex": {"effort": "high"}}},
        {"timeout": "10 minutes"},
        {"auto_retry": "false"},
        {"recovery": {"max_retries": 3}},
        {"repairs": {"max_rounds": 101}},
        {"repairs": {"fix_instruction": ""}},
        {"env": {"PASSWORD": "secret"}},
    ],
)
def test_invalid_defaults_never_replace_settings(values: dict[str, object]) -> None:
    with pytest.raises(ConfigError):
        save_global({"workflow_defaults": values})
    assert not settings_path().exists()


def test_read_revision_covers_exact_file_bytes() -> None:
    path = settings_path()
    path.parent.mkdir(parents=True)
    text = b'{"port": 8081}\n'
    path.write_bytes(text)
    assert read_settings()["revision"] == sha256(text).hexdigest()
    assert read_settings()["settings"]["port"] == 8081


def test_project_overrides_merge_by_field_and_reset_without_mutating_global(
    project: RelayProject,
) -> None:
    save_global(
        {
            "agent_preferences": ["codex", "claude"],
            "cleanup_policy": "retain",
            "workflow_defaults": {
                "model": "m1",
                "providers": {"codex": {"model": "m1", "effort": "high", "permission_mode": "ask"}},
                "recovery": {"enabled": True},
            },
        }
    )
    store = DjangoSettingsStore()
    from relay.owner_settings import revision

    store.save_project_defaults(
        project.project_id,
        {
            "workflow_defaults": {
                "providers": {"codex": {"effort": None}},
                "recovery": {"enabled": False},
            }
        },
        revision({}),
    )
    config = effective_config(store, project.project_id)
    assert config.agent_preferences == ("codex", "claude")
    assert config.cleanup_policy == "retain"
    assert config.workflow_defaults.providers["codex"].effort is None
    assert config.workflow_defaults.providers["codex"].permission_mode == "ask"
    assert not config.workflow_defaults.recovery.enabled
    assert load_config().workflow_defaults.recovery.enabled
    assert load_config().workflow_defaults.providers["codex"].effort == "high"


@pytest.mark.parametrize("model", ["m2", None])
def test_project_model_changes_cannot_inherit_options_for_another_model(
    project: RelayProject, model: str | None
) -> None:
    save_global(
        {
            "workflow_defaults": {
                "providers": {"codex": {"model": "m1", "effort": "high", "permission_mode": "ask"}}
            }
        }
    )
    resolved = effective_config(
        DjangoSettingsStore(),
        project.project_id,
        {"workflow_defaults": {"providers": {"codex": {"model": model}}}},
    )
    provider = resolved.workflow_defaults.providers["codex"]
    assert provider.model == model
    assert provider.effort is None
    assert provider.permission_mode is None
    assert load_config().workflow_defaults.providers["codex"].effort == "high"


@pytest.mark.parametrize("explicit", [False, True])
def test_defaults_respect_explicit_node_and_workflow_choices(
    project: RelayProject, explicit: bool
) -> None:
    workflow_model = "model: m2\n" if explicit else ""
    recovery = "recovery: {enabled: false}\n" if explicit else ""
    job = (
        "model: m1, timeout: null, auto_retry: true, "
        "agent_options: {codex: {effort: null, permission_mode: ask}}"
        if explicit
        else ""
    )
    project.write_workflow(
        "defaults",
        f"version: 1\nname: Defaults\nagents: [codex]\n{workflow_model}{recovery}nodes:\n"
        f"  work: {{type: agent, {job}}}\n"
        "  approve: {type: human_wait, prompt: Review}\n",
    )
    loaded = load_launch_workflow(project.relay_root, "defaults")
    defaults = validate_defaults(
        {
            "providers": {"codex": {"model": "m1", "effort": "low", "permission_mode": "ask"}},
            "timeout": "15m",
            "auto_retry": False,
            "recovery": {"enabled": True, "max_retries": 1},
        }
    )
    effective = apply_workflow_defaults(loaded, defaults, (), None)
    node = effective.root.definition.nodes["work"]
    assert node.model == "m1"
    assert node.timeout == (None if explicit else "15m")
    assert node.auto_retry is explicit
    assert node.agent_options["codex"].effort == (None if explicit else "low")
    assert effective.root.definition.nodes["approve"].timeout is None
    assert effective.root.definition.recovery.enabled is not explicit
    assert effective.root.text == loaded.root.text


def test_options_do_not_leak_between_models_or_override_permission_profile(
    project: RelayProject,
) -> None:
    project.write_workflow(
        "models",
        "version: 1\nname: Models\nmodel: m2\nagents: [codex]\nnodes:\n"
        "  other: {type: agent}\n"
        "  profile: {type: agent, model: m1, permission_profile: interactive}\n",
    )
    defaults = validate_defaults(
        {"providers": {"codex": {"model": "m1", "effort": "low", "permission_mode": "auto"}}}
    )
    loaded = apply_workflow_defaults(
        load_launch_workflow(project.relay_root, "models"), defaults, (), None
    )
    assert loaded.root.definition.nodes["other"].agent_options["codex"].effort is None
    assert loaded.root.definition.nodes["profile"].agent_options["codex"].permission_mode is None


@pytest.mark.usefixtures("registry_network")
def test_global_and_project_endpoints_require_owner_csrf_and_validate(
    owner: Client, served: RelayProject
) -> None:
    del served
    response = owner.get("/api/settings")
    assert response.status_code == 200
    assert response.json()["settings"]["login_required"] is True
    body = {"settings": {"port": 8123}, "revision": response.json()["revision"]}
    assert post(owner, "/api/settings", body).status_code == 200
    assert post(owner, "/api/settings", body).status_code == 409
    assert (
        post(owner, "/api/settings", {**body, "settings": {"host": "example.com"}}).status_code
        == 400
    )
    anonymous = Client(enforce_csrf_checks=True)
    assert anonymous.get("/api/settings").status_code == 401
    assert (
        anonymous.post(
            "/api/settings", data=json.dumps(body), content_type="application/json"
        ).status_code
        == 403
    )
    assert owner.put("/api/settings").status_code == 405


def test_project_preview_is_read_only_and_global_only_keys_are_rejected(
    owner: Client, served: RelayProject, tmp_path: Path
) -> None:
    original = owner.get("/api/projects/defaults").json()
    preview = post(
        owner,
        "/api/projects/defaults",
        {"preview": True, "overrides": {"workflow_defaults": {"timeout": "4m"}}},
    )
    assert preview.status_code == 200
    assert preview.json()["effective"]["workflow_defaults"]["timeout"] == "4m"
    assert owner.get("/api/projects/defaults").json() == original
    body = {"revision": original["revision"], "overrides": {"cleanup_policy": "retain"}}
    assert post(owner, "/api/projects/defaults", body).status_code == 200
    assert post(owner, "/api/projects/defaults", body).status_code == 409
    assert (
        post(
            owner, "/api/projects/defaults", {**body, "overrides": {"login_required": False}}
        ).status_code
        == 400
    )
    other = create_project(tmp_path / "other")
    assert owner.get(f"/api/projects/defaults?project={other.project_id}").json()["overrides"] == {}
    assert effective_config(DjangoSettingsStore(), served.project_id).cleanup_policy == "retain"


@pytest.mark.usefixtures("registry_network")
def test_launch_freezes_defaults_and_nested_jobs_without_rewriting_sources(
    owner: Client,
    served: RelayProject,
    engine: InlineEngine,
    fake_agents: FakeAgents,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_agents.install("codex", mode="configuration")
    monkeypatch.setattr(actions, "_enqueue_claim", engine.tokens.append)
    source = (
        "version: 1\nname: Defaults\nnodes:\n"
        "  wait: {type: human_wait, prompt: Approve}\n"
        "  child: {type: subworkflow, workflow: child, needs: [wait]}\n"
    )
    child = "version: 1\nname: Child\nnodes:\n  work: {type: agent}\n"
    served.write_workflow("parent", source)
    served.write_workflow("child", child)
    save_global(
        {
            "agent_preferences": ["codex"],
            "cleanup_policy": "retain",
            "workflow_defaults": {
                "providers": {"codex": {"model": "m1", "effort": "low", "permission_mode": "ask"}},
                "timeout": "15m",
                "recovery": {"enabled": True, "max_retries": 1},
            },
        }
    )
    launched = post(owner, "/api/runs", {"workflow_key": "parent", "inputs": {}})
    assert launched.status_code == 201, launched.json()
    run_id = launched.json()["run_id"]
    snapshot = RunSnapshot.objects.get(run_id=run_id)
    before = snapshot.launch_defaults
    assert snapshot.workflow_yaml == source
    assert snapshot.subworkflows["child.yaml"]["yaml"] == child
    assert snapshot.subworkflows["child.yaml"]["definition"]["nodes"]["work"]["timeout"] == "15m"
    assert snapshot.route_table["root.child.work"]["effort"] == "low"
    assert Run.objects.get(pk=run_id).cleanup_policy == "retain"
    assert Run.objects.get(pk=run_id).recovery_policy == {"enabled": True, "max_retries": 1}
    save_global({"agent_preferences": ["claude"], "workflow_defaults": {"timeout": "1s"}})
    engine.drain(run_id)
    wait = HumanInteraction.objects.get(attempt__node_run__run_id=run_id)
    answer = post(
        owner,
        f"/api/attempts/{wait.attempt_id}/wait",
        {
            "idempotency_key": "approve-defaults",
            "value": "yes",
            "interaction_id": str(wait.pk),
        },
    )
    assert answer.status_code == 202, answer.json()
    assert engine.store.resolve_human_wait_controls() == 1
    dispatch_ready_nodes(engine.store, run_id, engine.tokens.append)
    engine.drain(run_id)
    nested = NodeRun.objects.get(run_id=run_id, scope_path="root.child.work")
    assert nested.frozen_def["timeout"] == "15m"
    assert nested.frozen_def["agent_options"]["codex"]["effort"] == "low"
    assert Run.objects.get(pk=run_id).status == "succeeded"
    snapshot.refresh_from_db()
    assert snapshot.launch_defaults == before
    assert snapshot.route_table["root.child.work"]["model_value"] == "m1"
    assert (served.relay_root / "workflows/parent.yaml").read_text() == source


@pytest.mark.parametrize("login_required", [True, False])
def test_saving_login_is_restart_only_and_preserves_account(
    owner: Client, login_required: bool
) -> None:
    from django.contrib.auth.models import User

    current = owner.get("/api/settings").json()
    with override_settings(RELAY_LOGIN_REQUIRED=login_required):
        result = post(
            owner,
            "/api/settings",
            {"revision": current["revision"], "settings": {"login_required": not login_required}},
        )
        assert result.status_code == 200
        assert result.json()["active_login_required"] is login_required
        assert Client().get("/api/settings").status_code == (401 if login_required else 200)
    assert User.objects.count() == 1


def test_invalid_combined_project_defaults_are_not_saved(owner: Client) -> None:
    current = owner.get("/api/projects/defaults").json()
    result = post(
        owner,
        "/api/projects/defaults",
        {
            "revision": current["revision"],
            "overrides": {"workflow_defaults": {"providers": {"codex": {"effort": "low"}}}},
        },
    )
    assert result.status_code == 400
    assert owner.get("/api/projects/defaults").json() == current


@pytest.mark.parametrize("option", [{"model": "Unavailable"}, {"model": "m1", "effort": "unknown"}])
@pytest.mark.usefixtures("registry_network")
def test_invalid_saved_provider_choices_fail_fresh_launch_proof_without_creating_run(
    owner: Client, served: RelayProject, fake_agents: FakeAgents, option: dict[str, str]
) -> None:
    fake_agents.install("codex", mode="configuration")
    served.write_workflow("defaults", "version: 1\nname: Defaults\nnodes:\n  work: {type: agent}\n")
    save_global(
        {"agent_preferences": ["codex"], "workflow_defaults": {"providers": {"codex": option}}}
    )
    result = post(owner, "/api/runs", {"workflow_key": "defaults", "inputs": {}})
    assert result.status_code == 422, result.json()
    assert result.json()["code"] == (
        "model_unavailable_error"
        if option["model"] == "Unavailable"
        else "agent_configuration_error"
    )
    assert not Run.objects.exists()


def test_storage_usage_counts_project_data_without_enabling_cleanup(
    owner: Client, finished_run: str, waiting_run: tuple[str, int]
) -> None:
    del finished_run, waiting_run
    result = owner.get("/api/data/usage")
    assert result.status_code == 200
    body = result.json()
    assert body["runs"] == 2
    assert body["artifacts"] == Artifact.objects.count()
    assert body["artifact_bytes"] == sum(Artifact.objects.values_list("bytes", flat=True))
    assert body["working_copies"]["directories"] == 2
    assert body["working_copies"]["bytes"] > 0
    assert body["branches"] == 2
    assert body["cleanup_blocked"] is True
    assert Client().get("/api/data/usage").status_code == 401


def test_storage_scan_skips_symlinks_and_reports_bounded_lower_size(tmp_path: Path) -> None:
    root = worktrees_dir() / "usage"
    root.mkdir(parents=True)
    (root / "inside").write_bytes(b"123")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private").write_bytes(b"123456")
    try:
        (root / "link").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks are unavailable for this test account")
    usage = measure_working_copies((str(root), str(root)))
    assert (usage.bytes, usage.files, usage.directories, usage.truncated) == (3, 1, 1, False)
    assert measure_working_copies((str(root),), maximum_entries=0).truncated
    assert measure_working_copies(()).bytes == 0
    assert measure_working_copies(("", str(worktrees_dir()))).bytes == 0


@pytest.mark.usefixtures("registry_network")
def test_agent_inventory_remains_available_before_project_setup(
    owner: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_project(request: object) -> None:
        del request
        message = "Initialize or open a project."
        raise ProjectDiscoveryError(message)

    monkeypatch.setattr("relay.web.views.pages.current_project", no_project)
    assert owner.get("/api/agents").status_code == 200
    assert owner.get("/api/agents?project=missing").status_code == 404


@pytest.mark.parametrize("content", [b"", b"{", b"\xff"])
def test_corrupt_settings_are_reported_without_replacing_the_file(content: bytes) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    with pytest.raises(PersistenceError, match="could not read"):
        read_settings()
    assert path.read_bytes() == content


@pytest.mark.parametrize("operation", ["read", "save", "usage"])
def test_project_database_failures_have_relay_owned_messages(
    project: RelayProject, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    def unavailable(*args: object, **kwargs: object) -> None:
        del args, kwargs
        message = "private database details"
        raise DatabaseError(message)

    monkeypatch.setattr(
        Project.objects, "select_for_update" if operation == "save" else "filter", unavailable
    )
    store = DjangoSettingsStore()
    with pytest.raises(PersistenceError) as caught:
        if operation == "save":
            store.save_project_defaults(project.project_id, {}, "revision")
        elif operation == "usage":
            store.storage_usage(project.project_id)
        else:
            store.project_defaults(project.project_id)
    assert "private database details" not in str(caught.value)


def test_corrupt_project_defaults_fail_without_changing_global_settings(
    project: RelayProject,
) -> None:
    before = read_settings()
    Project.objects.filter(pk=project.project_id).update(defaults=[1])
    with pytest.raises(PersistenceError, match="Saved project defaults are invalid"):
        DjangoSettingsStore().project_defaults(project.project_id)
    assert read_settings() == before


def test_unreadable_working_copy_reports_an_incomplete_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = worktrees_dir() / "usage"
    root.mkdir(parents=True)

    def unavailable(path: object) -> None:
        del path
        message = "private filesystem details"
        raise PermissionError(message)

    monkeypatch.setattr("relay.projects.storage.os.scandir", unavailable)
    usage = measure_working_copies((str(root),))
    assert usage.truncated
    assert usage.bytes == 0


@pytest.mark.parametrize("outside", [True, False])
def test_directory_junctions_do_not_include_another_projects_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outside: bool
) -> None:
    root = worktrees_dir() / "measured"
    root.mkdir(parents=True)
    (root / "own-file").write_bytes(b"123")
    target = (tmp_path if outside else worktrees_dir()) / "other-project"
    target.mkdir()
    (target / "private-file").write_bytes(b"123456")
    junction = root / "junction"
    try:
        junction.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks are unavailable for this test account")

    class DirectoryJunction:
        path: str = str(junction)

        def is_symlink(self) -> bool:
            return False

        def is_dir(self, *, follow_symlinks: bool) -> bool:
            del follow_symlinks
            return True

    original = os.scandir

    @contextmanager
    def entries(path: Path) -> Iterator[Iterator[os.DirEntry[str] | DirectoryJunction]]:
        with original(path) as rows:
            # A junction is reported as a directory on Windows. The real
            # filesystem link still exercises containment and target resolution.
            yield iter(DirectoryJunction() if row.path == str(junction) else row for row in rows)

    monkeypatch.setattr("relay.projects.storage.os.scandir", entries)
    usage = measure_working_copies((str(root),))
    assert (usage.bytes, usage.files, usage.directories) == (3, 1, 1)
