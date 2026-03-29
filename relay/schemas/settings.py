from __future__ import annotations

from pydantic import BaseModel


class UserSettingsResponse(BaseModel):
    relay_data_dir: str
    copilot_cli_path_override: str | None = None
    phase_model_mapping: dict[str, str]
    autopilot: bool
    retry_limit: int
    review_fix_loop_limit: int
    theme: str = "system"


class UserSettingsUpdateRequest(BaseModel):
    copilot_cli_path_override: str | None = None
    phase_model_mapping: dict[str, str] | None = None
    autopilot: bool | None = None
    retry_limit: int | None = None
    review_fix_loop_limit: int | None = None
    theme: str | None = None


class HealthResponse(BaseModel):
    ok: bool
    database: str
    worker: str
    copilot: dict[str, object]


class SystemStatusResponse(BaseModel):
    version: str
    worker_status: str
    concurrency_limit: int
    active_workflows: int
    copilot: dict[str, object]
