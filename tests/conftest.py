"""Isolate every test: scratch Relay directories, test settings, and a fresh database copy.

Relay finds its storage through its `RELAY_*` overrides and through `platformdirs`, which
reads the XDG variables on Linux and macOS and `WIN_PD_OVERRIDE_LOCAL_APPDATA` on Windows
each time a path is requested. They point at scratch directories before Django loads the
settings module and again for every test, so no test can touch an owner's database, logs,
worktrees, or artifacts.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from datetime import datetime, tzinfo
from pathlib import Path
import shutil
import tempfile
import time
from types import SimpleNamespace
from typing import TYPE_CHECKING, TypeVar

import pytest

if TYPE_CHECKING:
    from relay.agents.models import AgentExecutionContext
    from tests.support import (
        Clock,
        FakeAgentDriver,
        FakeAgents,
        InlineEngine,
        RegistryNetwork,
        RelayProject,
    )

ThreadResult = TypeVar("ThreadResult")

_SESSION_ROOT = Path(tempfile.mkdtemp(prefix="relay-tests-"))
_TEMPLATE_DATABASE = _SESSION_ROOT / "template" / "relay.db"


def _scratch_directories(root: Path) -> dict[str, str]:
    return {
        "XDG_CONFIG_HOME": str(root / "config"),
        "XDG_DATA_HOME": str(root / "data"),
        "XDG_STATE_HOME": str(root / "state"),
        "WIN_PD_OVERRIDE_LOCAL_APPDATA": str(root / "local"),
        "RELAY_LOG_PATH": str(root / "logs" / "relay.log"),
    }


_SESSION_ENVIRONMENT: pytest.MonkeyPatch = pytest.MonkeyPatch()
for _name, _value in {
    "DJANGO_SETTINGS_MODULE": "relay.web.settings",
    "RELAY_DATABASE_PATH": str(_TEMPLATE_DATABASE),
    "RELAY_HUEY_DATABASE_PATH": str(_SESSION_ROOT / "huey" / "huey.db"),
    "RELAY_MIGRATION_LOCK_PATH": str(_SESSION_ROOT / "template" / "migrate.lock"),
    "RELAY_DJANGO_SECRET_KEY": "relay-tests-only-secret-key-0123456789abcdefghijklmnop",
    **_scratch_directories(_SESSION_ROOT / "dirs"),
}.items():
    _SESSION_ENVIRONMENT.setenv(_name, _value)


def _prepare_django() -> None:
    import django

    # Test modules import models at collection time, so the app registry loads first.
    django.setup()


_prepare_django()


@pytest.fixture(scope="session", autouse=True)
def migrated_template() -> Iterator[Path]:
    """Migrate one template database; each test receives its own copy."""
    from django.db import connection, connections
    from django.test.utils import setup_test_environment, teardown_test_environment

    from relay.manage import apply_migrations

    apply_migrations()
    setup_test_environment()
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    connections.close_all()
    yield _TEMPLATE_DATABASE
    teardown_test_environment()
    connections.close_all()
    shutil.rmtree(_SESSION_ROOT, ignore_errors=True)
    _SESSION_ENVIRONMENT.undo()


@pytest.fixture(autouse=True)
def isolated_relay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, migrated_template: Path
) -> Iterator[None]:
    """Give the test scratch directories, a fresh database, and empty process caches."""
    from django.conf import settings
    from django.db import connections

    from relay.execution import huey_app
    from relay.execution.dispatch import set_dispatch_notifier
    from relay.web import views

    for name, value in _scratch_directories(tmp_path / "relay").items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "empty-gitconfig"))
    connections.close_all()
    database = tmp_path / "database" / "relay.db"
    database.parent.mkdir()
    shutil.copyfile(migrated_template, database)
    monkeypatch.setitem(settings.DATABASES["default"], "NAME", str(database))
    # A web process caches its served project and a consumer caches its event cursor for
    # their whole lifetime; each test starts both from its own fresh database.
    monkeypatch.setattr(views, "_PROJECT", None)
    monkeypatch.setattr(huey_app, "_SCHEDULE_CURSOR", None)
    yield
    set_dispatch_notifier(None)
    connections.close_all()
    # API launches enqueue claim tokens in the shared session queue; no consumer runs them.
    huey_app.huey.flush()
    huey_app.huey.storage.close()


@pytest.fixture
def project(tmp_path: Path) -> RelayProject:
    from tests.support import create_project

    return create_project(tmp_path / "repo")


@pytest.fixture
def agent_driver() -> FakeAgentDriver:
    from tests.support import FakeAgentDriver

    return FakeAgentDriver()


@pytest.fixture
def engine(agent_driver: FakeAgentDriver) -> InlineEngine:
    from relay.execution.nodes import node_executors
    from relay.paths import artifacts_dir
    from tests.support import InlineEngine

    # The consumer preserves evidence under artifacts_dir(), where read APIs resolve it.
    return InlineEngine(node_executors(agent_driver=agent_driver), artifacts_dir(create=True))


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    from django.utils import timezone

    from relay.execution import runner
    from tests.support import Clock

    controlled = Clock()

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> datetime:
            value = controlled.instant
            return value.astimezone(tz) if tz is not None else value.replace(tzinfo=None)

    monkeypatch.setattr(time, "monotonic", controlled.monotonic)
    # Model defaults can retain timezone.now; freeze its datetime lookup as well.
    monkeypatch.setattr(timezone, "datetime", FrozenDateTime)
    monkeypatch.setattr(runner, "datetime", FrozenDateTime)
    return controlled


@pytest.fixture
def registry_network(monkeypatch: pytest.MonkeyPatch) -> RegistryNetwork:
    from relay.agents import registry
    from tests.support import RegistryNetwork

    network = RegistryNetwork()
    monkeypatch.setattr(registry, "urlopen", network.open)
    return network


@pytest.fixture
def fake_agents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeAgents:
    from relay.agents import discovery
    from tests.support import FakeAgents

    agents = FakeAgents(tmp_path / "agent-bin", tmp_path / "provider-transcript.jsonl", monkeypatch)
    agents.directory.mkdir()
    agents.isolate_path()
    # Git's installation directory can contain a real agent; keep discovery offline.
    monkeypatch.setattr(discovery, "shutil", SimpleNamespace(which=agents.find_executable))
    return agents


@pytest.fixture
def database_threads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Close Django connections in the thread that opened them, before its pool exits."""
    from django.db import connections

    to_thread = asyncio.to_thread

    async def call(
        function: Callable[..., ThreadResult], *args: object, **kwargs: object
    ) -> ThreadResult:
        def invoke() -> ThreadResult:
            try:
                return function(*args, **kwargs)
            finally:
                connections.close_all()

        return await to_thread(invoke)

    monkeypatch.setattr(asyncio, "to_thread", call)


@pytest.fixture
def agent_context(
    request: pytest.FixtureRequest,
    project: RelayProject,
    engine: InlineEngine,
    fake_agents: FakeAgents,
    registry_network: RegistryNetwork,
    database_threads: None,
) -> AgentExecutionContext:
    from relay.agents.models import AgentCommand, AgentExecutionContext
    from relay.execution.runner import AttemptContext
    from relay.workflows.schema import AgentNode

    del registry_network, database_threads
    agent_id = request.param if hasattr(request, "param") else "codex"
    executable = fake_agents.install(agent_id)
    project.write_workflow(
        "agent",
        "version: 1\nname: Agent\nmodel: m1\n"
        f"agents: [{agent_id}]\nnodes:\n"
        "  work: {type: agent, prompts: [{local: prompts/prompt.md}], "
        "writes: true, allow_no_commit: true}\n",
    )
    run_id = engine.launch(project, "agent")
    claim = engine.store.claim_dispatch(engine.tokens.popleft(), "provider-worker").attempt
    assert claim is not None and claim.run_id == run_id
    node = AgentNode.model_validate(claim.frozen_def)
    return AgentExecutionContext(
        AttemptContext(claim, Path(claim.primary_worktree), engine.store),
        node,
        agent_id,
        "m1",
        "respect_settings" if agent_id == "antigravity" else "interactive",
        AgentCommand(str(executable)),
    )
