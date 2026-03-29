from __future__ import annotations

import asyncio
from contextlib import suppress
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from relay.models import Phase, WorkflowRun
from relay.realtime.log_tailer import ensure_file, tail_file, tail_jsonl

router = APIRouter(tags=["ws"])


async def _stream_logs(websocket: WebSocket, run_id: str) -> None:
    current_log_path: str | None = None
    current_stream_path: str | None = None
    log_task: asyncio.Task[None] | None = None
    chunk_task: asyncio.Task[None] | None = None

    async def forward_log_lines(run_id: str, phase_id: str, attempt_number: int, log_path: str) -> None:
        async for line in tail_file(log_path):
            await websocket.send_json(
                {
                    "type": "log",
                    "run_id": run_id,
                    "phase_id": phase_id,
                    "attempt_number": attempt_number,
                    "stream": "stdout",
                    "line": line,
                    "timestamp": "",
                }
            )

    async def forward_exploration_chunks(run_id: str, stream_path: str) -> None:
        async for payload in tail_jsonl(stream_path):
            payload["type"] = "exploration_chunk"
            payload["run_id"] = run_id
            await websocket.send_json(payload)

    try:
        while await websocket.app.state.connection_manager.is_subscribed(websocket, run_id):
            async with websocket.app.state.db.session() as session:
                run = (
                    await session.execute(
                        select(WorkflowRun)
                        .options(selectinload(WorkflowRun.phases).selectinload(Phase.attempts))
                        .where(WorkflowRun.id == run_id)
                    )
                ).scalar_one_or_none()
            if run is None:
                return
            running_phase = next((phase for phase in run.phases if phase.status == "running" and phase.attempts), None)
            if running_phase is not None:
                latest_attempt = running_phase.attempts[-1]
                if latest_attempt.log_file_path != current_log_path:
                    if log_task is not None:
                        log_task.cancel()
                    current_log_path = latest_attempt.log_file_path
                    ensure_file(Path(current_log_path))
                    log_task = asyncio.create_task(
                        forward_log_lines(run_id, running_phase.id, latest_attempt.attempt_number, current_log_path)
                    )
                if running_phase.phase_type == "exploration":
                    stream_path = websocket.app.state.settings.data_dir / "logs" / run_id / "exploration_stream.jsonl"
                    if str(stream_path) != current_stream_path:
                        if chunk_task is not None:
                            chunk_task.cancel()
                        current_stream_path = str(stream_path)
                        ensure_file(stream_path)
                        chunk_task = asyncio.create_task(forward_exploration_chunks(run_id, str(stream_path)))
            await asyncio.sleep(1.0)
    finally:
        for task in (log_task, chunk_task):
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    manager = websocket.app.state.connection_manager
    await manager.connect(websocket)
    stream_tasks: dict[str, asyncio.Task[None]] = {}
    try:
        while True:
            message = await websocket.receive_json()
            message_type = message.get("type")
            run_id = message.get("run_id")
            if message_type == "subscribe" and isinstance(run_id, str):
                await manager.subscribe(websocket, run_id)
                if run_id not in stream_tasks:
                    stream_tasks[run_id] = asyncio.create_task(_stream_logs(websocket, run_id))
            elif message_type == "unsubscribe" and isinstance(run_id, str):
                await manager.unsubscribe(websocket, run_id)
                task = stream_tasks.pop(run_id, None)
                if task is not None:
                    task.cancel()
            elif message_type == "subscribe_all":
                await manager.subscribe_all(websocket)
    except WebSocketDisconnect:
        pass
    finally:
        for task in stream_tasks.values():
            task.cancel()
        await manager.disconnect(websocket)
