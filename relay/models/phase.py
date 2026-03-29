from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from relay.db import Base


class Phase(Base):
    __tablename__ = "phases"
    __table_args__ = (UniqueConstraint("workflow_run_id", "phase_type", name="uq_phase_workflow_type"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    workflow_run_id: Mapped[str] = mapped_column(ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False)
    phase_type: Mapped[str] = mapped_column(Text, nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    current_attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    workflow_run: Mapped["WorkflowRun"] = relationship("WorkflowRun", back_populates="phases", lazy="selectin")
    attempts: Mapped[list["PhaseAttempt"]] = relationship(
        "PhaseAttempt",
        back_populates="phase",
        cascade="all, delete-orphan",
        order_by="PhaseAttempt.attempt_number",
        lazy="selectin",
    )
