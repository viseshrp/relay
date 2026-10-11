"""Dashboard reads reflect durable work without changing or probing it."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock
import uuid

from django.contrib.auth.models import User
from django.db import DatabaseError, connection
from django.test import Client, override_settings
from django.test.utils import CaptureQueriesContext
import pytest

from relay.web.models import HumanInteraction, NodeAttempt, NodeRun, Run
from tests.support import RelayProject, create_project


@pytest.fixture
def client() -> Client:
    return Client()


@pytest.fixture
def owner(client: Client) -> Client:
    user = User.objects.create_user(username="owner", is_staff=True, is_superuser=True)
    client.force_login(user)
    return client


def saved_run(project: RelayProject, number: int, status: str = "succeeded") -> Run:
    when = datetime(2026, 10, 1, tzinfo=timezone.utc) + timedelta(minutes=number)
    return Run.objects.create(
        project_id=project.project_id,
        number=number,
        title=f"Work {number}",
        workflow_key="check.yaml",
        status=status,
        source_commit="a" * 40,
        run_branch=f"run-{project.project_id}-{number}",
        worktree_path=f"/unused/{project.project_id}/{number}",
        recorded_head="a" * 40,
        launcher="owner",
        source_branch="main",
        created_at=when,
        started_at=when,
        ended_at=when + timedelta(seconds=45)
        if status in {"succeeded", "failed", "canceled"}
        else None,
    )


def request_for(run: Run, *, attempt_status: str = "waiting", number: int = 1) -> HumanInteraction:
    node = NodeRun.objects.create(
        run=run,
        scope_path=f"root.review{number}",
        node_id=f"review{number}",
        node_type="human_wait",
        status="waiting",
    )
    attempt = NodeAttempt.objects.create(
        node_run=node,
        attempt_number=1,
        status=attempt_status,
        worker_id="test",
        starting_head="a" * 40,
    )
    return HumanInteraction.objects.create(
        run=run,
        node_run=node,
        attempt=attempt,
        kind="wait",
        request_payload={"provider_private": "never expose this"},
    )


def test_dashboard_counts_all_projects_and_only_actionable_requests(
    owner: Client, project: RelayProject, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    another = create_project(tmp_path / "another")
    create_project(tmp_path / "empty")
    waiting = saved_run(project, 1, "running")
    first = request_for(waiting)
    request_for(waiting, number=2)
    paused = saved_run(another, 1, "running")
    Run.objects.filter(pk=paused.pk).update(dispatch_paused=True)
    request_for(paused, attempt_status="ended")
    finished = saved_run(project, 2)
    saved_run(another, 2, "failed")
    probe = Mock(side_effect=RuntimeError("Dashboard must not probe Git"))
    monkeypatch.setattr("relay.web.views.pages.project_launch_source", probe)
    response = owner.get("/api/dashboard")
    assert response.status_code == 200
    value = response.json()
    assert value["counts"] == {"projects": 3, "waiting": 1, "unfinished": 2, "paused": 1}
    assert len(value["waiting"]["items"]) == 1
    row = value["waiting"]["items"][0]
    assert row["id"] == str(waiting.pk)
    assert row["waiting_count"] == 2
    assert row["request"] == {"id": str(first.pk), "kind": "wait", "scope_path": "root.review1"}
    assert row["project"]["id"] == project.project_id
    assert value["active"]["items"][0]["id"] == str(paused.pk)
    assert value["active"]["items"][0]["request"] is None
    assert len(value["recent"]["items"]) == 2
    projects = {item["id"]: item for item in value["projects"]["items"]}
    assert projects[project.project_id]["latest_run"]["id"] == str(finished.pk)
    assert projects[project.project_id]["waiting_count"] == 1
    assert "provider_private" not in response.content.decode()
    probe.assert_not_called()
    assert Run.objects.count() == 4
    assert owner.get("/api/attention").json()["waiting_count"] == value["counts"]["waiting"]


def test_dashboard_pagination_and_project_search_keep_global_counts(
    owner: Client, project: RelayProject, tmp_path: Path
) -> None:
    create_project(tmp_path / "other")
    rows = [saved_run(project, number) for number in range(1, 14)]
    first = owner.get("/api/dashboard?limit=3").json()
    assert [item["number"] for item in first["recent"]["items"]] == [13, 12, 11]
    cursor = first["recent"]["next_cursor"]
    second = owner.get(f"/api/dashboard?section=recent&cursor={cursor}&limit=3").json()
    assert set(second) == {"counts", "recent"}
    assert [item["number"] for item in second["recent"]["items"]] == [10, 9, 8]
    assert first["counts"] == second["counts"]
    assert str(rows[-1].pk) == first["recent"]["items"][0]["id"]
    matched = owner.get("/api/dashboard?query=other").json()
    assert len(matched["projects"]["items"]) == 1
    assert matched["counts"]["projects"] == 2
    assert matched["projects"]["items"][0]["latest_run"] is None
    page = owner.get("/api/dashboard?section=projects&limit=1").json()["projects"]
    tail = owner.get(
        f"/api/dashboard?section=projects&limit=1&cursor={page['next_cursor']}"
    ).json()["projects"]
    assert tail["items"][0]["id"] != page["items"][0]["id"]
    assert tail["next_cursor"] is None


def test_dashboard_empty_and_optional_login(client: Client) -> None:
    assert client.get("/api/dashboard").status_code == 401
    with override_settings(RELAY_LOGIN_REQUIRED=False):
        response = client.get("/api/dashboard")
        assert response.status_code == 200
        assert response.json()["counts"] == {
            "projects": 0,
            "waiting": 0,
            "unfinished": 0,
            "paused": 0,
        }
        for section in ("projects", "waiting", "active", "recent"):
            assert response.json()[section] == {"items": [], "next_cursor": None}


@pytest.mark.parametrize(
    "query", ["section=nope", "limit=0", "limit=-1", "limit=nope", "query=" + "x" * 1025]
)
def test_dashboard_rejects_invalid_filters(owner: Client, query: str) -> None:
    response = owner.get("/api/dashboard?" + query)
    assert response.status_code == 400
    assert response.json()["code"] == "config_error"


def test_dashboard_rejects_invalid_cursors_and_post(owner: Client) -> None:
    assert owner.get("/api/dashboard?section=recent&cursor=bad").status_code == 404
    missing = str(uuid.uuid4())
    assert owner.get(f"/api/dashboard?cursor={missing}").status_code == 400
    for section in ("recent", "projects"):
        assert owner.get(f"/api/dashboard?section={section}&cursor={missing}").status_code == 400
    assert owner.post("/api/dashboard").status_code == 405


def test_dashboard_query_count_does_not_grow_per_project(
    owner: Client, project: RelayProject, tmp_path: Path
) -> None:
    saved_run(project, 1)
    with CaptureQueriesContext(connection) as before:
        assert owner.get("/api/dashboard").status_code == 200
    for number in range(6):
        saved_run(create_project(tmp_path / str(number)), 1)
    with CaptureQueriesContext(connection) as after:
        assert owner.get("/api/dashboard").status_code == 200
    assert len(after) == len(before)


def test_dashboard_database_failure_is_a_public_error(
    owner: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "relay.web.models.Project.objects.count", Mock(side_effect=DatabaseError("private trace"))
    )
    response = owner.get("/api/dashboard")
    assert response.status_code == 503
    assert response.json()["code"] == "persistence_error"
    assert "private trace" not in response.content.decode()


def test_dashboard_cursor_survives_a_run_leaving_the_active_list(
    owner: Client, project: RelayProject
) -> None:
    older = saved_run(project, 1, "running")
    newer = saved_run(project, 2, "running")
    first = owner.get("/api/dashboard?section=active&limit=1").json()["active"]
    assert first["next_cursor"] == str(newer.pk)
    Run.objects.filter(pk=newer.pk).update(status="succeeded")
    response = owner.get(f"/api/dashboard?section=active&limit=1&cursor={first['next_cursor']}")
    assert response.status_code == 200
    assert response.json()["active"]["items"][0]["id"] == str(older.pk)
