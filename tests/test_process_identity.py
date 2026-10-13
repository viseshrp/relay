"""Uncertain process observation must never authorize workspace recovery."""

from __future__ import annotations

import ctypes
import importlib
import subprocess
from unittest.mock import Mock

import pytest

from relay.errors import PersistenceError
from relay.execution.process_identity import ProcessIdentity

processes = importlib.import_module("relay.execution.process_identity")


def test_windows_descendants_exclude_exited_and_older_reused_processes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = ProcessIdentity(101, "windows:1000")
    child = ProcessIdentity(102, "windows:2000")
    grandchild = ProcessIdentity(103, "windows:3000")
    older = ProcessIdentity(104, "windows:500")
    unrelated = ProcessIdentity(106, "windows:4000")
    identities = {
        identity.pid: identity for identity in (root, child, grandchild, older, unrelated)
    }
    rows = iter([(101, 99), (102, 101), (103, 102), (104, 101), (105, 101), (106, 99)])

    def next_entry(handle: int, pointer: object) -> bool:
        assert handle == 17
        try:
            pid, parent = next(rows)
        except StopIteration:
            return False
        entry = pointer._obj
        assert entry.size == ctypes.sizeof(processes.WindowsProcessEntry)
        entry.pid, entry.parent_pid = pid, parent
        return True

    kernel = Mock()
    kernel.CreateToolhelp32Snapshot.return_value = 17
    kernel.Process32FirstW.side_effect = next_entry
    kernel.Process32NextW.side_effect = next_entry
    monkeypatch.setattr(ctypes, "WinDLL", lambda *_args, **_kwargs: kernel, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 18, raising=False)
    monkeypatch.setattr(processes, "process_identity", identities.get)
    assert set(processes._windows_descendants(root)) == {root, child, grandchild}
    kernel.CloseHandle.assert_called_once_with(17)


def test_failed_windows_tree_snapshot_never_returns_an_empty_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kernel = Mock()
    kernel.CreateToolhelp32Snapshot.return_value = ctypes.c_void_p(-1).value
    monkeypatch.setattr(ctypes, "WinDLL", lambda *_args, **_kwargs: kernel, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 5, raising=False)
    with pytest.raises(PersistenceError, match="enumerate"):
        processes._windows_descendants(ProcessIdentity(101, "windows:1000"))
    kernel.Process32FirstW.assert_not_called()
    kernel.CloseHandle.assert_not_called()


@pytest.mark.skipif(processes.os.name == "nt", reason="POSIX process-group observation")
def test_group_observation_rechecks_creation_after_the_process_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = ProcessIdentity(102, "verified-birth")
    execute = Mock(
        return_value=subprocess.CompletedProcess(
            ["ps"], 0, stdout="1 101\n101 101\n102 101\n103 999\n"
        )
    )
    monkeypatch.setattr(processes.subprocess, "run", execute)
    monkeypatch.setattr(processes, "process_identity", {102: child}.get)
    assert processes.process_group_members(101) == (child,)
    assert execute.call_args.kwargs["timeout"] == 5


@pytest.mark.skipif(processes.os.name == "nt", reason="POSIX process-group observation")
@pytest.mark.parametrize("fault", ["malformed", "unavailable", "timeout"])
def test_failed_group_observation_never_proves_exit(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    execute = Mock(return_value=subprocess.CompletedProcess(["ps"], 0, stdout="invalid\n"))
    if fault == "unavailable":
        execute.side_effect = OSError("ps unavailable")
    elif fault == "timeout":
        execute.side_effect = subprocess.TimeoutExpired(["ps"], 5)
    monkeypatch.setattr(processes.subprocess, "run", execute)
    with pytest.raises(PersistenceError, match="owned process group"):
        processes.process_group_members(101)
