"""initial schema

Revision ID: 001_initial
Revises:
Create Date: 2026-03-28 23:10:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("is_git_repo", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("path"),
    )
    op.create_table(
        "user_settings",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "project_settings",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("phase_model_mapping", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("retry_count", sa.Integer(), nullable=True),
        sa.Column("review_fix_loop_limit", sa.Integer(), nullable=True),
        sa.Column("autopilot_default", sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id"),
    )
    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("branch", sa.Text(), nullable=True),
        sa.Column("head_commit", sa.Text(), nullable=True),
        sa.Column("autopilot", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("review_fix_loop_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("review_fix_loop_limit", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("retry_limit", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("phase_model_mapping", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("context_paths", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("finalize_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("pending_fix_prompt", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "phases",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("workflow_run_id", sa.Text(), nullable=False),
        sa.Column("phase_type", sa.Text(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("current_attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workflow_run_id", "phase_type", name="uq_phase_workflow_type"),
    )
    op.create_table(
        "exploration_messages",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("workflow_run_id", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workflow_run_id", "sequence_number", name="uq_exploration_sequence"),
    )
    op.create_table(
        "phase_attempts",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("phase_id", sa.Text(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("pid", sa.Integer(), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.Text(), nullable=True),
        sa.Column("ended_at", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("log_file_path", sa.Text(), nullable=False),
        sa.Column("rendered_prompt", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["phase_id"], ["phases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("phase_id", "attempt_number", name="uq_phase_attempt_number"),
    )
    op.create_table(
        "review_comments",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("phase_attempt_id", sa.Text(), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("line_number", sa.Integer(), nullable=True),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["phase_attempt_id"], ["phase_attempts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("review_comments")
    op.drop_table("phase_attempts")
    op.drop_table("exploration_messages")
    op.drop_table("phases")
    op.drop_table("workflow_runs")
    op.drop_table("project_settings")
    op.drop_table("user_settings")
    op.drop_table("projects")
