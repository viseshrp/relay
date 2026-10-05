"""Storage outages stay inside Relay's error contract across its public repository ports."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
import threading
from typing import NoReturn

from django.db import OperationalError, connection, connections, transaction
import pytest

from relay.errors import PersistenceError
from relay.execution.state import DraftValidationState
from relay.web.models import Installation
from relay.web.repositories import (
    DjangoAgentStore,
    DjangoExecutionStore,
    DjangoProjectStore,
    DjangoReadStore,
    DjangoWorkflowStore,
)

MISSING_UUID = "00000000-0000-0000-0000-000000000000"


def unavailable_database(
    execute: Callable[..., object], sql: str, params: object, many: bool, context: dict[str, object]
) -> NoReturn:
    """Fail at Django's SQL boundary; repository validation and error mapping stay real."""
    del execute, sql, params, many, context
    raise OperationalError("private-database-diagnostic")


@pytest.mark.parametrize(
    ("port", "method", "arguments", "keywords"),
    [
        ("agents", "list_model_observations", (), {}),
        ("agents", "replace_model_observations", ("codex", ()), {}),
        ("projects", "list_projects", (), {}),
        ("workflows", "get_draft", (MISSING_UUID, "workflow"), {}),
        (
            "workflows",
            "save_draft",
            (MISSING_UUID, "workflow", "yaml", "hash", DraftValidationState.VALID),
            {},
        ),
        ("workflows", "discard_draft", (MISSING_UUID, "workflow"), {}),
        ("workflows", "acquire_lease", (MISSING_UUID, "workflow", "owner"), {}),
        ("workflows", "require_lease", (MISSING_UUID, "workflow", "owner"), {}),
        (
            "reads",
            "list_runs",
            (),
            {"project_id": None, "status": None, "since": None, "limit": 10},
        ),
        ("reads", "run_detail", (MISSING_UUID,), {"collection": "nodes", "since": 0, "limit": 10}),
        ("reads", "page_events", (MISSING_UUID, 0, 10), {}),
        ("reads", "page_artifacts", (MISSING_UUID, 0, 10), {}),
        ("reads", "artifact_file", ("1",), {}),
        ("execution", "acquire_instance", (1, "host"), {}),
        ("execution", "heartbeat_instance", (MISSING_UUID,), {}),
        ("execution", "request_orderly_shutdown", (MISSING_UUID,), {}),
        ("execution", "active_attempt_processes", (), {}),
        ("execution", "owned_attempt_processes", (), {}),
        ("execution", "interrupt_active_attempts", (), {}),
        ("execution", "fail_worker_attempts", (), {}),
        ("execution", "release_instance", (MISSING_UUID,), {}),
        ("execution", "run_graph", (MISSING_UUID,), {}),
        ("execution", "load_run_schedule", (MISSING_UUID,), {}),
        ("execution", "scheduling_changes", (0,), {}),
        ("execution", "latest_event_id", (), {}),
        ("execution", "active_run_ids", (), {}),
        ("execution", "clean_project_data", (MISSING_UUID, "all"), {}),
        ("execution", "create_dispatch", ("1",), {}),
        ("execution", "claim_dispatch", ("token", "worker"), {}),
        ("execution", "mark_dispatch_enqueued", ("token",), {}),
        ("execution", "mark_dispatch_consumed", ("token",), {}),
        ("execution", "heartbeat_attempt", ("1", "worker"), {}),
        ("execution", "record_attempt_process", ("1", None), {}),
        (
            "execution",
            "request_agent_interaction",
            ("1", "permission", "Approve?", ()),
            {},
        ),
        ("execution", "scope_node_records", (MISSING_UUID, "root.child", ("work",)), {}),
        ("execution", "scope_node_record", (MISSING_UUID, "1"), {}),
        ("execution", "transition_scope_node", ("1", "dependencies_satisfied"), {}),
        ("execution", "mark_attempt_waiting", ("1", None), {}),
        ("execution", "release_attempt_lock", ("1",), {}),
        ("execution", "submit_control", ("1", "cancel", "owner", {}, 600.0), {}),
        ("execution", "claim_next_control", ("1", "worker"), {}),
        ("execution", "apply_control", ("1", "worker"), {}),
        ("execution", "recover_control_claims", (), {}),
        ("execution", "resolve_human_wait_controls", (), {}),
        ("execution", "expire_human_waits", (), {}),
        ("execution", "expire_scope_waits", (), {}),
        ("execution", "orphaned_dispatch_tokens", (), {}),
        ("execution", "reap_stale_attempts", (), {"orderly_shutdown": False}),
        ("execution", "request_run_cancellation", (MISSING_UUID, "owner"), {}),
        ("execution", "manual_rerun_target", (MISSING_UUID, "root.work", "owner"), {}),
        ("execution", "interrupted_targets", (), {}),
        ("execution", "interrupted_run_ids", (), {}),
    ],
)
def test_public_repository_calls_wrap_database_outages_in_relay_errors(
    port: str, method: str, arguments: tuple[object, ...], keywords: dict[str, object]
) -> None:
    stores = {
        "agents": DjangoAgentStore(),
        "projects": DjangoProjectStore(),
        "workflows": DjangoWorkflowStore(),
        "reads": DjangoReadStore(),
        "execution": DjangoExecutionStore(),
    }
    with (
        connection.execute_wrapper(unavailable_database),
        pytest.raises(PersistenceError) as raised,
    ):
        getattr(stores[port], method)(*arguments, **keywords)
    envelope = raised.value.to_envelope()
    assert envelope["code"] == "persistence_error"
    assert "private-database-diagnostic" not in str(envelope)


def test_concurrent_read_then_write_transactions_do_not_lose_updates_or_fail_with_busy_errors() -> (
    None
):
    Installation.objects.update_or_create(pk=1, defaults={"settings": {"counter": 0}})
    workers = 6
    started = threading.Barrier(workers)

    def increment(worker: int) -> None:
        del worker
        try:
            # Start together, before BEGIN IMMEDIATE serializes each read/write pair.
            started.wait()
            with transaction.atomic():
                installation = Installation.objects.get(pk=1)
                installation.settings["counter"] += 1
                installation.save(update_fields=("settings",))
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        list(executor.map(increment, range(workers)))

    assert Installation.objects.get(pk=1).settings == {"counter": workers}
