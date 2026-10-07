"""The authenticated HTTP contract through Django clients and real stores."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import json
from pathlib import Path

from django.contrib.auth.models import User
from django.db import DatabaseError, connection, transaction
from django.http import HttpResponse
from django.test import Client, override_settings
import pytest

from relay.agents.models import ModelObservation
from relay.constants import (
    APPLICATION_LOG_OWNERSHIP_LINE,
    DATABASE_INTEGER_MAX,
    RUN_PROBLEM_MESSAGE_MAX_EVENTS,
    RUN_PROBLEM_TEXT_MAX_CHARS,
)
from relay.execution.resume import recovery_workspace_lock
from relay.execution.runner import ExecutionOutcome, OutcomeKind
from relay.execution.state import AttemptStopReason, EventSensitivity, EventSource
from relay.web.models import Artifact, HumanInteraction, NodeRun, Run, RunEvent, RunSnapshot
from relay.web.repositories import DjangoAgentStore, DjangoReadStore
from relay.web.views import actions
from tests.support import (
    FakeAgents,
    InlineEngine,
    RelayProject,
    create_project,
    fake_executable,
    git,
    run_status,
)

PASSWORD = "Relay-Test-Passphrase-2026!"  # noqa: S105


def test_workflow_preflight_is_read_only_and_scoped_to_the_selected_project(
    owner: Client, served: RelayProject, tmp_path: Path
) -> None:
    text = "version: 1\nname: Check\nnodes:\n  check: {type: command, run: [git, status]}\n"
    served.write_workflow("nested/check", text)
    served.write("REVIEW.md", "Owner review\n")
    served.write("loose code.py", "Owner code\n")
    before = git(served.repository, "status", "--porcelain=v1")
    head = git(served.repository, "rev-parse", "HEAD")
    response = owner.get("/api/workflows/nested/check.yaml/preflight")
    assert response.status_code == 200
    assert response.json() == {
        "clean": False,
        "blocking_count": 1,
        "allowed_count": 1,
        "truncated": False,
        "files": [
            {
                "status": "??",
                "path": "loose code.py",
                "original_path": None,
                "allowed": False,
                "reasons": ["untracked"],
            },
            {
                "status": "??",
                "path": "REVIEW.md",
                "original_path": None,
                "allowed": True,
                "reasons": ["Root workflow report"],
            },
        ],
    }
    assert git(served.repository, "status", "--porcelain=v1") == before
    assert git(served.repository, "rev-parse", "HEAD") == head
    assert not Run.objects.exists()
    assert "Owner code" not in response.content.decode()
    other = create_project(tmp_path / "another")
    other.write_workflow("nested/check", text)
    selected = owner.get(f"/api/workflows/nested/check/preflight?project={other.project_id}")
    assert selected.status_code == 200
    assert selected.json() == {
        "clean": True,
        "blocking_count": 0,
        "allowed_count": 0,
        "files": [],
        "truncated": False,
    }
    assert owner.post("/api/workflows/nested/check/preflight").status_code == 405


def test_workflow_preflight_requires_login_and_returns_workflow_errors(
    client: Client, owner: Client, served: RelayProject
) -> None:
    client.logout()
    assert client.get("/api/workflows/workflow/preflight").status_code == 401
    client.force_login(User.objects.get(username="owner"))
    served.write(".relay/workflows/invalid.yaml", "nodes: [\n")
    response = owner.get("/api/workflows/invalid/preflight")
    assert response.status_code == 422
    assert response.json()["code"] == "workflow_validation_error"
    missing = owner.get("/api/workflows/missing/preflight")
    assert missing.status_code == 422
    assert missing.json()["code"] == "workflow_validation_error"


def test_historical_provider_failure_is_visible_without_replaying_activity(
    owner: Client, served: RelayProject, engine: InlineEngine
) -> None:
    served.write_workflow(
        "limited",
        "version: 1\nname: Limited\nnodes:\n  review: {type: command, run: [git, status]}\n",
    )
    run_id = engine.launch(served, "limited")
    attempt = engine.store.claim_dispatch(engine.tokens.popleft(), engine.worker_id).attempt
    assert attempt is not None
    for text in ("You've hit your session limit · ", "resets 1:50pm (UTC)"):
        engine.store.append_attempt_event(
            attempt.attempt_id,
            "agent.message",
            EventSource.AGENT,
            {"text": text, "message_id": "quota", "turn": 1},
        )
    engine.store.append_attempt_event(
        attempt.attempt_id,
        "agent.thought",
        EventSource.AGENT,
        {"text": "private reasoning"},
        sensitivity=EventSensitivity.REDACTED,
    )
    engine.store.append_attempt_event(
        attempt.attempt_id,
        "agent.provider_event",
        EventSource.AGENT,
        {"update": {"used": 325347, "size": 1000000, "sessionUpdate": "usage_update"}},
    )
    engine.store.append_attempt_event(
        attempt.attempt_id,
        "agent.message",
        EventSource.AGENT,
        {"text": "redacted text"},
        sensitivity=EventSensitivity.REDACTED,
    )
    engine.store.append_attempt_event(
        attempt.attempt_id,
        "agent.tool_result",
        EventSource.AGENT,
        {"summary": "A quoted example of another provider limit."},
    )
    engine.store.finish_attempt(
        attempt.attempt_id,
        ExecutionOutcome(
            OutcomeKind.FAILED,
            stop_reason=AttemptStopReason.FAILED,
            error_code="agent_protocol_error",
        ),
        attempt.starting_head,
    )
    # Old attempts have no stored failure summary; the detail read still finds
    # their own public message, even on a node page that excludes the failed node.
    assert Run.objects.get(pk=run_id).failure_summary is None
    detail = owner.get(f"/api/runs/{run_id}?since={DATABASE_INTEGER_MAX}").json()["run"]
    assert detail["nodes"] == []
    assert detail["problem"]["scope_path"] == "root.review"
    assert detail["problem"]["provider_message"] == (
        "You've hit your session limit · resets 1:50pm (UTC)"
    )
    assert detail["problem"]["provider_message_truncated"] is False
    assert detail["problem"]["error_code"] == "agent_protocol_error"
    # A new retry cannot keep showing the old quota as a current problem.
    response = post(
        owner,
        f"/api/runs/{run_id}/rerun-node",
        {"scope_path": "root.review", "idempotency_key": "retry-limited"},
    )
    assert response.status_code == 202
    assert owner.get(f"/api/runs/{run_id}").json()["run"]["problem"] is None


@pytest.mark.parametrize(
    ("chunks", "expected", "truncated"),
    [
        ([{"text": "older"}, {"text": "newer"}], "newer", False),
        (
            [
                {"text": "old turn", "message_id": "same", "turn": 1},
                {"text": "current turn", "message_id": "same", "turn": 2},
            ],
            "current turn",
            False,
        ),
        (
            [{"text": "x" * (RUN_PROBLEM_TEXT_MAX_CHARS + 1), "message_id": "long"}],
            "x" * RUN_PROBLEM_TEXT_MAX_CHARS,
            True,
        ),
        (
            [{"text": "x", "message_id": "many"}] * (RUN_PROBLEM_MESSAGE_MAX_EVENTS + 1),
            "x" * RUN_PROBLEM_MESSAGE_MAX_EVENTS,
            True,
        ),
    ],
    ids=["unidentified-message", "new-turn", "text-limit", "fragment-limit"],
)
def test_provider_failure_notice_bounds_and_message_identity(
    owner: Client,
    served: RelayProject,
    engine: InlineEngine,
    chunks: list[dict[str, str | int]],
    expected: str,
    truncated: bool,
) -> None:
    served.write_workflow(
        "bounded",
        "version: 1\nname: Bounded\nnodes:\n  work: {type: command, run: [git, status]}\n",
    )
    run_id = engine.launch(served, "bounded")
    attempt = engine.store.claim_dispatch(engine.tokens.popleft(), engine.worker_id).attempt
    assert attempt is not None
    for payload in chunks:
        engine.store.append_attempt_event(
            attempt.attempt_id, "agent.message", EventSource.AGENT, payload
        )
    engine.store.finish_attempt(
        attempt.attempt_id,
        ExecutionOutcome(OutcomeKind.FAILED, error_code="agent_protocol_error"),
        attempt.starting_head,
    )
    problem = owner.get(f"/api/runs/{run_id}").json()["run"]["problem"]
    assert (problem["provider_message"], problem["provider_message_truncated"]) == (
        expected,
        truncated,
    )


def test_command_failure_detail_reports_its_exit_code(
    owner: Client, served: RelayProject, engine: InlineEngine
) -> None:
    served.write_workflow(
        "command-failure",
        "version: 1\nname: Failed command\nnodes:\n"
        "  check: {type: command, run: [git, unknown-command]}\n",
    )
    run_id = engine.launch(served, "command-failure")
    engine.drain(run_id)
    problem = owner.get(f"/api/runs/{run_id}").json()["run"]["problem"]
    assert problem["scope_path"] == "root.check"
    assert problem["exit_code"] == 1
    assert problem["provider_message"] is None


@pytest.mark.usefixtures("served", "database_threads")
def test_model_menu_discovers_one_tool_without_starting_a_run(
    owner: Client, fake_agents: FakeAgents
) -> None:
    fake_agents.install("codex")
    response = post(owner, "/api/agents/codex/models", {})
    assert response.status_code == 200
    assert response.json()["models"] == [
        {"value": "m1", "name": "Model One"},
        {"value": "m2", "name": "Model Two"},
    ]
    assert not Run.objects.exists()
    assert not any(message.get("method") == "session/prompt" for message in fake_agents.messages())


def test_workflow_creation_in_the_selected_project_never_replaces_an_existing_file(
    owner: Client,
    served: RelayProject,
    tmp_path: Path,
) -> None:
    from tests.support import create_project

    other = create_project(tmp_path / "other")
    path = f"/api/workflows?project={other.project_id}"
    body = {"key": "nested/review", "holder": "creator"}
    response = post(owner, path, body)
    assert response.status_code == 201
    saved = other.relay_root / "workflows" / "nested" / "review.yaml"
    original = saved.read_bytes()
    assert not (served.relay_root / "workflows" / "nested" / "review.yaml").exists()
    assert post(owner, path, body).status_code == 409
    assert saved.read_bytes() == original
    inventory = owner.get(f"/api/workflows?project={other.project_id}").json()
    assert inventory["project"]["id"] == other.project_id
    assert any(item["key"] == "nested/review.yaml" for item in inventory["workflows"])


@pytest.mark.parametrize("key", ["../escape", "nested\\escape", "/escape", "NUL", "a:b", "COM¹"])
def test_creating_a_workflow_rejects_paths_outside_its_project(
    owner: Client,
    served: RelayProject,
    key: str,
) -> None:
    response = post(owner, "/api/workflows", {"key": key, "holder": "creator"})
    assert response.status_code == 422
    assert not (served.repository.parent / "escape.yaml").exists()


@pytest.mark.usefixtures("served")
def test_launch_rejects_a_workflow_bound_to_another_selected_project(owner: Client) -> None:
    response = post(
        owner,
        "/api/runs",
        {
            "workflow_key": "workflow",
            "inputs": {},
            "project_id": "different-project",
        },
    )
    assert (response.status_code, response.json()["code"]) == (400, "config_error")
    assert not Run.objects.exists()


def test_run_connections_use_captured_definitions_after_the_workflow_changes(
    owner: Client,
    served: RelayProject,
    engine: InlineEngine,
) -> None:
    served.write_workflow(
        "connected",
        "version: 1\nname: Connected\nnodes:\n"
        "  first: {type: human_wait, prompt: Review, deadline: 1h, on_timeout: end}\n"
        "  end: {type: command, needs: [first], run: [git, status]}\n",
    )
    run_id = engine.launch(served, "connected")
    served.write_workflow("connected", "version: 1\nname: Changed\nnodes: {}\n")
    detail = owner.get(f"/api/runs/{run_id}").json()["run"]
    nodes = {node["node_id"]: node for node in detail["nodes"]}
    assert nodes["end"]["dependencies"] == ["root.first"]
    assert nodes["first"]["controls"] == [{"target": "root.end", "label": "Time limit"}]
    assert detail["project"]["id"] == served.project_id


def test_boolean_handoffs_warn_without_changing_the_workflow(
    owner: Client,
    served: RelayProject,
) -> None:
    text = (
        "version: 1\nname: Report\nnodes:\n"
        "  report: {type: command, run: [git, status], outputs: {ready: {exists: REVIEW.md}}}\n"
    )
    served.write_workflow("report", text)
    response = owner.get("/api/workflows/report").json()
    assert response["warnings"][0]["artifact"] == "REVIEW.md"
    assert response["yaml"] == text


def test_child_workflow_report_warnings_keep_the_source_workflow_key(
    owner: Client, served: RelayProject
) -> None:
    served.write_workflow(
        "child",
        "version: 1\nname: Child\nnodes:\n"
        "  report: {type: command, run: [git, status], outputs: {ready: {exists: REVIEW.md}}}\n",
    )
    served.write_workflow(
        "parent",
        "version: 1\nname: Parent\nnodes:\n  child: {type: subworkflow, workflow: child}\n",
    )
    assert owner.get("/api/workflows/parent").json()["warnings"][0]["workflow_key"] == "child.yaml"


def test_pending_interaction_reads_and_target_links_do_not_return_old_answers(
    owner: Client, waiting_run: tuple[str, int]
) -> None:
    run_id, _attempt_id = waiting_run
    interaction = HumanInteraction.objects.get(run_id=run_id)
    path = f"/api/runs/{run_id}?collection=interactions"
    assert len(owner.get(f"{path}&pending=true").json()["run"]["interactions"]) == 1
    HumanInteraction.objects.filter(pk=interaction.pk).update(status="answered")
    assert owner.get(f"{path}&pending=true").json()["run"]["interactions"] == []
    rows = owner.get(f"{path}&interaction={interaction.pk}").json()["run"]["interactions"]
    assert rows[0]["status"] == "answered"


def test_run_detail_keeps_a_state_cursor_separate_from_replayed_output(
    owner: Client, waiting_run: tuple[str, int]
) -> None:
    run_id, _attempt_id = waiting_run
    detail = owner.get(f"/api/runs/{run_id}").json()["run"]
    events = owner.get(f"/api/runs/{run_id}/events?limit=200").json()["events"]
    assert detail["event_cursor"] == max(event["id"] for event in events)
    assert detail["status"] == "paused_wait"
    assert detail["nodes"][0]["status"] == "waiting"


def test_run_status_and_replay_cursor_agree_when_a_retry_commits_during_the_read(
    owner: Client, waiting_run: tuple[str, int]
) -> None:
    run_id, _attempt_id = waiting_run
    advanced = False

    def commit_retry_before_read(
        execute: Callable[..., object],
        sql: str,
        params: object,
        many: bool,
        context: dict[str, object],
    ) -> object:
        nonlocal advanced
        if not advanced and sql.startswith("SELECT") and f'FROM "{Run._meta.db_table}"' in sql:
            advanced = True
            # A worker finishes and retries before the run row is read. Its old
            # terminal event must already be covered by the returned cursor.
            with transaction.atomic():
                RunEvent.objects.create(
                    run_id=run_id, type="run.failed", source="run", payload={"status": "failed"}
                )
                Run.objects.filter(pk=run_id).update(status="running")
                RunEvent.objects.create(
                    run_id=run_id, type="run.resumed", source="run", payload={"status": "running"}
                )
        return execute(sql, params, many, context)

    with connection.execute_wrapper(commit_retry_before_read):
        detail = owner.get(f"/api/runs/{run_id}").json()["run"]

    assert advanced
    assert detail["status"] == "running"
    assert detail["event_cursor"] == RunEvent.objects.filter(run_id=run_id).latest("id").pk


def test_stale_interaction_answer_cannot_answer_the_current_review(
    owner: Client, waiting_run: tuple[str, int]
) -> None:
    _run_id, attempt_id = waiting_run
    response = post(
        owner,
        f"/api/attempts/{attempt_id}/wait",
        {"idempotency_key": "wrong-request", "interaction_id": "999999", "value": "yes"},
    )
    assert response.status_code == 422
    assert HumanInteraction.objects.get(attempt_id=attempt_id).status == "pending"


def test_review_previews_are_bounded_and_leave_original_artifacts_downloadable(
    owner: Client, finished_run: str
) -> None:
    artifact = Artifact.objects.filter(attempt__node_run__run_id=finished_run).first()
    assert artifact is not None
    retained, _name, _media = DjangoReadStore().artifact_file(str(artifact.pk))
    assert owner.get(f"/api/artifacts/{artifact.pk}/preview").json()["text"] == retained.read_text()
    changes = owner.get(f"/api/runs/{finished_run}/changes").json()
    assert changes["text"] == "" and changes["truncated"] is False


def test_temporary_cleanup_refuses_active_runs_and_keeps_unmarked_files(
    owner: Client, finished_run: str, waiting_run: tuple[str, int]
) -> None:
    from relay.execution.resources import allocate_attempt_resources
    from relay.web.models import NodeAttempt

    attempt_id = str(NodeAttempt.objects.get(node_run__run_id=finished_run).pk)
    resource = allocate_attempt_resources(finished_run, attempt_id)
    unrelated = resource.directory.parent / "personal-note.txt"
    unrelated.write_text("Keep", encoding="utf-8")
    assert (
        post(owner, f"/api/runs/{waiting_run[0]}/resources/clean", {"confirm": True}).status_code
        == 409
    )
    response = post(owner, f"/api/runs/{finished_run}/resources/clean", {"confirm": True})
    assert response.status_code == 200 and response.json()["removed"] == 1
    assert unrelated.read_text(encoding="utf-8") == "Keep"


def test_instruction_editor_keeps_project_paths_and_rejects_stale_saves(
    owner: Client, served: RelayProject, workflow_base: str
) -> None:
    del workflow_base
    url = "/api/workflows/workflow/prompt"
    body = {
        "holder": "tab-1",
        "reference": "prompts/ui/check.md",
        "text": "Review the API.\n",
        "base_hash": None,
    }
    response = post(owner, url, body)
    assert response.status_code == 200
    assert (served.relay_root / "prompts/ui/check.md").read_text() == body["text"]
    loaded = owner.get(f"{url}?reference=prompts/ui/check.md").json()
    assert loaded["text"] == body["text"]
    assert post(owner, url, {**body, "text": "Overwrite."}).status_code == 409
    assert (
        post(
            owner, url, {**body, "text": "Inspect callers.\n", "base_hash": loaded["base_hash"]}
        ).status_code
        == 200
    )
    assert post(owner, url, {**body, "reference": "../../outside.md"}).status_code == 400
    assert not (served.repository.parent / "outside.md").exists()


def test_a_workflow_named_create_can_still_be_opened(owner: Client, served: RelayProject) -> None:
    served.write_workflow("create", "version: 1\nname: Create\nnodes: {}\n")
    assert owner.get("/api/workflows/create").status_code == 200


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

    assert response.json() == {
        "owner_created": False,
        "authenticated": False,
        "username": None,
        "login_required": True,
        "password_rules": [
            "Your password can\u2019t be too similar to your other personal information.",
            "Your password must contain at least 8 characters.",
            "Your password can\u2019t be a commonly used password.",
            "Your password can\u2019t be entirely numeric.",
        ],
    }
    assert "relay_csrftoken" in client.cookies


@override_settings(
    AUTH_PASSWORD_VALIDATORS=[
        {
            "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
            "OPTIONS": {"min_length": 12},
        }
    ]
)
def test_onboarding_rules_follow_the_configured_password_policy(client: Client) -> None:
    assert client.get("/api/auth").json()["password_rules"] == [
        "Your password must contain at least 12 characters."
    ]


def test_created_accounts_do_not_show_onboarding_password_rules(owner: Client) -> None:
    assert owner.get("/api/auth").json()["password_rules"] == []


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


@override_settings(RELAY_LOGIN_REQUIRED=False)
def test_disabled_login_opens_projects_without_creating_an_owner(client: Client) -> None:
    response = client.get("/api/auth")

    assert response.json() == {
        "owner_created": False,
        "authenticated": True,
        "username": "local",
        "login_required": False,
        "password_rules": [
            "Your password can\u2019t be too similar to your other personal information.",
            "Your password must contain at least 8 characters.",
            "Your password can\u2019t be a commonly used password.",
            "Your password can\u2019t be entirely numeric.",
        ],
    }
    assert "relay_csrftoken" in client.cookies
    assert "relay_sessionid" not in client.cookies
    assert client.get("/api/projects").status_code == 200
    assert not User.objects.exists()


@override_settings(RELAY_LOGIN_REQUIRED=False, ALLOWED_HOSTS=["127.0.0.1", "localhost", "[::1]"])
def test_disabled_login_still_rejects_untrusted_hosts(client: Client) -> None:
    assert client.get("/api/projects", HTTP_HOST="other.example").status_code == 400


@override_settings(RELAY_LOGIN_REQUIRED=False)
def test_disabled_login_records_the_local_launcher(served: RelayProject) -> None:
    served.write_workflow(
        "local", "version: 1\nname: Local\nnodes:\n  a: {type: command, run: [git, status]}\n"
    )
    served.commit("Save the local command workflow")
    client = Client(enforce_csrf_checks=True)
    client.get("/api/auth")
    response = client.post(
        "/api/runs",
        data=json.dumps({"workflow_key": "local", "inputs": {}}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=client.cookies["relay_csrftoken"].value,
    )

    assert response.status_code == 201, response.json()
    run = Run.objects.get(pk=response.json()["run_id"])
    assert run.launcher == "local"
    assert not User.objects.exists()


@override_settings(RELAY_LOGIN_REQUIRED=False)
@pytest.mark.parametrize("cross_origin", [False, True])
def test_disabled_login_still_rejects_unsafe_browser_posts(cross_origin: bool) -> None:
    client = Client(enforce_csrf_checks=True)
    client.get("/api/auth")
    headers = (
        {
            "HTTP_X_CSRFTOKEN": client.cookies["relay_csrftoken"].value,
            "HTTP_ORIGIN": "https://other.example",
        }
        if cross_origin
        else {}
    )
    response = client.post(
        "/api/auth/logout", data="{}", content_type="application/json", **headers
    )

    assert (response.status_code, response.json()["code"]) == (403, "csrf_failed")


def test_reenabling_login_preserves_the_existing_owner_and_requires_a_session(
    owner: Client,
) -> None:
    password_hash = User.objects.get(username="owner").password
    browser = Client()
    with override_settings(RELAY_LOGIN_REQUIRED=False):
        assert browser.get("/api/projects").status_code == 200
        assert post(browser, "/api/auth/logout", {}).json() == {"authenticated": True}

    assert browser.get("/api/projects").status_code == 401
    assert owner.get("/api/projects").status_code == 200
    assert User.objects.get(username="owner").password == password_hash


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


def test_project_context_adds_fresh_launch_source_for_the_selected_project(
    owner: Client, served: RelayProject, tmp_path: Path
) -> None:
    other = create_project(tmp_path / "other")
    git(other.repository, "branch", "-m", "other/source")
    source = owner.get(f"/api/projects/current?project={other.project_id}")
    assert source.status_code == 200
    assert source.json()["project"]["id"] == other.project_id
    assert source.json()["launch_source"] == {
        "branch": "other/source",
        "commit": git(other.repository, "rev-parse", "HEAD"),
    }
    git(other.repository, "checkout", "--detach", "HEAD")
    assert (
        owner.get(f"/api/projects/current?project={other.project_id}").json()["launch_source"][
            "branch"
        ]
        is None
    )
    assert owner.get("/api/projects/current").json()["project"]["id"] == served.project_id


def test_project_context_launch_source_requires_owner_login(client: Client) -> None:
    assert client.get("/api/projects/current").status_code == 401


@pytest.mark.parametrize("status", ["succeeded", "failed", "canceled"])
def test_previous_run_inputs_returns_only_the_launch_choices(
    owner: Client, finished_run: str, status: str
) -> None:
    Run.objects.filter(pk=finished_run).update(status=status)
    inputs = {"task": "Owner choice", "count": 0, "ratio": 0.5, "approved": False, "empty": None}
    RunSnapshot.objects.filter(run_id=finished_run).update(
        typed_inputs=inputs, resolved_prompts=[{"private": "captured instructions"}]
    )
    run = Run.objects.get(pk=finished_run)
    response = owner.get(f"/api/runs/{finished_run}/launch-inputs")
    assert response.status_code == 200
    assert response.json() == {
        "project_id": str(run.project_id),
        "workflow_key": "done.yaml",
        "status": status,
        "inputs": inputs,
    }
    assert RunSnapshot.objects.get(run_id=finished_run).typed_inputs == inputs


@pytest.mark.parametrize(
    "status", ["pending", "running", "paused_wait", "canceling", "interrupted"]
)
def test_previous_run_inputs_rejects_a_run_that_has_not_finished(
    owner: Client, finished_run: str, status: str
) -> None:
    Run.objects.filter(pk=finished_run).update(status=status)
    response = owner.get(f"/api/runs/{finished_run}/launch-inputs")
    assert (response.status_code, response.json()["code"]) == (400, "config_error")
    assert "Wait for this run to finish" in response.json()["message"]


def test_previous_run_inputs_keeps_authentication_bounds_and_missing_run_errors(
    client: Client, owner: Client, finished_run: str
) -> None:
    unauthenticated = Client()
    assert unauthenticated.get(f"/api/runs/{finished_run}/launch-inputs").status_code == 401
    assert owner.get("/api/runs/not-a-uuid/launch-inputs").status_code == 404
    assert (
        owner.get("/api/runs/00000000-0000-0000-0000-000000000000/launch-inputs").status_code == 404
    )
    RunSnapshot.objects.filter(run_id=finished_run).update(typed_inputs={"task": "x" * 1_048_576})
    assert client.get(f"/api/runs/{finished_run}/launch-inputs").status_code == 400


def test_previous_run_inputs_database_errors_keep_the_public_envelope(
    owner: Client, finished_run: str
) -> None:
    def unavailable(
        execute: Callable[..., object], sql: str, params: object, many: bool, context: object
    ) -> object:
        if Run._meta.db_table in sql:
            message = "private third-party failure"
            raise DatabaseError(message)
        return execute(sql, params, many, context)

    with connection.execute_wrapper(unavailable):
        response = owner.get(f"/api/runs/{finished_run}/launch-inputs")
    assert (response.status_code, response.json()["code"]) == (503, "persistence_error")
    assert "private third-party" not in response.content.decode()


def test_previous_run_inputs_missing_snapshot_keeps_the_public_envelope(
    owner: Client, finished_run: str
) -> None:
    RunSnapshot.objects.filter(run_id=finished_run).delete()
    response = owner.get(f"/api/runs/{finished_run}/launch-inputs")
    assert (response.status_code, response.json()["code"]) == (503, "persistence_error")


def test_previous_inputs_launch_through_fresh_source_capture(
    owner: Client, served: RelayProject, engine: InlineEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(actions, "_enqueue_claim", engine.tokens.append)
    source = (
        "version: 1\nname: Previous\ninputs:\n  task: {type: string, default: Original}\n"
        "nodes:\n  check: {type: command, run: [git, status]}\n"
    )
    served.write_workflow("repeat", source)
    previous = engine.launch(served, "repeat", inputs={"task": "Owner choice"})
    engine.drain(previous)
    old_snapshot = RunSnapshot.objects.get(run_id=previous).workflow_yaml
    choices = owner.get(f"/api/runs/{previous}/launch-inputs").json()
    served.write_workflow("repeat", source.replace("Previous", "Current"))
    served.commit("Commit the current workflow")
    result = post(owner, "/api/runs", choices)
    assert result.status_code == 201
    current = result.json()["run_id"]
    assert current != previous
    assert Run.objects.get(pk=current).source_commit == git(served.repository, "rev-parse", "HEAD")
    assert RunSnapshot.objects.get(run_id=current).typed_inputs == {"task": "Owner choice"}
    assert RunSnapshot.objects.get(run_id=current).workflow_yaml != old_snapshot
    assert RunSnapshot.objects.get(run_id=previous).workflow_yaml == old_snapshot


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


def test_selected_worktree_cleanup_preserves_other_runs_and_retained_evidence(
    owner: Client, finished_run: str, served: RelayProject, engine: InlineEngine
) -> None:
    other_id = engine.launch(served, "done")
    engine.drain(other_id)
    other_before = owner.get(f"/api/runs/{other_id}").json()
    artifacts_before = owner.get(f"/api/runs/{finished_run}/artifacts").json()
    checkout = Path(Run.objects.get(pk=finished_run).worktree_path)
    other_checkout = Path(Run.objects.get(pk=other_id).worktree_path)

    response = post(
        owner,
        "/api/data/clean",
        {"scope": "worktrees", "run_id": finished_run, "confirm": True},
    )

    assert response.status_code == 200
    assert response.json()["deleted"]["worktrees"] == 1
    assert not checkout.exists()
    assert other_checkout.exists()
    assert owner.get(f"/api/runs/{other_id}").json() == other_before
    assert owner.get(f"/api/runs/{finished_run}/artifacts").json() == artifacts_before
    assert Run.objects.get(pk=finished_run).worktree_state == "removed"
    assert RunEvent.objects.get(run_id=finished_run, type="run.cleanup_succeeded").payload == {
        "worktree_state": "removed"
    }


def test_selected_all_cleanup_preserves_other_runs_and_shared_logs(
    owner: Client,
    finished_run: str,
    served: RelayProject,
    engine: InlineEngine,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    other_id = engine.launch(served, "done")
    engine.drain(other_id)
    other_before = owner.get(f"/api/runs/{other_id}").json()
    log = tmp_path / "shared.log"
    log_bytes = f"{APPLICATION_LOG_OWNERSHIP_LINE}\nRetained diagnostics\n".encode()
    log.write_bytes(log_bytes)
    monkeypatch.setenv("RELAY_LOG_PATH", str(log))

    response = post(
        owner, "/api/data/clean", {"scope": "all", "run_id": finished_run, "confirm": True}
    )

    assert response.status_code == 200
    assert response.json()["deleted"]["runs"] == 1
    assert response.json()["deleted"]["logs"] == 0
    assert owner.get(f"/api/runs/{finished_run}").status_code == 404
    assert owner.get(f"/api/runs/{other_id}").json() == other_before
    assert Path(Run.objects.get(pk=other_id).worktree_path).exists()
    assert log.read_bytes() == log_bytes


@pytest.mark.parametrize(
    "selector", [None, "", 7, "not-a-run", "00000000-0000-0000-0000-000000000000"]
)
def test_invalid_cleanup_selection_never_deletes_the_project(
    owner: Client, finished_run: str, selector: object
) -> None:
    before = owner.get(f"/api/runs/{finished_run}").json()

    response = post(owner, "/api/data/clean", {"scope": "all", "run_id": selector, "confirm": True})

    assert response.status_code in {400, 404}
    assert owner.get(f"/api/runs/{finished_run}").json() == before
    assert Path(Run.objects.get(pk=finished_run).worktree_path).exists()


def test_cleanup_rejects_a_run_from_another_project(
    owner: Client, finished_run: str, engine: InlineEngine, tmp_path: Path
) -> None:
    other_project = create_project(tmp_path / "other-project")
    other_project.write_workflow(
        "done", "version: 1\nname: Done\nnodes:\n  a: {type: command, run: [git, status]}\n"
    )
    other_id = engine.launch(other_project, "done")
    engine.drain(other_id)

    response = post(owner, "/api/data/clean", {"scope": "all", "run_id": other_id, "confirm": True})

    assert (response.status_code, response.json()["code"]) == (404, "project_discovery_error")
    assert Path(Run.objects.get(pk=finished_run).worktree_path).exists()
    assert Path(Run.objects.get(pk=other_id).worktree_path).exists()


def test_selected_worktree_cleanup_waits_for_evidence_preservation(
    owner: Client, finished_run: str
) -> None:
    Artifact.objects.filter(attempt__node_run__run_id=finished_run).update(
        preservation_state="pending"
    )

    response = post(
        owner,
        "/api/data/clean",
        {"scope": "worktrees", "run_id": finished_run, "confirm": True},
    )

    assert (response.status_code, response.json()["code"]) == (503, "persistence_error")
    assert Run.objects.get(pk=finished_run).worktree_state == "created"
    assert Path(Run.objects.get(pk=finished_run).worktree_path).exists()


def test_selected_cleanup_cannot_remove_a_workspace_during_recovery(
    owner: Client, finished_run: str
) -> None:
    with recovery_workspace_lock(finished_run):
        response = post(
            owner,
            "/api/data/clean",
            {"scope": "worktrees", "run_id": finished_run, "confirm": True},
        )

    assert (response.status_code, response.json()["code"]) == (503, "persistence_error")
    assert Path(Run.objects.get(pk=finished_run).worktree_path).exists()


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


@pytest.mark.usefixtures("registry_network", "database_threads")
@pytest.mark.parametrize(
    "mode,ready,code",
    [
        ("success", True, None),
        ("auth", False, "agent_auth_error"),
        ("no-selector", False, "model_selector_error"),
    ],
)
def test_readiness_preserves_structured_probe_results(
    owner: Client,
    served: RelayProject,
    fake_agents: FakeAgents,
    mode: str,
    ready: bool,
    code: str | None,
) -> None:
    del served
    fake_agents.install("codex", mode=mode)
    response = post(owner, "/api/agents/check", {})
    assert response.status_code == 200
    rows = {row["id"]: row for row in response.json()["agents"]}
    assert rows["codex"]["installed"] is True
    assert rows["codex"]["ready"] is ready
    assert rows["codex"]["error_code"] == code
    assert rows["codex"]["login_command"] == "codex login"
    assert rows["cursor"]["installed"] is False
    assert rows["cursor"]["ready"] is False
    assert not any(message.get("method") == "session/prompt" for message in fake_agents.messages())
    assert not any(message.get("method") == "authenticate" for message in fake_agents.messages())


@pytest.mark.usefixtures("registry_network")
def test_readiness_with_no_agents_is_an_actionable_inventory(
    owner: Client,
    served: RelayProject,
    fake_agents: FakeAgents,
) -> None:
    del served, fake_agents
    response = post(owner, "/api/agents/check", {})
    assert response.status_code == 200
    rows = response.json()["agents"]
    assert len(rows) == 5
    assert all(not row["ready"] and not row["installed"] for row in rows)
    assert all(row["install_url"].startswith("https://") for row in rows)


@pytest.mark.usefixtures("registry_network", "database_threads")
def test_readiness_checks_all_five_supported_transports(
    owner: Client,
    served: RelayProject,
    fake_agents: FakeAgents,
) -> None:
    del served
    for agent_id in ("codex", "claude", "copilot", "cursor", "antigravity"):
        fake_agents.install(agent_id, mode="configuration")
    response = post(owner, "/api/agents/check", {})
    assert response.status_code == 200
    assert all(row["ready"] for row in response.json()["agents"])
    assert not any(message.get("method") == "session/prompt" for message in fake_agents.messages())


def test_readiness_is_owner_only_and_post_only(owner: Client, served: RelayProject) -> None:
    del served
    assert Client().post("/api/agents/check", content_type="application/json").status_code == 401
    assert owner.get("/api/agents/check").status_code == 405


def test_readiness_keeps_csrf_in_no_login_mode(served: RelayProject) -> None:
    from django.test import override_settings

    del served
    with override_settings(RELAY_LOGIN_REQUIRED=False):
        response = Client(enforce_csrf_checks=True).post(
            "/api/agents/check", data="{}", content_type="application/json"
        )
    assert response.status_code == 403
    assert response.json()["code"] == "csrf_failed"


def test_template_gallery_is_owner_only_and_copies_a_real_bundle(
    owner: Client,
    served: RelayProject,
) -> None:
    from relay.workflows.starters import STARTER_ROOT

    assert Client().get("/api/workflow-templates").status_code == 401
    gallery = owner.get("/api/workflow-templates")
    assert gallery.status_code == 200
    assert len(gallery.json()["templates"]) == 6
    created = post(
        owner,
        "/api/workflows",
        {
            "key": "starter",
            "holder": "template-tab",
            "template_id": "ask-agent",
        },
    )
    assert created.status_code == 201
    assert created.json()["yaml"].encode("utf-8") == (STARTER_ROOT / "ask-agent.yaml").read_bytes()
    assert (served.relay_root / "prompts" / "ask-agent.md").read_bytes() == (
        STARTER_ROOT / "ask-agent.md"
    ).read_bytes()


@pytest.mark.parametrize("extra", [{"yaml": "nodes: {}"}, {"template_id": "unknown"}])
def test_invalid_template_requests_write_no_sources(
    owner: Client,
    served: RelayProject,
    extra: dict[str, object],
) -> None:
    created = post(
        owner,
        "/api/workflows",
        {
            "key": "starter",
            "holder": "template-tab",
            "template_id": "ask-agent",
            **extra,
        },
    )
    assert created.status_code in {400, 422}
    assert not (served.relay_root / "workflows" / "starter.yaml").exists()
    assert not (served.relay_root / "prompts" / "ask-agent.md").exists()


def test_job_history_filters_tail_events_and_keeps_attempts_separate(
    owner: Client, served: RelayProject, engine: InlineEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(actions, "_enqueue_claim", engine.tokens.append)
    served.write_workflow(
        "jobs", "version: 1\nname: Jobs\nnodes:\n  check: {type: command, run: [git, status]}\n"
    )
    run_id = engine.launch(served, "jobs")
    first = engine.store.claim_dispatch(engine.tokens.popleft(), engine.worker_id).attempt
    assert first is not None
    for index in range(205):
        engine.store.append_attempt_event(
            first.attempt_id, "command.stdout", EventSource.COMMAND, {"chunk": f"line {index}\n"}
        )
    engine.store.append_attempt_event(
        first.attempt_id, "command.stderr", EventSource.COMMAND, {"chunk": "Last error\n"}
    )
    engine.store.finish_attempt(
        first.attempt_id,
        ExecutionOutcome(OutcomeKind.FAILED, error_message="First failure", exit_code=3),
        first.starting_head,
    )
    retry = post(
        owner,
        f"/api/runs/{run_id}/rerun-node",
        {"scope_path": "root.check", "idempotency_key": "second-job-attempt"},
    )
    assert retry.status_code == 202
    second = engine.store.claim_dispatch(engine.tokens.popleft(), engine.worker_id).attempt
    assert second is not None
    engine.store.append_attempt_event(
        second.attempt_id, "command.stderr", EventSource.COMMAND, {"chunk": "Second error\n"}
    )
    engine.store.finish_attempt(
        second.attempt_id,
        ExecutionOutcome(OutcomeKind.FAILED, error_message="Second failure", exit_code=4),
        second.starting_head,
    )
    path = f"/api/runs/{run_id}"
    first_page = owner.get(f"{path}/job?job=root.check&limit=1").json()
    assert first_page["job"]["attempts"][0]["number"] == 1
    assert first_page["job"]["latest_attempt"]["number"] == 2
    assert first_page["job"]["latest_attempt"]["error_message"] == "Second failure"
    assert first_page["job"]["latest_attempt"]["exit_code"] == 4
    assert "worker_id" not in first_page["job"]["latest_attempt"]
    next_page = owner.get(f"{path}/job?job=root.check&limit=1&since={first_page['next']}").json()
    assert next_page["job"]["attempts"][0]["number"] == 2
    assert next_page["next"] is None
    tail = owner.get(f"{path}/events?job=root.check&attempt=1&latest=true&limit=3").json()
    assert any(event["payload"].get("chunk") == "Last error\n" for event in tail["events"])
    ids = [event["id"] for event in tail["events"]]
    assert ids == sorted(ids)
    older = owner.get(
        f"{path}/events?job=root.check&attempt=1&latest=true&limit=3&before={tail['next']}"
    ).json()
    assert all(event["id"] < ids[0] for event in older["events"])
    assert all(event["payload"]["attempt_number"] == 1 for event in older["events"])
    current = owner.get(f"{path}/events?job=root.check&attempt=2").json()
    assert all(event["payload"].get("attempt_number", 2) == 2 for event in current["events"])
    assert any(event["payload"].get("chunk") == "Second error\n" for event in current["events"])
    assert "Last error" not in json.dumps(current)
    summary = owner.get(path).json()["run"]["nodes"][0]
    assert summary["started_at"] and summary["ended_at"]


def test_job_instructions_are_read_from_the_snapshot_after_the_source_changes(
    owner: Client, served: RelayProject, engine: InlineEngine, fake_agents: FakeAgents
) -> None:
    fake_agents.install("codex", mode="configuration")
    served.write(".relay/prompts/owner.md", "Frozen owner instructions\n")
    served.write_workflow(
        "instructions",
        "version: 1\nname: Instructions\nmodel: m1\nagents: [codex]\nnodes:\n"
        "  work: {type: agent, prompts: [{local: prompts/owner.md}]}\n",
    )
    run_id = engine.launch(served, "instructions")
    served.write(".relay/prompts/owner.md", "Edited after launch\n")
    response = owner.get(f"/api/runs/{run_id}/job?job=root.work").json()["job"]
    assert response["instructions"] == [
        {
            "reference": {"local": "prompts/owner.md"},
            "text": "Frozen owner instructions\n",
            "truncated": False,
        }
    ]
    assert response["latest_attempt"] is None
    assert response["command"] is None
    assert response["outputs"] == {}


def test_failed_job_settings_match_the_existing_run_record(
    owner: Client, served: RelayProject, engine: InlineEngine, fake_agents: FakeAgents
) -> None:
    fake_agents.install("codex", mode="configuration")
    served.write_workflow(
        "failed-settings",
        "version: 1\nname: Failed settings\nmodel: m1\nagents: [codex]\nnodes:\n"
        "  work:\n    type: agent\n    outputs:\n"
        "      verdict: {json_path: {artifact: missing.json, path: verdict}}\n",
    )
    run_id = engine.launch(served, "failed-settings")
    engine.drain(run_id)
    assert run_status(run_id) == "failed"
    detail = owner.get(f"/api/runs/{run_id}").json()["run"]
    job = owner.get(f"/api/runs/{run_id}/job?job=root.work").json()["job"]
    assert job["working_folder"] == Run.objects.get(pk=run_id).worktree_path
    assert detail["working_folder"] == job["working_folder"]
    assert job["retry_settings"] == detail["nodes"][0]["retry_settings"]
    assert job["retry_settings"]["agent_id"] == "codex"
    assert job["retry_settings"]["model_value"] == "m1"


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("", 400),
        ("?job=../outside", 422),
        ("?job=root.missing", 404),
        ("?job=root.check&limit=0", 400),
        ("?job=root.check&since=-1", 400),
    ],
)
def test_job_reads_reject_missing_or_invalid_targets(
    owner: Client, served: RelayProject, engine: InlineEngine, query: str, expected: int
) -> None:
    served.write_workflow(
        "job", "version: 1\nname: Job\nnodes:\n  check: {type: command, run: [git, status]}\n"
    )
    run_id = engine.launch(served, "job")
    assert owner.get(f"/api/runs/{run_id}/job{query}").status_code == expected


@pytest.mark.parametrize(
    "path",
    [
        "job?job=root.check",
        "events?attempt=0",
        "events?attempt=-1",
        "events?before=bad",
        "changes?attempt=0",
        "changes?attempt=bad",
    ],
)
def test_job_routes_preserve_auth_and_validate_parameters(
    owner: Client, served: RelayProject, engine: InlineEngine, path: str
) -> None:
    served.write_workflow(
        "job", "version: 1\nname: Job\nnodes:\n  check: {type: command, run: [git, status]}\n"
    )
    run_id = engine.launch(served, "job")
    url = f"/api/runs/{run_id}/{path}"
    assert Client().get(url).status_code == 401
    assert owner.post(url).status_code == 405
    if not path.startswith("job?"):
        assert owner.get(url).status_code == 400


def test_job_changes_are_limited_to_the_selected_attempt(
    owner: Client, served: RelayProject, engine: InlineEngine
) -> None:
    served.write_workflow(
        "changes",
        "version: 1\nname: Changes\nnodes:\n"
        "  work: {type: command, writes: true, run: [git, status]}\n",
    )
    run_id = engine.launch(served, "changes")
    attempt = engine.store.claim_dispatch(engine.tokens.popleft(), engine.worker_id).attempt
    assert attempt is not None
    from relay.vcs.git import run_git

    head = run_git(served.repository, ["rev-parse", "HEAD"]).stdout.strip()
    run_git(served.repository, ["commit", "--allow-empty", "-m", "Job's own commit"])
    ending = run_git(served.repository, ["rev-parse", "HEAD"]).stdout.strip()
    engine.store.finish_attempt(attempt.attempt_id, ExecutionOutcome(OutcomeKind.SUCCEEDED), ending)
    response = owner.get(f"/api/runs/{run_id}/changes?job=root.work&attempt=1").json()
    assert response["source_commit"] == head
    assert response["recorded_head"] == ending
    assert response["commits"] == [{"sha": ending, "title": "Job's own commit"}]
    missing = owner.get(f"/api/runs/{run_id}/changes?job=root.work&attempt=2").json()
    assert missing["commits"] == []
    assert missing["text"] == ""


def test_job_reads_omit_redacted_output_and_failure_text(
    owner: Client, served: RelayProject, engine: InlineEngine
) -> None:
    served.write_workflow(
        "private",
        "version: 1\nname: Private\nnodes:\n  check: {type: command, run: [git, status]}\n",
    )
    run_id = engine.launch(served, "private")
    attempt = engine.store.claim_dispatch(engine.tokens.popleft(), engine.worker_id).attempt
    assert attempt is not None
    engine.store.append_attempt_event(
        attempt.attempt_id, "agent.message", EventSource.AGENT, {"text": "Public failure"}
    )
    engine.store.append_attempt_event(
        attempt.attempt_id,
        "agent.message",
        EventSource.AGENT,
        {"text": "Private provider content"},
        sensitivity=EventSensitivity.REDACTED,
    )
    engine.store.finish_attempt(
        attempt.attempt_id,
        ExecutionOutcome(OutcomeKind.FAILED, error_message="Private failure"),
        attempt.starting_head,
    )
    RunEvent.objects.filter(attempt_id=attempt.attempt_id, type="attempt.ended").update(
        sensitivity=EventSensitivity.REDACTED.value
    )
    job = owner.get(f"/api/runs/{run_id}/job?job=root.check").json()["job"]
    assert job["latest_attempt"]["error_message"] is None
    assert job["latest_attempt"]["provider_message"] == "Public failure"
    for query in ("job=root.check", "attempt=1", "job=root.check&attempt=1&latest=true"):
        response = owner.get(f"/api/runs/{run_id}/events?{query}").json()
        assert "Private provider content" not in json.dumps(response)
        assert "Private failure" not in json.dumps(response)


def test_job_instruction_preview_shares_a_utf8_byte_budget(
    owner: Client, served: RelayProject, engine: InlineEngine, fake_agents: FakeAgents
) -> None:
    fake_agents.install("codex", mode="configuration")
    first = "界" * 100000
    served.write(".relay/prompts/large.md", first)
    served.write(".relay/prompts/last.md", "Last instruction")
    served.write_workflow(
        "large",
        "version: 1\nname: Large\nmodel: m1\nagents: [codex]\nnodes:\n"
        "  work: {type: agent, prompts: [{local: prompts/large.md}, {local: prompts/last.md}]}\n",
    )
    run_id = engine.launch(served, "large")
    instructions = owner.get(f"/api/runs/{run_id}/job?job=root.work").json()["job"]["instructions"]
    assert instructions[0]["text"] == first[: 262144 // 3]
    assert instructions[0]["truncated"] is True
    assert instructions[1]["text"] == "L"
    assert instructions[1]["truncated"] is True
    assert sum(len(row["text"].encode("utf-8")) for row in instructions) == 262144


def test_job_database_failure_keeps_the_public_error_envelope(
    owner: Client, served: RelayProject, engine: InlineEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    served.write_workflow(
        "failure",
        "version: 1\nname: Failure\nnodes:\n  check: {type: command, run: [git, status]}\n",
    )
    run_id = engine.launch(served, "failure")

    def unavailable(*args: object, **kwargs: object) -> None:
        del args, kwargs
        message = "Private database trace"
        raise DatabaseError(message)

    monkeypatch.setattr(NodeRun.objects, "filter", unavailable)
    response = owner.get(f"/api/runs/{run_id}/job?job=root.check")
    assert response.status_code == 503
    assert response.json()["code"] == "persistence_error"
    assert "Private database trace" not in response.content.decode()


@pytest.mark.parametrize("kind", ["permission", "elicitation"])
def test_attention_counts_only_requests_on_waiting_attempts(
    owner: Client, served: RelayProject, engine: InlineEngine, kind: str
) -> None:
    served.write_workflow(
        "attention",
        "version: 1\nname: Attention\nnodes:\n  check: {type: command, run: [git, status]}\n",
    )
    run_id = engine.launch(served, "attention")
    attempt = engine.store.claim_dispatch(engine.tokens.popleft(), engine.worker_id).attempt
    assert attempt is not None
    before = owner.get("/api/attention").json()
    assert before["waiting_count"] == 0
    interaction_id = engine.store.request_agent_interaction(
        attempt.attempt_id, kind, "Answer this request.", ({"id": "allow"},)
    )
    attention = owner.get("/api/attention").json()
    assert attention["waiting_count"] == 1
    assert attention["waiting_runs"] == [run_id]
    assert attention["finished"] == []
    assert "Answer this request" not in json.dumps(attention)
    detail = owner.get(f"/api/runs/{run_id}?collection=interactions&pending=true").json()["run"]
    assert detail["waiting_count"] == 1
    assert detail["interactions"][0]["respondable"] is True
    assert detail["interactions"][0]["id"] == interaction_id
    assert owner.get("/api/runs").json()["runs"][0]["waiting_count"] == 1
    engine.store.finish_attempt(
        attempt.attempt_id, ExecutionOutcome(OutcomeKind.FAILED), attempt.starting_head
    )
    assert owner.get("/api/attention").json()["waiting_count"] == 0
    finished = owner.get(f"/api/attention?since={before['event_cursor']}").json()
    assert finished["finished"][0]["status"] == "failed"
    assert finished["finished"][0]["run_id"] == run_id


def test_attention_reads_nested_human_waits_and_excludes_dispatch_pauses(
    owner: Client, served: RelayProject, engine: InlineEngine
) -> None:
    served.write_workflow(
        "nested-wait",
        "version: 1\nname: Nested wait\nnodes:\n"
        "  approvals:\n    type: loop\n    max_iterations: 1\n    until: '${{ loop.index >= 1 }}'\n"
        "    exhausted: fallback\n    body:\n"
        "      approval: {type: human_wait, prompt: Read the report.}\n"
        "  fallback: {type: command, needs: [approvals], run: [git, status]}\n",
    )
    run_id = engine.launch(served, "nested-wait")
    engine.drain(run_id)
    response = post(
        owner, f"/api/runs/{run_id}/pause", {"paused": True, "idempotency_key": "pause"}
    )
    assert response.status_code == 202
    assert owner.get("/api/attention").json()["waiting_runs"] == [run_id]
    detail = owner.get(f"/api/runs/{run_id}?collection=interactions&pending=true").json()["run"]
    assert detail["interactions"][0]["scope_path"] == "root.approvals#1.approval"
    assert detail["interactions"][0]["respondable"] is True
    assert detail["dispatch_paused"] is True
    response = post(owner, f"/api/runs/{run_id}/cancel", {"idempotency_key": "cancel-wait"})
    assert response.status_code == 202
    engine.store.resolve_human_wait_controls()
    engine.drain(run_id)
    assert owner.get("/api/attention").json()["waiting_count"] == 0


def test_attention_completion_cursor_is_bounded_and_omits_payloads(
    owner: Client, finished_run: str
) -> None:
    last = owner.get("/api/attention").json()
    assert last["finished"] == []
    RunEvent.objects.bulk_create(
        [
            RunEvent(
                run_id=finished_run,
                type="run.succeeded",
                source=EventSource.SYSTEM.value,
                payload={"private": "Do not return event payloads."},
            )
            for _ in range(201)
        ]
    )
    page = owner.get(f"/api/attention?since={last['event_cursor']}").json()
    assert len(page["finished"]) == 200
    assert page["more"] is True
    assert "Do not return" not in json.dumps(page)
    next_page = owner.get(f"/api/attention?since={page['event_cursor']}").json()
    assert len(next_page["finished"]) == 1
    assert next_page["more"] is False
    assert next_page["finished"][0]["id"] > page["finished"][-1]["id"]


def test_attention_requires_owner_access_and_valid_cursors(owner: Client) -> None:
    assert Client().get("/api/attention").status_code == 401
    assert owner.post("/api/attention").status_code == 405
    for cursor in ("bad", "-1", str(DATABASE_INTEGER_MAX + 1)):
        assert owner.get(f"/api/attention?since={cursor}").status_code == 400


def test_attention_counts_runs_independently_of_their_request_count(
    owner: Client, served: RelayProject, engine: InlineEngine
) -> None:
    served.write_workflow(
        "two-approvals",
        "version: 1\nname: Two approvals\nnodes:\n"
        "  first: {type: human_wait, prompt: First approval}\n"
        "  second: {type: human_wait, prompt: Second approval}\n",
    )
    run_id = engine.launch(served, "two-approvals")
    engine.drain(run_id)
    assert owner.get(f"/api/runs/{run_id}").json()["run"]["waiting_count"] == 2
    assert owner.get("/api/attention").json()["waiting_count"] == 1


def test_attention_database_errors_keep_the_public_envelope(
    owner: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable(*args: object, **kwargs: object) -> None:
        del args, kwargs
        message = "Private database trace"
        raise DatabaseError(message)

    monkeypatch.setattr(HumanInteraction.objects, "filter", unavailable)
    response = owner.get("/api/attention")
    assert response.status_code == 503
    assert response.json()["code"] == "persistence_error"
    assert "Private database trace" not in response.content.decode()


def test_history_filters_are_additive_and_titles_stay_captured(
    owner: Client, served: RelayProject, engine: InlineEngine
) -> None:
    workflow = (
        "version: 1\nname: Build and review\nnodes:\n  check: {type: command, run: [git, status]}\n"
    )
    served.write_workflow("identity", workflow)
    run_id = engine.launch(served, "identity")
    engine.drain(run_id)
    served.write_workflow("identity", workflow.replace("Build and review", "New workflow name"))
    for query in ("workflow=identity", "branch=main", "query=review", "query=Build"):
        response = owner.get(f"/api/runs?project={served.project_id}&{query}")
        assert response.status_code == 200
        rows = response.json()["runs"]
        assert [row["id"] for row in rows] == [run_id]
        assert rows[0]["title"] == "Build and review"
        assert rows[0]["number"] == 1
        assert rows[0]["source_branch"] == "main"
        assert rows[0]["created_at"]
    assert owner.get("/api/runs?branch=missing").json()["runs"] == []
    assert owner.get("/api/runs?query=missing").json()["runs"] == []
    assert owner.get("/api/runs?workflow=missing").json()["runs"] == []
    assert owner.get("/api/runs?query=" + "x" * 1025).status_code == 400
