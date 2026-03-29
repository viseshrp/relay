from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from relay.config import Settings, default_phase_model_mapping
from relay.models import Project, ProjectSetting, UserSetting
from relay.schemas.project import ProjectSettingsResponse
from relay.schemas.settings import UserSettingsResponse, UserSettingsUpdateRequest


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _loads_mapping(raw: str | None) -> dict[str, str]:
    if not raw:
        return default_phase_model_mapping()
    value = json.loads(raw)
    merged = default_phase_model_mapping()
    merged.update({str(key): str(item) for key, item in value.items()})
    return merged


def _dumps(value: object) -> str:
    return json.dumps(value)


@dataclass(slots=True)
class ResolvedRunSettings:
    phase_model_mapping: dict[str, str]
    retry_limit: int
    review_fix_loop_limit: int
    autopilot: bool


class SettingsService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def get_user_settings(self, session: AsyncSession) -> UserSettingsResponse:
        rows = (await session.execute(select(UserSetting))).scalars().all()
        values = {row.key: json.loads(row.value) for row in rows}
        return UserSettingsResponse(
            relay_data_dir=str(self.settings.data_dir),
            copilot_cli_path_override=values.get("copilot_cli_path_override"),
            phase_model_mapping={**default_phase_model_mapping(), **values.get("phase_model_mapping", {})},
            autopilot=values.get("autopilot", self.settings.default_autopilot),
            retry_limit=values.get("retry_limit", self.settings.default_retry_limit),
            review_fix_loop_limit=values.get(
                "review_fix_loop_limit",
                self.settings.default_review_fix_loop_limit,
            ),
            theme=values.get("theme", "system"),
        )

    async def update_user_settings(
        self,
        session: AsyncSession,
        payload: UserSettingsUpdateRequest,
    ) -> UserSettingsResponse:
        current = await self.get_user_settings(session)
        merged = current.model_dump()
        for key, value in payload.model_dump(exclude_unset=True).items():
            if value is not None:
                merged[key] = value
        storage_map = {
            "copilot_cli_path_override": merged["copilot_cli_path_override"],
            "phase_model_mapping": merged["phase_model_mapping"],
            "autopilot": merged["autopilot"],
            "retry_limit": merged["retry_limit"],
            "review_fix_loop_limit": merged["review_fix_loop_limit"],
            "theme": merged["theme"],
        }
        timestamp = _utc_now()
        for key, value in storage_map.items():
            row = await session.get(UserSetting, key)
            if row is None:
                row = UserSetting(key=key, value=_dumps(value), updated_at=timestamp)
                session.add(row)
            else:
                row.value = _dumps(value)
                row.updated_at = timestamp
        await session.commit()
        return await self.get_user_settings(session)

    async def get_project_settings(self, session: AsyncSession, project_id: str) -> ProjectSettingsResponse:
        row = (
            await session.execute(select(ProjectSetting).where(ProjectSetting.project_id == project_id))
        ).scalar_one_or_none()
        if row is None:
            return ProjectSettingsResponse(
                project_id=project_id,
                phase_model_mapping=default_phase_model_mapping(),
                retry_count=None,
                review_fix_loop_limit=None,
                autopilot_default=None,
            )
        return ProjectSettingsResponse(
            project_id=project_id,
            phase_model_mapping=_loads_mapping(row.phase_model_mapping),
            retry_count=row.retry_count,
            review_fix_loop_limit=row.review_fix_loop_limit,
            autopilot_default=row.autopilot_default,
        )

    async def update_project_settings(
        self,
        session: AsyncSession,
        project_id: str,
        phase_model_mapping: dict[str, str] | None,
        retry_count: int | None,
        review_fix_loop_limit: int | None,
        autopilot_default: bool | None,
    ) -> ProjectSettingsResponse:
        project = await session.get(Project, project_id)
        if project is None:
            raise ValueError("Project not found.")
        row = (
            await session.execute(select(ProjectSetting).where(ProjectSetting.project_id == project_id))
        ).scalar_one_or_none()
        if row is None:
            row = ProjectSetting(
                id=f"{project_id}-settings",
                project_id=project_id,
                phase_model_mapping=_dumps(phase_model_mapping or default_phase_model_mapping()),
                retry_count=retry_count,
                review_fix_loop_limit=review_fix_loop_limit,
                autopilot_default=autopilot_default,
            )
            session.add(row)
        else:
            if phase_model_mapping is not None:
                row.phase_model_mapping = _dumps(phase_model_mapping)
            row.retry_count = retry_count
            row.review_fix_loop_limit = review_fix_loop_limit
            row.autopilot_default = autopilot_default
        await session.commit()
        return await self.get_project_settings(session, project_id)

    async def resolve_run_settings(
        self,
        session: AsyncSession,
        project_id: str,
        *,
        phase_model_mapping: dict[str, str] | None,
        retry_limit: int | None,
        review_fix_loop_limit: int | None,
        autopilot: bool | None,
    ) -> ResolvedRunSettings:
        global_settings = await self.get_user_settings(session)
        project_settings = await self.get_project_settings(session, project_id)
        resolved_mapping = default_phase_model_mapping()
        resolved_mapping.update(global_settings.phase_model_mapping)
        resolved_mapping.update(project_settings.phase_model_mapping)
        if phase_model_mapping is not None:
            resolved_mapping.update(phase_model_mapping)
        return ResolvedRunSettings(
            phase_model_mapping=resolved_mapping,
            retry_limit=(
                retry_limit
                if retry_limit is not None
                else (
                    project_settings.retry_count
                    if project_settings.retry_count is not None
                    else global_settings.retry_limit
                )
            ),
            review_fix_loop_limit=(
                review_fix_loop_limit
                if review_fix_loop_limit is not None
                else (
                    project_settings.review_fix_loop_limit
                    if project_settings.review_fix_loop_limit is not None
                    else global_settings.review_fix_loop_limit
                )
            ),
            autopilot=(
                autopilot
                if autopilot is not None
                else (
                    project_settings.autopilot_default
                    if project_settings.autopilot_default is not None
                    else global_settings.autopilot
                )
            ),
        )
