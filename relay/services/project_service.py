from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from relay.models import Project, WorkflowRun
from relay.schemas.project import FileTreeNode, ProjectResponse
from relay.worker.git_ops import get_current_branch, is_git_repo


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _project_to_response(project: Project, active_run_count: int, path_accessible: bool) -> ProjectResponse:
    current_branch = get_current_branch(project.path) if project.is_git_repo and path_accessible else None
    return ProjectResponse(
        id=project.id,
        name=project.name,
        path=project.path,
        is_git_repo=project.is_git_repo,
        active_run_count=active_run_count,
        path_accessible=path_accessible,
        current_branch=current_branch,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


class ProjectService:
    async def list_projects(self, session: AsyncSession) -> list[ProjectResponse]:
        rows = (
            await session.execute(
                select(Project, func.count(WorkflowRun.id))
                .outerjoin(
                    WorkflowRun,
                    (WorkflowRun.project_id == Project.id)
                    & WorkflowRun.status.in_(["queued", "running", "waiting_for_user"]),
                )
                .group_by(Project.id)
                .order_by(Project.updated_at.desc())
            )
        ).all()
        return [
            _project_to_response(project, active_run_count, Path(project.path).exists())
            for project, active_run_count in rows
        ]

    async def create_project(self, session: AsyncSession, path: str, name: str | None = None) -> ProjectResponse:
        project_path = Path(path).expanduser()
        if not project_path.is_absolute():
            raise ValueError("Project path must be absolute.")
        if not project_path.exists() or not project_path.is_dir():
            raise ValueError("Project path must be an existing directory.")
        if not os.access(project_path, os.R_OK):
            raise ValueError("Project path is not readable.")
        existing = (await session.execute(select(Project).where(Project.path == str(project_path)))).scalar_one_or_none()
        if existing is not None:
            raise ValueError("Project path is already registered.")
        now = _utc_now()
        project = Project(
            id=str(uuid.uuid4()),
            name=name or project_path.name,
            path=str(project_path),
            is_git_repo=is_git_repo(str(project_path)),
            created_at=now,
            updated_at=now,
        )
        session.add(project)
        await session.commit()
        await session.refresh(project)
        return _project_to_response(project, 0, True)

    async def get_project(self, session: AsyncSession, project_id: str) -> ProjectResponse:
        row = (
            await session.execute(
                select(Project, func.count(WorkflowRun.id))
                .outerjoin(
                    WorkflowRun,
                    (WorkflowRun.project_id == Project.id)
                    & WorkflowRun.status.in_(["queued", "running", "waiting_for_user"]),
                )
                .where(Project.id == project_id)
                .group_by(Project.id)
            )
        ).one_or_none()
        if row is None:
            raise ValueError("Project not found.")
        project, active_run_count = row
        return _project_to_response(project, active_run_count, Path(project.path).exists())

    async def update_project(self, session: AsyncSession, project_id: str, name: str) -> ProjectResponse:
        project = await session.get(Project, project_id)
        if project is None:
            raise ValueError("Project not found.")
        project.name = name
        project.updated_at = _utc_now()
        await session.commit()
        return await self.get_project(session, project_id)

    async def delete_project(self, session: AsyncSession, project_id: str) -> None:
        project = await session.get(Project, project_id)
        if project is None:
            raise ValueError("Project not found.")
        await session.delete(project)
        await session.commit()

    async def browse_file_tree(self, session: AsyncSession, project_id: str) -> list[FileTreeNode]:
        project = await session.get(Project, project_id)
        if project is None:
            raise ValueError("Project not found.")
        root_path = Path(project.path)
        if not root_path.exists():
            raise ValueError("Project path is no longer accessible.")

        def build_node(path: Path) -> FileTreeNode:
            if path.is_dir():
                children = [
                    build_node(child)
                    for child in sorted(path.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
                    if child.name not in {".git", ".relay", "node_modules", "__pycache__"}
                ]
                return FileTreeNode(path=str(path), name=path.name, node_type="directory", children=children)
            return FileTreeNode(path=str(path), name=path.name, node_type="file", children=[])

        return [build_node(child) for child in sorted(root_path.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))]
