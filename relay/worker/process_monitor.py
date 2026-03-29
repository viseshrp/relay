from __future__ import annotations

import psutil
from sqlalchemy import select

from relay.db import DatabaseManager
from relay.models import Phase, PhaseAttempt, WorkflowRun


class ProcessMonitor:
    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    async def recover_orphans(self) -> None:
        await self.check_health()

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
                    continue
                if phase.status not in {"starting", "running"}:
                    continue
                phase.status = "failed"
                attempt.status = "failed"
                attempt.error_message = "process_lost"
                run.status = "failed"
            await session.commit()
