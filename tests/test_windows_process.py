"""Windows job ownership at the native API and subprocess boundaries."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import shutil
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from relay.constants import EXIT_RELAY_ERROR
from relay.execution import windows_process

# Win32 JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE and JobObjectExtendedLimitInformation.
KILL_ON_JOB_CLOSE = 0x2000
EXTENDED_LIMIT_INFORMATION = 9


@pytest.fixture
def native_job(monkeypatch: pytest.MonkeyPatch) -> tuple[Mock, Mock, Mock]:
    kernel = Mock(
        spec=[
            "CreateJobObjectW",
            "SetInformationJobObject",
            "GetCurrentProcess",
            "AssignProcessToJobObject",
            "CloseHandle",
        ]
    )
    kernel.CreateJobObjectW.return_value = 17
    kernel.SetInformationJobObject.return_value = 1
    kernel.GetCurrentProcess.return_value = -1
    kernel.AssignProcessToJobObject.return_value = 1
    kernel.CloseHandle.return_value = 1
    load = Mock(return_value=kernel)
    target = Mock(return_value=7)
    # Replace only the launcher's platform view, leaving pathlib and pytest on
    # the host OS. Replace the DLL, executable lookup, and target boundaries.
    monkeypatch.setattr(windows_process, "os", SimpleNamespace(name="nt", path=os.path))
    lookup = Mock(side_effect=lambda name: os.path.abspath(f"resolved-{name}"))
    monkeypatch.setattr(windows_process, "shutil", SimpleNamespace(which=lookup))
    monkeypatch.setattr(ctypes, "WinDLL", load, raising=False)
    monkeypatch.setattr(windows_process, "subprocess", SimpleNamespace(call=target))
    return kernel, load, target


def test_target_joins_an_unnamed_kill_on_close_job_before_it_starts(
    native_job: tuple[Mock, Mock, Mock],
) -> None:
    kernel, load, target = native_job
    arguments = ["git", "-C", "/repository with spaces", "status"]

    def start(arguments: list[str], *, shell: bool) -> int:
        assert arguments == [
            os.path.abspath("resolved-git"),
            "-C",
            "/repository with spaces",
            "status",
        ]
        assert shell is False
        kernel.AssignProcessToJobObject.assert_called_once_with(17, -1)
        return 7

    target.side_effect = start
    assert windows_process.run_owned_command(arguments) == 7
    assert arguments == ["git", "-C", "/repository with spaces", "status"]
    load.assert_called_once_with("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.assert_called_once_with(None, None)
    job, information, pointer, size = kernel.SetInformationJobObject.call_args.args
    limits = windows_process.ExtendedLimits.from_buffer_copy(ctypes.string_at(pointer, size))
    assert job == 17
    assert information == EXTENDED_LIMIT_INFORMATION
    assert size == ctypes.sizeof(windows_process.ExtendedLimits)
    assert limits.basic.flags == KILL_ON_JOB_CLOSE
    # ExitProcess owns the successful handle lifetime; an early close would
    # stop this launcher before its target's result reaches the caller.
    kernel.CloseHandle.assert_not_called()


def test_the_target_uses_the_attempt_path_instead_of_the_launcher_directory(
    native_job: tuple[Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _kernel, _load, target = native_job
    selected = tmp_path / "workflow tools" / "python.exe"
    selected.parent.mkdir()
    selected.write_bytes(b"Selected executable")
    selected.chmod(0o755)
    monkeypatch.setenv("PATH", str(selected.parent))
    monkeypatch.setenv("PATHEXT", ".EXE")
    monkeypatch.setattr(windows_process, "shutil", shutil)
    arguments = ["python.exe", "-m", "pytest", "a file with spaces.py", "literal&argument"]

    assert windows_process.run_owned_command(arguments) == 7
    target.assert_called_once_with([str(selected), *arguments[1:]], shell=False)
    assert arguments[0] == "python.exe"


def test_a_missing_path_executable_never_starts_a_fallback_target(
    native_job: tuple[Mock, Mock, Mock], monkeypatch: pytest.MonkeyPatch
) -> None:
    _kernel, _load, target = native_job
    lookup = Mock(return_value=None)
    monkeypatch.setattr(windows_process, "shutil", SimpleNamespace(which=lookup))

    assert windows_process.run_owned_command(["missing", "argument"]) == EXIT_RELAY_ERROR
    lookup.assert_called_once_with("missing")
    target.assert_not_called()


def test_a_relative_path_result_is_qualified_before_native_launch(
    native_job: tuple[Mock, Mock, Mock], monkeypatch: pytest.MonkeyPatch
) -> None:
    _kernel, _load, target = native_job
    selected = os.path.join("relative tools", "target.exe")
    lookup = Mock(return_value=selected)
    monkeypatch.setattr(windows_process, "shutil", SimpleNamespace(which=lookup))

    assert windows_process.run_owned_command(["target.exe", "argument"]) == 7
    target.assert_called_once_with([os.path.abspath(selected), "argument"], shell=False)


@pytest.mark.parametrize("failure", ["create", "configure", "assign"])
def test_a_job_ownership_failure_never_starts_the_target(
    native_job: tuple[Mock, Mock, Mock], failure: str
) -> None:
    kernel, _load, target = native_job
    operation = {
        "create": kernel.CreateJobObjectW,
        "configure": kernel.SetInformationJobObject,
        "assign": kernel.AssignProcessToJobObject,
    }[failure]
    operation.return_value = 0

    assert windows_process.run_owned_command(["target"]) == EXIT_RELAY_ERROR
    target.assert_not_called()
    if failure == "create":
        kernel.SetInformationJobObject.assert_not_called()
        kernel.CloseHandle.assert_not_called()
    else:
        kernel.CloseHandle.assert_called_once_with(17)
    if failure != "assign":
        kernel.AssignProcessToJobObject.assert_not_called()


@pytest.mark.parametrize("error", [OSError, KeyboardInterrupt])
def test_target_spawn_failure_returns_the_relay_exit_code(
    native_job: tuple[Mock, Mock, Mock], error: type[OSError] | type[KeyboardInterrupt]
) -> None:
    _kernel, _load, target = native_job
    target.side_effect = error
    assert windows_process.run_owned_command(["target"]) == EXIT_RELAY_ERROR


def test_an_empty_command_does_not_load_a_job(native_job: tuple[Mock, Mock, Mock]) -> None:
    _kernel, load, target = native_job
    assert windows_process.run_owned_command([]) == EXIT_RELAY_ERROR
    load.assert_not_called()
    target.assert_not_called()


def test_the_windows_launcher_refuses_other_platforms(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(windows_process, "os", SimpleNamespace(name="posix"))
    load = Mock()
    monkeypatch.setattr(ctypes, "WinDLL", load, raising=False)
    assert windows_process.run_owned_command(["target"]) == EXIT_RELAY_ERROR
    load.assert_not_called()
