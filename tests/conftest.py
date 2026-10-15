"""Isolate every test: scratch Relay directories, test settings, and a fresh database copy.

Relay finds its storage through its `RELAY_*` overrides and through `platformdirs`, which
reads the XDG variables on Linux and macOS and `WIN_PD_OVERRIDE_LOCAL_APPDATA` on Windows
each time a path is requested. They point at scratch directories before Django loads the
settings module and again for every test, so no test can touch an owner's database, logs,
worktrees, or artifacts.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Generator, Iterator
from datetime import datetime, tzinfo
from pathlib import Path
import re
import shutil
import tempfile
import time
import traceback
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
pytest_plugins = ["tests.ci_reporting"]


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    """Show causes suppressed by public Relay envelopes in failed CI reports."""
    from relay.errors import PersistenceError, persistence_cause

    del item
    report = yield
    if call.excinfo is not None:
        error: BaseException | None = call.excinfo.value
        seen: set[int] = set()
        while error is not None and id(error) not in seen:
            seen.add(id(error))
            if isinstance(error, PersistenceError) and (cause := persistence_cause(error)):
                report.sections.append(
                    ("Persistence cause", "".join(traceback.format_exception(cause)))
                )
            error = error.__cause__ or error.__context__
    return report


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


def pytest_unconfigure() -> None:
    """Also release controller and collection-only scratch roots without fixtures."""
    from django.db import connections

    connections.close_all()
    shutil.rmtree(_SESSION_ROOT, ignore_errors=True)
    _SESSION_ENVIRONMENT.undo()


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
    for alias in ("default", "snapshot"):
        monkeypatch.setitem(settings.DATABASES[alias], "NAME", str(database))
    # A web process caches its served project and a consumer caches its event cursor for
    # their whole lifetime; each test starts both from its own fresh database.
    monkeypatch.setattr(views, "_PROJECT", None)
    monkeypatch.setattr(huey_app, "_SCHEDULE_CURSOR", None)
    monkeypatch.setattr(huey_app, "_DELIVERY_CURSOR", None)
    yield
    set_dispatch_notifier(None)
    connections.close_all()
    # API launches enqueue claim tokens in the shared session queue; no consumer runs them.
    huey_app.huey.flush()
    huey_app.huey.storage.close()


@pytest.fixture
def short_busy_timeout(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    from django.conf import settings
    from django.db import connections

    connections.close_all()
    for database in settings.DATABASES.values():
        options = dict(database.get("OPTIONS", {}))
        options["timeout"] = 0.05
        options["init_command"] = re.sub(
            r"PRAGMA busy_timeout=\d+;?", "", str(options.get("init_command", ""))
        )
        monkeypatch.setitem(database, "OPTIONS", options)

    yield
    connections.close_all()


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
    from relay.web import actions_repository

    monkeypatch.setattr(actions_repository, "datetime", FrozenDateTime)
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
        (
            f"name: Agent\n"
            f"jobs:\n"
            f"  work:\n"
            f"    steps:\n"
            f"    - id: work\n"
            f"      uses: relay/agent@v1\n"
            f"      with:\n"
            f"        agent: {agent_id}\n"
            f"        model: m1\n"
            f"        prompt-files: prompts/prompt.md\n"
        ),
    )
    run_id = engine.launch(project, "agent")
    from relay.execution.dispatch import dispatch_node
    from relay.web.models import NodeRun
    from relay.workflows.schema import ActionsJobNode, ActionsStepNode

    parent = engine.store.claim_dispatch(engine.tokens.popleft(), "provider-worker").attempt
    assert parent is not None
    job = ActionsJobNode.model_validate(parent.frozen_def)
    step = ActionsStepNode(
        job_id=job.job_id,
        step_id="work",
        step=job.job["steps"][0],
        job=job.job,
        workflow=job.workflow,
        state_scope=parent.scope_path,
        index=0,
        bound_agent=job.bound_agents["work"],
    )
    engine.store.ensure_scope_nodes(
        run_id, parent.scope_path, {"work": step.model_dump(mode="json")}, {}
    )
    row = NodeRun.objects.get(run_id=run_id, scope_path=f"{parent.scope_path}.work")
    engine.store.transition_scope_node(
        str(row.pk), "dependencies_satisfied", expected_status="pending"
    )
    token = dispatch_node(engine.store, str(row.pk), lambda _token: None)
    assert token is not None
    claim = engine.store.claim_dispatch(token, "provider-worker").attempt
    assert claim is not None and claim.run_id == run_id
    node = AgentNode.model_validate(claim.frozen_def["bound_agent"])
    return AgentExecutionContext(
        AttemptContext(claim, Path(claim.primary_worktree), engine.store),
        node,
        agent_id,
        "m1",
        "respect_settings" if agent_id == "antigravity" else "interactive",
        AgentCommand(str(executable)),
    )
