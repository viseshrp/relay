from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from relay.artifacts.manager import artifact_dir, read_artifact
from relay.artifacts.parsers import extract_review_comments, extract_review_summary, extract_verdict
from relay.copilot.prompts import build_fix_prompt
from relay.models import Phase, WorkflowRun
from relay.schemas.run import RerunRequest, ReviewFixRequest, RunDetailResponse

router = APIRouter(prefix="/runs/{run_id}", tags=["workflow-control"])


async def _load_run(session, run_id: str) -> WorkflowRun | None:
    return (
        await session.execute(
            select(WorkflowRun)
            .options(selectinload(WorkflowRun.phases), selectinload(WorkflowRun.project))
            .where(WorkflowRun.id == run_id)
        )
    ).scalar_one_or_none()


def _ordered_phases(run: WorkflowRun) -> list[Phase]:
    return sorted(run.phases, key=lambda item: item.sequence_number)


@router.post("/advance", response_model=RunDetailResponse)
async def advance_run(request: Request, run_id: str) -> RunDetailResponse:
    async with request.app.state.db.session() as session:
        run = await _load_run(session, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        if run.status != "waiting_for_user":
            raise HTTPException(status_code=400, detail="Workflow is not waiting for user input.")
        phase = next((item for item in run.phases if item.status == "waiting_for_user"), None)
        if phase is None or phase.phase_type not in {"exploration", "plan_critique"}:
            raise HTTPException(status_code=400, detail="This pause point cannot be advanced with /advance.")
        phase.status = "succeeded"
        phases = _ordered_phases(run)
        next_phase = phases[phase.sequence_number + 1]
        next_phase.status = "queued"
        run.status = "running"
        await session.commit()
        return await request.app.state.run_service.get_run(session, run.id)


@router.post("/cancel", response_model=RunDetailResponse)
async def cancel_run(request: Request, run_id: str) -> RunDetailResponse:
    async with request.app.state.db.session() as session:
        run = await _load_run(session, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        run.cancel_requested = True
        await session.commit()
        return await request.app.state.run_service.get_run(session, run.id)


@router.post("/rerun", response_model=RunDetailResponse)
async def rerun_run(request: Request, run_id: str, payload: RerunRequest) -> RunDetailResponse:
    async with request.app.state.db.session() as session:
        run = await _load_run(session, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        phases = _ordered_phases(run)
        phase_lookup = {item.phase_type: item for item in phases}
        target = phase_lookup[payload.from_phase_type.value]
        run.status = "running"
        run.cancel_requested = False
        run.finalize_requested = False
        for phase in phases:
            if phase.sequence_number < target.sequence_number:
                continue
            if phase.id == target.id:
                phase.status = "queued"
            else:
                phase.status = "stale"
        await session.commit()
        return await request.app.state.run_service.get_run(session, run.id)


@router.post("/review/approve", response_model=RunDetailResponse)
async def approve_review(request: Request, run_id: str) -> RunDetailResponse:
    async with request.app.state.db.session() as session:
        run = await _load_run(session, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        if run.status != "waiting_for_user":
            raise HTTPException(status_code=400, detail="Workflow is not waiting for review approval.")
        review_phase = next((item for item in run.phases if item.phase_type == "review"), None)
        if review_phase is None:
            raise HTTPException(status_code=400, detail="Review phase not found.")
        summary_path = artifact_dir(run.project.path, run.id, "review") / "REVIEW_SUMMARY.md"  # type: ignore[union-attr]
        summary = summary_path.read_text(encoding="utf-8") if summary_path.exists() else ""
        verdict = extract_verdict(summary)
        review_phase.status = "succeeded"
        run.status = "completed" if verdict == "PASS" else "completed_with_unresolved_findings"
        await session.commit()
        return await request.app.state.run_service.get_run(session, run.id)


@router.post("/review/fix", response_model=RunDetailResponse)
async def fix_review(request: Request, run_id: str, payload: ReviewFixRequest) -> RunDetailResponse:
    async with request.app.state.db.session() as session:
        run = await _load_run(session, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        if run.status != "waiting_for_user":
            raise HTTPException(status_code=400, detail="Workflow is not waiting for review action.")
        if run.project is None:
            raise HTTPException(status_code=400, detail="Project missing for workflow.")
        review_dir = artifact_dir(run.project.path, run.id, "review")
        raw_summary = (review_dir / "REVIEW_SUMMARY.md").read_text(encoding="utf-8") if (review_dir / "REVIEW_SUMMARY.md").exists() else ""
        raw_output = (review_dir / "REVIEW_RAW.md").read_text(encoding="utf-8") if (review_dir / "REVIEW_RAW.md").exists() else raw_summary
        comments, _parsed = extract_review_comments(raw_output)
        summary = extract_review_summary(raw_summary or raw_output)
        run.pending_fix_prompt = payload.fix_prompt or build_fix_prompt(
            comments,
            summary,
            read_artifact(run.project.path, run.id, "planning", "SPEC.md"),
            read_artifact(run.project.path, run.id, "plan_correction", "IMPLEMENTATION_PLAN.md"),
            json.loads(run.context_paths),
        )
        run.review_fix_loop_count += 1
        execution_phase = next(item for item in run.phases if item.phase_type == "execution")
        review_phase = next(item for item in run.phases if item.phase_type == "review")
        execution_phase.status = "queued"
        review_phase.status = "queued"
        run.status = "running"
        await session.commit()
        return await request.app.state.run_service.get_run(session, run.id)
