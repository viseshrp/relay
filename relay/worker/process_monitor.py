from __future__ import annotations

import logging

import psutil
from sqlalchemy import select

from relay.db import DatabaseManager
from relay.models import Phase, PhaseAttempt, WorkflowRun
from relay.worker.retry import backoff_seconds, can_retry


logger = logging.getLogger(__name__)


class ProcessMonitor:
    def __init__(self, db: DatabaseManager) -> None:
        self.db = db
        self._monitored_pids: set[int] = set()

    async def recover_orphans(self) -> None:
        async with self.db.session() as session:
            attempts = (
                await session.execute(
                    select(PhaseAttempt, Phase, WorkflowRun)
                    .join(Phase, PhaseAttempt.phase_id == Phase.id)
                    .join(WorkflowRun, Phase.workflow_run_id == WorkflowRun.id)
                    .where(Phase.status.in_(["starting", "running"]))
                )
            ).all()
            for attempt, phase, run in attempts:
                if attempt.pid is None:
                    continue
                if psutil.pid_exists(attempt.pid):
                    self._monitored_pids.add(attempt.pid)
                    logger.info(
                        "Re-adopted orphaned process PID %s for phase %s (stdout/stderr monitoring unavailable)",
                        attempt.pid,
                        phase.phase_type,
                    )
                    continue
                await self._handle_process_loss(
                    attempt=attempt,
                    phase=phase,
                    run=run,
                    error_message="process_lost_worker_restart",
                )
            await session.commit()

    async def check_health(self) -> None:
        async with self.db.session() as session:
            attempts = (
                await session.execute(
                    select(PhaseAttempt, Phase, WorkflowRun)
                    .join(Phase, PhaseAttempt.phase_id == Phase.id)
                    .join(WorkflowRun, Phase.workflow_run_id == WorkflowRun.id)
                    .where(Phase.status.in_(["starting", "running"]))
                )
            ).all()
            for attempt, phase, run in attempts:
                if attempt.pid is None:
                    continue
                if psutil.pid_exists(attempt.pid):
                    self._monitored_pids.add(attempt.pid)
                    continue
                if phase.status not in {"starting", "running"}:
                    continue
                await self._handle_process_loss(attempt=attempt, phase=phase, run=run, error_message="process_lost")
            await session.commit()

    async def _handle_process_loss(
        self,
        *,
        attempt: PhaseAttempt,
        phase: Phase,
        run: WorkflowRun,
        error_message: str,
    ) -> None:
        timestamp = run.updated_at = phase.updated_at = _utc_now()
        attempt.status = "failed"
        attempt.error_message = error_message
        attempt.ended_at = timestamp
        if attempt.pid is not None:
            self._monitored_pids.discard(attempt.pid)
        if can_retry(attempt.attempt_number, run.retry_limit):
            retry_delay = backoff_seconds(attempt.attempt_number)
            phase.status = "retrying"
            logger.warning(
                "Lost PID %s for run %s phase %s; scheduling retry in %ss",
                attempt.pid,
                run.id,
                phase.phase_type,
                retry_delay,
            )
            return
        phase.status = "failed"
        run.status = "failed"


def _utc_now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
