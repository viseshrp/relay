"""File interfaces, masking, and retained products against isolated storage."""

import os
from pathlib import Path
import subprocess

import pytest

from relay.errors import NodeExecutionError, PathSafetyError, WorkflowValidationError
from relay.execution.action_commands import ActionRuntime, CommandLog
from relay.execution.action_files import (
    consume,
    declared_subjects,
    file_text,
    key_values,
    read_state,
    shell_script,
    step_files,
)
from relay.execution.action_products import cache_mode, capture, checked_path, restore, verify
from relay.execution.masking import Redactor
from relay.workflows.actions.patterns import matches, select_paths


def test_implicit_shell_writes_utf8_file_commands_on_the_host_platform(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.write_text("", encoding="utf-8")
    source = (
        '[System.IO.File]::WriteAllText($env:RELAY_OUTPUT, "value=ready`n", '
        "[System.Text.UTF8Encoding]::new($false))"
        if os.name == "nt"
        else 'printf "value=ready\\n" > "$RELAY_OUTPUT"'
    )
    arguments = shell_script(tmp_path, source, None)
    assert Path(arguments[0]).stem.lower() in ({"pwsh"} if os.name == "nt" else {"bash", "sh"})
    subprocess.run(  # noqa: S603 - owned test script with the platform's default interpreter
        arguments,
        env={**os.environ, "RELAY_OUTPUT": str(output)},
        check=True,
        capture_output=True,
        timeout=15,
        shell=False,
    )
    assert key_values(file_text(output)) == {"value": "ready"}


def test_multiline_file_values_preserve_crlf_and_empty_values() -> None:
    assert key_values("a=\r\nb<<END\r\nfirst\r\nsecond\r\nEND\r\n") == {
        "a": "",
        "b": "first\r\nsecond",
    }


@pytest.mark.parametrize("text", ["missing", "a<<\n", "a<<END\nno end\n", "=invalid"])
def test_invalid_file_commands_are_rejected(text: str) -> None:
    with pytest.raises(NodeExecutionError):
        key_values(text)


def test_step_files_are_consumed_once_and_env_is_visible_to_later_steps(tmp_path: Path) -> None:
    state = read_state(tmp_path / "state")
    paths = step_files(tmp_path)
    paths["RELAY_ENV"].write_text("CUSTOM=next\n", encoding="utf-8")
    paths["RELAY_OUTPUT"].write_text("value=42\n", encoding="utf-8")
    paths["RELAY_PATH"].write_text(str(tmp_path) + "\n", encoding="utf-8")
    assert consume(state, "attempt", paths, tmp_path)[0] == {"value": "42"}
    assert state["env"] == {"CUSTOM": "next"}
    assert state["path"] == [str(tmp_path)]
    paths["RELAY_ENV"].write_text("CUSTOM=changed\n", encoding="utf-8")
    assert consume(state, "attempt", paths, tmp_path)[0] == {}
    assert state["env"]["CUSTOM"] == "next"


@pytest.mark.parametrize("name", ["RELAY_SHA", "RELAY_HOST_OS", "NODE_OPTIONS"])
def test_file_commands_cannot_overwrite_protected_environment(name: str, tmp_path: Path) -> None:
    paths = step_files(tmp_path)
    paths["RELAY_ENV"].write_text(f"{name}=unsafe\n", encoding="utf-8")
    with pytest.raises(NodeExecutionError):
        consume(read_state(tmp_path / "state"), "attempt", paths, tmp_path)


def test_artifact_subjects_hash_and_retain_only_local_files(tmp_path: Path) -> None:
    (tmp_path / "result.txt").write_text("bytes", encoding="utf-8")
    subjects, retained = declared_subjects("# comment\nresult.txt", tmp_path, [])
    assert [item["kind"] for item in subjects] == ["file"]
    assert retained == {"subject:result.txt": "result.txt"}
    assert declared_subjects("result.txt", tmp_path, subjects)[0] == subjects
    for reference in (
        "oci://registry.example/image@sha256:" + "a" * 64,
        "registry.example/image@sha256:ab",
    ):
        with pytest.raises(NodeExecutionError, match="local artifact file"):
            declared_subjects(reference, tmp_path, [])


@pytest.mark.parametrize("relative", ["../outside", ".git/config", "/outside"])
def test_product_paths_cannot_escape_or_include_git(relative: str, tmp_path: Path) -> None:
    with pytest.raises(PathSafetyError):
        checked_path(tmp_path, relative)


def test_subject_and_product_links_are_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_text("private", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(PathSafetyError):
        declared_subjects("link", tmp_path, [])
    with pytest.raises(PathSafetyError):
        select_paths(tmp_path, ["**"], files_only=True)


def test_retained_product_hashes_block_corruption_before_restore(tmp_path: Path) -> None:
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "value").write_text("original", encoding="utf-8")
    directory, manifest, size, digest = capture(source, ["**"], "artifacts", "run")
    assert size == 8 and len(digest) == 64
    verify(directory, manifest, "artifacts", "run")
    restore(directory, manifest, target)
    assert (target / "value").read_text() == "original"
    (directory / "value").write_text("corrupt", encoding="utf-8")
    with pytest.raises(NodeExecutionError):
        verify(directory, manifest, "artifacts", "run")
    with pytest.raises(PathSafetyError):
        verify(directory, manifest, "artifacts", "another-run")


@pytest.mark.parametrize("relative", [".relay/workflows/source.yml", ".git/HEAD", "../escape"])
def test_restore_cannot_replace_workflow_sources(relative: str, tmp_path: Path) -> None:
    with pytest.raises(PathSafetyError):
        checked_path(tmp_path, relative, restore=True)


@pytest.mark.parametrize(
    "caller,child,expected",
    [
        ("read", "write", "read"),
        ("write-only", "read", "none"),
        ("none", "write", "none"),
        ("write", "write-only", "write-only"),
    ],
)
def test_reusable_cache_capabilities_can_only_narrow(
    caller: str, child: str, expected: str
) -> None:
    first = cache_mode({}, {"cache-mode": child}, caller)
    assert first == expected
    assert cache_mode({}, {"cache-mode": "write"}, first) == expected


def test_ordered_filters_include_reinclude_and_literal_escapes() -> None:
    assert matches("release/one", ["release/**", "!release/**", "release/one"])
    assert matches("release+one", [r"release\+one"])
    assert matches("file.c", ["file.[!h]"], file_glob=True)
    assert not matches("file.h", ["file.[!h]"], file_glob=True)
    with pytest.raises(WorkflowValidationError):
        matches("file", ["[invalid", "a\\"])


def test_masks_hold_split_secrets_and_redact_nested_payloads() -> None:
    masks = Redactor()
    masks.register("private-123")
    chunks = [masks.stream("log", part) for part in ["prefix priv", "ate-", "123 suffix"]]
    chunks.append(masks.stream("log", "", final=True))
    assert "".join(chunks) == "prefix *** suffix"
    assert masks.payload({"private-123": ["private-123"]}) == {"***": ["***"]}


class RecordingLog:
    events: list[tuple[str, dict[str, object]]]

    def __init__(self) -> None:
        self.events = []

    def append_attempt_event(
        self,
        _attempt: str,
        kind: str,
        _source: object,
        payload: dict[str, object],
        **_kwargs: object,
    ) -> None:
        self.events.append((kind, payload))


def test_workflow_commands_stop_resume_mask_and_annotate() -> None:
    from typing import cast

    from relay.execution.runner import RunnerStore
    from relay.execution.state import EventSource

    recorder = RecordingLog()
    masks = Redactor()
    log = CommandLog(cast(RunnerStore, recorder), "attempt", masks)
    log.feed(
        "command.stdout",
        "::add-mask::private\n::warning file=a.py,line=3::private%0Amessage\n"
        "::stop-commands::token\n::error::literal\n::token::\n::notice::done\n",
    )
    proxy = ActionRuntime(cast(RunnerStore, recorder), log, masks)
    proxy.append_attempt_event(
        "attempt", "agent.message", EventSource.AGENT, {"text": "::error::private"}
    )
    log.flush()
    assert recorder.events[0] == (
        "actions.warning",
        {"message": "***\nmessage", "properties": {"file": "a.py", "line": "3"}},
    )
    assert any(
        kind == "command.stdout" and payload["chunk"] == "::error::literal\n"
        for kind, payload in recorder.events
    )
    assert recorder.events[-1] == ("agent.message", {"text": "::error::***"})
