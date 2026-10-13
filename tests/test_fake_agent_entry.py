"""The lightweight fake-agent probe preserves version and real wire contracts."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from relay.agents.profiles import PROFILES
from tests.support import FakeAgents


@pytest.mark.parametrize("agent_id", tuple(PROFILES))
def test_fake_agent_versions_skip_acp_and_preserve_utf8_transcripts(
    fake_agents: FakeAgents,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    agent_id: str,
) -> None:
    executable = fake_agents.install(agent_id)
    blocker = tmp_path / "import-blocker"
    blocker.mkdir()
    (blocker / "acp.py").write_text(
        "raise ImportError('Version probes must not load ACP')\n", encoding="utf-8"
    )
    encodings = tmp_path / "stream-encodings.json"
    (blocker / "sitecustomize.py").write_text(
        "import atexit, json, os, sys\n"
        "from pathlib import Path\n"
        "def capture_encodings():\n"
        "    Path(os.environ['FAKE_STREAM_ENCODINGS']).write_text(\n"
        "        json.dumps([stream.encoding for stream in\n"
        "                    (sys.stdin, sys.stdout, sys.stderr)]), encoding='utf-8')\n"
        "atexit.register(capture_encodings)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PYTHONPATH", str(blocker))
    monkeypatch.setenv("PYTHONIOENCODING", "ascii")
    monkeypatch.setenv("FAKE_STREAM_ENCODINGS", str(encodings))

    result = subprocess.run(  # noqa: S603
        [str(executable), "--version"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        encoding="utf-8",
        timeout=10,
        check=True,
    )

    assert result.stdout == "fake-agent 1.2.3\n"
    assert result.stderr == ""
    assert fake_agents.messages() == [{"version_probe": True}]
    assert json.loads(encodings.read_text(encoding="utf-8")) == ["utf-8"] * 3


def test_fake_agent_version_can_run_without_a_transcript(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FAKE_AGENT_TRACE", raising=False)
    working_directory = tmp_path / "empty-workspace"
    working_directory.mkdir()
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(Path(__file__).with_name("fake_agent_entry.py")), "--version"],
        cwd=working_directory,
        capture_output=True,
        encoding="utf-8",
        timeout=10,
        check=True,
    )

    assert result.stdout == "fake-agent 1.2.3\n"
    assert result.stderr == ""
    assert list(working_directory.iterdir()) == []


@pytest.mark.parametrize(
    ("agent_id", "arguments", "messages"),
    [
        (
            "codex",
            (),
            [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "session/prompt",
                    "params": {"prompt": [{"type": "text", "text": "Review café.\nNext."}]},
                },
            ],
        ),
        ("antigravity", ("models",), []),
        (
            "antigravity",
            ("--model", "m2"),
            [{"event": "user", "message": {"content": "Review café.\nNext."}}],
        ),
    ],
)
def test_fake_agent_entry_preserves_acp_and_native_wire_behavior(
    fake_agents: FakeAgents,
    tmp_path: Path,
    agent_id: str,
    arguments: tuple[str, ...],
    messages: list[dict[str, object]],
) -> None:
    executable = fake_agents.install(agent_id)
    transport = "agy" if agent_id == "antigravity" else "acp"
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "ascii"
    original_transcript = tmp_path / "original-transcript.jsonl"
    environment["FAKE_AGENT_TRACE"] = str(original_transcript)
    payload = "".join(json.dumps(message, ensure_ascii=False) + "\n" for message in messages)

    original = subprocess.run(  # noqa: S603
        [sys.executable, str(Path(__file__).with_name("fake_agent.py")), transport, *arguments],
        input=payload,
        capture_output=True,
        encoding="utf-8",
        timeout=10,
        check=True,
        env=environment,
    )
    environment["FAKE_AGENT_TRACE"] = str(fake_agents.transcript)
    launched = subprocess.run(  # noqa: S603
        [str(executable), *arguments],
        input=payload,
        capture_output=True,
        encoding="utf-8",
        timeout=10,
        check=True,
        env=environment,
    )

    assert launched.stdout == original.stdout
    assert launched.stderr == original.stderr == ""
    original_messages = (
        [json.loads(line) for line in original_transcript.read_text(encoding="utf-8").splitlines()]
        if original_transcript.exists()
        else []
    )
    assert fake_agents.messages() == original_messages
    if agent_id == "codex":
        responses = [json.loads(line) for line in launched.stdout.splitlines()]
        assert responses[-1]["result"] == {"stopReason": "end_turn"}
        assert original_messages == messages
    elif messages:
        responses = [json.loads(line) for line in launched.stdout.splitlines()]
        assert responses[0] == {"event": "init", "init": {"model": "m2"}}
        assert responses[-1]["result"]["status"] == "SUCCESS"
        assert original_messages[-1] == {"input_closed": True}
    else:
        assert "m1 Model One\nm2 Model Two" in launched.stdout
