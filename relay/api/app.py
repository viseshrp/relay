from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from relay.api import artifacts, exploration, phases, projects, runs, settings as settings_router, system, workflow_control, ws
from relay.config import Settings, get_settings
from relay.copilot.models import discover_available_models
from relay.db import DatabaseManager
from relay.realtime.connection_manager import ConnectionManager
from relay.realtime.notifier import StatusNotifier
from relay.services.phase_service import PhaseService
from relay.services.project_service import ProjectService
from relay.services.run_service import RunService
from relay.services.settings_service import SettingsService


def _alembic_config(settings: Settings) -> Config:
    root = Path(__file__).resolve().parent.parent.parent
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    return config


async def run_migrations(settings: Settings) -> None:
    await asyncio.to_thread(command.upgrade, _alembic_config(settings), "head")


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    db = DatabaseManager(resolved_settings.db_path)
    connection_manager = ConnectionManager()
    settings_service = SettingsService(resolved_settings)
    project_service = ProjectService()
    run_service = RunService(settings_service)
    phase_service = PhaseService()
    notifier = StatusNotifier(db, connection_manager)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await run_migrations(resolved_settings)
        app.state.settings = resolved_settings
        app.state.db = db
        app.state.connection_manager = connection_manager
        app.state.settings_service = settings_service
        app.state.project_service = project_service
        app.state.run_service = run_service
        app.state.phase_service = phase_service
        app.state.notifier = notifier
        app.state.active_tasks = {}
        # Rebuild the Copilot model catalog at app startup so every fresh launch
        # reflects the CLI's current supported models instead of a stale list
        # baked into the frontend bundle.
        app.state.available_copilot_models = [
            option.to_dict() for option in await discover_available_models(resolved_settings.copilot_cli_path)
        ]
        notifier_task = asyncio.create_task(notifier.run())
        try:
            yield
        finally:
            await notifier.stop()
            notifier_task.cancel()
            with suppress(asyncio.CancelledError):
                await notifier_task
            await db.dispose()

    app = FastAPI(title="Relay", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    api_prefix = "/api/v1"
    app.include_router(system.router, prefix=api_prefix)
    app.include_router(projects.router, prefix=api_prefix)
    app.include_router(runs.router, prefix=api_prefix)
    app.include_router(phases.router, prefix=api_prefix)
    app.include_router(exploration.router, prefix=api_prefix)
    app.include_router(workflow_control.router, prefix=api_prefix)
    app.include_router(artifacts.router, prefix=api_prefix)
    app.include_router(settings_router.router, prefix=api_prefix)
    app.include_router(ws.router, prefix=api_prefix)

    assets_dir = resolved_settings.frontend_dist_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        @app.get("/{full_path:path}", response_model=None)
        async def spa_fallback(full_path: str):  # pragma: no cover - static serving
            if full_path.startswith("api/"):
                return JSONResponse({"detail": "Not found."}, status_code=404)
            return FileResponse(resolved_settings.frontend_dist_dir / "index.html")

    return app
