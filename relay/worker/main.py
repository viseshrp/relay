from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from relay.config import get_settings
from relay.db import DatabaseManager
from relay.models import Phase, UserSetting, WorkflowRun
from relay.worker.orchestrator import TERMINAL_WORKFLOW_STATES, WorkflowRuntime, advance_workflow
from relay.worker.process_monitor import ProcessMonitor
from relay.worker.scheduler import Scheduler


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


async def _set_worker_metadata(db: DatabaseManager, key: str, value: object) -> None:
    async with db.session() as session:
        row = await session.get(UserSetting, key)
        payload = json.dumps(value)
        if row is None:
            session.add(UserSetting(key=key, value=payload, updated_at=_utc_now()))
        else:
            row.value = payload
            row.updated_at = _utc_now()
        await session.commit()


async def _handle_passive_cancellations(db: DatabaseManager) -> None:
    async with db.session() as session:
        runs = (
            await session.execute(
                select(WorkflowRun)
                .options(selectinload(WorkflowRun.phases))
                .where(
                    WorkflowRun.cancel_requested.is_(True),
                    WorkflowRun.status.in_(["queued", "waiting_for_user"]),
                )
            )
        ).scalars().all()
        for run in runs:
            run.status = "cancelled"
            run.cancel_requested = False
            for phase in run.phases:
                if phase.status in {"queued", "waiting_for_user"}:
                    phase.status = "cancelled"
        await session.commit()


async def _pick_next_run_id(db: DatabaseManager, active_ids: set[str]) -> str | None:
    async with db.session() as session:
        runs = (
            await session.execute(
                select(WorkflowRun)
                .options(selectinload(WorkflowRun.phases))
                .where(WorkflowRun.status.in_(["queued", "running"]))
                .order_by(WorkflowRun.created_at.asc())
            )
        ).scalars().all()
        for run in runs:
            if run.id in active_ids:
                continue
            # Re-adopted subprocesses continue to own the phase until the
            # process monitor marks them lost. Starting the run again here would
            # spawn a duplicate subprocess for the same phase.
            if any(phase.status in {"starting", "running"} for phase in run.phases):
                continue
            return run.id
    return None


async def run_worker() -> None:
    settings = get_settings()
    db = DatabaseManager(settings.db_path)
    scheduler = Scheduler()
    monitor = ProcessMonitor(db)
    runtimes: dict[str, WorkflowRuntime] = {}
    active_tasks: dict[str, asyncio.Task[str]] = {}
    last_health_check = 0.0

    await _set_worker_metadata(db, "worker_status", "running")
    await _set_worker_metadata(db, "worker_concurrency_limit", scheduler.concurrency_limit)
    await monitor.recover_orphans()

    async def run_workflow(run_id: str) -> str:
        runtime = runtimes.setdefault(run_id, WorkflowRuntime())
        while True:
            outcome = await advance_workflow(db, settings, run_id=run_id, runtime=runtime)
            if outcome in TERMINAL_WORKFLOW_STATES or outcome in {"waiting_for_user", "idle"}:
                return outcome
            await asyncio.sleep(0)

    try:
        while True:
            await _set_worker_metadata(db, "worker_heartbeat", _utc_now())
            await _handle_passive_cancellations(db)

            finished = [run_id for run_id, task in active_tasks.items() if task.done()]
            for run_id in finished:
                task = active_tasks.pop(run_id)
                try:
                    outcome = task.result()
                except Exception:
                    outcome = "failed"
                if outcome in TERMINAL_WORKFLOW_STATES:
                    runtime = runtimes.pop(run_id, None)
                    if runtime is not None:
                        await runtime.shutdown()

            if scheduler.has_capacity(len(active_tasks)):
                run_id = await _pick_next_run_id(db, set(active_tasks))
                if run_id is not None:
                    active_tasks[run_id] = asyncio.create_task(run_workflow(run_id))

            now = time.monotonic()
            if now - last_health_check >= settings.process_monitor_interval_seconds:
                await monitor.check_health()
                last_health_check = now
            await asyncio.sleep(settings.poll_interval_seconds)
    finally:
        await _set_worker_metadata(db, "worker_status", "stopped")
        for runtime in runtimes.values():
            await runtime.shutdown()
        await db.dispose()
