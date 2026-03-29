from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from relay.schemas.phase import AttemptDetailResponse, LogResponse, PhaseDetailResponse, PromptResponse

router = APIRouter(prefix="/runs/{run_id}/phases", tags=["phases"])


@router.get("", response_model=list[PhaseDetailResponse])
async def list_phases(request: Request, run_id: str) -> list[PhaseDetailResponse]:
    async with request.app.state.db.session() as session:
        return await request.app.state.phase_service.list_phases(session, run_id)


@router.get("/{phase_id}", response_model=PhaseDetailResponse)
async def get_phase(request: Request, run_id: str, phase_id: str) -> PhaseDetailResponse:
    async with request.app.state.db.session() as session:
        try:
            return await request.app.state.phase_service.get_phase(session, run_id, phase_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{phase_id}/attempts/{attempt_number}", response_model=AttemptDetailResponse)
async def get_attempt(request: Request, run_id: str, phase_id: str, attempt_number: int) -> AttemptDetailResponse:
    async with request.app.state.db.session() as session:
        try:
            return await request.app.state.phase_service.get_attempt(session, run_id, phase_id, attempt_number)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{phase_id}/attempts/{attempt_number}/logs", response_model=LogResponse)
async def get_logs(
    request: Request,
    run_id: str,
    phase_id: str,
    attempt_number: int,
    offset: int = Query(default=0),
) -> LogResponse:
    async with request.app.state.db.session() as session:
        try:
            return await request.app.state.phase_service.get_logs(session, run_id, phase_id, attempt_number, offset)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{phase_id}/prompt", response_model=PromptResponse)
async def get_prompt(request: Request, run_id: str, phase_id: str) -> PromptResponse:
    async with request.app.state.db.session() as session:
        try:
            return await request.app.state.phase_service.get_latest_prompt(session, run_id, phase_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
