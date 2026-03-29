from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from relay.schemas.run import RunCreateRequest, RunDetailResponse, RunListQuery, RunListResponse, WorkflowStatus

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("", response_model=RunListResponse)
async def list_runs(
    request: Request,
    project_id: str | None = None,
    status: list[WorkflowStatus] | None = Query(default=None),
    limit: int = 50,
    offset: int = 0,
) -> RunListResponse:
    async with request.app.state.db.session() as session:
        query = RunListQuery(project_id=project_id, status=status or [], limit=limit, offset=offset)
        return await request.app.state.run_service.list_runs(session, query)


@router.post("", response_model=RunDetailResponse)
async def create_run(request: Request, payload: RunCreateRequest) -> RunDetailResponse:
    async with request.app.state.db.session() as session:
        try:
            return await request.app.state.run_service.create_run(session, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{run_id}", response_model=RunDetailResponse)
async def get_run(request: Request, run_id: str) -> RunDetailResponse:
    async with request.app.state.db.session() as session:
        try:
            return await request.app.state.run_service.get_run(session, run_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{run_id}", status_code=204)
async def delete_run(request: Request, run_id: str) -> None:
    async with request.app.state.db.session() as session:
        try:
            await request.app.state.run_service.delete_run(session, run_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
