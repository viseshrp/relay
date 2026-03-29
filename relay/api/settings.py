from __future__ import annotations

from fastapi import APIRouter, Request

from relay.schemas.settings import UserSettingsResponse, UserSettingsUpdateRequest

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=UserSettingsResponse)
async def get_settings(request: Request) -> UserSettingsResponse:
    async with request.app.state.db.session() as session:
        return await request.app.state.settings_service.get_user_settings(session)


@router.put("", response_model=UserSettingsResponse)
async def update_settings(request: Request, payload: UserSettingsUpdateRequest) -> UserSettingsResponse:
    async with request.app.state.db.session() as session:
        return await request.app.state.settings_service.update_user_settings(session, payload)
