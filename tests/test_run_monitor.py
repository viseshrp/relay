"""Coherent read-only monitoring snapshots retain bounded cursor pagination."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from django.db import connections, transaction
from django.test import Client
import pytest

from relay.constants import API_MAX_PAGE_BYTES
from relay.web.models import Artifact, HumanInteraction, NodeAttempt, NodeRun, Run, RunEvent
from relay.web.repositories import DjangoReadStore
from relay.workflows.schema import ActionsJobNode
from tests.sqlite_support import SqliteWriteProbe, hold_write_lock
from tests.support import InlineEngine, RelayProject
from tests.test_web_api import client as client
from tests.test_web_api import finished_run as finished_run
from tests.test_web_api import owner as owner
from tests.test_web_api import served as served
from tests.test_web_api import waiting_run as waiting_run


def test_monitor_reads_through_a_writer_lock(owner: Client, finished_run: str) -> None:
    database = Path(connections["default"].settings_dict["NAME"])
    with hold_write_lock(database), SqliteWriteProbe() as probe:
        response = owner.get(f"/api/runs/{finished_run}/monitor")
    assert response.status_code == 200
    assert response.json()["run"]["id"] == finished_run
    assert probe.transactions == probe.autocommit_writes == 0


def test_output_advances_the_event_cursor_without_invalidating_state(
    owner: Client,
    finished_run: str,
) -> None:
    first = owner.get(f"/api/runs/{finished_run}/monitor").json()
    output = RunEvent.objects.create(
        run_id=finished_run, type="command.stdout", source="command", payload={"text": "tail"}
    )
    second = owner.get(f"/api/runs/{finished_run}/monitor").json()
    assert second["event_cursor"] == output.pk
    assert second["state_cursor"] == first["state_cursor"]
    state = RunEvent.objects.create(run_id=finished_run, type="run.rerun", source="run", payload={})
    third = owner.get(f"/api/runs/{finished_run}/monitor").json()
    assert third["state_cursor"] == state.pk


def test_resolved_action_names_advance_monitor_state_once(
    owner: Client, served: RelayProject, engine: InlineEngine
) -> None:
    from relay.web.actions_repository import display_name

    served.write_workflow(
        "names", "jobs:\n  main:\n    steps:\n      - run: print('ready')\n        shell: python\n"
    )
    run_id = engine.launch(served, "names")
    engine.drain(run_id)
    attempt = NodeAttempt.objects.get(
        node_run__run_id=run_id, node_run__scope_path="root.main.step_1"
    )
    first = owner.get(f"/api/runs/{run_id}/monitor").json()

    display_name(str(attempt.pk), "Check Windows output")

    updated = owner.get(f"/api/runs/{run_id}/monitor").json()
    assert updated["state_cursor"] > first["state_cursor"]
    step = next(row for row in updated["nodes"] if row["scope_path"] == "root.main.step_1")
    assert step["display_name"] == "Check Windows output"
    display_name(str(attempt.pk), "Check Windows output")
    assert (
        owner.get(f"/api/runs/{run_id}/monitor").json()["state_cursor"] == updated["state_cursor"]
    )


def test_monitor_returns_one_consistent_snapshot(
    owner: Client,
    waiting_run: tuple[str, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id, attempt_id = waiting_run
    interaction = HumanInteraction.objects.get(attempt_id=attempt_id)
    original = DjangoReadStore._node_records
    committed = False

    def answer() -> None:
        try:
            with transaction.atomic():
                HumanInteraction.objects.filter(pk=interaction.pk).update(status="answered")
                RunEvent.objects.create(run_id=run_id, type="wait.answered", source="control")
        finally:
            connections.close_all()

    def change_between_reads(
        run: Run, since: int, limit: int, byte_budget: int
    ) -> tuple[list[dict[str, object]], int | None]:
        nonlocal committed
        rows = original(run, since, limit, byte_budget)
        if not committed:
            committed = True
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(answer).result(timeout=5)
        return rows

    monkeypatch.setattr(DjangoReadStore, "_node_records", staticmethod(change_between_reads))
    old = owner.get(f"/api/runs/{run_id}/monitor").json()
    assert old["run"]["waiting_count"] == 1
    assert old["interactions"][0]["status"] == "pending"
    fresh = owner.get(f"/api/runs/{run_id}/monitor").json()
    assert fresh["state_cursor"] > old["state_cursor"]
    assert fresh["run"]["waiting_count"] == 0
    assert fresh["interactions"] == []


@pytest.mark.parametrize("large_unicode", [False, True])
def test_monitor_pages_pending_requests_without_exceeding_the_byte_limit(
    owner: Client,
    waiting_run: tuple[str, int],
    large_unicode: bool,
) -> None:
    run_id, attempt_id = waiting_run
    interaction = HumanInteraction.objects.get(attempt_id=attempt_id)
    count = 25 if large_unicode else 1005
    HumanInteraction.objects.bulk_create(
        [
            HumanInteraction(
                run_id=run_id,
                node_run=interaction.node_run,
                attempt_id=attempt_id,
                kind="wait",
                request_payload={"prompt": "\U0001f642" * 5000 if large_unicode else "Continue?"},
            )
            for _ in range(count)
        ]
    )
    ids: list[str] = []
    cursor = 0
    while True:
        response = owner.get(f"/api/runs/{run_id}/monitor?interactions_since={cursor}")
        assert response.status_code == 200
        assert len(response.content) <= API_MAX_PAGE_BYTES
        value = response.json()
        assert len(value["interactions"]) <= 200
        ids.extend(row["id"] for row in value["interactions"])
        if value["interactions_next"] is None:
            break
        assert value["interactions_next"] > cursor
        cursor = value["interactions_next"]
    assert len(set(ids)) == len(ids) == count + 1


def test_monitor_pages_all_nodes_beyond_a_thousand(owner: Client, finished_run: str) -> None:
    NodeRun.objects.bulk_create(
        [
            NodeRun(
                run_id=finished_run,
                scope_path=f"root.extra_{index}",
                node_id=f"extra_{index}",
                node_type="actions_job",
                frozen_def=ActionsJobNode(
                    job_id=f"extra_{index}", job={"steps": [{"run": "echo ok"}]}, workflow={}
                ).model_dump(mode="json"),
            )
            for index in range(1005)
        ]
    )
    ids: list[str] = []
    cursor = 0
    while True:
        response = owner.get(f"/api/runs/{finished_run}/monitor?nodes_since={cursor}&limit=1000")
        assert response.status_code == 200
        assert len(response.content) <= API_MAX_PAGE_BYTES
        value = response.json()
        rows = value["nodes"]
        assert 0 < len(rows) <= 200
        ids.extend(row["id"] for row in rows)
        if value["nodes_next"] is None:
            break
        assert value["nodes_next"] > cursor
        cursor = value["nodes_next"]
    assert len(set(ids)) == len(ids) == 1007


def test_job_pages_include_metadata_in_the_byte_budget_and_continue_beyond_a_thousand(
    owner: Client, finished_run: str
) -> None:
    node = NodeRun.objects.get(run_id=finished_run, node_type="actions_job")
    head = NodeAttempt.objects.get(node_run=node).starting_head
    attempts = NodeAttempt.objects.bulk_create(
        [
            NodeAttempt(
                node_run=node,
                attempt_number=index + 2,
                status="failed",
                worker_id="historical-worker",
                starting_head=head,
            )
            for index in range(1005)
        ]
    )
    RunEvent.objects.bulk_create(
        [
            RunEvent(
                run_id=finished_run,
                node_run=node,
                attempt=attempt,
                type="attempt.ended",
                source="node",
                payload={"error_message": "\U0001f642" * 5000},
            )
            for attempt in attempts
        ]
    )
    ids: list[str] = []
    cursor = 0
    while True:
        response = owner.get(
            f"/api/runs/{finished_run}/job?job={node.scope_path}&since={cursor}&limit=1000"
        )
        assert response.status_code == 200
        assert len(response.content) <= API_MAX_PAGE_BYTES
        value = response.json()
        records = value["job"]["attempts"]
        assert 0 < len(records) <= 200
        ids.extend(row["id"] for row in records)
        if value["next"] is None:
            break
        assert value["next"] > cursor
        cursor = value["next"]
    assert len(set(ids)) == len(ids) == 1006


def test_linked_answer_is_separate_from_pending_requests(
    owner: Client,
    waiting_run: tuple[str, int],
) -> None:
    run_id, attempt_id = waiting_run
    interaction = HumanInteraction.objects.get(attempt_id=attempt_id)
    HumanInteraction.objects.filter(pk=interaction.pk).update(status="answered")
    response = owner.get(f"/api/runs/{run_id}/monitor?interaction={interaction.pk}")
    assert response.status_code == 200
    assert response.json()["interactions"] == []
    assert response.json()["linked_interaction"]["status"] == "answered"


def test_monitor_rejects_invalid_pages_and_requires_login(
    client: Client,
    owner: Client,
    finished_run: str,
) -> None:
    # The owner fixture signs in its client, so use a distinct browser for auth.
    assert Client().get(f"/api/runs/{finished_run}/monitor").status_code == 401
    for query in ("nodes_since=-1", "interactions_since=bad", "limit=0"):
        assert owner.get(f"/api/runs/{finished_run}/monitor?{query}").status_code == 400


def test_monitor_reports_artifact_total_and_committed_changes(
    owner: Client, finished_run: str
) -> None:
    attempt = NodeAttempt.objects.filter(node_run__run_id=finished_run).first()
    assert attempt is not None
    Artifact.objects.bulk_create(
        [
            Artifact(
                attempt=attempt,
                declared_name=f"report-{index}.md",
                source_path=f"report-{index}.md",
                retained_path=f"retained/report-{index}.md",
                sha256="0" * 64,
                media_type="text/markdown",
                bytes=10,
                preservation_state="preserved",
            )
            for index in range(55)
        ]
        + [
            # Empty change records and unpreserved bytes are not review material.
            Artifact(
                attempt=attempt,
                declared_name="commits",
                source_path="commits",
                retained_path="retained/commits",
                sha256="0" * 64,
                media_type="application/json",
                bytes=2,
                preservation_state="preserved",
            ),
            Artifact(
                attempt=attempt,
                declared_name="pending.md",
                source_path="pending.md",
                retained_path="retained/pending.md",
                sha256="0" * 64,
                media_type="text/markdown",
                bytes=10,
            ),
        ]
    )
    visible = DjangoReadStore().page_artifacts(finished_run, 0, 200, visible_only=True)[0]
    run = Run.objects.get(pk=finished_run)
    unchanged = owner.get(f"/api/runs/{finished_run}/monitor").json()["run"]
    assert len(visible) >= 55
    assert not {"commits", "pending.md"} & {row["name"] for row in visible}
    # The total covers every visible record, not only the first browser page.
    assert unchanged["artifact_count"] == len(visible)
    assert unchanged["recorded_head"] == run.source_commit
    assert unchanged["has_committed_changes"] is False

    Run.objects.filter(pk=finished_run).update(recorded_head="f" * 40)
    changed = owner.get(f"/api/runs/{finished_run}/monitor").json()["run"]
    assert changed["artifact_count"] == unchanged["artifact_count"]
    assert changed["recorded_head"] == "f" * 40
    assert changed["has_committed_changes"] is True


def test_queued_jobs_use_their_declared_names(
    owner: Client, served: RelayProject, engine: InlineEngine
) -> None:
    served.write_workflow(
        "named",
        (
            "jobs:\n"
            "  approve:\n"
            "    steps:\n"
            "    - uses: relay/human-wait@v1\n"
            "      with:\n"
            "        prompt: Go?\n"
            "  build:\n"
            "    name: Build the app\n"
            "    needs: approve\n"
            "    steps:\n"
            "    - run: echo built\n"
            "  dynamic:\n"
            "    name: Build ${{ inputs.target }}\n"
            "    needs: approve\n"
            "    steps:\n"
            "    - run: echo built\n"
        ),
    )
    run_id = engine.launch(served, "named")
    engine.drain(run_id)
    NodeRun.objects.create(
        run_id=run_id,
        scope_path="root.build.step_1.iteration_2",
        node_id="iteration_2",
        node_type="actions_job",
        frozen_def=ActionsJobNode(
            job_id="iteration", job={"uses": "./.relay/workflows/cycle.yaml"}, workflow={}
        ).model_dump(mode="json"),
    )
    # An unnamed loop round resolves to its job ID at run time.
    run = Run.objects.get(pk=run_id)
    run.actions_state = {
        **run.actions_state,
        "display_names": {
            **run.actions_state.get("display_names", {}),
            "root.build.step_1.iteration_2": "iteration",
        },
    }
    run.save(update_fields=("actions_state",))
    nodes = {
        row["scope_path"]: row for row in owner.get(f"/api/runs/{run_id}/monitor").json()["nodes"]
    }
    assert nodes["root.build"]["status"] == "pending"
    assert nodes["root.build"]["display_name"] == "Build the app"
    # Interpolated names are resolved only when the job starts.
    assert nodes["root.dynamic"]["display_name"] == "dynamic"
    assert nodes["root.approve"]["display_name"] == "approve"
    assert nodes["root.build.step_1.iteration_2"]["display_name"] == "Round 2"
