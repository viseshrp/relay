"""Coherent read-only monitoring snapshots retain bounded cursor pagination."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from django.db import connections, transaction
from django.test import Client
import pytest

from relay.constants import API_MAX_PAGE_BYTES
from relay.web.models import HumanInteraction, NodeAttempt, NodeRun, Run, RunEvent
from relay.web.repositories import DjangoReadStore
from tests.sqlite_support import SqliteWriteProbe, hold_write_lock
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
                node_type="command",
                frozen_def={"type": "command", "run": ["echo", "ok"]},
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
    assert len(set(ids)) == len(ids) == 1006


def test_job_pages_include_metadata_in_the_byte_budget_and_continue_beyond_a_thousand(
    owner: Client, finished_run: str
) -> None:
    node = NodeRun.objects.get(run_id=finished_run)
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
