"""Private state and command-file contracts reject unsafe or malformed bytes."""

import json
from pathlib import Path
import sys

import pytest

from relay.errors import NodeExecutionError, PathSafetyError
from relay.execution import action_files
from tests.support import symlink_or_skip


@pytest.mark.parametrize(
    "raw,reason", [(b"invalid", "unreadable"), (b"\xff", "unreadable"), (b"[]", "invalid")]
)
def test_unreadable_private_state_is_rejected(tmp_path: Path, raw: bytes, reason: str) -> None:
    path = tmp_path / "state"
    path.write_bytes(raw)
    with pytest.raises(NodeExecutionError, match=reason):
        action_files.read_state(path)


def test_private_state_atomic_publication_preserves_old_bytes_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "state"
    action_files.atomic_state(path, {"value": "old"})

    def fail(*args: object) -> None:
        message = "Disposable publication failure"
        raise OSError(message)

    monkeypatch.setattr(action_files.os, "replace", fail)
    with pytest.raises(OSError, match="publication failure"):
        action_files.atomic_state(path, {"value": "new"})
    assert json.loads(path.read_text("utf-8")) == {"value": "old"}
    assert list(tmp_path.glob(".job-state-*")) == []


def test_linked_and_oversized_private_state_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "link"
    symlink_or_skip(link, target)
    with pytest.raises(PathSafetyError):
        action_files.read_state(link)
    with pytest.raises(PathSafetyError):
        action_files.atomic_state(link, {})
    with target.open("wb") as stream:
        stream.truncate(60 * action_files.MAX_FILE + 1)
    with pytest.raises(PathSafetyError, match="oversized"):
        action_files.read_state(target)


@pytest.mark.parametrize(
    "raw,reason", [(b"\xff", "UTF-8"), (b"key=\0", "NUL"), (b"oversized", "limit")]
)
def test_command_file_encoding_nul_and_size_limits(tmp_path: Path, raw: bytes, reason: str) -> None:
    path = tmp_path / "output"
    path.write_bytes(raw)
    with pytest.raises(NodeExecutionError, match=reason):
        action_files.file_text(path, limit=8)
    path.unlink()
    with pytest.raises(PathSafetyError, match="removed"):
        action_files.file_text(path)


def test_command_file_utf8_bom_and_empty_lines(tmp_path: Path) -> None:
    path = tmp_path / "output"
    path.write_bytes(b"\xef\xbb\xbf\nvalue=ready\n\n")
    assert action_files.key_values(action_files.file_text(path)) == {"value": "ready"}
    with pytest.raises(NodeExecutionError, match="output name"):
        action_files.key_values("bad\0=value")


def test_output_limits_use_utf16_and_environment_values_reject_nul(tmp_path: Path) -> None:
    files = action_files.step_files(tmp_path)
    state = action_files.read_state(tmp_path / "state")
    files["RELAY_OUTPUT"].write_bytes(b"v=" + b"x" * (action_files.MAX_FILE // 2))
    with pytest.raises(NodeExecutionError, match="output limit"):
        action_files.consume(state, "attempt", files, tmp_path)
    assert state["consumed"] == []
    files["RELAY_OUTPUT"].write_bytes(b"")
    files["RELAY_ENV"].write_bytes(b"VALUE=bad\0")
    with pytest.raises(NodeExecutionError):
        action_files.consume(state, "attempt", files, tmp_path)
    assert state["env"] == {}


def test_declared_subjects_reject_missing_conflicting_and_excessive_reports(tmp_path: Path) -> None:
    with pytest.raises(PathSafetyError, match="regular workspace file"):
        action_files.declared_subjects("missing", tmp_path, [])
    (tmp_path / "result.txt").write_text("bytes", encoding="utf-8")
    previous = [{"name": "result.txt", "digest": "sha256:" + "b" * 64, "kind": "file"}]
    with pytest.raises(NodeExecutionError, match="Conflicting"):
        action_files.declared_subjects("result.txt", tmp_path, previous)
    for index in range(501):
        (tmp_path / f"result-{index}.txt").write_text("bytes", encoding="utf-8")
    text = "\n".join(f"result-{index}.txt" for index in range(501))
    with pytest.raises(NodeExecutionError, match="500"):
        action_files.declared_subjects(text, tmp_path, [])


@pytest.mark.parametrize(
    "shell,suffix",
    [
        ("sh", ".sh"),
        ("cmd", ".cmd"),
        ("powershell", ".ps1"),
        ("python", ".py"),
        ("custom --flag {0}", ".script"),
    ],
)
def test_explicit_shell_scripts_use_owned_paths_and_argument_vectors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shell: str, suffix: str
) -> None:
    monkeypatch.setattr(action_files.shutil, "which", lambda name: sys.executable)
    argv = action_files.shell_script(tmp_path, "first\r\nsecond\n", shell)
    assert argv[0] == sys.executable
    assert str(tmp_path / ("script" + suffix)) in " ".join(argv)
    script = (tmp_path / ("script" + suffix)).read_bytes()
    if shell == "cmd":
        assert script == b"@echo off\r\nfirst\r\nsecond\r\n"
    elif shell == "powershell":
        assert b"$ErrorActionPreference = 'stop'" in script and b"LASTEXITCODE" in script
    else:
        assert script == b"first\r\nsecond\n"


@pytest.mark.parametrize("shell", ["custom", "custom {0} {0}"])
def test_custom_shell_requires_exactly_one_placeholder(tmp_path: Path, shell: str) -> None:
    with pytest.raises(NodeExecutionError, match="exactly one"):
        action_files.shell_script(tmp_path, "ready", shell)


def test_unavailable_explicit_shell_fails_without_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(action_files.shutil, "which", lambda name: None)
    with pytest.raises(NodeExecutionError, match="not installed"):
        action_files.shell_script(tmp_path, "ready", "bash")


@pytest.mark.parametrize("shell", [None, "bash", "sh", "pwsh", "powershell", "cmd", "python"])
def test_browser_script_preview_uses_the_execution_argument_planner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shell: str | None
) -> None:
    monkeypatch.setattr(action_files.shutil, "which", lambda name: sys.executable)
    preview = action_files.script_previews()[shell or "default"]
    assert isinstance(preview, dict)
    assert preview["installed"] is True
    arguments = preview["argv"]
    assert isinstance(arguments, list)
    argv = action_files.shell_script(tmp_path, "quoted = '王秀英'\n", shell)
    assert argv == [
        str(argument).replace("<private attempt>", str(tmp_path)) for argument in arguments
    ]
