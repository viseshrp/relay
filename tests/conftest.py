from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from relay.api.app import create_app
from relay.config import Settings
from relay.copilot.session import set_session_factory
from relay.db import DatabaseManager


@pytest.fixture
def event_loop() -> asyncio.AbstractEventLoop:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def db_manager(tmp_path: Path) -> DatabaseManager:
    manager = DatabaseManager(tmp_path / "relay.db")
    yield manager
    await manager.dispose()


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src" / "main.py").write_text("print('relay')\n", encoding="utf-8")
    return project


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "relay-data",
        db_path=tmp_path / "relay.db",
        host="127.0.0.1",
        port=8080,
        copilot_cli_path="gh",
        frontend_dist_dir=tmp_path / "dist",
        poll_interval_seconds=0.1,
        process_monitor_interval_seconds=0.1,
        default_retry_limit=5,
        default_review_fix_loop_limit=5,
        default_autopilot=True,
    )


@pytest.fixture(autouse=True)
def reset_session_factory() -> None:
    set_session_factory(None)
    yield
    set_session_factory(None)


@pytest.fixture
async def app(test_settings: Settings):
    application = create_app(test_settings)
    async with LifespanManager(application):
        yield application


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        yield http_client
