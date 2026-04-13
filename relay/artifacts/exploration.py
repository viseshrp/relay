from __future__ import annotations

import json
from pathlib import Path

from relay.artifacts.manager import ensure_artifact_dirs, relay_root


def messages_dir(project_path: str, run_id: str) -> Path:
    root = ensure_artifact_dirs(project_path, run_id)
    path = root / "exploration" / "messages"
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_message_file(
    project_path: str,
    run_id: str,
    *,
    message_id: str,
    role: str,
    content: str,
    timestamp: str,
    sequence: int,
) -> Path:
    path = messages_dir(project_path, run_id) / f"{sequence:03d}_{role}.json"
    path.write_text(
        json.dumps(
            {
                "id": message_id,
                "role": role,
                "content": content,
                "timestamp": timestamp,
                "sequence": sequence,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def write_transcript(project_path: str, run_id: str, messages: list[dict[str, object]]) -> Path:
    root = ensure_artifact_dirs(project_path, run_id)
    transcript_path = root / "exploration" / "transcript.md"
    chunks = []
    for message in messages:
        role = str(message["role"]).capitalize()
        chunks.append(f"## {role}\n\n{message['content']}\n")
    transcript_path.write_text("\n".join(chunks), encoding="utf-8")
    return transcript_path


def planning_prompt_path(project_path: str, run_id: str) -> Path:
    return ensure_artifact_dirs(project_path, run_id) / "exploration" / "planning_prompt.md"


def exploration_stream_path(data_dir: str, run_id: str) -> Path:
    path = Path(data_dir) / "logs" / run_id / "exploration_stream.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def reset_exploration_stream(data_dir: str, run_id: str) -> Path:
    stream_path = exploration_stream_path(data_dir, run_id)
    stream_path.write_text("", encoding="utf-8")
    return stream_path


def exploration_root(project_path: str, run_id: str) -> Path:
    return relay_root(project_path, run_id) / "exploration"
