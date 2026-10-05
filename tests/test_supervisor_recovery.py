"""Orphan recovery stops only children with durable, matching OS creation identities."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from queue import Queue
import signal
import socket
import subprocess
import sys
import threading
from types import SimpleNamespace
import uuid

from django.conf import settings
import pytest

from relay.config import RelayConfig
from relay.errors import ConfigError, PersistenceError
from relay.execution.cancellation import signal_process_tree
from relay.execution.process_identity import ProcessIdentity, process_identity
from relay.manage import MigrationLock
from relay.paths import data_dir
from relay.web import process_ownership, supervisor
from relay.web.models import Instance, Run, RunSnapshot
from relay.web.process_ownership import (
    ChildOwnership,
    SupervisorOwnership,
    abandoned_ownership,
    ownership_path,
    read_ownership,
    stop_owned_children,
)
from tests.support import Clock, InlineEngine, RelayProject, symlink_or_skip


@dataclass
class ProcessBoundary:
    identities: dict[int, ProcessIdentity] = field(default_factory=dict)
    signals: list[tuple[int, bool]] = field(default_factory=list)
    refuse_grace: bool = False
    replace_on_grace: bool = False

    def identity(self, pid: int) -> ProcessIdentity | None:
        return self.identities.get(pid)

    def stop(
        self, pid: int, *, force: bool = False, graceful_signal: signal.Signals = signal.SIGTERM
    ) -> None:
        del graceful_signal
        self.signals.append((pid, force))
        if not force and self.refuse_grace:
            message = "Detached child has no console"
            raise OSError(message)
        if self.replace_on_grace:
            self.identities[pid] = ProcessIdentity(pid, "replacement-birth")
        else:
            self.identities.pop(pid, None)


@pytest.fixture
def process_boundary(monkeypatch: pytest.MonkeyPatch) -> ProcessBoundary:
    boundary = ProcessBoundary()
    data_dir(create=True)
    monkeypatch.setattr(process_ownership, "process_identity", boundary.identity)
    monkeypatch.setattr(process_ownership, "signal_process_tree", boundary.stop)
    return boundary


def recorded_children(boundary: ProcessBoundary) -> SupervisorOwnership:
    record = SupervisorOwnership(
        str(uuid.uuid4()),
        ProcessIdentity(100, "previous-supervisor"),
        [
            ChildOwnership("web", ProcessIdentity(101, "original-web")),
            ChildOwnership("worker", ProcessIdentity(102, "original-worker")),
        ],
    )
    for child in record.children:
        boundary.identities[child.identity.pid] = child.identity
    record.save()
    return record


def test_a_live_recorded_owner_prevents_takeover_despite_a_stale_heartbeat(
    process_boundary: ProcessBoundary,
) -> None:
    record = recorded_children(process_boundary)
    process_boundary.identities[record.owner.pid] = record.owner
    with pytest.raises(ConfigError):
        abandoned_ownership()
    assert process_boundary.signals == []
    assert read_ownership() == record


def test_reused_child_pids_are_left_alone_during_orphan_recovery(
    process_boundary: ProcessBoundary,
) -> None:
    record = recorded_children(process_boundary)
    replacement = ProcessIdentity(101, "another-process")
    process_boundary.identities[101] = replacement
    stop_owned_children(record)
    assert process_boundary.signals == [(102, False)]
    assert process_boundary.identities[101] == replacement
    record.clear()
    assert not ownership_path().exists()


def test_pid_reuse_after_a_graceful_signal_never_authorizes_escalation(
    process_boundary: ProcessBoundary,
) -> None:
    record = recorded_children(process_boundary)
    process_boundary.replace_on_grace = True
    stop_owned_children(record)
    assert process_boundary.signals == [(101, False), (102, False)]
    assert set(process_boundary.identities) == {101, 102}


def test_unavailable_console_escalates_only_after_rechecking_birth(
    process_boundary: ProcessBoundary, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = recorded_children(process_boundary)
    process_boundary.refuse_grace = True
    monkeypatch.setattr(
        process_ownership,
        "threading",
        SimpleNamespace(Event=lambda: SimpleNamespace(wait=clock.advance)),
    )
    stop_owned_children(record)
    assert process_boundary.signals == [(101, False), (102, False), (101, True), (102, True)]
    assert not process_boundary.identities


def test_ownership_is_retained_until_matching_children_exit(
    process_boundary: ProcessBoundary,
) -> None:
    record = recorded_children(process_boundary)
    record.clear()
    assert read_ownership() == record
    process_boundary.identities.clear()
    record.clear()
    assert not ownership_path().exists()


def test_clearing_old_ownership_preserves_a_replacement_supervisor_record(
    process_boundary: ProcessBoundary,
) -> None:
    old = recorded_children(process_boundary)
    replacement = SupervisorOwnership(str(uuid.uuid4()), ProcessIdentity(200, "new-supervisor"))
    replacement.save()
    process_boundary.identities.clear()
    old.clear()
    assert read_ownership() == replacement


@pytest.mark.parametrize("fault", ["bad-json", "other-host", "repeated-pid", "unsafe-pid"])
def test_invalid_ownership_never_authorizes_a_signal(
    process_boundary: ProcessBoundary, fault: str
) -> None:
    recorded_children(process_boundary)
    path = ownership_path()
    raw = json.loads(path.read_text(encoding="utf-8"))
    if fault == "bad-json":
        path.write_text("{", encoding="utf-8")
    else:
        if fault == "other-host":
            raw["host"] = "another-host"
        elif fault == "repeated-pid":
            raw["children"][1]["identity"]["pid"] = 101
        else:
            raw["owner"]["pid"] = 1
        path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(PersistenceError):
        abandoned_ownership()
    assert process_boundary.signals == []


def test_linked_ownership_is_rejected_without_modifying_its_target(
    tmp_path: Path, process_boundary: ProcessBoundary
) -> None:
    del process_boundary
    target = tmp_path / "unrelated.json"
    target.write_text("unrelated", encoding="utf-8")
    symlink_or_skip(ownership_path(), target)
    with pytest.raises(PersistenceError):
        abandoned_ownership()
    assert target.read_text(encoding="utf-8") == "unrelated"


def test_a_held_supervisor_kernel_lock_prevents_another_launch() -> None:
    with (
        MigrationLock(data_dir(create=True) / "supervisor.lock", timeout=0),
        pytest.raises(PersistenceError),
    ):
        supervisor.run_supervisor(RelayConfig(), open_browser=False)
    assert not ownership_path().exists()
    assert not Instance.objects.exists()


def test_os_identity_is_stable_for_a_live_process() -> None:
    identity = process_identity(os.getpid())
    assert identity is not None
    assert identity.pid == os.getpid()
    assert process_identity(os.getpid()) == identity


@pytest.mark.parametrize("pid", [0, 1, -1, True, 1 << 32])
def test_unsafe_process_identifiers_fail_closed(pid: int) -> None:
    with pytest.raises(PersistenceError):
        process_identity(pid)


def stdout_line(process: subprocess.Popen[str], timeout: float) -> str:
    """Wait for actual process output, bounded even when startup crashes or hangs."""
    result = Queue()

    def read() -> None:
        if process.stdout is not None:
            result.put(process.stdout.readline())

    threading.Thread(target=read, daemon=True).start()
    return result.get(timeout=timeout)


def test_a_reaped_child_no_longer_has_an_os_creation_identity() -> None:
    with subprocess.Popen(
        [sys.executable, "-u", "-c", "import sys; print('ready'); sys.stdin.buffer.read()"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    ) as child:
        try:
            assert stdout_line(child, 10) == "ready\n"
            identity = process_identity(child.pid)
            assert identity is not None
            assert identity != process_identity(os.getpid())
        finally:
            child.communicate(timeout=10)
        assert process_identity(child.pid) is None


def test_restart_recovers_real_orphan_children_and_preserves_completed_runs(
    project: RelayProject, engine: InlineEngine, tmp_path: Path
) -> None:
    project.write_workflow(
        "complete",
        "version: 1\nname: Complete\nnodes:\n  work: {type: command, run: [git, status]}\n",
    )
    run_id = engine.launch(project, "complete")
    engine.drain(run_id)
    before = Run.objects.values("status", "recorded_head").get(pk=run_id)
    assert before["status"] == "succeeded"
    snapshot = RunSnapshot.objects.values().get(run_id=run_id)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    environment = {
        **os.environ,
        "RELAY_DATABASE_PATH": str(settings.DATABASES["default"]["NAME"]),
        "RELAY_HUEY_DATABASE_PATH": str(tmp_path / "orphan-huey.db"),
        "RELAY_MIGRATION_LOCK_PATH": str(tmp_path / "orphan-migrate.lock"),
    }
    arguments = [
        sys.executable,
        "-u",
        "-c",
        "from relay.config import RelayConfig; "
        "from relay.web.supervisor import run_supervisor; "
        f"run_supervisor(RelayConfig(port={port}), open_browser=False, "
        "on_ready=lambda url: print(url, flush=True))",
    ]
    children = []
    supervisors = []
    with (tmp_path / "orphan-runtime.log").open("w", encoding="utf-8") as diagnostics:

        def start() -> subprocess.Popen[str]:
            process = subprocess.Popen(  # noqa: S603
                arguments,
                cwd=project.repository,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=diagnostics,
                text=True,
                **(
                    {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
                    if os.name == "nt"
                    else {"start_new_session": True}
                ),
            )
            supervisors.append(process)
            assert stdout_line(process, 30) == f"http://127.0.0.1:{port}/\n", diagnostics.name
            record = read_ownership()
            assert record is not None
            children.extend(child.identity for child in record.children)
            return process

        try:
            first = start()
            old = read_ownership()
            assert old is not None
            first.kill()
            first.wait(timeout=10)
            assert all(
                process_identity(child.identity.pid) == child.identity for child in old.children
            )
            second = start()
            current = read_ownership()
            assert current is not None
            assert current.owner.pid == second.pid
            assert current.instance_id != old.instance_id
            assert not any(
                process_identity(child.identity.pid) == child.identity for child in old.children
            )
            assert str(Instance.objects.get().pk) == current.instance_id
            assert Run.objects.values("status", "recorded_head").get(pk=run_id) == before
            assert RunSnapshot.objects.values().get(run_id=run_id) == snapshot
            signal_process_tree(second.pid, graceful_signal=signal.SIGINT)
            assert second.wait(timeout=30) == 0
            assert not ownership_path().exists()
            assert not Instance.objects.exists()
        finally:
            for process in reversed(supervisors):
                if process.poll() is None:
                    signal_process_tree(process.pid, force=True)
                process.wait(timeout=10)
                if process.stdout is not None:
                    process.stdout.close()
            for identity in children:
                if process_identity(identity.pid) == identity:
                    signal_process_tree(identity.pid, force=True)
