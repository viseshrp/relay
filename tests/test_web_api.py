"""The authenticated HTTP contract through Django clients and real stores."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from django.contrib.auth.models import User
from django.http import HttpResponse
from django.test import Client
import pytest

from relay.agents.models import ModelObservation
from relay.constants import DATABASE_INTEGER_MAX
from relay.web.models import Artifact, HumanInteraction, Run
from relay.web.repositories import DjangoAgentStore, DjangoReadStore
from tests.support import InlineEngine, RelayProject, fake_executable, run_status

PASSWORD = "Relay-Test-Passphrase-2026!"  # noqa: S105


def post(client: Client, url: str, body: dict[str, object]) -> HttpResponse:
    return client.post(url, data=json.dumps(body), content_type="application/json")


@pytest.fixture
def client() -> Client:
    return Client()


@pytest.fixture
def owner(client: Client) -> Client:
    response = post(client, "/api/auth/onboard", {"username": "owner", "password": PASSWORD})
    assert response.status_code == 201
    return client


@pytest.fixture
def served(project: RelayProject, monkeypatch: pytest.MonkeyPatch) -> RelayProject:
    monkeypatch.setenv("RELAY_PROJECT_ROOT", str(project.repository))
    return project


@pytest.fixture
def workflow_base(owner: Client, served: RelayProject) -> str:
    del served
    base = owner.get("/api/workflows/workflow").json()["base_hash"]
    lease = post(owner, "/api/workflows/workflow/lease", {"holder": "tab-1"})
    assert lease.status_code == 200
    return base


@pytest.fixture
def finished_run(served: RelayProject, engine: InlineEngine) -> str:
    served.write_workflow(
        "done", "version: 1\nname: Done\nnodes:\n  a: {type: command, run: [git, status]}\n"
    )
    run_id = engine.launch(served, "done")
    engine.drain(run_id)
    return run_id


@pytest.fixture
def waiting_run(served: RelayProject, engine: InlineEngine) -> tuple[str, int]:
    served.write_workflow(
        "approval",
        "version: 1\nname: Approval\nnodes:\n  approve: {type: human_wait, prompt: Go?}\n",
    )
    run_id = engine.launch(served, "approval")
    engine.drain(run_id)
    return run_id, HumanInteraction.objects.get(run_id=run_id).attempt_id


def test_auth_state_before_onboarding_issues_a_csrf_cookie(client: Client) -> None:
    response = client.get("/api/auth")

    assert response.json() == {"owner_created": False, "authenticated": False, "username": None}
    assert "relay_csrftoken" in client.cookies


def test_onboarding_authenticates_the_new_owner(client: Client) -> None:
    response = post(client, "/api/auth/onboard", {"username": " owner ", "password": PASSWORD})

    assert response.status_code == 201
    assert response.json() == {"authenticated": True, "username": "owner"}
    assert client.get("/api/auth").json()["owner_created"] is True


@pytest.mark.parametrize(
    "body",
    [
        {"username": "owner", "password": "password"},
        {"username": "  ", "password": PASSWORD},
        {"username": "x" * 151, "password": PASSWORD},
    ],
)
def test_invalid_owner_credentials_are_rejected(client: Client, body: dict[str, str]) -> None:
    response = post(client, "/api/auth/onboard", dict(body))
    assert (response.status_code, response.json()["code"]) == (400, "config_error")
    assert not User.objects.exists()


def test_onboarding_cannot_create_a_second_owner(owner: Client) -> None:
    response = post(owner, "/api/auth/onboard", {"username": "other", "password": PASSWORD})
    assert (response.status_code, response.json()["code"]) == (409, "permission_flow_error")


def test_logout_ends_access_to_authenticated_routes(owner: Client) -> None:
    response = post(owner, "/api/auth/logout", {})
    assert response.json() == {"authenticated": False}
    assert owner.get("/api/projects").status_code == 401


def test_the_owner_can_sign_in_again(owner: Client) -> None:
    post(owner, "/api/auth/logout", {})
    response = post(owner, "/api/auth/login", {"username": "owner", "password": PASSWORD})
    assert response.json() == {"authenticated": True, "username": "owner"}
    assert owner.get("/api/auth").json()["authenticated"] is True


@pytest.mark.parametrize("superuser", [False, True], ids=["non-owner", "wrong-password"])
def test_invalid_logins_do_not_create_sessions(client: Client, superuser: bool) -> None:
    User.objects.create_user("user", password=PASSWORD, is_superuser=superuser)
    password = "incorrect" if superuser else PASSWORD
    response = post(client, "/api/auth/login", {"username": "user", "password": password})
    assert (response.status_code, response.json()["code"]) == (401, "authentication_failed")


def test_csrf_failures_use_the_json_envelope() -> None:
    response = post(
        Client(enforce_csrf_checks=True),
        "/api/auth/login",
        {"username": "owner", "password": PASSWORD},
    )
    assert (response.status_code, response.json()["code"]) == (403, "csrf_failed")


def test_wrong_methods_use_the_json_envelope(owner: Client) -> None:
    response = owner.get("/api/auth/login")
    assert (response.status_code, response.json()["code"]) == (405, "method_not_allowed")
    assert response["Allow"] == "POST"


@pytest.mark.parametrize(
    ("body", "content_type"),
    [
        ("{", "application/json"),
        ("[1]", "application/json"),
        ("{}", "text/plain"),
        ('{"username": 5, "password": "x"}', "application/json"),
    ],
)
def test_malformed_bodies_are_rejected(client: Client, body: str, content_type: str) -> None:
    response = client.post("/api/auth/onboard", data=body, content_type=content_type)
    assert (response.status_code, response.json()["code"]) == (400, "config_error")


@pytest.mark.parametrize("path", ["/api", "/api/", "/api/no/such/route"])
def test_unknown_api_routes_return_not_found(owner: Client, path: str) -> None:
    response = owner.get(path)
    assert (response.status_code, response.json()["code"]) == (404, "not_found")


def test_registered_projects_are_listed(owner: Client, project: RelayProject) -> None:
    rows = owner.get("/api/projects").json()["projects"]
    assert [row["id"] for row in rows] == [project.project_id]


def test_opening_a_registered_project_keeps_its_identity(
    owner: Client, project: RelayProject
) -> None:
    response = post(owner, "/api/projects/open", {"path": str(project.repository)})
    assert response.status_code == 200
    assert response.json()["project"]["id"] == project.project_id


def test_a_missing_project_is_not_found(owner: Client, tmp_path: Path) -> None:
    assert post(owner, "/api/projects/open", {"path": str(tmp_path / "missing")}).status_code == 404


def test_relinking_preserves_the_project_identity(
    owner: Client, project: RelayProject, tmp_path: Path
) -> None:
    moved = tmp_path / "moved"
    project.repository.rename(moved)

    response = post(
        owner, "/api/projects/relink", {"old": str(project.repository), "new": str(moved)}
    )

    assert response.status_code == 200
    assert response.json()["project"]["id"] == project.project_id


def test_saving_a_workflow_requires_a_live_lease(owner: Client, served: RelayProject) -> None:
    del served
    base = owner.get("/api/workflows/workflow").json()["base_hash"]
    response = post(
        owner,
        "/api/workflows/workflow/save",
        {"holder": "tab-1", "yaml": "version: 1\nname: Edited\nnodes: {}\n", "base_hash": base},
    )
    assert (response.status_code, response.json()["code"]) == (409, "permission_flow_error")


@pytest.mark.usefixtures("workflow_base")
def test_a_second_browser_cannot_take_a_live_workflow_lease(owner: Client) -> None:
    response = post(owner, "/api/workflows/workflow/lease", {"holder": "tab-2"})
    assert response.status_code == 409


def test_invalid_drafts_are_retained_for_the_browser(owner: Client, workflow_base: str) -> None:
    response = post(
        owner,
        "/api/workflows/workflow/draft",
        {"holder": "tab-1", "yaml": "nodes: [", "base_hash": workflow_base},
    )
    assert response.json()["draft"]["validation_state"] == "invalid"
    assert owner.get("/api/workflows/workflow").json()["draft"]["yaml"] == "nodes: ["


@pytest.mark.parametrize("field", ["base_hash", "yaml", "holder"])
def test_invalid_workflow_save_fields_are_rejected(
    owner: Client, workflow_base: str, field: str
) -> None:
    body = {
        "holder": "tab-1",
        "yaml": "version: 1\nname: Edited\nnodes: {}\n",
        "base_hash": workflow_base,
    }
    body[field] = {"base_hash": "XYZ", "yaml": 5, "holder": "h" * 201}[field]
    response = post(owner, "/api/workflows/workflow/save", body)
    assert (response.status_code, response.json()["code"]) == (400, "config_error")


def test_saving_a_workflow_updates_the_durable_yaml(
    owner: Client, served: RelayProject, workflow_base: str
) -> None:
    updated = "version: 1\nname: Edited\nnodes: {}\n"
    response = post(
        owner,
        "/api/workflows/workflow/save",
        {"holder": "tab-1", "yaml": updated, "base_hash": workflow_base},
    )
    assert response.json() == {"ok": True}
    assert (served.relay_root / "workflows/workflow.yaml").read_text(encoding="utf-8") == updated


@pytest.mark.parametrize("cleanup_policy", ["sometimes", 1])
def test_launch_rejects_invalid_cleanup_policies(
    owner: Client, served: RelayProject, cleanup_policy: object
) -> None:
    del served
    response = post(
        owner,
        "/api/runs",
        {"workflow_key": "workflow", "inputs": {}, "cleanup_policy": cleanup_policy},
    )
    assert (response.status_code, response.json()["code"]) == (400, "config_error")


def test_http_launch_records_the_authenticated_launcher(
    owner: Client, served: RelayProject
) -> None:
    served.write_workflow(
        "check", "version: 1\nname: Check\nnodes:\n  a: {type: command, run: [git, status]}\n"
    )
    response = post(owner, "/api/runs", {"workflow_key": "check", "inputs": {}})
    assert response.status_code == 201
    assert Run.objects.get(pk=response.json()["run_id"]).launcher == "owner"


def test_runs_can_be_filtered_by_project_and_status(
    owner: Client, served: RelayProject, finished_run: str
) -> None:
    rows = owner.get(f"/api/runs?project={served.project_id}&status=succeeded").json()["runs"]
    assert [row["id"] for row in rows] == [finished_run]


def test_run_list_cursors_exclude_the_cursor_run(owner: Client, finished_run: str) -> None:
    assert owner.get(f"/api/runs?since={finished_run}").json() == {"runs": [], "next": None}


@pytest.mark.parametrize(("query", "status"), [("status=bogus", 400), ("project=invalid", 404)])
def test_invalid_run_filters_are_rejected(owner: Client, query: str, status: int) -> None:
    assert owner.get(f"/api/runs?{query}").status_code == status


def test_run_detail_exposes_nodes_and_the_launch_snapshot(owner: Client, finished_run: str) -> None:
    detail = owner.get(f"/api/runs/{finished_run}").json()["run"]
    assert detail["nodes"][0]["scope_path"] == "root.a"
    assert detail["snapshot"]["relay_version"]


def test_run_detail_can_select_interactions(owner: Client, finished_run: str) -> None:
    detail = owner.get(f"/api/runs/{finished_run}?collection=interactions").json()["run"]
    assert detail["interactions"] == []


def test_event_pages_have_a_cursor_for_remaining_history(owner: Client, finished_run: str) -> None:
    first = owner.get(f"/api/runs/{finished_run}/events?limit=1").json()
    second = owner.get(f"/api/runs/{finished_run}/events?since={first['next']}&limit=1").json()
    assert len(first["events"]) == len(second["events"]) == 1
    assert first["events"][0]["id"] < second["events"][0]["id"]


@pytest.mark.parametrize(
    "query",
    ["collection=edges", "since=-1", "since=x", "limit=0", f"since={DATABASE_INTEGER_MAX + 1}"],
)
def test_invalid_detail_page_parameters_are_rejected(
    owner: Client, finished_run: str, query: str
) -> None:
    response = owner.get(f"/api/runs/{finished_run}?{query}")
    assert (response.status_code, response.json()["code"]) == (400, "config_error")


def test_unknown_runs_are_not_found(owner: Client) -> None:
    assert owner.get("/api/runs/00000000-0000-0000-0000-000000000000").status_code == 404


def test_wait_answers_enter_the_control_mailbox(
    owner: Client, waiting_run: tuple[str, int]
) -> None:
    _run_id, attempt_id = waiting_run
    response = post(
        owner, f"/api/attempts/{attempt_id}/wait", {"idempotency_key": "w1", "value": "yes"}
    )
    assert (response.status_code, response.json()) == (202, {"result": "accepted"})


def test_wait_answers_require_a_value(owner: Client, waiting_run: tuple[str, int]) -> None:
    _run_id, attempt_id = waiting_run
    response = post(owner, f"/api/attempts/{attempt_id}/wait", {"idempotency_key": "w1"})
    assert (response.status_code, response.json()["code"]) == (400, "config_error")


@pytest.mark.parametrize(
    ("kind", "payload"),
    [("permission", {"decision": "allow"}), ("elicitation", {"value": {"a": 1}})],
)
def test_a_wait_node_rejects_unrelated_control_kinds(
    owner: Client, waiting_run: tuple[str, int], kind: str, payload: dict[str, object]
) -> None:
    _run_id, attempt_id = waiting_run
    response = post(
        owner, f"/api/attempts/{attempt_id}/{kind}", {"idempotency_key": "x", **payload}
    )
    assert (response.status_code, response.json()) == (422, {"result": "invalid"})


def test_cancel_requests_enter_a_waiting_runs_mailbox(
    owner: Client, waiting_run: tuple[str, int]
) -> None:
    run_id, _attempt_id = waiting_run
    response = post(owner, f"/api/runs/{run_id}/cancel", {"idempotency_key": "c1"})
    assert (response.status_code, response.json()) == (202, {"result": "accepted"})


def test_canceling_an_interrupted_run_returns_a_stale_conflict(
    owner: Client, waiting_run: tuple[str, int]
) -> None:
    run_id, _attempt_id = waiting_run
    # An interrupted persisted run requires resume rather than a cancel mailbox.
    Run.objects.filter(pk=run_id).update(status="interrupted")
    response = post(owner, f"/api/runs/{run_id}/cancel", {"idempotency_key": "c1"})
    assert (response.status_code, response.json()) == (409, {"result": "stale"})


def test_a_failed_node_can_be_rerun_idempotently(
    owner: Client, served: RelayProject, engine: InlineEngine
) -> None:
    served.write_workflow(
        "failure",
        "version: 1\nname: Failure\nnodes:\n  fail: {type: command, run: [git, not-a-command]}\n",
    )
    run_id = engine.launch(served, "failure")
    engine.drain(run_id)
    body = {"scope_path": "root.fail", "idempotency_key": "r1"}
    response = post(owner, f"/api/runs/{run_id}/rerun-node", body)
    duplicate = post(owner, f"/api/runs/{run_id}/rerun-node", body)
    assert (response.status_code, response.json()) == (202, {"result": "accepted"})
    assert duplicate.json() == {"result": "already_applied"}
    assert run_status(run_id) == "running"


def test_artifacts_download_as_byte_exact_attachments(owner: Client, finished_run: str) -> None:
    artifact = Artifact.objects.filter(attempt__node_run__run_id=finished_run).first()
    assert artifact is not None
    download = owner.get(f"/api/artifacts/{artifact.pk}")
    retained, _name, _media_type = DjangoReadStore().artifact_file(str(artifact.pk))
    assert download.status_code == 200
    assert "attachment" in download["Content-Disposition"]
    assert b"".join(download.streaming_content) == retained.read_bytes()


def test_artifact_pages_expose_retained_evidence(owner: Client, finished_run: str) -> None:
    rows = owner.get(f"/api/runs/{finished_run}/artifacts").json()["artifacts"]
    assert {row["name"] for row in rows} >= {"commits"}


@pytest.mark.parametrize("artifact_id", ["0", "invalid", str(DATABASE_INTEGER_MAX)])
def test_unknown_artifacts_are_not_found(owner: Client, artifact_id: str) -> None:
    assert owner.get(f"/api/artifacts/{artifact_id}").status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"scope": "runs"},
        {"scope": "everything", "confirm": True},
        {"scope": "runs", "confirm": True},
    ],
)
def test_cleanup_rejects_unconfirmed_or_unsafe_scopes(
    owner: Client, finished_run: str, body: dict[str, object]
) -> None:
    del finished_run
    response = post(owner, "/api/data/clean", body)
    assert (response.status_code, response.json()["code"]) == (409, "permission_flow_error")


def test_all_cleanup_removes_a_terminal_runs_rows_and_worktree(
    owner: Client, finished_run: str
) -> None:
    response = post(owner, "/api/data/clean", {"scope": "all", "confirm": True})
    deleted = response.json()["deleted"]
    assert (deleted["runs"], deleted["worktrees"], deleted["branches"]) == (1, 1, 1)
    assert not Run.objects.filter(pk=finished_run).exists()


@pytest.mark.usefixtures("registry_network")
def test_agents_report_detection_registry_and_model_observations(
    owner: Client, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bin_dir = tmp_path / "bin"
    fake_executable(bin_dir, "codex-acp", "print('codex-acp 1.2.3')\n")
    monkeypatch.setenv("PATH", str(bin_dir))
    DjangoAgentStore().replace_model_observations(
        "codex",
        (
            ModelObservation(
                "codex",
                "gpt-x",
                "GPT X",
                "model",
                "1.2.3",
                datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
        ),
    )

    body = owner.get("/api/agents").json()

    rows = {row["id"]: row for row in body["agents"]}
    assert rows["codex"]["installed"] is True
    assert rows["codex"]["detected_version"] == "codex-acp 1.2.3"
    assert rows["codex"]["models"][0]["value"] == "gpt-x"
    assert rows["codex"]["registry"]["distributions"][0]["manager"] == "npx"
    assert rows["antigravity"]["installed"] is False
    assert body["registry"]["stale"] is False
