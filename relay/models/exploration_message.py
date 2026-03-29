from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from relay.db import Base


class ExplorationMessage(Base):
    __tablename__ = "exploration_messages"
    __table_args__ = (UniqueConstraint("workflow_run_id", "sequence_number", name="uq_exploration_sequence"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    workflow_run_id: Mapped[str] = mapped_column(ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    workflow_run: Mapped["WorkflowRun"] = relationship("WorkflowRun", back_populates="exploration_messages", lazy="selectin")
