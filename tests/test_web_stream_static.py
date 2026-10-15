"""Replayable HTTP streams and the public view boundary helpers."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
import json
from pathlib import Path
from typing import NoReturn

from asgiref.sync import sync_to_async
from django.contrib.auth.models import User
from django.core.exceptions import RequestDataTooBig
from django.db import connection, connections
from django.db.models.query import QuerySet
from django.http import HttpRequest, HttpResponse
from django.test import AsyncClient, RequestFactory, override_settings
import pytest

from relay.constants import DATABASE_INTEGER_MAX, SSE_MAX_FRAME_BYTES
from relay.errors import ConfigError, ProjectDiscoveryError
from relay.web.models import AutomaticRetry, RunEvent
from relay.web.views import (
    api_errors,
    canonical_record_id,
    canonical_uuid,
    current_project,
    log_context_value,
)
from tests.support import (
    FakeAgents,
    InlineEngine,
    RegistryNetwork,
    RelayProject,
    answer_wait,
    run_status,
)
from tests.test_usage_retries import limited_run


@pytest.fixture
def finished_run(project: RelayProject, engine: InlineEngine) -> str:
    project.write_workflow(
        "done",
        (
            "name: Done\n"
            "jobs:\n"
            "  a:\n"
            "    steps:\n"
            "    - id: work\n"
            "      uses: relay/command@v1\n"
            "      with:\n"
            '        argv: \'["git", "status"]\'\n'
        ),
    )
    run_id = engine.launch(project, "done")
    engine.drain(run_id)
    return run_id


def stream(
    path: str, *, login: bool = True, method: str = "get", **headers: str
) -> tuple[int, list[str], dict[str, object] | None]:
    async def fetch() -> tuple[int, list[str], dict[str, object] | None]:
        # The executor thread must close its connection before the temporary database
        # is replaced or removed, including on Windows where open files are locked.
        await sync_to_async(connections.close_all)()
        try:
            client = AsyncClient()
            if login:
                user, _created = await User.objects.aget_or_create(
                    username="owner", defaults={"is_superuser": True, "is_staff": True}
                )
                await client.aforce_login(user)
            response = await getattr(client, method)(path, headers=headers)
            if getattr(response, "streaming", False):
                chunks = [chunk.decode() async for chunk in response.streaming_content]
                return response.status_code, chunks, None
            return response.status_code, [], json.loads(response.content)
        finally:
            await sync_to_async(connections.close_all)()

    return asyncio.run(fetch())


def frame_ids(chunks: list[str]) -> list[int]:
    """Read the first SSE field: 'id: 42\nevent: done\n' yields 42."""
    return [int(chunk.split("\n", 1)[0].removeprefix("id: ")) for chunk in chunks]


def test_a_terminal_run_replays_every_event_and_ends(finished_run: str) -> None:
    stored = list(
        RunEvent.objects.filter(run_id=finished_run).order_by("id").values_list("id", flat=True)
    )

    status, chunks, _body = stream(f"/api/runs/{finished_run}/stream")

    assert status == 200
    assert frame_ids(chunks) == stored
    assert json.loads(chunks[0].split("data: ", 1)[1])["type"] == "run.created"


def test_terminal_events_committed_after_an_empty_read_are_replayed(
    finished_run: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    cursor = (
        RunEvent.objects.filter(run_id=finished_run)
        .order_by("id")
        .values_list("id", flat=True)
        .last()
    )
    committed: list[int] = []
    original_iterator = QuerySet.aiterator

    def commit_tail() -> None:
        for event_type in ("wait.answered", "attempt.ended", "run.succeeded"):
            event = RunEvent.objects.create(
                run_id=finished_run, type=event_type, source="system", payload={}
            )
            committed.append(event.pk)

    async def complete_after_read(
        query: QuerySet[RunEvent], chunk_size: int = 2000
    ) -> AsyncIterator[RunEvent]:
        async for row in original_iterator(query, chunk_size=chunk_size):
            yield row
        if not committed:
            # Completion can commit between the event read and the status read.
            await sync_to_async(commit_tail)()

    monkeypatch.setattr(QuerySet, "aiterator", complete_after_read)

    status, chunks, _body = stream(f"/api/runs/{finished_run}/stream?since={cursor}")

    assert status == 200
    assert len(committed) == 3
    assert frame_ids(chunks) == committed


@pytest.mark.parametrize("terminal", ["succeeded", "failed", "canceled"])
@pytest.mark.parametrize("page_rows", [0, 2, 3], ids=["empty", "partial", "full"])
def test_completion_between_event_and_status_reads_drains_every_batch(
    project: RelayProject,
    engine: InlineEngine,
    monkeypatch: pytest.MonkeyPatch,
    terminal: str,
    page_rows: int,
) -> None:
    command = "relay-test-missing-command" if terminal == "failed" else "status"
    project.write_workflow(
        "stream-race",
        (
            f"name: Stream race\n"
            f"jobs:\n"
            f"  review:\n"
            f"    steps:\n"
            f"    - id: work\n"
            f"      uses: relay/human-wait@v1\n"
            f"      with:\n"
            f"        prompt: Continue?\n"
            f"  finish:\n"
            f"    needs:\n"
            f"    - review\n"
            f"    steps:\n"
            f"    - id: work\n"
            f"      uses: relay/command@v1\n"
            f"      with:\n"
            f'        argv: \'["git", "{command}"]\'\n'
        ),
    )
    run_id = engine.launch(project, "stream-race")
    engine.drain(run_id)
    assert run_status(run_id) == "paused_wait"
    cursor = RunEvent.objects.filter(run_id=run_id).latest("id").pk
    RunEvent.objects.bulk_create(
        [
            RunEvent(run_id=run_id, type="command.stdout", source="command", payload={})
            for _ in range(page_rows)
        ]
    )
    # A small configured batch exercises all page boundaries with real rows.
    monkeypatch.setattr("relay.web.views.stream.SSE_MAX_BATCH", 3)
    original_iterator = QuerySet.aiterator
    completed = False

    def complete() -> None:
        if terminal == "canceled":
            engine.store.request_run_cancellation(run_id, "cancel-at-read-boundary")
            engine.store.resolve_human_wait_controls()
            engine.drain(run_id)
        else:
            assert answer_wait(engine, run_id) == "accepted"
        assert run_status(run_id) == terminal

    async def finish_after_page(
        query: QuerySet[RunEvent], chunk_size: int = 2000
    ) -> AsyncIterator[RunEvent]:
        nonlocal completed
        async for row in original_iterator(query, chunk_size=chunk_size):
            yield row
        if query.model is RunEvent and not completed:
            completed = True
            await sync_to_async(complete)()

    monkeypatch.setattr(QuerySet, "aiterator", finish_after_page)

    status, chunks, _body = stream(f"/api/runs/{run_id}/stream?since={cursor}")

    stored = list(
        RunEvent.objects.filter(run_id=run_id, id__gt=cursor)
        .order_by("id")
        .values_list("id", flat=True)
    )
    assert completed
    assert status == 200
    assert len(stored) > 3
    assert frame_ids(chunks) == stored
    assert any(f'"type":"run.{terminal}"' in chunk for chunk in chunks)


def test_a_stream_failure_reconnects_after_the_last_delivered_page(
    finished_run: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    stored = list(
        RunEvent.objects.filter(run_id=finished_run).order_by("id").values_list("id", flat=True)
    )
    original_iterator = QuerySet.aiterator
    reads = 0

    async def fail_second_page(
        query: QuerySet[RunEvent], chunk_size: int = 2000
    ) -> AsyncIterator[RunEvent]:
        nonlocal reads
        if query.model is RunEvent:
            reads += 1
            if reads == 2:
                message = "private database diagnostic"
                raise OSError(message)
        async for row in original_iterator(query, chunk_size=chunk_size):
            yield row

    with monkeypatch.context() as patch:
        patch.setattr("relay.web.views.stream.SSE_MAX_BATCH", 1)
        patch.setattr(QuerySet, "aiterator", fail_second_page)
        status, chunks, _body = stream(f"/api/runs/{finished_run}/stream")

    assert status == 200
    assert frame_ids(chunks) == [stored[0], stored[0]]
    error = json.loads(chunks[-1].split("data: ", 1)[1])
    assert error["payload"]["code"] == "stream_error"
    assert "private database diagnostic" not in "".join(chunks)

    status, resumed, _body = stream(
        f"/api/runs/{finished_run}/stream", **{"Last-Event-ID": str(stored[0])}
    )
    assert status == 200
    assert frame_ids(chunks[:-1] + resumed) == stored


@pytest.mark.parametrize("state", ["scheduled", "preparing"])
def test_an_automatic_recovery_keeps_a_failed_stream_open_until_canceled(
    project: RelayProject,
    tmp_path: Path,
    fake_agents: FakeAgents,
    registry_network: RegistryNetwork,
    monkeypatch: pytest.MonkeyPatch,
    state: str,
) -> None:
    from tests.test_automatic_recovery import ReportDriver, launch_report_run

    del registry_network
    engine, run_id = launch_report_run(project, tmp_path, fake_agents, ReportDriver())
    engine.store.configure_recovery(run_id, True, "enable-stream-recovery")
    retry = AutomaticRetry.objects.get(attempt__node_run__run_id=run_id)
    AutomaticRetry.objects.filter(pk=retry.pk).update(state=state)
    polls = 0

    async def cancel_at_poll(_interval: float) -> None:
        nonlocal polls
        polls += 1
        await sync_to_async(engine.store.request_run_cancellation)(run_id, "stop-recovery")

    monkeypatch.setattr("relay.web.views.stream.asyncio.sleep", cancel_at_poll)

    status, chunks, _body = stream(f"/api/runs/{run_id}/stream")

    assert status == 200
    assert polls == 1
    assert any('"type":"run.recovery_canceled"' in chunk for chunk in chunks)
    retry.refresh_from_db()
    assert retry.state == "canceled"


@override_settings(RELAY_LOGIN_REQUIRED=False)
def test_disconnecting_during_a_live_poll_propagates_cancellation(
    project: RelayProject, engine: InlineEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    project.write_workflow(
        "disconnect",
        (
            "name: Disconnect\n"
            "jobs:\n"
            "  review:\n"
            "    steps:\n"
            "    - id: work\n"
            "      uses: relay/human-wait@v1\n"
            "      with:\n"
            "        prompt: Continue?\n"
        ),
    )
    run_id = engine.launch(project, "disconnect")
    engine.drain(run_id)
    cursor = RunEvent.objects.filter(run_id=run_id).latest("id").pk

    async def disconnect() -> None:
        polling = asyncio.Event()

        async def hold_poll(_interval: float) -> None:
            polling.set()
            await asyncio.Future()

        monkeypatch.setattr("relay.web.views.stream.asyncio.sleep", hold_poll)
        await sync_to_async(connections.close_all)()
        response = await AsyncClient().get(f"/api/runs/{run_id}/stream?since={cursor}")
        assert response.status_code == 200
        iterator = response.streaming_content
        pending = asyncio.create_task(anext(iterator))
        try:
            await asyncio.wait_for(polling.wait(), timeout=5)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
        finally:
            pending.cancel()
            with suppress(asyncio.CancelledError):
                await pending
            await iterator.aclose()
            await sync_to_async(connections.close_all)()

    asyncio.run(disconnect())
    assert run_status(run_id) == "paused_wait"
    assert RunEvent.objects.filter(run_id=run_id).latest("id").pk == cursor


@override_settings(RELAY_LOGIN_REQUIRED=False)
def test_disabled_login_replays_live_events_without_a_session(finished_run: str) -> None:
    stored = list(
        RunEvent.objects.filter(run_id=finished_run).order_by("id").values_list("id", flat=True)
    )

    status, chunks, _body = stream(f"/api/runs/{finished_run}/stream", login=False)

    assert status == 200
    assert frame_ids(chunks) == stored
    assert not User.objects.exists()


def test_a_scheduled_job_streams_until_the_owner_cancels_its_retry(
    project: RelayProject,
    engine: InlineEngine,
    fake_agents: FakeAgents,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import timedelta

    from django.utils import timezone

    run_id, _ = limited_run(project, engine, fake_agents, timezone.now() + timedelta(hours=1))

    def cancel() -> None:
        engine.store.request_run_cancellation(run_id, "stop-schedule")
        engine.drain(run_id)

    async def cancel_at_poll(_interval: float) -> None:
        await sync_to_async(cancel)()

    monkeypatch.setattr("relay.web.views.stream.asyncio.sleep", cancel_at_poll)
    status, chunks, _body = stream(f"/api/runs/{run_id}/stream")
    assert status == 200
    assert any('"type":"run.retry_canceled"' in chunk for chunk in chunks)


@pytest.mark.parametrize("header", [False, True], ids=["url-cursor", "header-takes-priority"])
def test_reconnection_replays_only_events_after_the_cursor(finished_run: str, header: bool) -> None:
    stored = list(
        RunEvent.objects.filter(run_id=finished_run).order_by("id").values_list("id", flat=True)
    )
    if header:
        status, chunks, _body = stream(
            f"/api/runs/{finished_run}/stream?since=0", **{"Last-Event-ID": str(stored[2])}
        )
    else:
        status, chunks, _body = stream(f"/api/runs/{finished_run}/stream?since={stored[2]}")

    assert status == 200
    assert frame_ids(chunks) == stored[3:]


def test_an_oversized_event_is_replaced_by_a_bounded_error_frame(finished_run: str) -> None:
    event = RunEvent.objects.create(
        run_id=finished_run,
        type="agent.message",
        source="agent",
        payload={"text": "x" * SSE_MAX_FRAME_BYTES},
    )

    status, chunks, _body = stream(f"/api/runs/{finished_run}/stream?since={event.pk - 1}")

    assert status == 200
    assert frame_ids(chunks) == [event.pk]
    assert len(chunks[0].encode()) <= SSE_MAX_FRAME_BYTES
    payload = json.loads(chunks[0].split("data: ", 1)[1])
    assert payload["payload"]["code"] == "sse_frame_too_large"


@pytest.mark.parametrize("separator", ["\r", "\n", "\r\n"])
def test_corrupted_event_types_cannot_inject_sse_fields(finished_run: str, separator: str) -> None:
    event = RunEvent.objects.create(
        run_id=finished_run,
        type=f"agent.message{separator}event: forged",
        source="agent",
        payload={},
    )

    _status, chunks, _body = stream(f"/api/runs/{finished_run}/stream?since={event.pk - 1}")

    fields = chunks[0].splitlines()
    assert frame_ids(chunks) == [event.pk]
    assert sum(line.startswith("event:") for line in fields) == 1
    assert fields[1] == f"event: agent.message{' ' * len(separator)}event: forged"


@pytest.mark.parametrize(
    ("suffix", "login", "method", "status", "code"),
    [
        ("stream", False, "get", 401, "authentication_required"),
        ("stream", True, "post", 405, "method_not_allowed"),
        ("stream?since=-5", True, "get", 400, "config_error"),
        ("stream?since=abc", True, "get", 400, "config_error"),
        (f"stream?since={DATABASE_INTEGER_MAX + 1}", True, "get", 400, "config_error"),
    ],
)
def test_stream_requests_are_validated(
    finished_run: str, suffix: str, login: bool, method: str, status: int, code: str
) -> None:
    actual_status, _chunks, body = stream(
        f"/api/runs/{finished_run}/{suffix}", login=login, method=method
    )
    assert body is not None
    assert (actual_status, body["code"]) == (status, code)


@pytest.mark.parametrize("run_id", ["not-a-uuid", "00000000-0000-0000-0000-000000000000"])
def test_unknown_runs_are_not_streamed(run_id: str) -> None:
    assert stream(f"/api/runs/{run_id}/stream")[0] == 404


def test_view_log_values_escape_line_breaks() -> None:
    assert log_context_value("run\nforged\rline") == "run\\nforged\\rline"


def test_uuid_route_values_are_canonicalized() -> None:
    assert canonical_uuid("550E8400E29B41D4A716446655440000", resource="run") == (
        "550e8400-e29b-41d4-a716-446655440000"
    )


def test_record_route_values_allow_leading_zeroes() -> None:
    assert canonical_record_id("00042", resource="attempt") == "42"


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "x", "\uff11", str(DATABASE_INTEGER_MAX + 1)])
def test_invalid_record_route_values_are_not_found(value: str) -> None:
    with pytest.raises(ProjectDiscoveryError):
        canonical_record_id(value, resource="attempt")


def test_invalid_uuid_route_values_are_not_found() -> None:
    with pytest.raises(ProjectDiscoveryError):
        canonical_uuid("nope", resource="run")


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (RuntimeError("secret internal detail"), 500, "internal_error"),
        (RequestDataTooBig("too large"), 400, "config_error"),
        (ConfigError("bad input"), 400, "config_error"),
    ],
)
def test_view_errors_use_stable_json_envelopes(error: Exception, status: int, code: str) -> None:
    @api_errors
    def failing(request: HttpRequest) -> HttpResponse:
        del request
        raise error

    response = failing(RequestFactory().get("/api/test"))

    assert response.status_code == status
    assert json.loads(response.content)["code"] == code
    assert b"secret internal detail" not in response.content


def test_the_served_project_is_registered_once(
    project: RelayProject, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RELAY_PROJECT_ROOT", str(project.repository))
    first_root, first = current_project()

    def unexpected_query(
        execute: Callable[..., object],
        sql: str,
        params: object,
        many: bool,
        context: dict[str, object],
    ) -> NoReturn:
        del execute, sql, params, many, context
        message = "Resolving the served project again must not access the database."
        raise AssertionError(message)

    def unexpected_subprocess(*args: object, **kwargs: object) -> NoReturn:
        del args, kwargs
        message = "Resolving the served project again must not repeat Git discovery."
        raise AssertionError(message)

    # Observe both external boundaries; equal cached objects alone cannot prove
    # that a later request avoided registration and its last_opened_at update.
    monkeypatch.setattr("relay.vcs.git.subprocess.run", unexpected_subprocess)
    with connection.execute_wrapper(unexpected_query):
        second_root, second = current_project()

    assert first_root == second_root == project.relay_root.resolve()
    assert first == second
