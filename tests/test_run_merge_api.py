"""Merge policy inheritance, strict previews, and additive public run facts."""

from __future__ import annotations

from django.test import Client
import pytest

from relay.web.models import Run
from relay.web.views import actions
from tests.support import InlineEngine, RelayProject
from tests.test_web_api import client as client
from tests.test_web_api import owner as owner
from tests.test_web_api import post
from tests.test_web_api import served as served


def test_global_project_and_launch_merge_choices_are_captured_and_reported(
    owner: Client,
    served: RelayProject,
    engine: InlineEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(actions, "_enqueue_claim", engine.tokens.append)
    served.write_workflow(
        "merge",
        "name: Merge\njobs:\n  write:\n    runs-on: self-hosted\n    steps:\n"
        "      - uses: relay/command@v1\n"
        '        with: {argv: \'["git", "commit", "--allow-empty", "-q", "-m", "result"]\'}\n',
    )
    settings = owner.get("/api/settings").json()
    response = post(
        owner,
        "/api/settings",
        {
            "revision": settings["revision"],
            "settings": {**settings["settings"], "cleanup_policy": "merge_on_success"},
        },
    )
    assert response.status_code == 200
    for policy in (None, "retain", "merge_on_success"):
        if policy == "retain":
            overrides = owner.get("/api/projects/defaults").json()
            assert (
                post(
                    owner,
                    "/api/projects/defaults",
                    {
                        "revision": overrides["revision"],
                        "overrides": {"cleanup_policy": "retain"},
                    },
                ).status_code
                == 200
            )
        body: dict[str, object] = {"workflow_key": "merge", "inputs": {}}
        if policy == "merge_on_success":
            body["cleanup_policy"] = policy
        launched = post(owner, "/api/runs", body)
        assert launched.status_code == 201
        run_id = launched.json()["run_id"]
        engine.drain(run_id)
        detail = owner.get(f"/api/runs/{run_id}").json()["run"]
        assert detail["status"] == "succeeded"
        assert detail["cleanup_policy"] == (policy or "merge_on_success")
        assert bool(detail["merged_commit"]) == (policy != "retain")
        assert detail["worktree_state"] == ("created" if policy == "retain" else "removed")


def test_strict_preflight_uses_selected_or_inherited_policy(
    owner: Client,
    served: RelayProject,
) -> None:
    served.write_workflow(
        "workflow", "jobs: {main: {runs-on: self-hosted, steps: [{run: echo Ready}]}}\n"
    )
    served.write("REVIEW.md", "owner report\n")
    normal = owner.get("/api/workflows/workflow/preflight").json()
    strict = owner.get("/api/workflows/workflow/preflight?cleanup_policy=merge_on_success").json()
    assert normal["clean"] is True
    assert strict["clean"] is False
    assert strict["allowed_count"] == 0
    assert strict["blocking_count"] == normal["blocking_count"] + normal["allowed_count"]
    assert all(not item["allowed"] for item in strict["files"])
    current = owner.get("/api/projects/defaults").json()
    assert (
        post(
            owner,
            "/api/projects/defaults",
            {
                "revision": current["revision"],
                "overrides": {"cleanup_policy": "merge_on_success"},
            },
        ).status_code
        == 200
    )
    assert owner.get("/api/workflows/workflow/preflight").json() == strict
    assert owner.get("/api/projects/current").json()["cleanup_policy"] == "merge_on_success"
    response = post(owner, "/api/runs", {"workflow_key": "workflow", "inputs": {}})
    assert response.status_code == 409
    assert response.json()["code"] == "dirty_repository_error"
    assert not Run.objects.exists()
    assert owner.get("/api/workflows/workflow/preflight?cleanup_policy=unknown").status_code == 400
