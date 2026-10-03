"""Storage, log ownership, migration locks, and process cleanup boundaries."""

from __future__ import annotations

import asyncio
from contextlib import ExitStack
import json
import logging
import os
from pathlib import Path
import subprocess
import sys

import pytest

from relay import manage, paths
from relay.constants import APPLICATION_LOG_OWNERSHIP_LINE, APPLICATION_LOG_RETAINED_PROCESSES
from relay.errors import PathSafetyError, PersistenceError
from relay.execution.cancellation import (
    ProcessCancellation,
    discard_process_stream,
    signal_process_tree,
    spawn_process,
    terminate_async_process_tree,
    terminate_process_tree,
)
from relay.media import media_type_for
from relay.web.logging import ContextFormatter, OwnedRotatingFileHandler

OWNED = f"{APPLICATION_LOG_OWNERSHIP_LINE}\n".encode()


@pytest.mark.parametrize(
    "directory",
    ["global_prompts_dir", "registry_cache_dir", "artifacts_dir", "worktrees_dir"],
)
def test_storage_directories_are_created_private_on_demand(directory: str) -> None:
    created = getattr(paths, directory)(create=True)
    assert created.is_dir()
    if os.name != "nt":
        assert created.stat().st_mode & 0o777 == 0o700


def test_private_directory_creation_includes_missing_parents(tmp_path: Path) -> None:
    created = paths.ensure_private_dir(tmp_path / "private/nested")
    assert created.is_dir()


def test_safe_resolve_keeps_contained_paths(tmp_path: Path) -> None:
    assert paths.safe_resolve(tmp_path, "a/b.md") == (tmp_path / "a/b.md").resolve()


def test_safe_resolve_rejects_an_escape(tmp_path: Path) -> None:
    with pytest.raises(PathSafetyError):
        paths.safe_resolve(tmp_path / "root", "../outside.md")


@pytest.fixture
def log_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    base = tmp_path / "logs/app.log"
    base.parent.mkdir()
    monkeypatch.setenv("RELAY_LOG_PATH", str(base))
    return base


def test_each_process_gets_its_own_log_name(log_base: Path) -> None:
    assert paths.application_log_path() == log_base.with_name(f"app-{os.getpid()}.log")


def test_log_selection_requires_both_a_process_name_and_the_ownership_line(log_base: Path) -> None:
    contents = {
        "app-41.log": OWNED + b"record\n",
        "app-41.log.1": OWNED + b"older\n",
        "app-42.log": f"{APPLICATION_LOG_OWNERSHIP_LINE}\r\nrecord\r\n".encode(),
        "app-20261002.log": b"another tool\n",
        "app-notes.log": OWNED,
        "app.log": OWNED,
    }
    for name, body in contents.items():
        (log_base.parent / name).write_bytes(body)
    (log_base.parent / "app-43.log").mkdir()

    owned = sorted(path.name for path in paths.application_log_files())

    assert owned == ["app-41.log", "app-41.log.1", "app-42.log"]


def test_clearing_preserves_ownership_and_other_tools_files(log_base: Path) -> None:
    folder = log_base.parent
    (folder / "app-41.log").write_bytes(OWNED + b"record\n")
    windows_line = f"{APPLICATION_LOG_OWNERSHIP_LINE}\r\n".encode()
    (folder / "app-42.log").write_bytes(windows_line + b"record\r\n")
    (folder / "app-20261002.log").write_bytes(b"another tool\n")

    cleared = paths.clear_application_logs()

    assert cleared == 2
    assert (folder / "app-41.log").read_bytes() == OWNED
    assert (folder / "app-42.log").read_bytes() == windows_line
    assert (folder / "app-20261002.log").read_bytes() == b"another tool\n"


def test_clearing_logs_preserves_a_live_append_handle(log_base: Path) -> None:
    path = paths.application_log_path()
    handler = OwnedRotatingFileHandler(str(path), delay=True)
    try:
        handler.emit(logging.LogRecord("relay.test", logging.WARNING, "", 0, "before", (), None))

        assert paths.clear_application_logs() == 1

        handler.emit(logging.LogRecord("relay.test", logging.WARNING, "", 0, "after", (), None))
        assert path.read_text(encoding="utf-8").splitlines() == [
            APPLICATION_LOG_OWNERSHIP_LINE,
            "after",
        ]
    finally:
        handler.close()


def test_a_missing_log_directory_has_no_relay_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RELAY_LOG_PATH", str(tmp_path / "absent/relay.log"))
    assert paths.application_log_files() == ()
    assert paths.clear_application_logs() == 0


def finished_pid() -> int:
    """Use an observed, reaped process instead of guessing whether a PID is live."""
    process = subprocess.run(
        [sys.executable, "-c", "import os; print(os.getpid())"],
        capture_output=True,
        text=True,
        check=True,
    )
    return int(process.stdout)


def owned_log(folder: Path, pid: int, body: bytes, modified: int) -> Path:
    path = folder / f"app-{pid}.log"
    path.write_bytes(OWNED + body)
    os.utime(path, (modified, modified))
    return path


def test_pruning_caps_stopped_logs_and_preserves_live_and_foreign_files(log_base: Path) -> None:
    folder = log_base.parent
    stopped = [
        owned_log(folder, finished_pid(), b"record\n", index + 10)
        for index in range(APPLICATION_LOG_RETAINED_PROCESSES + 1)
    ]
    emptied = owned_log(folder, finished_pid(), b"", 100)
    live = owned_log(folder, os.getpid(), b"live\n", 1)
    foreign = folder / "app-20261002.log"
    foreign.write_bytes(b"another tool\n")

    paths.prune_application_logs()

    assert set(folder.iterdir()) == {*stopped[1:], live, foreign}
    assert not emptied.exists()
    assert foreign.read_bytes() == b"another tool\n"


def test_locked_logs_do_not_block_pruning(log_base: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stale = owned_log(log_base.parent, finished_pid(), b"", 1)

    def locked(self: Path, missing_ok: bool = False) -> None:
        del self, missing_ok
        message = "in use"
        raise PermissionError(message)

    with monkeypatch.context() as filesystem:
        filesystem.setattr(Path, "unlink", locked)
        paths.prune_application_logs()

    assert stale.exists()


def test_empty_commands_do_not_create_log_files(tmp_path: Path) -> None:
    handler = OwnedRotatingFileHandler(str(tmp_path / "relay.log"), delay=True)
    handler.close()
    assert not (tmp_path / "relay.log").exists()


def test_every_log_rotation_keeps_the_ownership_line(tmp_path: Path) -> None:
    handler = OwnedRotatingFileHandler(str(tmp_path / "relay.log"), maxBytes=200, backupCount=2)
    try:
        for _ in range(12):
            handler.emit(
                logging.LogRecord("relay.test", logging.WARNING, "", 0, "x" * 40, (), None)
            )
    finally:
        handler.close()

    files = sorted(tmp_path.glob("relay.log*"))
    assert [file.name for file in files] == ["relay.log", "relay.log.1", "relay.log.2"]
    assert all(file.read_bytes().splitlines()[0] == OWNED.rstrip(b"\n") for file in files)


def test_structured_log_context_cannot_inject_line_breaks() -> None:
    record = logging.makeLogRecord({"msg": "discovery", "path": "repo\r\nforged\x1b"})
    rendered = ContextFormatter("%(message)s").format(record)
    assert "\r" not in rendered and "\n" not in rendered and "\x1b" not in rendered
    assert json.loads(rendered.split(" context=", 1)[1])["path"] == "repo\r\nforged\x1b"


@pytest.mark.parametrize(
    ("name", "expected"),
    [("notes.txt", "text/plain"), ("data.unknownext", "application/octet-stream")],
)
def test_artifact_media_types_use_the_file_suffix(tmp_path: Path, name: str, expected: str) -> None:
    assert media_type_for(tmp_path / name) == expected


def test_an_occupied_migration_lock_fails_without_waiting(tmp_path: Path) -> None:
    lock_path = tmp_path / "locks/migrate.lock"
    with (
        manage.MigrationLock(lock_path),
        pytest.raises(PersistenceError),
        manage.MigrationLock(lock_path, timeout=0),
    ):
        pass


def test_releasing_a_migration_lock_allows_the_next_owner(tmp_path: Path) -> None:
    lock_path = tmp_path / "locks/migrate.lock"
    with manage.MigrationLock(lock_path):
        pass
    with manage.MigrationLock(lock_path, timeout=0):
        pass


def test_migration_failures_are_logged_with_a_trace_and_wrapped(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from django.core import management

    def broken(*args: object, **kwargs: object) -> None:
        del args, kwargs
        message = "migration exploded"
        raise RuntimeError(message)

    # django.setup() replaces root handlers; keep pytest's capture on this logger.
    manage.LOGGER.addHandler(caplog.handler)
    monkeypatch.setattr(management, "call_command", broken)
    try:
        with pytest.raises(PersistenceError) as caught:
            manage.apply_migrations()
    finally:
        manage.LOGGER.removeHandler(caplog.handler)

    assert caught.value.error_code == "persistence_error"
    assert any(record.name == "relay.manage" and record.exc_info for record in caplog.records)
    handlers = [
        handler
        for handler in logging.getLogger().handlers
        if isinstance(handler, logging.FileHandler)
    ]
    assert any(
        "RuntimeError" in Path(handler.baseFilename).read_text(encoding="utf-8")
        for handler in handlers
    )


def test_the_management_entrypoint_runs_django_checks(capsys: pytest.CaptureFixture[str]) -> None:
    assert manage.main(["relay-manage", "check"]) is None
    assert capsys.readouterr().out


def settings_process() -> subprocess.CompletedProcess[str]:
    """Import public settings in a new process with this test's isolated environment."""
    return subprocess.run(
        [sys.executable, "-c", "from relay.web.settings import SECRET_KEY; print(SECRET_KEY)"],
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_installation_secret_key_is_published_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RELAY_DJANGO_SECRET_KEY")

    first = settings_process()
    second = settings_process()

    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout
    assert (paths.data_dir() / "django-secret-key").read_text(
        encoding="utf-8"
    ).strip() == first.stdout.strip()
    assert not list(paths.data_dir().glob(".django-secret-*"))


def test_concurrent_startups_share_one_complete_installation_secret_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RELAY_DJANGO_SECRET_KEY")
    source = (
        "import secrets, sys\n"
        "def generated_key(size: int) -> str:\n"
        "    print('ready', flush=True)\n"
        "    sys.stdin.readline()\n"
        "    return sys.argv[1] * size\n"
        "secrets.token_urlsafe = generated_key\n"
        "from relay.web.settings import SECRET_KEY\n"
        "print(SECRET_KEY, flush=True)\n"
    )
    with ExitStack() as processes:
        children = [
            processes.enter_context(
                subprocess.Popen(  # noqa: S603
                    [sys.executable, "-c", source, marker],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            )
            for marker in ("a", "b", "c", "d")
        ]
        # Every child reaches key generation before any can publish its candidate.
        for child in children:
            assert child.stdout is not None
            assert child.stdout.readline() == "ready\n"
        for child in children:
            assert child.stdin is not None
            child.stdin.write("publish\n")
            child.stdin.flush()
        results = [child.communicate(timeout=10) for child in children]
        assert [child.returncode for child in children] == [0, 0, 0, 0]

    keys = {stdout.strip() for stdout, _stderr in results}
    assert len(keys) == 1
    assert (paths.data_dir() / "django-secret-key").read_text(encoding="utf-8").strip() in keys
    assert not list(paths.data_dir().glob(".django-secret-*"))


def test_a_truncated_installation_key_prevents_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RELAY_DJANGO_SECRET_KEY")
    (paths.data_dir(create=True) / "django-secret-key").write_text("short", encoding="utf-8")

    result = settings_process()

    assert result.returncode != 0
    assert "PersistenceError" in result.stderr


WAIT_ON_INPUT = (
    "import signal, sys\n"
    "for name in ('SIGTERM', 'SIGBREAK'):\n"
    "    if hasattr(signal, name):\n"
    "        signal.signal(getattr(signal, name), signal.SIG_IGN)\n"
    "print('ready', flush=True)\n"
    "sys.stdin.buffer.read()\n"
)


def test_a_finished_process_needs_no_signals() -> None:
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    assert terminate_process_tree(process) == ProcessCancellation(True, False, process.returncode)


def test_an_uncooperative_process_is_force_stopped_without_a_real_grace_wait() -> None:
    with subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", WAIT_ON_INPUT],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        start_new_session=os.name != "nt",
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    ) as process:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == b"ready"
        stopped = terminate_process_tree(process, grace_seconds=0)
        assert stopped.forced and stopped.exited


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group signaling")
def test_signaling_a_reaped_process_group_is_harmless() -> None:
    with subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True) as process:
        process.wait()
        signal_process_tree(process.pid)
        signal_process_tree(process.pid, force=True)


def test_async_spawn_drains_output_larger_than_a_pipe_buffer(tmp_path: Path) -> None:
    async def scenario() -> int | None:
        process = await spawn_process(
            [sys.executable, "-c", "print('x' * 1000000)"], tmp_path, input_pipe=False
        )
        await discard_process_stream(process.stdout)
        await discard_process_stream(process.stderr)
        await process.wait()
        await terminate_async_process_tree(process)
        return process.returncode

    assert asyncio.run(scenario()) == 0


def test_async_spawn_with_input_ends_on_eof(tmp_path: Path) -> None:
    async def scenario() -> bytes:
        process = await spawn_process(
            [sys.executable, "-c", "import sys; print(sys.stdin.read())"], tmp_path
        )
        assert process.stdin is not None
        process.stdin.write(b"hello")
        await process.stdin.drain()
        process.stdin.close()
        assert process.stdout is not None
        body = await process.stdout.read()
        await process.wait()
        return body

    assert asyncio.run(scenario()).rstrip() == b"hello"
