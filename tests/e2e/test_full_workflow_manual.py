from __future__ import annotations

import json

import pytest

from relay.copilot.session import set_session_factory
from relay.worker.orchestrator import WorkflowRuntime
from tests.helpers.workflow import SessionFactoryQueue, drive_workflow
from tests.mocks.fake_copilot import FakeCopilotSession


def _planning_prompt() -> str:
    return """# Problem
Build the requested feature.

# Goals
- Walk the manual workflow.

# Constraints
- Pause at each approval gate.

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
Manual review summary.

## Verdict
{verdict}
"""


@pytest.mark.asyncio
async def test_full_workflow_manual(client, app, test_settings, project_dir) -> None:
    project = (await client.post("/api/v1/projects", json={"path": str(project_dir)})).json()
    run = (await client.post("/api/v1/runs", json={"project_id": project["id"], "name": "Manual", "autopilot": False})).json()

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

    await client.post(f"/api/v1/runs/{run['id']}/exploration/messages", json={"content": "Please build the requested feature."})
    await client.post(f"/api/v1/runs/{run['id']}/exploration/finalize")

    runtime = WorkflowRuntime()
    first_outcome = await drive_workflow(app, test_settings, run["id"], runtime)
    first_run = (await client.get(f"/api/v1/runs/{run['id']}")).json()

    await client.post(f"/api/v1/runs/{run['id']}/advance")
    second_outcome = await drive_workflow(app, test_settings, run["id"], runtime)
    second_run = (await client.get(f"/api/v1/runs/{run['id']}")).json()

    await client.post(f"/api/v1/runs/{run['id']}/advance")
    third_outcome = await drive_workflow(app, test_settings, run["id"], runtime)
    third_run = (await client.get(f"/api/v1/runs/{run['id']}")).json()

    approve_response = await client.post(f"/api/v1/runs/{run['id']}/review/approve")
    final_run = (await client.get(f"/api/v1/runs/{run['id']}")).json()

    assert first_outcome == "waiting_for_user"
    assert first_run["status"] == "waiting_for_user"
    assert second_outcome == "waiting_for_user"
    assert second_run["status"] == "waiting_for_user"
    assert third_outcome == "waiting_for_user"
    assert third_run["status"] == "waiting_for_user"
    assert approve_response.status_code == 200
    assert final_run["status"] == "completed"
