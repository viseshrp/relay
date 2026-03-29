from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreateRequest(BaseModel):
    path: str
    name: str | None = None


class ProjectUpdateRequest(BaseModel):
    name: str = Field(min_length=1)


class ProjectSettingsUpdateRequest(BaseModel):
    phase_model_mapping: dict[str, str] | None = None
    retry_count: int | None = None
    review_fix_loop_limit: int | None = None
    autopilot_default: bool | None = None


class ProjectSettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: str
    phase_model_mapping: dict[str, str]
    retry_count: int | None = None
    review_fix_loop_limit: int | None = None
    autopilot_default: bool | None = None


class FileTreeNode(BaseModel):
    path: str
    name: str
    node_type: str
    children: list["FileTreeNode"] = Field(default_factory=list)


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    path: str
    is_git_repo: bool
    active_run_count: int = 0
    path_accessible: bool = True
    current_branch: str | None = None
    created_at: str
    updated_at: str
