from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from relay.db import Base


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    is_git_repo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    settings: Mapped["ProjectSetting | None"] = relationship(
        "ProjectSetting",
        back_populates="project",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="selectin",
    )
    workflow_runs: Mapped[list["WorkflowRun"]] = relationship(
        "WorkflowRun",
        back_populates="project",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class ProjectSetting(Base):
    __tablename__ = "project_settings"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, unique=True)
    phase_model_mapping: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    retry_count: Mapped[int | None] = mapped_column(nullable=True)
    review_fix_loop_limit: Mapped[int | None] = mapped_column(nullable=True)
    autopilot_default: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    project: Mapped[Project] = relationship("Project", back_populates="settings", lazy="selectin")
