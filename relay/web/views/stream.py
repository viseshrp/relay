"""Authenticated, replayable Server-Sent Events for one durable run."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timezone
import json
import logging
import uuid

from django.db import connections
from django.http import HttpRequest, JsonResponse, StreamingHttpResponse

from relay.constants import (
    DATABASE_INTEGER_MAX,
    SSE_MAX_BATCH,
    SSE_MAX_FRAME_BYTES,
    SSE_POLL_INTERVAL_SECONDS,
)
from relay.execution.state import TERMINAL_RUN_STATUSES

from ..models import Run, RunEvent
from . import log_context_value

LOGGER = logging.getLogger(__name__)
_TERMINAL = {item.value for item in TERMINAL_RUN_STATUSES}


def _error(code: str, message: str, status: int) -> JsonResponse:
    return JsonResponse({"code": code, "message": message, "context": {}}, status=status)


def _cursor(request: HttpRequest) -> int:
    raw = request.headers.get("Last-Event-ID", "0")
    try:
        value = int(raw)
    except ValueError:
        return -1
    return value if 0 <= value <= DATABASE_INTEGER_MAX else -1


def _event_dict(row: RunEvent) -> dict[str, object]:
    timestamp = getattr(row, "ts", None)
    return {
        "id": row.pk,
        "type": getattr(row, "type", "error"),
        "version": getattr(row, "version", 1),
        "source": getattr(row, "source", "system"),
        "ts": timestamp.isoformat() if isinstance(timestamp, datetime) else "",
        "payload": getattr(row, "payload", {}),
    }


def _frame(row: RunEvent) -> bytes:
    """Encode one row as one frame and neutralize line breaks in its type.

    An internal type ``agent.message`` stays unchanged. A corrupted type
    ``agent.message\nignored`` is rendered as ``agent.message ignored`` so it
    cannot inject another SSE field.
    """
    stored_type = getattr(row, "type", "error")
    event_type = (
        stored_type.replace("\r", " ").replace("\n", " ")
        if isinstance(stored_type, str)
        else "error"
    )
    timestamp = getattr(row, "ts", None)
    data = json.dumps(
        _event_dict(row),
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=False,
    )
    frame = f"id: {row.pk}\nevent: {event_type}\ndata: {data}\n\n".encode()
    if len(frame) <= SSE_MAX_FRAME_BYTES:
        return frame
    envelope = {
        "id": row.pk,
        "type": "error",
        "version": 1,
        "source": "system",
        "ts": timestamp.isoformat() if isinstance(timestamp, datetime) else "",
        "payload": {
            "code": "sse_frame_too_large",
            "message": "A stored event exceeds the live-stream frame limit.",
            "context": {"event_id": str(row.pk)},
            "next_action": "Load this event from the paginated run history.",
        },
    }
    encoded = json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode()
    return f"id: {row.pk}\nevent: error\ndata: {encoded.decode()}\n\n".encode()


async def _stream(run_id: str, after: int) -> AsyncIterator[bytes]:
    cursor = after
    try:
        while True:
            query = RunEvent.objects.filter(run_id=run_id, id__gt=cursor).order_by("id")[
                :SSE_MAX_BATCH
            ]
            rows = [row async for row in query.aiterator(chunk_size=SSE_MAX_BATCH)]
            for row in rows:
                cursor = row.pk
                yield _frame(row)
            if len(rows) == SSE_MAX_BATCH:
                continue
            status = await Run.objects.filter(pk=run_id).values_list("status", flat=True).afirst()
            if status is None or status in _TERMINAL:
                return
            await asyncio.sleep(SSE_POLL_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        raise
    except Exception:
        LOGGER.exception(
            "Relay SSE stream failed",
            extra={"run_id": log_context_value(run_id), "cursor": cursor},
        )
        payload = {
            "id": cursor,
            "type": "error",
            "version": 1,
            "source": "system",
            "ts": datetime.now(timezone.utc).isoformat(),
            "payload": {
                "code": "stream_error",
                "message": "Relay could not continue the live event stream.",
                "context": {"run": run_id},
                "next_action": "Reconnect with the last received event id.",
            },
        }
        data = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        yield f"id: {cursor}\nevent: error\ndata: {data}\n\n".encode()
    finally:
        await asyncio.to_thread(connections.close_all)


async def run_stream(request: HttpRequest, run_id: str) -> StreamingHttpResponse | JsonResponse:
    """Replay rows after `Last-Event-ID`, then follow new rows until terminal."""
    if request.method != "GET":
        response = _error(
            "method_not_allowed",
            "This Relay API route accepts only GET.",
            405,
        )
        response["Allow"] = "GET"
        return response
    resolve_user = getattr(request, "auser", None)
    if not callable(resolve_user):
        return _error("internal_error", "Relay could not read the owner session.", 500)
    user = await resolve_user()
    if not bool(getattr(user, "is_authenticated", False)):
        return _error("authentication_required", "Sign in to the local Relay owner account.", 401)
    after = _cursor(request)
    if after < 0:
        return _error(
            "config_error",
            "Last-Event-ID must be within Relay's nonnegative database integer range.",
            400,
        )
    try:
        uuid.UUID(run_id)
    except ValueError:
        return _error("not_found", "The requested run does not exist.", 404)
    if not await Run.objects.filter(pk=run_id).aexists():
        return _error("not_found", "The requested run does not exist.", 404)
    response = StreamingHttpResponse(_stream(run_id, after), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


__all__ = ["run_stream"]
