"""Two runs of one project compare by inputs, captured hashes, and job results."""

from __future__ import annotations

import json
from pathlib import Path

from django.test import Client

from relay.web.models import NodeAttempt, NodeRun, Project, Run
from tests.support import InlineEngine, RelayProject
from tests.test_web_api import client as client
from tests.test_web_api import owner as owner
from tests.test_web_api import served as served


def _workflow(project: RelayProject, name: str) -> None:
    project.write_workflow(
        "compare",
        json.dumps(
            {
                "name": name,
                "on": {"workflow_dispatch": {"inputs": {"argv": {"type": "string"}}}},
                "jobs": {
                    "check": {
                        "steps": [
                            {
                                "id": "work",
                                "uses": "relay/command@v1",
                                "with": {"argv": "${{ inputs.argv }}"},
                            }
                        ]
                    }
                },
            }
        ),
    )


def _two_runs(project: RelayProject, engine: InlineEngine) -> tuple[str, str]:
    _workflow(project, "Compare")
    failed = engine.launch(project, "compare", inputs={"argv": '["git", "no-such-command"]'})
    engine.drain(failed)
    _workflow(project, "Compare again")
    passed = engine.launch(project, "compare", inputs={"argv": '["git", "status"]'})
    engine.drain(passed)
    return failed, passed


def test_compare_pairs_inputs_hashes_and_job_results(
    owner: Client, served: RelayProject, engine: InlineEngine
) -> None:
    left, right = _two_runs(served, engine)
    assert Run.objects.get(pk=left).status == "failed"
    assert Run.objects.get(pk=right).status == "succeeded"
    response = owner.get(f"/api/runs/compare?left={left}&right={right}")
    assert response.status_code == 200, response.content
    body = response.json()
    assert (body["left"]["id"], body["right"]["id"]) == (left, right)
    assert (body["left"]["workflow_name"], body["right"]["workflow_name"]) == (
        "Compare",
        "Compare again",
    )
    assert body["inputs"] == [
        {
            "name": "argv",
            "left": '["git", "no-such-command"]',
            "right": '["git", "status"]',
            "same": False,
        }
    ]
    workflow_hash = next(row for row in body["hashes"] if row["name"] == "workflow")
    assert workflow_hash["same"] is False
    step = next(row for row in body["steps"] if row["scope_path"] == "root.check.work")
    assert step["left"]["status"] == "failed"
    assert step["right"]["status"] == "succeeded"
    assert step["left"]["attempt_count"] == 1
    assert step["left"]["latest_attempt"]["error_code"]
    assert step["right"]["latest_attempt"]["error_code"] is None
    assert body["truncated"] is False


def test_compare_keeps_steps_present_on_only_one_side(
    owner: Client, served: RelayProject, engine: InlineEngine
) -> None:
    left, right = _two_runs(served, engine)
    NodeAttempt.objects.filter(
        node_run__run_id=right, node_run__scope_path="root.check.work"
    ).delete()
    NodeRun.objects.filter(run_id=right, scope_path="root.check.work").update(
        scope_path="root.check.renamed"
    )
    body = owner.get(f"/api/runs/compare?left={left}&right={right}").json()
    rows = {row["scope_path"]: row for row in body["steps"]}
    assert rows["root.check.work"]["right"] is None
    assert rows["root.check.renamed"]["left"] is None
    assert rows["root.check.renamed"]["right"]["latest_attempt"] is None


def test_compare_rejects_other_projects_missing_runs_and_bad_ids(
    owner: Client, served: RelayProject, engine: InlineEngine, tmp_path: Path
) -> None:
    left, right = _two_runs(served, engine)
    other = Project.objects.create(
        canonical_path=str(tmp_path / "other"), display_name="Other", git_root=str(tmp_path)
    )
    Run.objects.filter(pk=right).update(project=other)
    response = owner.get(f"/api/runs/compare?left={left}&right={right}")
    assert (response.status_code, response.json()["code"]) == (400, "config_error")
    assert owner.get(f"/api/runs/compare?left={left}").status_code == 400
    # Malformed and unknown IDs share the run-not-found contract.
    bad = owner.get(f"/api/runs/compare?left={left}&right=not-a-run")
    missing = owner.get(f"/api/runs/compare?left={left}&right=00000000-0000-4000-8000-000000000000")
    assert bad.status_code == missing.status_code == 404
    assert bad.json()["code"] == missing.json()["code"]


def test_compare_requires_login(client: Client, served: RelayProject) -> None:
    del served
    assert client.get("/api/runs/compare?left=a&right=b").status_code == 401
