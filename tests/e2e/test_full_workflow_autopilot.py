from __future__ import annotations

import json

import pytest

from relay.artifacts.manager import artifact_dir
from relay.copilot.session import set_session_factory
from relay.worker.orchestrator import WorkflowRuntime
from tests.helpers.workflow import SessionFactoryQueue, drive_workflow, load_run
from tests.mocks.fake_copilot import FakeCopilotSession


def _planning_prompt() -> str:
    return """# Problem
Build the requested feature.

# Goals
- Finish the full workflow.

# Constraints
- Keep the test deterministic.

# Preferred Stack
- Python and React.

# Files to Read
- src/main.py

# Desired Output
- A complete implementation.
"""


def _review_output(verdict: str) -> str:
    return f"""```relay-review-comments
{json.dumps([])}
```

## Summary
Autopilot review summary.

## Verdict
{verdict}
"""


@pytest.mark.asyncio
async def test_full_workflow_autopilot(client, app, test_settings, project_dir) -> None:
    project = (await client.post("/api/v1/projects", json={"path": str(project_dir)})).json()
    run = (await client.post("/api/v1/runs", json={"project_id": project["id"], "name": "Autopilot", "autopilot": True})).json()

    set_session_factory(
        SessionFactoryQueue(
            [
                FakeCopilotSession(["Exploration reply", _planning_prompt()]),
                FakeCopilotSession(["Planning output", "Corrected plan output"]),
                FakeCopilotSession(["Critiqued plan output"]),
                FakeCopilotSession(["Execution output"]),
                FakeCopilotSession([_review_output("PASS")]),
            ]
        )
    )

    message_response = await client.post(f"/api/v1/runs/{run['id']}/exploration/messages", json={"content": "Please build the requested feature."})
    finalize_response = await client.post(f"/api/v1/runs/{run['id']}/exploration/finalize")
    outcome = await drive_workflow(app, test_settings, run["id"], WorkflowRuntime())
    db_run = await load_run(app, run["id"])

    assert message_response.status_code == 200
    assert finalize_response.status_code == 200
    assert outcome == "completed"
    assert db_run.status == "completed"
    assert all(phase.status == "succeeded" for phase in db_run.phases)
    assert (artifact_dir(str(project_dir), run["id"], "exploration") / "planning_prompt.md").exists()
    assert (artifact_dir(str(project_dir), run["id"], "planning") / "SPEC.md").exists()
    assert (artifact_dir(str(project_dir), run["id"], "planning") / "IMPLEMENTATION_PLAN.md").exists()
    assert (artifact_dir(str(project_dir), run["id"], "plan_critique") / "IMPLEMENTATION_PLAN_CRITIQUED.md").exists()
    assert (artifact_dir(str(project_dir), run["id"], "review") / "REVIEW_SUMMARY.md").exists()
