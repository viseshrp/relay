from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from relay.models import ExplorationMessage, Phase, WorkflowRun
from relay.schemas.exploration import (
    ExplorationContextResponse,
    ExplorationContextUpdateRequest,
    ExplorationFinalizeResponse,
    ExplorationMessageCreateRequest,
    ExplorationMessageResponse,
)

router = APIRouter(prefix="/runs/{run_id}/exploration", tags=["exploration"])


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


async def _load_run(session, run_id: str) -> WorkflowRun | None:
    return (
        await session.execute(
            select(WorkflowRun)
            .options(
                selectinload(WorkflowRun.phases),
                selectinload(WorkflowRun.exploration_messages),
            )
            .where(WorkflowRun.id == run_id)
        )
    ).scalar_one_or_none()


@router.post("/messages", response_model=ExplorationMessageResponse)
async def post_message(
    request: Request,
    run_id: str,
    payload: ExplorationMessageCreateRequest,
) -> ExplorationMessageResponse:
    async with request.app.state.db.session() as session:
        run = await _load_run(session, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        phase = next(item for item in run.phases if item.phase_type == "exploration")
        if phase.status in {"waiting_for_user", "succeeded", "failed", "cancelled"} or run.finalize_requested:
            raise HTTPException(status_code=400, detail="Exploration is no longer accepting messages.")
        next_sequence = max([message.sequence_number for message in run.exploration_messages], default=0) + 1
        message = ExplorationMessage(
            id=str(uuid.uuid4()),
            workflow_run_id=run.id,
            role="user",
            content=payload.content,
            sequence_number=next_sequence,
            created_at=_utc_now(),
        )
        session.add(message)
        if run.status == "queued":
            run.status = "running"
        await session.commit()
        return ExplorationMessageResponse.model_validate(message)


@router.get("/messages", response_model=list[ExplorationMessageResponse])
async def get_messages(request: Request, run_id: str) -> list[ExplorationMessageResponse]:
    async with request.app.state.db.session() as session:
        run = await _load_run(session, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        return [ExplorationMessageResponse.model_validate(item) for item in run.exploration_messages]


@router.post("/finalize", response_model=ExplorationFinalizeResponse)
async def finalize_exploration(request: Request, run_id: str) -> ExplorationFinalizeResponse:
    async with request.app.state.db.session() as session:
        run = await _load_run(session, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        phase = next(item for item in run.phases if item.phase_type == "exploration")
        if phase.status in {"waiting_for_user", "succeeded"}:
            raise HTTPException(status_code=400, detail="Exploration is already finalized.")
        if not run.exploration_messages:
            raise HTTPException(status_code=400, detail="Exploration must contain at least one message before finalizing.")
        run.finalize_requested = True
        if run.status == "queued":
            run.status = "running"
        await session.commit()
        return ExplorationFinalizeResponse(run_id=run.id, finalize_requested=True)


@router.put("/context", response_model=ExplorationContextResponse)
async def update_context(
    request: Request,
    run_id: str,
    payload: ExplorationContextUpdateRequest,
) -> ExplorationContextResponse:
    async with request.app.state.db.session() as session:
        run = await _load_run(session, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        phase = next(item for item in run.phases if item.phase_type == "exploration")
        if phase.status in {"waiting_for_user", "succeeded", "failed", "cancelled"}:
            raise HTTPException(status_code=400, detail="Exploration context is immutable after finalization.")
        run.context_paths = json.dumps(payload.context_paths)
        await session.commit()
        return ExplorationContextResponse(run_id=run.id, context_paths=payload.context_paths)


@router.get("/context", response_model=ExplorationContextResponse)
async def get_context(request: Request, run_id: str) -> ExplorationContextResponse:
    async with request.app.state.db.session() as session:
        run = await session.get(WorkflowRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        return ExplorationContextResponse(run_id=run.id, context_paths=json.loads(run.context_paths))
