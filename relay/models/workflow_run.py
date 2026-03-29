from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from relay.db import Base


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    branch: Mapped[str | None] = mapped_column(Text, nullable=True)
    head_commit: Mapped[str | None] = mapped_column(Text, nullable=True)
    autopilot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    review_fix_loop_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    review_fix_loop_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    retry_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    phase_model_mapping: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    context_paths: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    finalize_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pending_fix_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    project: Mapped["Project"] = relationship("Project", back_populates="workflow_runs", lazy="selectin")
    phases: Mapped[list["Phase"]] = relationship(
        "Phase",
        back_populates="workflow_run",
        cascade="all, delete-orphan",
        order_by="Phase.sequence_number",
        lazy="selectin",
    )
    exploration_messages: Mapped[list["ExplorationMessage"]] = relationship(
        "ExplorationMessage",
        back_populates="workflow_run",
        cascade="all, delete-orphan",
        order_by="ExplorationMessage.sequence_number",
        lazy="selectin",
    )
