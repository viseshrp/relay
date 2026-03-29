from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class PhaseStatus(StrEnum):
    QUEUED = "queued"
    STARTING = "starting"
    RUNNING = "running"
    RETRYING = "retrying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    STALE = "stale"
    WAITING_FOR_USER = "waiting_for_user"


class ReviewSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    SUGGESTION = "suggestion"


class ReviewCommentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    file_path: str | None = None
    line_number: int | None = None
    severity: str
    comment: str


class AttemptDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    phase_id: str
    attempt_number: int
    status: str
    pid: int | None = None
    exit_code: int | None = None
    started_at: str | None = None
    ended_at: str | None = None
    error_message: str | None = None
    log_file_path: str
    rendered_prompt: str
    review_comments: list[ReviewCommentResponse] = Field(default_factory=list)


class PhaseDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workflow_run_id: str
    phase_type: str
    sequence_number: int
    status: str
    current_attempt: int
    attempts: list[AttemptDetailResponse] = Field(default_factory=list)


class LogResponse(BaseModel):
    lines: list[str]
    next_offset: int


class PromptResponse(BaseModel):
    prompt: str
