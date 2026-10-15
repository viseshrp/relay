"""File interfaces, masking, and retained products against isolated storage."""

import json
import os
from pathlib import Path
import stat
import subprocess
from typing import cast

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
from relay.execution.runner import RunnerStore
from relay.execution.state import EventSource
from relay.workflows.actions.patterns import matches, select_paths
from tests.support import symlink_or_skip


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


def test_python_shell_uses_utf8_for_redirected_output_and_files(tmp_path: Path) -> None:
    arguments = shell_script(
        tmp_path,
        "from pathlib import Path\nprint('王秀英')\nPath('result.txt').write_text('王秀英')\n",
        "python",
    )
    environment = {
        **os.environ,
        "PYTHONUTF8": "0",
        "PYTHONCOERCECLOCALE": "0",
        "LC_ALL": "C",
    }
    environment.pop("PYTHONIOENCODING", None)
    result = subprocess.run(  # noqa: S603 - owned script with Relay's Python interpreter
        arguments,
        cwd=tmp_path,
        env=environment,
        check=True,
        capture_output=True,
        timeout=15,
        shell=False,
    )
    assert result.stdout.decode("utf-8").strip() == "王秀英"
    assert (tmp_path / "result.txt").read_text(encoding="utf-8") == "王秀英"


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
    symlink_or_skip(link, target)
    with pytest.raises(PathSafetyError):
        declared_subjects("link", tmp_path, [])
    with pytest.raises(PathSafetyError):
        select_paths(tmp_path, ["**"], files_only=True)


@pytest.mark.skipif(os.name != "nt", reason="Windows directory junction")
def test_subject_and_product_junctions_are_rejected(tmp_path: Path) -> None:
    workspace, target = tmp_path / "workspace", tmp_path / "outside"
    workspace.mkdir()
    target.mkdir()
    sentinel = target / "private.txt"
    sentinel.write_text("private", encoding="utf-8")
    link = workspace / "link"
    subprocess.run(  # noqa: S603 - create a junction between owned temporary directories
        [
            str(Path(os.environ["SYSTEMROOT"]) / "System32" / "cmd.exe"),
            "/d",
            "/c",
            "mklink",
            "/J",
            str(link),
            str(target),
        ],
        capture_output=True,
        check=True,
        timeout=15,
        shell=False,
    )
    try:
        assert link.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
        assert (link / "private.txt").read_text(encoding="utf-8") == "private"
        with pytest.raises(PathSafetyError):
            declared_subjects("link/private.txt", workspace, [])
        with pytest.raises(PathSafetyError):
            select_paths(workspace, ["**"], files_only=True)
        assert sentinel.read_text(encoding="utf-8") == "private"
    finally:
        link.rmdir()
    assert sentinel.read_text(encoding="utf-8") == "private"


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


@pytest.fixture
def action_log() -> tuple[ActionRuntime, CommandLog, RecordingLog]:
    recorder = RecordingLog()
    masks = Redactor()
    log = CommandLog(cast(RunnerStore, recorder), "attempt", masks)
    return ActionRuntime(cast(RunnerStore, recorder), log, masks), log, recorder


def tool_output(recorder: RecordingLog) -> str:
    return "".join(
        json.loads(str(payload["summary"])).get("output_delta", "")
        for kind, payload in recorder.events
        if kind in {"agent.tool_call", "agent.tool_result"}
    )


@pytest.mark.parametrize(
    ("secret", "deltas"),
    [
        ("TOKEN-1234567890", ("prefix TOKEN-12345", "67890\n")),
        ('TOKEN-"\\\tEND', ('prefix TOKEN-"\\\tEND\n',)),
        ('TOKEN-"\\\tEND', ('prefix TOKEN-"\\', "\tEND\n")),
    ],
    ids=["split", "escaped", "split-escaped"],
)
def test_agent_tool_deltas_mask_decoded_secrets(
    action_log: tuple[ActionRuntime, CommandLog, RecordingLog],
    secret: str,
    deltas: tuple[str, ...],
) -> None:
    proxy, log, recorder = action_log
    proxy.masks.register(secret)
    for delta in deltas:
        proxy.append_attempt_event(
            "attempt",
            "agent.tool_call",
            EventSource.AGENT,
            {"tool_call_id": "terminal", "turn": 1, "summary": json.dumps({"output_delta": delta})},
        )
    log.flush()
    assert tool_output(recorder) == "prefix ***\n"
    assert all(payload["tool_call_id"] == "terminal" for _, payload in recorder.events)


@pytest.mark.parametrize(
    ("other_attempt", "other_tool", "other_turn"),
    [("other", "terminal", 1), ("attempt", "other", 1), ("attempt", "terminal", 2)],
    ids=["attempt", "tool", "turn"],
)
def test_agent_tool_prefixes_do_not_cross_stream_boundaries(
    action_log: tuple[ActionRuntime, CommandLog, RecordingLog],
    other_attempt: str,
    other_tool: str,
    other_turn: int,
) -> None:
    proxy, log, recorder = action_log
    proxy.masks.register("TOKEN-1234567890")
    other_recorder = RecordingLog()
    other_log = CommandLog(cast(RunnerStore, other_recorder), other_attempt, proxy.masks)
    other_proxy = ActionRuntime(cast(RunnerStore, other_recorder), other_log, proxy.masks)
    proxy.append_attempt_event(
        "attempt",
        "agent.tool_call",
        EventSource.AGENT,
        {"tool_call_id": "terminal", "turn": 1, "summary": '{"output_delta":"TOKEN-12345"}'},
    )
    assert tool_output(recorder) == ""
    other_proxy.append_attempt_event(
        other_attempt,
        "agent.tool_call",
        EventSource.AGENT,
        {"tool_call_id": other_tool, "turn": other_turn, "summary": '{"output_delta":"67890\\n"}'},
    )
    proxy.append_attempt_event(
        "attempt",
        "agent.tool_result",
        EventSource.AGENT,
        {"tool_call_id": "terminal", "turn": 1, "summary": '{"output_delta":"67890\\n"}'},
    )
    log.flush()
    other_log.flush()
    assert tool_output(recorder) == "***\n"
    assert tool_output(other_recorder) == "67890\n"


@pytest.mark.parametrize(
    ("event_type", "summary", "expected_summary"),
    [
        ("agent.tool_result", '{"status":"completed"}', {"status": "completed"}),
        ("agent.tool_call", '{"exit_code":0}', {"exit_code": 0}),
        ("agent.tool_result", '{"output_delta":""}', {"output_delta": "TOKEN-"}),
    ],
    ids=["result", "exit", "final-delta"],
)
def test_agent_tool_completion_flushes_safe_prefixes_before_step_shutdown(
    action_log: tuple[ActionRuntime, CommandLog, RecordingLog],
    event_type: str,
    summary: str,
    expected_summary: dict[str, object],
) -> None:
    proxy, log, recorder = action_log
    proxy.masks.register("TOKEN-1234567890")
    proxy.append_attempt_event(
        "attempt",
        "agent.tool_call",
        EventSource.AGENT,
        {"tool_call_id": "terminal", "turn": 1, "summary": '{"output_delta":"prefix TOKEN-"}'},
    )
    assert tool_output(recorder) == "prefix "
    proxy.append_attempt_event(
        "attempt",
        event_type,
        EventSource.AGENT,
        {"tool_call_id": "terminal", "turn": 1, "summary": summary},
    )
    assert tool_output(recorder) == "prefix TOKEN-"
    assert json.loads(str(recorder.events[-1][1]["summary"])) == expected_summary
    completed_events = list(recorder.events)
    log.flush()
    assert recorder.events == completed_events


def test_step_shutdown_flushes_unfinished_tool_output_once(
    action_log: tuple[ActionRuntime, CommandLog, RecordingLog],
) -> None:
    proxy, log, recorder = action_log
    proxy.masks.register("TOKEN-1234567890")
    proxy.append_attempt_event(
        "attempt",
        "agent.tool_call",
        EventSource.AGENT,
        {"tool_call_id": "terminal", "turn": 1, "summary": '{"output_delta":"prefix TOKEN-"}'},
    )
    assert tool_output(recorder) == "prefix "
    log.flush()
    assert tool_output(recorder) == "prefix TOKEN-"
    assert all(
        kind == "agent.tool_call" and payload["tool_call_id"] == "terminal" and payload["turn"] == 1
        for kind, payload in recorder.events
    )
    flushed_events = list(recorder.events)
    log.flush()
    assert recorder.events == flushed_events


@pytest.mark.parametrize("field", ["content", "raw_output", "nested_output"])
def test_cumulative_tool_snapshots_hold_secret_prefixes_until_replaced(
    action_log: tuple[ActionRuntime, CommandLog, RecordingLog], field: str
) -> None:
    proxy, log, recorder = action_log
    proxy.masks.register("TOKEN-1234567890")
    for text in ("prefix TOKEN-12345", "prefix TOKEN-1234567890\n"):
        if field == "content":
            summary = {"content": [{"text": text}]}
        elif field == "raw_output":
            summary = {"raw_output": {"stdout": text}}
        else:
            summary = {"raw_output": {"contents": [{"text": text}]}}
        proxy.append_attempt_event(
            "attempt",
            "agent.tool_call",
            EventSource.AGENT,
            {"tool_call_id": "snapshot", "turn": 1, "summary": json.dumps(summary)},
        )
    first, second = (json.loads(str(payload["summary"])) for _, payload in recorder.events)
    assert "TOKEN-" not in json.dumps(first)
    assert "prefix " in json.dumps(first)
    assert "TOKEN-" not in json.dumps(second)
    assert "prefix ***\\n" in json.dumps(second)
    proxy.append_attempt_event(
        "attempt",
        "agent.tool_result",
        EventSource.AGENT,
        {"tool_call_id": "snapshot", "turn": 1, "summary": '{"status":"completed"}'},
    )
    log.flush()
    assert len(recorder.events) == 3


def test_replaced_snapshots_discard_their_previous_pending_suffix(
    action_log: tuple[ActionRuntime, CommandLog, RecordingLog],
) -> None:
    proxy, log, recorder = action_log
    proxy.masks.register("TOKEN-1234567890")
    for text in ("prefix TOKEN-", "different output"):
        proxy.append_attempt_event(
            "attempt",
            "agent.tool_call",
            EventSource.AGENT,
            {
                "tool_call_id": "snapshot",
                "turn": 1,
                "summary": json.dumps({"content": [{"text": text}]}),
            },
        )
    log.flush()
    assert len(recorder.events) == 2
    assert json.loads(str(recorder.events[-1][1]["summary"])) == {
        "content": [{"text": "different output"}]
    }


def test_replaced_snapshot_arrays_discard_removed_text_fields(
    action_log: tuple[ActionRuntime, CommandLog, RecordingLog],
) -> None:
    proxy, log, recorder = action_log
    proxy.masks.register("TOKEN-1234567890")
    for content in ([{"text": "unchanged"}, {"text": "TOKEN-"}], [{"text": "unchanged"}]):
        proxy.append_attempt_event(
            "attempt",
            "agent.tool_call",
            EventSource.AGENT,
            {"tool_call_id": "snapshot", "turn": 1, "summary": json.dumps({"content": content})},
        )
    log.flush()
    assert len(recorder.events) == 2
    assert not proxy.masks.pending


def test_snapshot_field_keys_cannot_alias_another_tools_opaque_id(
    action_log: tuple[ActionRuntime, CommandLog, RecordingLog],
) -> None:
    proxy, log, recorder = action_log
    proxy.masks.register("TOKEN-1234567890")
    other_tool = 'terminal:snapshot:["content",0,"text"]'
    for tool, summary in (
        ("terminal", {"content": [{"text": "prefix TOKEN-12345"}]}),
        (other_tool, {"output_delta": "67890\n"}),
        ("terminal", {"content": [{"text": "prefix TOKEN-1234567890\n"}]}),
    ):
        proxy.append_attempt_event(
            "attempt",
            "agent.tool_call",
            EventSource.AGENT,
            {"tool_call_id": tool, "turn": 1, "summary": json.dumps(summary)},
        )
    log.flush()
    other = [payload for _, payload in recorder.events if payload["tool_call_id"] == other_tool]
    assert len(other) == 1
    assert json.loads(str(other[0]["summary"])) == {"output_delta": "67890\n"}
    assert "TOKEN-" not in json.dumps(recorder.events)


@pytest.mark.parametrize("shutdown", [False, True], ids=["tool-result", "step-shutdown"])
def test_snapshot_completion_flushes_only_its_own_safe_suffixes_once(
    action_log: tuple[ActionRuntime, CommandLog, RecordingLog], shutdown: bool
) -> None:
    proxy, log, recorder = action_log
    proxy.masks.register("TOKEN-1234567890")
    for tool, summary in (
        (
            "snapshot",
            {"content": [{"text": "first TOKEN-"}], "raw_output": {"stderr": "second TOKEN-"}},
        ),
        ("other", {"content": [{"text": "other TOKEN-"}]}),
    ):
        proxy.append_attempt_event(
            "attempt",
            "agent.tool_call",
            EventSource.AGENT,
            {"tool_call_id": tool, "turn": 1, "summary": json.dumps(summary)},
        )
    if shutdown:
        log.flush()
    else:
        proxy.append_attempt_event(
            "attempt",
            "agent.tool_result",
            EventSource.AGENT,
            {"tool_call_id": "snapshot", "turn": 1, "summary": '{"status":"completed"}'},
        )
        assert all(payload["tool_call_id"] == "snapshot" for _, payload in recorder.events[2:])
        assert recorder.events[-1][0] == "agent.tool_result"
        log.flush()
    assert tool_output(recorder) == "TOKEN-TOKEN-TOKEN-"
    flushed = list(recorder.events)
    log.flush()
    assert recorder.events == flushed


def test_plain_tool_result_still_masks_secrets_and_flushes_held_output(
    action_log: tuple[ActionRuntime, CommandLog, RecordingLog],
) -> None:
    proxy, _, recorder = action_log
    proxy.masks.register("TOKEN-1234567890")
    proxy.append_attempt_event(
        "attempt",
        "agent.tool_call",
        EventSource.AGENT,
        {"tool_call_id": "terminal", "turn": 1, "summary": '{"output_delta":"prefix TOKEN-"}'},
    )
    proxy.append_attempt_event(
        "attempt",
        "agent.tool_result",
        EventSource.AGENT,
        {"tool_call_id": "terminal", "turn": 1, "summary": "finished TOKEN-1234567890"},
    )
    assert (
        "".join(
            json.loads(str(payload["summary"]))["output_delta"]
            for _, payload in recorder.events[:-1]
        )
        == "prefix TOKEN-"
    )
    assert recorder.events[-1][1]["summary"] == "finished ***"


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


@pytest.mark.parametrize(
    "output",
    ["ordinary line\n" * 20_000, 'Ω"\\' * 20_000 + "\n"],
    ids=["many-lines", "escaped-unicode"],
)
def test_command_output_retains_large_reads_in_bounded_batches(
    action_log: tuple[ActionRuntime, CommandLog, RecordingLog], output: str
) -> None:
    from relay.constants import EVENT_MAX_PAYLOAD_BYTES

    _, log, recorder = action_log
    log.feed("command.stdout", output)
    log.flush()

    assert "".join(str(payload["chunk"]) for _, payload in recorder.events) == output
    assert len(recorder.events) < 100
    assert all(
        len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) < EVENT_MAX_PAYLOAD_BYTES
        for _, payload in recorder.events
    )


def test_command_batches_preserve_mask_and_annotation_order(
    action_log: tuple[ActionRuntime, CommandLog, RecordingLog],
) -> None:
    _, log, recorder = action_log
    log.feed(
        "command.stdout",
        "before\n::add-mask::private\nprivate\n::notice::private\nafter\n",
    )
    log.flush()

    assert recorder.events == [
        ("command.stdout", {"chunk": "before\n"}),
        ("command.stdout", {"chunk": "***\n"}),
        ("actions.notice", {"message": "***", "properties": {}}),
        ("command.stdout", {"chunk": "after\n"}),
    ]
