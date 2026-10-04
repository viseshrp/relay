"""Attempt ownership, scratch isolation, and surviving process-tree cleanup."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import uuid

import pytest

from relay.errors import PathSafetyError
from relay.execution.cancellation import release_process_group, spawn_process
from relay.execution.resources import allocate_attempt_resources, cleanup_run_resources
from tests.support import InlineEngine, RelayProject, symlink_or_skip


def test_attempt_resources_preserve_foreign_files_and_live_attempt_allocations() -> None:
    run_id = str(uuid.uuid4())
    finished = allocate_attempt_resources(run_id, "1")
    active = allocate_attempt_resources(run_id, "2")
    foreign = finished.directory.parent / "owner-notes"
    foreign.mkdir()
    (foreign / "note.txt").write_text("Keep me", encoding="utf-8")
    environment = finished.environment()
    assert Path(environment["TMPDIR"]) == finished.directory / "temp"
    assert Path(environment["RELAY_BROWSER_PROFILE_DIR"]).is_dir()
    assert cleanup_run_resources(run_id, eligible_attempts=frozenset({"1"})) == 1
    assert active.directory.is_dir()
    assert (foreign / "note.txt").read_text(encoding="utf-8") == "Keep me"


def test_cleanup_unlinks_an_inner_profile_link_without_touching_its_target(tmp_path: Path) -> None:
    allocation = allocate_attempt_resources(str(uuid.uuid4()), "1")
    profile = tmp_path / "personal-browser"
    profile.mkdir()
    credential = profile / "credentials"
    credential.write_text("Personal data", encoding="utf-8")
    symlink_or_skip(allocation.directory / "browser-profiles" / "personal", profile)
    allocation.cleanup()
    assert credential.read_text(encoding="utf-8") == "Personal data"
    assert not allocation.directory.exists()


def test_cleanup_refuses_a_replaced_run_directory(tmp_path: Path) -> None:
    allocation = allocate_attempt_resources(str(uuid.uuid4()), "1")
    root = allocation.directory.parent
    moved = root.with_name(f"{root.name}-retained")
    root.rename(moved)
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    symlink_or_skip(root, foreign)
    with pytest.raises(PathSafetyError):
        allocation.cleanup()
    assert foreign.is_dir()
    assert (moved / allocation.directory.name).is_dir()


def test_a_changed_ownership_token_prevents_attempt_cleanup() -> None:
    allocation = allocate_attempt_resources(str(uuid.uuid4()), "1")
    marker = allocation.directory / ".relay-resource-owner.json"
    owner = json.loads(marker.read_text(encoding="utf-8"))
    owner["token"] = str(uuid.uuid4())
    marker.write_text(json.dumps(owner), encoding="utf-8")
    allocation.cleanup()
    assert allocation.directory.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows directory junction")
def test_cleanup_refuses_a_windows_junction_to_personal_data(tmp_path: Path) -> None:
    allocation = allocate_attempt_resources(str(uuid.uuid4()), "1")
    root = allocation.directory.parent
    root.rename(root.with_name(f"{root.name}-retained"))
    foreign = tmp_path / "personal-profile"
    foreign.mkdir()
    credential = foreign / "credentials"
    credential.write_text("Keep", encoding="utf-8")
    created = subprocess.run(  # noqa: S603
        [
            str(Path(os.environ["SYSTEMROOT"]) / "System32" / "cmd.exe"),
            "/d",
            "/c",
            "mklink",
            "/J",
            str(root),
            str(foreign),
        ],
        capture_output=True,
        check=True,
    )
    assert created.returncode == 0
    with pytest.raises(PathSafetyError):
        cleanup_run_resources(allocation.run_id)
    assert credential.read_text(encoding="utf-8") == "Keep"


def test_command_temporary_and_profile_storage_disappears_after_execution(
    project: RelayProject, engine: InlineEngine
) -> None:
    program = (
        "import os, pathlib; "
        "p=pathlib.Path(os.environ['RELAY_BROWSER_PROFILE_DIR']); "
        "(p/'session').write_text('scratch'); "
        "print(os.environ['TMPDIR']); print(p)"
    )
    project.write_workflow(
        "scratch",
        "version: 1\nname: Scratch\nnodes:\n"
        f"  work: {{type: command, run: {json.dumps([sys.executable, '-c', program])}}}\n",
    )
    run_id = engine.launch(project, "scratch")
    outcomes = engine.drain(run_id)
    assert all(outcome is not None and outcome.error_code is None for outcome in outcomes), outcomes
    from relay.web.repositories import DjangoReadStore

    events, _cursor = DjangoReadStore().page_events(run_id, since=0, limit=200)
    paths = "".join(
        str(item["payload"].get("chunk", "")) for item in events if item["type"] == "command.stdout"
    ).splitlines()
    assert len(paths) == 2
    assert all(not Path(path).exists() for path in paths)


def test_a_finished_owned_process_releases_descendants_and_keeps_unrelated_processes(
    tmp_path: Path,
) -> None:
    # A socket acknowledgement proves the child is running; EOF or a Windows
    # connection reset proves the owned process was stopped.
    # No sleep or PID-liveness guess is needed on either platform.
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(10)
        child = (
            "import socket, sys; s=socket.create_connection(('127.0.0.1',int(sys.argv[1]))); "
            "s.sendall(b'ready'); s.recv(1); s.recv(1)"
        )
        parent = (
            "import subprocess, sys; "
            "subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]], "
            "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
            "sys.stdin.buffer.read(1)"
        )
        with subprocess.Popen(
            [sys.executable, "-c", "import sys; sys.stdin.buffer.read()"],
            stdin=subprocess.PIPE,
            start_new_session=os.name != "nt",
        ) as unrelated:

            async def scenario() -> None:
                process = await spawn_process(
                    [sys.executable, "-c", parent, child, str(listener.getsockname()[1])],
                    tmp_path,
                )
                connection, _address = await asyncio.to_thread(listener.accept)
                with connection:
                    connection.settimeout(10)
                    assert await asyncio.to_thread(connection.recv, 5) == b"ready"
                    assert process.stdin is not None
                    process.stdin.write(b"x")
                    await process.stdin.drain()
                    await asyncio.wait_for(process.wait(), timeout=10)
                    release_process_group(process.pid)
                    try:
                        closed = await asyncio.to_thread(connection.recv, 1)
                    except ConnectionResetError:
                        if os.name != "nt":
                            raise
                    else:
                        assert closed == b""
                    assert unrelated.poll() is None

            try:
                asyncio.run(scenario())
            finally:
                assert unrelated.stdin is not None
                unrelated.stdin.close()
                unrelated.wait(timeout=10)
