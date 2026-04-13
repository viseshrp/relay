from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from relay.models import Phase, PhaseAttempt
from relay.schemas.phase import AttemptDetailResponse, LogResponse, PhaseDetailResponse, PromptResponse, ReviewCommentResponse


def _serialize_attempt(attempt: PhaseAttempt) -> AttemptDetailResponse:
    return AttemptDetailResponse(
        id=attempt.id,
        phase_id=attempt.phase_id,
        attempt_number=attempt.attempt_number,
        status=attempt.status,
        pid=attempt.pid,
        exit_code=attempt.exit_code,
        started_at=attempt.started_at,
        ended_at=attempt.ended_at,
        error_message=attempt.error_message,
        log_file_path=attempt.log_file_path,
        rendered_prompt=attempt.rendered_prompt,
        review_comments=[
            ReviewCommentResponse(
                id=comment.id,
                file_path=comment.file_path,
                line_number=comment.line_number,
                severity=comment.severity,
                comment=comment.comment,
            )
            for comment in attempt.review_comments
        ],
    )


class PhaseService:
    async def list_phases(self, session: AsyncSession, run_id: str) -> list[PhaseDetailResponse]:
        phases = (
            await session.execute(
                select(Phase)
                .options(selectinload(Phase.attempts).selectinload(PhaseAttempt.review_comments))
                .where(Phase.workflow_run_id == run_id)
                .order_by(Phase.sequence_number.asc())
            )
        ).scalars().all()
        return [self._serialize_phase(phase) for phase in phases]

    async def get_phase(self, session: AsyncSession, run_id: str, phase_id: str) -> PhaseDetailResponse:
        phase = (
            await session.execute(
                select(Phase)
                .options(selectinload(Phase.attempts).selectinload(PhaseAttempt.review_comments))
                .where(Phase.workflow_run_id == run_id, Phase.id == phase_id)
            )
        ).scalar_one_or_none()
        if phase is None:
            raise ValueError("Phase not found.")
        return self._serialize_phase(phase)

    async def get_attempt(
        self,
        session: AsyncSession,
        run_id: str,
        phase_id: str,
        attempt_number: int,
    ) -> AttemptDetailResponse:
        attempt = (
            await session.execute(
                select(PhaseAttempt)
                .join(Phase)
                .options(selectinload(PhaseAttempt.review_comments))
                .where(
                    Phase.workflow_run_id == run_id,
                    Phase.id == phase_id,
                    PhaseAttempt.attempt_number == attempt_number,
                )
            )
        ).scalar_one_or_none()
        if attempt is None:
            raise ValueError("Attempt not found.")
        return _serialize_attempt(attempt)

    async def get_logs(
        self,
        session: AsyncSession,
        run_id: str,
        phase_id: str,
        attempt_number: int,
        offset: int = 0,
    ) -> LogResponse:
        attempt = await self.get_attempt(session, run_id, phase_id, attempt_number)
        log_path = Path(attempt.log_file_path)
        if not log_path.exists():
            return LogResponse(lines=[], next_offset=offset)
        lines = log_path.read_text(encoding="utf-8").splitlines(keepends=True)
        return LogResponse(lines=lines[offset:], next_offset=len(lines))

    async def get_latest_prompt(self, session: AsyncSession, run_id: str, phase_id: str) -> PromptResponse:
        phase = (
            await session.execute(
                select(Phase)
                .options(selectinload(Phase.attempts))
                .where(Phase.workflow_run_id == run_id, Phase.id == phase_id)
            )
        ).scalar_one_or_none()
        if phase is None or not phase.attempts:
            raise ValueError("Prompt not found.")
        return PromptResponse(prompt=phase.attempts[-1].rendered_prompt)

    def _serialize_phase(self, phase: Phase) -> PhaseDetailResponse:
        return PhaseDetailResponse(
            id=phase.id,
            workflow_run_id=phase.workflow_run_id,
            phase_type=phase.phase_type,
            sequence_number=phase.sequence_number,
            status=phase.status,
            current_attempt=phase.current_attempt,
            attempts=[_serialize_attempt(attempt) for attempt in phase.attempts],
        )
