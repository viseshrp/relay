from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class WorkflowStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_FOR_USER = "waiting_for_user"
    COMPLETED = "completed"
    COMPLETED_WITH_UNRESOLVED_FINDINGS = "completed_with_unresolved_findings"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PhaseType(StrEnum):
    EXPLORATION = "exploration"
    PLANNING = "planning"
    PLAN_CRITIQUE = "plan_critique"
    PLAN_CORRECTION = "plan_correction"
    EXECUTION = "execution"
    REVIEW = "review"


class RunCreateRequest(BaseModel):
    project_id: str
    name: str = Field(min_length=1)
    phase_model_mapping: dict[str, str] | None = None
    retry_limit: int | None = None
    review_fix_loop_limit: int | None = None
    autopilot: bool | None = None


class RerunRequest(BaseModel):
    from_phase_type: PhaseType


class ReviewFixRequest(BaseModel):
    fix_prompt: str | None = None


class RunListQuery(BaseModel):
    project_id: str | None = None
    status: list[WorkflowStatus] = Field(default_factory=list)
    limit: int = 50
    offset: int = 0


class AttemptSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    attempt_number: int
    status: str
    started_at: str | None = None
    ended_at: str | None = None


class PhaseSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    phase_type: str
    sequence_number: int
    status: str
    current_attempt: int
    latest_attempt: AttemptSummary | None = None


class RunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    project_name: str
    name: str
    status: str
    branch: str | None = None
    head_commit: str | None = None
    autopilot: bool
    review_fix_loop_count: int
    review_fix_loop_limit: int
    retry_limit: int
    context_paths: list[str]
    created_at: str
    updated_at: str


class RunDetailResponse(RunSummary):
    phases: list[PhaseSummary] = Field(default_factory=list)


class RunListResponse(BaseModel):
    items: list[RunSummary]
    total: int
