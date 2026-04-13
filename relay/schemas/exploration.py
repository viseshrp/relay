from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ExplorationMessageCreateRequest(BaseModel):
    content: str = Field(min_length=1)


class ExplorationMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workflow_run_id: str
    role: str
    content: str
    sequence_number: int
    created_at: str


class ExplorationContextUpdateRequest(BaseModel):
    context_paths: list[str]


class ExplorationContextResponse(BaseModel):
    run_id: str
    context_paths: list[str]


class ExplorationFinalizeResponse(BaseModel):
    run_id: str
    finalize_requested: bool
