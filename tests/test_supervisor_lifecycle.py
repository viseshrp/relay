"""Supervisor lifecycle through real persistence and fake operating-system boundaries."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
import os
import signal
import socket
import subprocess
from types import FrameType, SimpleNamespace

import pytest

from relay.config import RelayConfig
from relay.constants import INSTANCE_HEARTBEAT_INTERVAL_SECONDS
from relay.errors import ConfigError, PersistenceError
from relay.paths import shutdown_marker_path
from relay.web import supervisor
from relay.web.models import Instance, NodeAttempt, Run
from relay.web.repositories import DjangoExecutionStore
from tests.support import Clock, InlineEngine, RelayProject

SignalHandler = Callable[[int, FrameType | None], None] | int | None


@dataclass
class ChildProcess:
    arguments: tuple[str, ...]
    pid: int
    returncode: int | None = None
    ignore_grace: bool = False

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float) -> int:
        if self.returncode is None:
            raise subprocess.TimeoutExpired(self.arguments, timeout)
        return self.returncode


@dataclass
class BoundSocket:
    occupied: bool

    def setsockopt(self, level: int, option: int, value: int) -> None:
        del level, option, value

    def bind(self, address: object) -> None:
        del address
        if self.occupied:
            message = "Address already in use"
            raise OSError(message)

    def listen(self, backlog: int) -> None:
        del backlog

    def close(self) -> None:
        pass


@dataclass
class ControlledEvent:
    boundary: SupervisorBoundary
    requested: bool = False

    def set(self) -> None:
        self.requested = True

    def is_set(self) -> bool:
        return self.requested

    def wait(self, timeout: float) -> bool:
        if not self.requested:
            self.boundary.clock.advance(INSTANCE_HEARTBEAT_INTERVAL_SECONDS + 1)
            self.boundary.waits += 1
            if self.boundary.stop_after_waits == self.boundary.waits:
                self.boundary.send_stop()
        return self.requested


@dataclass
class SupervisorBoundary:
    clock: Clock
    children: list[ChildProcess] = field(default_factory=list)
    launches: list[dict[str, object]] = field(default_factory=list)
    handlers: dict[int, SignalHandler] = field(default_factory=dict)
    requests: list[tuple[str, str]] = field(default_factory=list)
    browser_urls: list[str] = field(default_factory=list)
    forced_pids: list[int] = field(default_factory=list)
    spawn_failure_at: int | None = None
    startup_exit_at: int | None = None
    occupied: bool = False
    readiness_status: int = 200
    readiness_error: bool = False
    browser_accepts: bool = True
    stop_after_waits: int | None = 2
    waits: int = 0

    def addresses(
        self, host: str, port: int, **options: int
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        family = socket.AF_INET6 if host == "::1" else socket.AF_INET
        return [(family, options["type"], 0, "", (host, port))]

    def socket(self, family: int, kind: int, protocol: int) -> BoundSocket:
        del family, kind, protocol
        return BoundSocket(self.occupied)

    def spawn(self, arguments: Sequence[str], **options: object) -> ChildProcess:
        if self.spawn_failure_at == len(self.children):
            message = "Child executable unavailable"
            raise OSError(message)
        child = ChildProcess(tuple(arguments), 13_000 + len(self.children))
        if self.startup_exit_at == len(self.children):
            child.returncode = 7
        self.children.append(child)
        self.launches.append(options)
        return child

    def event(self) -> ControlledEvent:
        return ControlledEvent(self)

    def hostname(self) -> str:
        return "test-host"

    def wall_time(self) -> float:
        return self.clock.instant.timestamp()

    def stop_when_ready(self, url: str) -> None:
        del url
        self.send_stop()

    def get_handler(self, number: int) -> SignalHandler:
        return self.handlers.get(number, signal.SIG_DFL)

    def set_handler(self, number: int, handler: SignalHandler) -> SignalHandler:
        previous = self.get_handler(number)
        self.handlers[number] = handler
        return previous

    def send_stop(self) -> None:
        handler = self.get_handler(signal.SIGINT)
        if not callable(handler):
            message = "The supervisor did not install its signal handler"
            raise TypeError(message)
        handler(signal.SIGINT, None)

    def stop_tree(
        self, pid: int, *, graceful_signal: signal.Signals = signal.SIGTERM, force: bool = False
    ) -> None:
        del graceful_signal
        if force:
            self.forced_pids.append(pid)
        for child in self.children:
            if child.pid == pid and (force or not child.ignore_grace):
                child.returncode = 0

    def connection(self, host: str, port: int, *, timeout: float) -> SupervisorBoundary:
        del host, port, timeout
        return self

    def request(self, method: str, path: str) -> None:
        if self.readiness_error:
            message = "Loopback child unavailable"
            raise OSError(message)
        self.requests.append((method, path))

    def getresponse(self) -> SupervisorBoundary:
        if self.readiness_status != 200:
            self.clock.advance(INSTANCE_HEARTBEAT_INTERVAL_SECONDS + 1)
        return self

    @property
    def status(self) -> int:
        return self.readiness_status

    def read(self) -> bytes:
        return b"{}"

    def close(self) -> None:
        pass

    def open_browser(self, url: str) -> bool:
        self.browser_urls.append(url)
        return self.browser_accepts


@pytest.fixture
def supervisor_boundary(
    project: RelayProject, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> SupervisorBoundary:
    boundary = SupervisorBoundary(clock)
    monkeypatch.chdir(project.repository)
    monkeypatch.setattr(
        supervisor,
        "socket",
        SimpleNamespace(
            getaddrinfo=boundary.addresses,
            socket=boundary.socket,
            gethostname=boundary.hostname,
            AF_INET6=socket.AF_INET6,
            SOCK_STREAM=socket.SOCK_STREAM,
            SOL_SOCKET=socket.SOL_SOCKET,
            SO_REUSEADDR=socket.SO_REUSEADDR,
            SO_EXCLUSIVEADDRUSE=getattr(socket, "SO_EXCLUSIVEADDRUSE", 0),
            IPPROTO_IPV6=socket.IPPROTO_IPV6,
            IPV6_V6ONLY=socket.IPV6_V6ONLY,
        ),
    )
    monkeypatch.setattr(
        supervisor,
        "subprocess",
        SimpleNamespace(
            Popen=boundary.spawn,
            DEVNULL=subprocess.DEVNULL,
            CREATE_NEW_PROCESS_GROUP=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            TimeoutExpired=subprocess.TimeoutExpired,
            SubprocessError=subprocess.SubprocessError,
        ),
    )
    monkeypatch.setattr(
        supervisor,
        "signal",
        SimpleNamespace(
            SIGINT=signal.SIGINT,
            SIGTERM=signal.SIGTERM,
            getsignal=boundary.get_handler,
            signal=boundary.set_handler,
        ),
    )
    monkeypatch.setattr(supervisor, "threading", SimpleNamespace(Event=boundary.event))
    monkeypatch.setattr(supervisor, "HTTPConnection", boundary.connection)
    monkeypatch.setattr(supervisor, "signal_process_tree", boundary.stop_tree)
    monkeypatch.setattr(
        supervisor,
        "time",
        SimpleNamespace(monotonic=clock.monotonic, time=boundary.wall_time, sleep=clock.advance),
    )
    monkeypatch.setattr(supervisor, "webbrowser", SimpleNamespace(open=boundary.open_browser))
    return boundary


@pytest.mark.parametrize(
    ("host", "url"),
    [
        ("127.0.0.1", "http://127.0.0.1:7845/"),
        ("localhost", "http://localhost:7845/"),
        ("::1", "http://[::1]:7845/"),
    ],
)
def test_supervisor_opens_the_ready_loopback_url_and_releases_its_lease(
    supervisor_boundary: SupervisorBoundary, host: str, url: str
) -> None:
    boundary = supervisor_boundary
    boundary.browser_accepts = False
    supervisor.run_supervisor(RelayConfig(host=host), open_browser=True)
    assert boundary.browser_urls == [url]
    assert boundary.requests == [("GET", "/api/auth")]
    assert all(child.returncode == 0 for child in boundary.children)
    assert len(boundary.children) == 2
    assert not Instance.objects.exists()
    assert not shutdown_marker_path().exists()
    assert boundary.handlers == {signal.SIGINT: signal.SIG_DFL, signal.SIGTERM: signal.SIG_DFL}


def test_supervisor_launches_thread_workers_with_the_owner_configuration(
    supervisor_boundary: SupervisorBoundary, project: RelayProject
) -> None:
    boundary = supervisor_boundary
    supervisor.run_supervisor(
        RelayConfig(port=9001, workers=3), open_browser=False, on_ready=boundary.stop_when_ready
    )
    web, consumer = boundary.children
    assert web.arguments[1:5] == ("-m", "uvicorn", "relay.web.asgi:application", "--host")
    assert web.arguments[web.arguments.index("--port") + 1] == "9001"
    assert consumer.arguments[consumer.arguments.index("-k") + 1] == "thread"
    assert consumer.arguments[consumer.arguments.index("-w") + 1] == "3"
    assert all(
        options["env"]["RELAY_PROJECT_ROOT"] == str(project.repository)
        for options in boundary.launches
    )
    assert not boundary.browser_urls


@pytest.mark.parametrize("failed_child", [0, 1])
def test_supervisor_child_failure_settles_the_claim_and_releases_the_lease(
    supervisor_boundary: SupervisorBoundary,
    project: RelayProject,
    engine: InlineEngine,
    failed_child: int,
) -> None:
    project.write_workflow(
        "running",
        "version: 1\nname: Running\nnodes:\n  work: {type: command, run: [git, status]}\n",
    )
    run_id = engine.launch(project, "running")
    claim = engine.store.claim_dispatch(engine.tokens.popleft(), "active-worker").attempt
    assert claim is not None
    boundary = supervisor_boundary

    def child_exits(_url: str) -> None:
        boundary.children[failed_child].returncode = 7

    with pytest.raises(PersistenceError):
        supervisor.run_supervisor(RelayConfig(), open_browser=False, on_ready=child_exits)
    attempt = NodeAttempt.objects.get(pk=claim.attempt_id)
    assert (attempt.status, attempt.stop_reason) == (
        ("terminal", "interrupted") if failed_child == 0 else ("terminal", "worker_lost")
    )
    assert Run.objects.get(pk=run_id).status == ("interrupted" if failed_child == 0 else "failed")
    assert not Instance.objects.exists()
    assert not shutdown_marker_path().exists()
    assert all(child.returncode is not None for child in boundary.children)


@pytest.mark.parametrize("index", [0, 1])
def test_supervisor_spawn_failure_stops_any_child_already_started(
    supervisor_boundary: SupervisorBoundary, index: int
) -> None:
    boundary = supervisor_boundary
    boundary.spawn_failure_at = index
    with pytest.raises(PersistenceError):
        supervisor.run_supervisor(RelayConfig(), open_browser=False)
    assert all(child.returncode == 0 for child in boundary.children)
    assert not Instance.objects.exists()


@pytest.mark.parametrize("index", [0, 1])
def test_supervisor_startup_child_exit_stops_its_sibling_without_opening_a_browser(
    supervisor_boundary: SupervisorBoundary, index: int
) -> None:
    boundary = supervisor_boundary
    boundary.startup_exit_at = index
    with pytest.raises(PersistenceError):
        supervisor.run_supervisor(RelayConfig(), open_browser=True)
    assert not boundary.browser_urls
    assert all(child.returncode is not None for child in boundary.children)
    assert not Instance.objects.exists()


def test_supervisor_rejects_an_occupied_port_before_starting_children(
    supervisor_boundary: SupervisorBoundary,
) -> None:
    boundary = supervisor_boundary
    boundary.occupied = True
    with pytest.raises(ConfigError):
        supervisor.run_supervisor(RelayConfig(), open_browser=False)
    assert not boundary.children
    assert not Instance.objects.exists()


@pytest.mark.parametrize("failure", ["http-error", "not-ready"])
def test_supervisor_startup_deadline_stops_children_without_publishing_a_url(
    supervisor_boundary: SupervisorBoundary, failure: str
) -> None:
    boundary = supervisor_boundary
    boundary.readiness_error = failure == "http-error"
    boundary.readiness_status = 503
    boundary.stop_after_waits = None
    with pytest.raises(PersistenceError):
        supervisor.run_supervisor(RelayConfig(), open_browser=True)
    assert not boundary.browser_urls
    assert all(child.returncode == 0 for child in boundary.children)
    assert not Instance.objects.exists()


def test_supervisor_forces_children_that_ignore_orderly_shutdown(
    supervisor_boundary: SupervisorBoundary,
) -> None:
    boundary = supervisor_boundary

    def stop_stubborn_children(_url: str) -> None:
        for child in boundary.children:
            child.ignore_grace = True
        boundary.send_stop()

    supervisor.run_supervisor(RelayConfig(), open_browser=False, on_ready=stop_stubborn_children)
    assert set(boundary.forced_pids) == {child.pid for child in boundary.children}
    assert all(child.returncode == 0 for child in boundary.children)
    assert not shutdown_marker_path().exists()


def test_supervisor_lost_lease_stops_children_and_reports_a_persistence_error(
    supervisor_boundary: SupervisorBoundary,
) -> None:
    boundary = supervisor_boundary

    def release_lease(_url: str) -> None:
        owner = Instance.objects.get()
        DjangoExecutionStore().release_instance(str(owner.pk))

    with pytest.raises(PersistenceError):
        supervisor.run_supervisor(RelayConfig(), open_browser=False, on_ready=release_lease)
    assert all(child.returncode is not None for child in boundary.children)
    assert not Instance.objects.exists()
    assert shutdown_marker_path().exists()


def test_supervisor_marker_write_failure_stops_children_and_releases_its_lease(
    supervisor_boundary: SupervisorBoundary, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable_marker(path: object, flags: int, mode: int) -> int:
        del path, flags, mode
        message = "Shutdown marker storage unavailable"
        raise OSError(message)

    monkeypatch.setattr(
        supervisor,
        "os",
        SimpleNamespace(
            name=os.name,
            environ=os.environ,
            getpid=os.getpid,
            open=unavailable_marker,
            fdopen=os.fdopen,
            fsync=os.fsync,
            O_WRONLY=os.O_WRONLY,
            O_CREAT=os.O_CREAT,
            O_TRUNC=os.O_TRUNC,
        ),
    )
    with pytest.raises(OSError):
        supervisor.run_supervisor(RelayConfig(), open_browser=False)
    assert all(child.returncode is not None for child in supervisor_boundary.children)
    assert not Instance.objects.exists()


def test_supervisor_keyboard_interrupt_stops_children_and_releases_its_lease(
    supervisor_boundary: SupervisorBoundary,
) -> None:
    def keyboard_interrupt(_url: str) -> None:
        raise KeyboardInterrupt

    supervisor.run_supervisor(RelayConfig(), open_browser=False, on_ready=keyboard_interrupt)
    assert all(child.returncode is not None for child in supervisor_boundary.children)
    assert not Instance.objects.exists()
    assert not shutdown_marker_path().exists()


def test_startup_marker_never_authorizes_signaling_a_previous_attempt_pid(
    supervisor_boundary: SupervisorBoundary, project: RelayProject, engine: InlineEngine
) -> None:
    project.write_workflow(
        "resume", "version: 1\nname: Resume\nnodes:\n  work: {type: command, run: [git, status]}\n"
    )
    run_id = engine.launch(project, "resume")
    claim = engine.store.claim_dispatch(engine.tokens.popleft(), "old-worker").attempt
    assert claim is not None
    engine.store.record_agent_session(
        claim.attempt_id, process_id=os.getpid(), session_id=None, agent_version="", config_ids={}
    )
    marker = shutdown_marker_path()
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("{}", encoding="utf-8")
    boundary = supervisor_boundary
    supervisor.run_supervisor(RelayConfig(), open_browser=False, on_ready=boundary.stop_when_ready)
    assert os.getpid() not in boundary.forced_pids
    assert NodeAttempt.objects.get(pk=claim.attempt_id).stop_reason == "interrupted"
    assert Run.objects.get(pk=run_id).status == "interrupted"
    assert not marker.exists()
