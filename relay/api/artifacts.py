from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

from relay.artifacts.manager import artifact_path, relay_root
from relay.models import Project, WorkflowRun

router = APIRouter(prefix="/runs/{run_id}/artifacts", tags=["artifacts"])


@router.get("/{artifact_path:path}", response_class=PlainTextResponse)
async def get_artifact(request: Request, run_id: str, artifact_path: str) -> PlainTextResponse:
    async with request.app.state.db.session() as session:
        run = await session.get(WorkflowRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        project = await session.get(Project, run.project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found.")
        root = relay_root(project.path, run.id).resolve()
        target = artifact_path(project.path, run.id, artifact_path).resolve()
        if root not in target.parents and target != root:
            raise HTTPException(status_code=400, detail="Invalid artifact path.")
        if not target.exists() or not target.is_file():
            raise HTTPException(status_code=404, detail="Artifact not found.")
        return PlainTextResponse(target.read_text(encoding="utf-8"))
