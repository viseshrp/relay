from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from relay.artifacts.exploration import (
    planning_prompt_path,
    reset_exploration_stream,
    save_message_file,
    write_transcript,
)
from relay.artifacts.manager import (
    archive_attempt,
    artifact_dir,
    check_artifacts_exist,
    ensure_artifact_dirs,
    read_artifact,
    save_artifact,
)
from relay.artifacts.parsers import (
    extract_review_comments,
    extract_review_summary,
    extract_verdict,
    persist_review_outputs,
)
from relay.config import Settings
from relay.copilot.prompts import (
    build_correction_prompt,
    build_critique_prompt,
    build_execution_prompt,
    build_exploration_finalization_prompt,
    build_planning_prompt,
    build_review_prompt,
)
from relay.copilot.session import (
    CopilotSession,
    build_agent_command,
    build_exploration_command,
    create_session,
)
from relay.db import DatabaseManager
from relay.models import ExplorationMessage, Phase, PhaseAttempt, Project, ReviewComment, WorkflowRun


PHASE_LOG_PREFIX = {
    "exploration": "exploration",
    "planning": "planning",
    "plan_critique": "critique",
    "plan_correction": "correction",
    "execution": "execution",
    "review": "review",
}

EXPECTED_PHASE_ARTIFACTS = {
    "planning": ["SPEC.md", "IMPLEMENTATION_PLAN.md"],
    "plan_critique": ["IMPLEMENTATION_PLAN_CRITIQUED.md"],
    "plan_correction": ["IMPLEMENTATION_PLAN.md"],
}


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(raw_value: str) -> object:
    return json.loads(raw_value) if raw_value else []


def _phase_model(run: WorkflowRun, phase_type: str) -> str:
    mapping = json.loads(run.phase_model_mapping)
    return str(mapping.get(phase_type, ""))


def _log_path(settings: Settings, run_id: str, phase_type: str, attempt_number: int) -> Path:
    path = settings.data_dir / "logs" / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{PHASE_LOG_PREFIX[phase_type]}_attempt_{attempt_number}.log"


async def _load_run_context(session: AsyncSession, run_id: str, phase_id: str) -> tuple[WorkflowRun, Phase, Project]:
    run = (
        await session.execute(
            select(WorkflowRun)
            .options(
                selectinload(WorkflowRun.project),
                selectinload(WorkflowRun.phases).selectinload(Phase.attempts),
                selectinload(WorkflowRun.exploration_messages),
            )
            .where(WorkflowRun.id == run_id)
        )
    ).scalar_one()
    phase = next(item for item in run.phases if item.id == phase_id)
    if run.project is None:
        raise RuntimeError("Workflow run is missing its project relationship.")
    return run, phase, run.project


async def _start_attempt(
    db: DatabaseManager,
    settings: Settings,
    *,
    run_id: str,
    phase_id: str,
    phase_type: str,
    rendered_prompt: str,
) -> tuple[int, str]:
    async with db.session() as session:
        run, phase, _project = await _load_run_context(session, run_id, phase_id)
        phase.current_attempt += 1
        now = _utc_now()
        # Relay models process creation explicitly so the UI can distinguish
        # "worker picked the phase" from "subprocess is confirmed alive".
        phase.status = "starting"
        phase.updated_at = now
        run.status = "running"
        run.updated_at = now
        log_file_path = str(_log_path(settings, run.id, phase_type, phase.current_attempt))
        attempt = PhaseAttempt(
            id=str(uuid.uuid4()),
            phase_id=phase.id,
            attempt_number=phase.current_attempt,
            status="starting",
            pid=None,
            exit_code=None,
            started_at=now,
            ended_at=None,
            error_message=None,
            log_file_path=log_file_path,
            rendered_prompt=rendered_prompt,
        )
        session.add(attempt)
        await session.commit()
        return phase.current_attempt, log_file_path


async def _mark_attempt_running(
    db: DatabaseManager,
    *,
    run_id: str,
    phase_id: str,
    attempt_number: int,
    pid: int | None,
) -> None:
    async with db.session() as session:
        attempt = (
            await session.execute(
                select(PhaseAttempt)
                .join(Phase)
                .where(
                    Phase.workflow_run_id == run_id,
                    Phase.id == phase_id,
                    PhaseAttempt.attempt_number == attempt_number,
                )
            )
        ).scalar_one()
        phase = await session.get(Phase, phase_id)
        if phase is None:
            raise RuntimeError(f"Phase {phase_id} is missing while marking an attempt as running.")
        phase.status = "running"
        phase.updated_at = _utc_now()
        attempt.status = "running"
        attempt.pid = pid
        await session.commit()


async def _finish_attempt(
    db: DatabaseManager,
    *,
    run_id: str,
    phase_id: str,
    attempt_number: int,
    status: str,
    exit_code: int | None,
    error_message: str | None = None,
) -> None:
    async with db.session() as session:
        attempt = (
            await session.execute(
                select(PhaseAttempt)
                .join(Phase)
                .where(
                    Phase.workflow_run_id == run_id,
                    Phase.id == phase_id,
                    PhaseAttempt.attempt_number == attempt_number,
                )
            )
        ).scalar_one()
        attempt.status = status
        attempt.exit_code = exit_code
        attempt.error_message = error_message
        attempt.ended_at = _utc_now()
        await session.commit()


async def _save_review_comments(
    session: AsyncSession,
    phase_id: str,
    attempt_number: int,
    comments: list[dict[str, object]],
) -> None:
    attempt = (
        await session.execute(
            select(PhaseAttempt)
            .where(PhaseAttempt.phase_id == phase_id, PhaseAttempt.attempt_number == attempt_number)
            .options(selectinload(PhaseAttempt.review_comments))
        )
    ).scalar_one()
    for comment in attempt.review_comments:
        await session.delete(comment)
    for item in comments:
        session.add(
            ReviewComment(
                id=str(uuid.uuid4()),
                phase_attempt_id=attempt.id,
                file_path=item.get("file"),
                line_number=item.get("line"),
                severity=str(item.get("severity", "warning")),
                comment=str(item.get("comment", "")),
            )
        )


def _build_phase_prompt(run: WorkflowRun, project_path: str, phase_type: str) -> str:
    context_paths = list(_load_json(run.context_paths))
    if phase_type == "planning":
        planning_brief = read_artifact(project_path, run.id, "exploration", "planning_prompt.md")
        return build_planning_prompt(planning_brief, context_paths, str(artifact_dir(project_path, run.id, "planning")))
    if phase_type == "plan_critique":
        return build_critique_prompt(
            read_artifact(project_path, run.id, "planning", "SPEC.md"),
            read_artifact(project_path, run.id, "planning", "IMPLEMENTATION_PLAN.md"),
            read_artifact(project_path, run.id, "exploration", "planning_prompt.md"),
            context_paths,
            str(artifact_dir(project_path, run.id, "plan_critique") / "IMPLEMENTATION_PLAN_CRITIQUED.md"),
        )
    if phase_type == "plan_correction":
        return build_correction_prompt(
            read_artifact(project_path, run.id, "plan_critique", "IMPLEMENTATION_PLAN_CRITIQUED.md"),
            read_artifact(project_path, run.id, "exploration", "planning_prompt.md"),
            read_artifact(project_path, run.id, "planning", "SPEC.md"),
            context_paths,
            str(artifact_dir(project_path, run.id, "plan_correction") / "IMPLEMENTATION_PLAN.md"),
        )
    if phase_type == "execution":
        if run.pending_fix_prompt:
            return run.pending_fix_prompt
        return build_execution_prompt(
            read_artifact(project_path, run.id, "planning", "SPEC.md"),
            read_artifact(project_path, run.id, "plan_correction", "IMPLEMENTATION_PLAN.md"),
            context_paths,
        )
    if phase_type == "review":
        return build_review_prompt(
            read_artifact(project_path, run.id, "planning", "SPEC.md"),
            read_artifact(project_path, run.id, "plan_correction", "IMPLEMENTATION_PLAN.md"),
            context_paths,
            str(artifact_dir(project_path, run.id, "review")),
        )
    raise ValueError(f"Unsupported phase type: {phase_type}")


def _persist_phase_output_fallback(project_path: str, run_id: str, phase_type: str, raw_output: str) -> None:
    if phase_type == "planning":
        if not check_artifacts_exist(project_path, run_id, phase_type, EXPECTED_PHASE_ARTIFACTS[phase_type]):
            save_artifact(project_path, run_id, phase_type, "SPEC.md", raw_output)
            save_artifact(project_path, run_id, phase_type, "IMPLEMENTATION_PLAN.md", raw_output)
    elif phase_type == "plan_critique":
        if not check_artifacts_exist(project_path, run_id, phase_type, EXPECTED_PHASE_ARTIFACTS[phase_type]):
            save_artifact(project_path, run_id, phase_type, "IMPLEMENTATION_PLAN_CRITIQUED.md", raw_output)
    elif phase_type == "plan_correction":
        if not check_artifacts_exist(project_path, run_id, phase_type, EXPECTED_PHASE_ARTIFACTS[phase_type]):
            save_artifact(project_path, run_id, phase_type, "IMPLEMENTATION_PLAN.md", raw_output)


@dataclass(slots=True)
class PhaseExecutionResult:
    success: bool
    attempt_number: int
    exit_code: int | None
    raw_output: str = ""
    error_message: str | None = None
    review_comments: list[dict[str, object]] | None = None
    review_summary: str | None = None
    review_verdict: str | None = None


async def run_standard_phase(
    db: DatabaseManager,
    settings: Settings,
    *,
    run_id: str,
    phase_id: str,
    phase_type: str,
    reusable_session: CopilotSession | None = None,
) -> tuple[PhaseExecutionResult, CopilotSession | None]:
    async with db.session() as session:
        run, phase, project = await _load_run_context(session, run_id, phase_id)
        ensure_artifact_dirs(project.path, run.id)
        if phase_type == "plan_correction":
            archive_attempt(project.path, run.id, "plan_correction", phase.current_attempt + 1)
        rendered_prompt = _build_phase_prompt(run, project.path, phase_type)
        model = _phase_model(run, phase_type)
        session_handle = reusable_session or create_session()
        attempt_number, log_file_path = await _start_attempt(
            db,
            settings,
            run_id=run.id,
            phase_id=phase.id,
            phase_type=phase_type,
            rendered_prompt=rendered_prompt,
        )
        if not session_handle.is_alive():
            try:
                await session_handle.start(build_agent_command(settings.copilot_cli_path, model), project.path)
            except Exception as exc:
                await _finish_attempt(
                    db,
                    run_id=run.id,
                    phase_id=phase.id,
                    attempt_number=attempt_number,
                    status="failed",
                    exit_code=1,
                    error_message=str(exc),
                )
                return PhaseExecutionResult(False, attempt_number, 1, error_message=str(exc)), None
        await _mark_attempt_running(
            db,
            run_id=run.id,
            phase_id=phase.id,
            attempt_number=attempt_number,
            pid=session_handle.pid,
        )
    log_path = Path(log_file_path)
    raw_output_chunks: list[str] = []
    sender = session_handle.send_followup if reusable_session is not None else session_handle.send
    watcher_stop = asyncio.Event()
    cancel_requested = False

    async def watch_for_cancellation() -> None:
        nonlocal cancel_requested
        while not watcher_stop.is_set():
            async with db.session() as session:
                run = await session.get(WorkflowRun, run_id)
                if run is not None and run.cancel_requested:
                    cancel_requested = True
                    watcher_stop.set()
                    await session_handle.kill()
                    return
            await asyncio.sleep(0.5)

    cancellation_task = asyncio.create_task(watch_for_cancellation())
    try:
        with log_path.open("a", encoding="utf-8") as log_file:
            async for chunk in sender(rendered_prompt):
                raw_output_chunks.append(chunk)
                log_file.write(chunk)
                log_file.flush()
    except Exception as exc:
        cancellation_task.cancel()
        if cancel_requested:
            await _finish_attempt(
                db,
                run_id=run_id,
                phase_id=phase_id,
                attempt_number=attempt_number,
                status="cancelled",
                exit_code=-9,
                error_message="cancelled",
            )
            return PhaseExecutionResult(False, attempt_number, -9, error_message="cancelled"), session_handle
        await _finish_attempt(
            db,
            run_id=run_id,
            phase_id=phase_id,
            attempt_number=attempt_number,
            status="failed",
            exit_code=1,
            error_message=str(exc),
        )
        return PhaseExecutionResult(False, attempt_number, 1, error_message=str(exc)), session_handle
    finally:
        watcher_stop.set()
        cancellation_task.cancel()

    raw_output = "".join(raw_output_chunks)
    if cancel_requested:
        await _finish_attempt(
            db,
            run_id=run_id,
            phase_id=phase_id,
            attempt_number=attempt_number,
            status="cancelled",
            exit_code=-9,
            error_message="cancelled",
        )
        return PhaseExecutionResult(False, attempt_number, -9, raw_output, "cancelled"), session_handle
    # The session process is a long-lived Relay wrapper around prompt-mode
    # Copilot invocations. The phase result must be driven by the most recent
    # prompt exit code, not by whether the wrapper process itself stays alive.
    exit_code = session_handle.last_response_exit_code
    if exit_code is None:
        process = getattr(session_handle, "process", None)
        exit_code = getattr(process, "returncode", None)
    if exit_code is None:
        exit_code = 0

    async with db.session() as session:
        run, phase, project = await _load_run_context(session, run_id, phase_id)
        if phase_type in EXPECTED_PHASE_ARTIFACTS:
            _persist_phase_output_fallback(project.path, run.id, phase_type, raw_output)
            if not check_artifacts_exist(project.path, run.id, phase_type, EXPECTED_PHASE_ARTIFACTS[phase_type]):
                await _finish_attempt(
                    db,
                    run_id=run.id,
                    phase_id=phase.id,
                    attempt_number=attempt_number,
                    status="failed",
                    exit_code=exit_code,
                    error_message="artifacts_missing",
                )
                return PhaseExecutionResult(False, attempt_number, exit_code, raw_output, "artifacts_missing"), session_handle
        if phase_type == "review":
            review_dir = artifact_dir(project.path, run.id, "review")
            comments, parsed = extract_review_comments(raw_output)
            summary = extract_review_summary(raw_output)
            persist_review_outputs(review_dir, raw_output, comments, summary)
            if parsed:
                await _save_review_comments(session, phase.id, attempt_number, comments)
            await session.commit()
            verdict = extract_verdict(summary)
            await _finish_attempt(
                db,
                run_id=run.id,
                phase_id=phase.id,
                attempt_number=attempt_number,
                status="succeeded" if exit_code == 0 else "failed",
                exit_code=exit_code,
                error_message=None if exit_code == 0 else raw_output[-500:],
            )
            return PhaseExecutionResult(
                exit_code == 0,
                attempt_number,
                exit_code,
                raw_output=raw_output,
                review_comments=comments,
                review_summary=summary,
                review_verdict=verdict,
            ), session_handle
        if phase_type == "execution":
            run.pending_fix_prompt = None
            await session.commit()
    await _finish_attempt(
        db,
        run_id=run_id,
        phase_id=phase_id,
        attempt_number=attempt_number,
        status="succeeded" if exit_code == 0 else "failed",
        exit_code=exit_code,
        error_message=None if exit_code == 0 else raw_output[-500:],
    )
    return PhaseExecutionResult(exit_code == 0, attempt_number, exit_code, raw_output), session_handle


async def run_exploration_phase(
    db: DatabaseManager,
    settings: Settings,
    *,
    run_id: str,
    phase_id: str,
    session_handle: CopilotSession | None = None,
) -> tuple[PhaseExecutionResult, CopilotSession | None]:
    async with db.session() as session:
        run, phase, project = await _load_run_context(session, run_id, phase_id)
        ensure_artifact_dirs(project.path, run.id)
        model = _phase_model(run, "exploration")
        session_handle = session_handle or create_session()
        attempt_number, log_file_path = await _start_attempt(
            db,
            settings,
            run_id=run.id,
            phase_id=phase.id,
            phase_type="exploration",
            rendered_prompt="Relay exploration session",
        )
        if not session_handle.is_alive():
            try:
                await session_handle.start(build_exploration_command(settings.copilot_cli_path, model), project.path)
            except Exception as exc:
                await _finish_attempt(
                    db,
                    run_id=run.id,
                    phase_id=phase.id,
                    attempt_number=attempt_number,
                    status="failed",
                    exit_code=1,
                    error_message=str(exc),
                )
                return PhaseExecutionResult(False, attempt_number, 1, error_message=str(exc)), None
        await _mark_attempt_running(
            db,
            run_id=run.id,
            phase_id=phase.id,
            attempt_number=attempt_number,
            pid=session_handle.pid,
        )
        stream_path = reset_exploration_stream(str(settings.data_dir), run.id)
        last_processed_user_sequence = max(
            [message.sequence_number for message in run.exploration_messages if message.role == "assistant"],
            default=0,
        )

    log_path = Path(log_file_path)
    while True:
        await asyncio.sleep(0.2)
        async with db.session() as session:
            run, phase, project = await _load_run_context(session, run_id, phase_id)
            if run.cancel_requested:
                await session_handle.kill()
                await _finish_attempt(
                    db,
                    run_id=run.id,
                    phase_id=phase.id,
                    attempt_number=attempt_number,
                    status="cancelled",
                    exit_code=-9,
                    error_message="cancelled",
                )
                return PhaseExecutionResult(False, attempt_number, -9, error_message="cancelled"), session_handle

            pending_messages = (
                await session.execute(
                    select(ExplorationMessage)
                    .where(
                        ExplorationMessage.workflow_run_id == run.id,
                        ExplorationMessage.role == "user",
                        ExplorationMessage.sequence_number > last_processed_user_sequence,
                    )
                    .order_by(ExplorationMessage.sequence_number.asc())
                )
            ).scalars().all()

            for message in pending_messages:
                save_message_file(
                    project.path,
                    run.id,
                    message_id=message.id,
                    role=message.role,
                    content=message.content,
                    timestamp=message.created_at,
                    sequence=message.sequence_number,
                )
                last_processed_user_sequence = message.sequence_number
                response_chunks: list[str] = []
                response_message_id = str(uuid.uuid4())
                try:
                    with log_path.open("a", encoding="utf-8") as log_file, stream_path.open("a", encoding="utf-8") as stream_file:
                        sender = session_handle.send_followup if session_handle.is_alive() else session_handle.send
                        async for chunk in sender(message.content):
                            response_chunks.append(chunk)
                            log_file.write(chunk)
                            stream_file.write(json.dumps({"message_id": response_message_id, "content": chunk, "done": False}) + "\n")
                            log_file.flush()
                            stream_file.flush()
                        stream_file.write(json.dumps({"message_id": response_message_id, "content": "", "done": True}) + "\n")
                except Exception as exc:
                    await _finish_attempt(
                        db,
                        run_id=run.id,
                        phase_id=phase.id,
                        attempt_number=attempt_number,
                        status="failed",
                        exit_code=session_handle.last_response_exit_code or 1,
                        error_message=str(exc),
                    )
                    return PhaseExecutionResult(False, attempt_number, session_handle.last_response_exit_code or 1, error_message=str(exc)), session_handle
                assistant_content = "".join(response_chunks)
                next_sequence = (
                    await session.execute(
                        select(func.max(ExplorationMessage.sequence_number)).where(
                            ExplorationMessage.workflow_run_id == run.id
                        )
                    )
                ).scalar_one()
                assistant_message = ExplorationMessage(
                    id=response_message_id,
                    workflow_run_id=run.id,
                    role="assistant",
                    content=assistant_content,
                    sequence_number=(next_sequence or 0) + 1,
                    created_at=_utc_now(),
                )
                session.add(assistant_message)
                await session.commit()
                save_message_file(
                    project.path,
                    run.id,
                    message_id=assistant_message.id,
                    role="assistant",
                    content=assistant_message.content,
                    timestamp=assistant_message.created_at,
                    sequence=assistant_message.sequence_number,
                )

            if run.finalize_requested:
                message_rows = (
                    await session.execute(
                        select(ExplorationMessage)
                        .where(ExplorationMessage.workflow_run_id == run.id)
                        .order_by(ExplorationMessage.sequence_number.asc())
                    )
                ).scalars().all()
                transcript_path = write_transcript(
                    project.path,
                    run.id,
                    [
                        {
                            "role": item.role,
                            "content": item.content,
                        }
                        for item in message_rows
                    ],
                )
                planning_prompt_chunks: list[str] = []
                prompt = build_exploration_finalization_prompt(
                    transcript_path.read_text(encoding="utf-8"),
                    list(_load_json(run.context_paths)),
                    str(planning_prompt_path(project.path, run.id)),
                )
                try:
                    with log_path.open("a", encoding="utf-8") as log_file:
                        sender = session_handle.send_followup if session_handle.is_alive() else session_handle.send
                        async for chunk in sender(prompt):
                            planning_prompt_chunks.append(chunk)
                            log_file.write(chunk)
                            log_file.flush()
                except Exception as exc:
                    await _finish_attempt(
                        db,
                        run_id=run.id,
                        phase_id=phase.id,
                        attempt_number=attempt_number,
                        status="failed",
                        exit_code=session_handle.last_response_exit_code or 1,
                        error_message=str(exc),
                    )
                    return PhaseExecutionResult(False, attempt_number, session_handle.last_response_exit_code or 1, error_message=str(exc)), session_handle
                planning_output = "".join(planning_prompt_chunks)
                planning_prompt_path(project.path, run.id).write_text(planning_output, encoding="utf-8")
                run.finalize_requested = False
                await session.commit()
                await _finish_attempt(
                    db,
                    run_id=run.id,
                    phase_id=phase.id,
                    attempt_number=attempt_number,
                    status="succeeded",
                    exit_code=0,
                )
                return PhaseExecutionResult(True, attempt_number, 0, planning_output), session_handle
