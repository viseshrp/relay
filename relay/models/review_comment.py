from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from relay.db import Base


class ReviewComment(Base):
    __tablename__ = "review_comments"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    phase_attempt_id: Mapped[str] = mapped_column(ForeignKey("phase_attempts.id", ondelete="CASCADE"), nullable=False)
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    line_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)

    phase_attempt: Mapped["PhaseAttempt"] = relationship("PhaseAttempt", back_populates="review_comments", lazy="selectin")
