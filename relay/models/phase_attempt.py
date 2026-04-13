from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from relay.db import Base


class PhaseAttempt(Base):
    __tablename__ = "phase_attempts"
    __table_args__ = (UniqueConstraint("phase_id", "attempt_number", name="uq_phase_attempt_number"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    phase_id: Mapped[str] = mapped_column(ForeignKey("phases.id", ondelete="CASCADE"), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    ended_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    log_file_path: Mapped[str] = mapped_column(Text, nullable=False)
    rendered_prompt: Mapped[str] = mapped_column(Text, nullable=False)

    phase: Mapped["Phase"] = relationship("Phase", back_populates="attempts", lazy="selectin")
    review_comments: Mapped[list["ReviewComment"]] = relationship(
        "ReviewComment",
        back_populates="phase_attempt",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
