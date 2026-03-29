from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import text

from relay import __version__
from relay.copilot.detection import detect_copilot_status
from relay.models import UserSetting
from relay.schemas.settings import HealthResponse, SystemStatusResponse

router = APIRouter(tags=["system"])


def _parse_timestamp(raw: str | None) -> datetime | None:
    if not raw:
        return None
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


async def _worker_status(request: Request) -> tuple[str, int, int]:
    async with request.app.state.db.session() as session:
        heartbeat = await session.get(UserSetting, "worker_heartbeat")
        limit = await session.get(UserSetting, "worker_concurrency_limit")
        status = await session.get(UserSetting, "worker_status")
        active_workflows = (
            await session.execute(text("SELECT COUNT(*) FROM workflow_runs WHERE status = 'running'"))
        ).scalar_one()
    heartbeat_at = _parse_timestamp(json.loads(heartbeat.value)) if heartbeat else None
    is_live = heartbeat_at is not None and heartbeat_at >= datetime.now(UTC) - timedelta(seconds=15)
    concurrency_limit = json.loads(limit.value) if limit else 0
    if is_live:
        return json.loads(status.value) if status else "running", concurrency_limit, active_workflows
    return "offline", concurrency_limit, active_workflows


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    async with request.app.state.db.session() as session:
        try:
            await session.execute(text("SELECT 1"))
            db_status = "ok"
        except Exception as exc:  # pragma: no cover - defensive
            raise HTTPException(status_code=500, detail=str(exc)) from exc
    copilot = await detect_copilot_status(request.app.state.settings)
    worker_status, _limit, _active = await _worker_status(request)
    copilot_payload = copilot.to_dict()
    # Test harnesses and lightweight app fixtures may not preload this field,
    # so default to an empty catalog rather than raising an attribute error.
    copilot_payload["available_models"] = getattr(request.app.state, "available_copilot_models", [])
    return HealthResponse(ok=db_status == "ok", database=db_status, worker=worker_status, copilot=copilot_payload)


@router.get("/system/status", response_model=SystemStatusResponse)
async def system_status(request: Request) -> SystemStatusResponse:
    worker_status, concurrency_limit, active_workflows = await _worker_status(request)
    copilot = await detect_copilot_status(request.app.state.settings)
    copilot_payload = copilot.to_dict()
    copilot_payload["available_models"] = getattr(request.app.state, "available_copilot_models", [])
    return SystemStatusResponse(
        version=__version__,
        worker_status=worker_status,
        concurrency_limit=concurrency_limit,
        active_workflows=active_workflows,
        copilot=copilot_payload,
    )
