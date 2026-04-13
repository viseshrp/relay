from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from relay.schemas.project import ProjectCreateRequest, ProjectResponse, ProjectSettingsResponse, ProjectSettingsUpdateRequest, ProjectUpdateRequest

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectResponse])
async def list_projects(request: Request) -> list[ProjectResponse]:
    async with request.app.state.db.session() as session:
        return await request.app.state.project_service.list_projects(session)


@router.post("", response_model=ProjectResponse)
async def create_project(request: Request, payload: ProjectCreateRequest) -> ProjectResponse:
    async with request.app.state.db.session() as session:
        try:
            return await request.app.state.project_service.create_project(session, payload.path, payload.name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(request: Request, project_id: str) -> ProjectResponse:
    async with request.app.state.db.session() as session:
        try:
            return await request.app.state.project_service.get_project(session, project_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(request: Request, project_id: str, payload: ProjectUpdateRequest) -> ProjectResponse:
    async with request.app.state.db.session() as session:
        try:
            return await request.app.state.project_service.update_project(session, project_id, payload.name)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{project_id}", status_code=204)
async def delete_project(request: Request, project_id: str) -> None:
    async with request.app.state.db.session() as session:
        try:
            await request.app.state.project_service.delete_project(session, project_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{project_id}/files")
async def browse_project_files(request: Request, project_id: str) -> list[dict[str, object]]:
    async with request.app.state.db.session() as session:
        try:
            return [item.model_dump() for item in await request.app.state.project_service.browse_file_tree(session, project_id)]
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{project_id}/settings", response_model=ProjectSettingsResponse)
async def get_project_settings(request: Request, project_id: str) -> ProjectSettingsResponse:
    async with request.app.state.db.session() as session:
        return await request.app.state.settings_service.get_project_settings(session, project_id)


@router.put("/{project_id}/settings", response_model=ProjectSettingsResponse)
async def update_project_settings(
    request: Request,
    project_id: str,
    payload: ProjectSettingsUpdateRequest,
) -> ProjectSettingsResponse:
    async with request.app.state.db.session() as session:
        try:
            return await request.app.state.settings_service.update_project_settings(
                session,
                project_id,
                payload.phase_model_mapping,
                payload.retry_count,
                payload.review_fix_loop_limit,
                payload.autopilot_default,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
