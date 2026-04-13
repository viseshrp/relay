from __future__ import annotations

import asyncio
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from relay.artifacts.manager import artifact_dir
from relay.db import DatabaseManager
from relay.models import Phase, PhaseAttempt, WorkflowRun
from relay.realtime.connection_manager import ConnectionManager


class StatusNotifier:
    def __init__(self, db: DatabaseManager, connection_manager: ConnectionManager) -> None:
        self.db = db
        self.connection_manager = connection_manager
        self._stop = asyncio.Event()
        self._workflow_cache: dict[str, str] = {}
        self._phase_cache: dict[str, tuple[str, int]] = {}

    async def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        while not self._stop.is_set():
            await self._poll_once()
            await asyncio.sleep(1.0)

    async def _poll_once(self) -> None:
        async with self.db.session() as session:
            runs = (
                await session.execute(
                    select(WorkflowRun)
                    .options(selectinload(WorkflowRun.phases).selectinload(Phase.attempts), selectinload(WorkflowRun.project))
                )
            ).scalars().all()
            for run in runs:
                if self._workflow_cache.get(run.id) != run.status:
                    self._workflow_cache[run.id] = run.status
                    await self.connection_manager.broadcast(
                        {
                            "type": "workflow_status",
                            "run_id": run.id,
                            "status": run.status,
                            "timestamp": run.updated_at,
                        },
                        run.id,
                    )
                for phase in run.phases:
                    cache_key = f"{run.id}:{phase.id}"
                    cache_value = (phase.status, phase.current_attempt)
                    if self._phase_cache.get(cache_key) == cache_value:
                        continue
                    self._phase_cache[cache_key] = cache_value
                    await self.connection_manager.broadcast(
                        {
                            "type": "phase_status",
                            "run_id": run.id,
                            "phase_id": phase.id,
                            "phase_type": phase.phase_type,
                            "status": phase.status,
                            "attempt_number": phase.current_attempt,
                            "timestamp": phase.updated_at,
                        },
                        run.id,
                    )
                    if phase.phase_type == "review" and phase.status == "succeeded":
                        await self._emit_review_results(run, phase)
                    if phase.phase_type == "exploration" and phase.status in {"succeeded", "waiting_for_user"}:
                        await self._emit_exploration_finalized(run)
                    if phase.status == "failed":
                        latest_attempt = phase.attempts[-1] if phase.attempts else None
                        await self.connection_manager.broadcast(
                            {
                                "type": "error",
                                "run_id": run.id,
                                "message": latest_attempt.error_message if latest_attempt else "Phase failed.",
                                "phase_type": phase.phase_type,
                                "timestamp": phase.updated_at,
                            },
                            run.id,
                        )

    async def _emit_review_results(self, run: WorkflowRun, phase: Phase) -> None:
        if run.project is None:
            return
        review_dir = artifact_dir(run.project.path, run.id, "review")
        summary_path = review_dir / "REVIEW_SUMMARY.md"
        comments_path = review_dir / "REVIEW_COMMENTS.json"
        summary = summary_path.read_text(encoding="utf-8") if summary_path.exists() else ""
        comments = json.loads(comments_path.read_text(encoding="utf-8")) if comments_path.exists() else []
        verdict = "FAIL"
        for line in summary.splitlines():
            if line.strip() in {"PASS", "FAIL", "PASS_WITH_WARNINGS"}:
                verdict = line.strip()
        await self.connection_manager.broadcast(
            {
                "type": "review_results",
                "run_id": run.id,
                "phase_id": phase.id,
                "attempt_number": phase.current_attempt,
                "verdict": verdict,
                "comment_count": len(comments),
                "summary_preview": summary[:500],
            },
            run.id,
        )

    async def _emit_exploration_finalized(self, run: WorkflowRun) -> None:
        if run.project is None:
            return
        prompt_path = artifact_dir(run.project.path, run.id, "exploration") / "planning_prompt.md"
        if not prompt_path.exists():
            return
        await self.connection_manager.broadcast(
            {
                "type": "exploration_finalized",
                "run_id": run.id,
                "planning_prompt_preview": prompt_path.read_text(encoding="utf-8")[:500],
            },
            run.id,
        )
