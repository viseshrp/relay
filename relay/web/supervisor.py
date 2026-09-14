"""Two-child local runtime supervisor with durable orderly shutdown."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import suppress
from http.client import HTTPConnection, HTTPException
import json
import logging
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time
from types import FrameType
from typing import Protocol
import webbrowser

from relay.config import RelayConfig
from relay.constants import (
    INSTANCE_HEARTBEAT_INTERVAL_SECONDS,
    SHUTDOWN_TIMEOUT_SECONDS,
)
from relay.errors import ConfigError, PersistenceError, RelayError
from relay.execution.huey_app import enqueue_claim
from relay.execution.reconcile import ReconcileStore, reconcile_once
from relay.execution.recovery import RecoveryEvidenceStore, prepare_recovery_workspace
from relay.execution.resume import ResumeStore, resume_interrupted
from relay.execution.scheduler import SchedulingStore, dispatch_ready_nodes
from relay.manage import apply_migrations
from relay.paths import data_dir, shutdown_marker_path
from relay.projects.discovery import discover_relay_root
from relay.projects.service import register_current_project

LOGGER = logging.getLogger(__name__)
_STARTUP_TIMEOUT_SECONDS = 15.0
_ESCALATION_TIMEOUT_SECONDS = 2.0


class SupervisorStore(
    ReconcileStore,
    ResumeStore,
    SchedulingStore,
    RecoveryEvidenceStore,
    Protocol,
):
    """Durable operations coordinated by the parent process."""

    def active_run_ids(self) -> tuple[str, ...]: ...

    def heartbeat_instance(self, instance_id: str) -> bool: ...

    def request_orderly_shutdown(self, instance_id: str) -> int: ...

    def active_attempt_processes(self) -> tuple[tuple[str, int], ...]: ...

    def interrupt_active_attempts(self) -> int: ...


def _browser_url(host: str, port: int) -> str:
    """Render an IPv4/name URL directly and bracket an IPv6 literal.

    For example, ``127.0.0.1`` becomes ``http://127.0.0.1:7845/`` while
    ``::1`` becomes ``http://[::1]:7845/``.
    """
    rendered_host = f"[{host}]" if ":" in host else host
    return f"http://{rendered_host}:{port}/"


def _validate_bind(host: str, port: int) -> None:
    """Fail before child creation when no loopback socket can own the address."""
    if host not in {"127.0.0.1", "localhost", "::1"}:
        message = "Relay may bind only to a loopback address."
        raise ConfigError(message)
    errors: list[OSError] = []
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        message = "Relay could not resolve the requested loopback address."
        raise ConfigError(message) from None
    for family, kind, protocol, _canonical, address in addresses:
        probe = socket.socket(family, kind, protocol)
        bound = False
        try:
            if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            elif os.name != "nt":
                # Match asyncio's POSIX server socket behavior so an immediate restart
                # is not rejected only because the prior listener is in TIME_WAIT.
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if family == socket.AF_INET6:
                probe.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            probe.bind(address)
            probe.listen(1)
            bound = True
        except OSError as error:
            errors.append(error)
        finally:
            probe.close()
        if bound:
            return
    detail = str(errors[-1]) if errors else "no usable loopback address"
    message = f"Relay cannot bind {host}:{port}: {detail}."
    raise ConfigError(
        message,
        next_action="Choose an unused loopback port and run relay up again.",
    )


def _spawn_child(
    arguments: Sequence[str],
    repository: Path,
    environment: dict[str, str],
) -> subprocess.Popen[bytes]:
    if os.name == "nt":
        return subprocess.Popen(  # noqa: S603
            arguments,
            cwd=str(repository),
            env=environment,
            stdin=subprocess.DEVNULL,
            shell=False,
            text=False,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
    return subprocess.Popen(  # noqa: S603
        arguments,
        cwd=str(repository),
        env=environment,
        stdin=subprocess.DEVNULL,
        shell=False,
        text=False,
        start_new_session=True,
    )


def _spawn_children(
    repository: Path,
    config: RelayConfig,
) -> tuple[subprocess.Popen[bytes], subprocess.Popen[bytes]]:
    environment = os.environ.copy()
    environment["RELAY_PROJECT_ROOT"] = str(repository)
    try:
        web = _spawn_child(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "relay.web.asgi:application",
                "--host",
                config.host,
                "--port",
                str(config.port),
                "--http",
                "h11",
                "--no-access-log",
            ],
            repository,
            environment,
        )
        try:
            consumer = _spawn_child(
                [
                    sys.executable,
                    "-m",
                    "relay.manage",
                    "run_huey",
                    "-k",
                    "thread",
                    "-w",
                    str(config.workers),
                    "-t",
                    str(int(SHUTDOWN_TIMEOUT_SECONDS)),
                    "-g",
                    "INT",
                ],
                repository,
                environment,
            )
        except OSError:
            _terminate_child(web, graceful_signal=signal.SIGTERM)
            with suppress(subprocess.TimeoutExpired):
                web.wait(timeout=_ESCALATION_TIMEOUT_SECONDS)
            _kill_child(web)
            with suppress(subprocess.TimeoutExpired):
                web.wait(timeout=_ESCALATION_TIMEOUT_SECONDS)
            raise
    except OSError:
        message = "Relay could not start its local web and worker processes."
        raise PersistenceError(message) from None
    return web, consumer


def _terminate_child(process: subprocess.Popen[bytes], *, graceful_signal: signal.Signals) -> None:
    if process.poll() is not None:
        return
    with suppress(OSError, ProcessLookupError):
        if os.name == "nt":
            process.terminate()
        else:
            os.killpg(process.pid, graceful_signal)


def _kill_child(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    with suppress(OSError, ProcessLookupError):
        if os.name == "nt":
            process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)


def _force_attempt_processes(rows: tuple[tuple[str, int], ...]) -> None:
    for attempt_id, process_id in rows:
        if process_id <= 1 or process_id == os.getpid():
            LOGGER.error(
                "Refusing unsafe recorded attempt pid",
                extra={"attempt_id": attempt_id, "process_id": process_id},
            )
            continue
        try:
            if os.name == "nt":
                subprocess.run(  # noqa: S603
                    ["taskkill", "/PID", str(process_id), "/T", "/F"],  # noqa: S607
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                os.killpg(process_id, signal.SIGKILL)
        except (OSError, subprocess.SubprocessError):
            LOGGER.exception(
                "Attempt process-tree escalation failed",
                extra={"attempt_id": attempt_id, "process_id": process_id},
            )


def _wait_until_ready(
    web: subprocess.Popen[bytes],
    consumer: subprocess.Popen[bytes],
    host: str,
    port: int,
    stop: threading.Event,
) -> None:
    deadline = time.monotonic() + _STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline and not stop.is_set():
        if web.poll() is not None:
            message = f"Relay's web child exited during startup with status {web.returncode}."
            raise PersistenceError(message)
        if consumer.poll() is not None:
            message = (
                f"Relay's worker child exited during startup with status {consumer.returncode}."
            )
            raise PersistenceError(message)
        connection = HTTPConnection(host, port, timeout=0.5)
        try:
            connection.request("GET", "/api/auth")
            response = connection.getresponse()
            response.read()
            if response.status == 200:
                return
        except (OSError, HTTPException):
            stop.wait(0.05)
        finally:
            connection.close()
    if stop.is_set():
        return
    message = "Relay's loopback web application did not become ready in time."
    raise PersistenceError(
        message,
        next_action="Inspect the local Relay log for the child startup failure.",
    )


def _write_shutdown_marker(instance_id: str) -> None:
    target = shutdown_marker_path()
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload = json.dumps(
        {"instance_id": instance_id, "pid": os.getpid(), "requested_at": time.time()},
        sort_keys=True,
    ).encode()
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _startup_reconcile(store: SupervisorStore) -> None:
    marker = shutdown_marker_path()
    orderly_shutdown = marker.exists()
    reconcile_once(store, enqueue_claim, orderly_shutdown=orderly_shutdown)
    if orderly_shutdown:
        # The singleton lease is already ours, so any process recorded by the
        # prior marked instance is an orphan rather than a concurrent worker.
        _force_attempt_processes(store.active_attempt_processes())
        store.interrupt_active_attempts()
    resumed = resume_interrupted(
        store,
        lambda target: prepare_recovery_workspace(store, target),
    )
    for run_id in dict.fromkeys((*store.active_run_ids(), *resumed)):
        dispatch_ready_nodes(store, run_id, enqueue_claim)
    marker.unlink(missing_ok=True)


def _shutdown_children(
    store: SupervisorStore,
    web: subprocess.Popen[bytes],
    consumer: subprocess.Popen[bytes],
) -> None:
    deadline = time.monotonic() + SHUTDOWN_TIMEOUT_SECONDS
    _terminate_child(web, graceful_signal=signal.SIGTERM)
    if os.name != "nt":
        _terminate_child(consumer, graceful_signal=signal.SIGINT)

    windows_stop_sent = False
    while time.monotonic() < deadline:
        if os.name == "nt" and not windows_stop_sent and not store.active_attempt_processes():
            _terminate_child(consumer, graceful_signal=signal.SIGTERM)
            windows_stop_sent = True
        if web.poll() is not None and consumer.poll() is not None:
            break
        time.sleep(0.05)

    if web.poll() is None or consumer.poll() is None:
        _force_attempt_processes(store.active_attempt_processes())
        _terminate_child(web, graceful_signal=signal.SIGTERM)
        _terminate_child(consumer, graceful_signal=signal.SIGTERM)
        escalation_deadline = time.monotonic() + _ESCALATION_TIMEOUT_SECONDS
        while time.monotonic() < escalation_deadline:
            if web.poll() is not None and consumer.poll() is not None:
                break
            time.sleep(0.05)
        _kill_child(web)
        _kill_child(consumer)
    with suppress(subprocess.TimeoutExpired):
        web.wait(timeout=_ESCALATION_TIMEOUT_SECONDS)
    with suppress(subprocess.TimeoutExpired):
        consumer.wait(timeout=_ESCALATION_TIMEOUT_SECONDS)
    store.interrupt_active_attempts()


def run_supervisor(
    config: RelayConfig,
    *,
    open_browser: bool,
    on_ready: Callable[[str], None] | None = None,
) -> None:
    """Run until a signal or child failure, then preserve resumable state."""
    _validate_bind(config.host, config.port)
    try:
        relay_root = discover_relay_root(Path.cwd())
    except RelayError as error:
        raise ConfigError(
            error.message,
            context=error.context,
            next_action=error.next_action,
        ) from None
    repository = relay_root.parent.resolve()
    os.environ["RELAY_PROJECT_ROOT"] = str(repository)
    data_dir(create=True)
    apply_migrations()

    from relay.web.repositories import DjangoExecutionStore, DjangoProjectStore

    register_current_project(DjangoProjectStore(), repository)
    store = DjangoExecutionStore()
    instance_id = store.acquire_instance(os.getpid(), socket.gethostname())
    stop = threading.Event()
    signal_requested = threading.Event()
    unexpected: RelayError | None = None
    web: subprocess.Popen[bytes] | None = None
    consumer: subprocess.Popen[bytes] | None = None
    previous_handlers: dict[
        signal.Signals,
        Callable[[int, FrameType | None], object] | int | None,
    ] = {}

    def request_stop(_signum: int, _frame: FrameType | None) -> None:
        signal_requested.set()
        stop.set()

    try:
        _startup_reconcile(store)
        for candidate in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[candidate] = signal.getsignal(candidate)
            signal.signal(candidate, request_stop)
        web, consumer = _spawn_children(repository, config)
        url = _browser_url(config.host, config.port)
        _wait_until_ready(web, consumer, config.host, config.port, stop)
        if not stop.is_set():
            if on_ready is not None:
                on_ready(url)
            if open_browser and not webbrowser.open(url):
                LOGGER.warning("No browser accepted the Relay URL", extra={"url": url})

        heartbeat_due = time.monotonic() + INSTANCE_HEARTBEAT_INTERVAL_SECONDS
        while not stop.is_set():
            for name, child in (("web", web), ("worker", consumer)):
                status = child.poll()
                if status is not None:
                    unexpected = PersistenceError(
                        f"Relay's {name} child exited unexpectedly with status {status}."
                    )
                    stop.set()
                    break
            now = time.monotonic()
            if now >= heartbeat_due and not stop.is_set():
                if not store.heartbeat_instance(instance_id):
                    unexpected = PersistenceError("Relay lost its supervisor lease.")
                    stop.set()
                    break
                heartbeat_due = now + INSTANCE_HEARTBEAT_INTERVAL_SECONDS
            stop.wait(0.2)
    except KeyboardInterrupt:
        stop.set()
    finally:
        for candidate, handler in previous_handlers.items():
            signal.signal(candidate, handler)
        clean_shutdown = False
        try:
            if web is not None and consumer is not None:
                worker_failed = consumer.poll() is not None and not signal_requested.is_set()
                if worker_failed:
                    _terminate_child(web, graceful_signal=signal.SIGTERM)
                    _force_attempt_processes(store.active_attempt_processes())
                    store.fail_worker_attempts()
                    _kill_child(web)
                    with suppress(subprocess.TimeoutExpired):
                        web.wait(timeout=_ESCALATION_TIMEOUT_SECONDS)
                else:
                    _write_shutdown_marker(instance_id)
                    store.request_orderly_shutdown(instance_id)
                    _shutdown_children(store, web, consumer)
                    clean_shutdown = True
        finally:
            if clean_shutdown:
                with suppress(OSError):
                    shutdown_marker_path().unlink(missing_ok=True)
            store.release_instance(instance_id)
    if unexpected is not None:
        raise unexpected


__all__ = ["run_supervisor"]
