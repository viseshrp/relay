from __future__ import annotations

import json
import subprocess
import sys


def _emit(event: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(event) + "\n")
    sys.stdout.flush()


def _run_prompt(command: list[str], prompt: str) -> int:
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    try:
        if process.stdin is not None:
            process.stdin.write(prompt)
            process.stdin.write("\n")
            process.stdin.close()
        if process.stdout is not None:
            for line in process.stdout:
                _emit({"type": "chunk", "data": line})
        return process.wait()
    finally:
        if process.stdout is not None:
            process.stdout.close()
        if process.poll() is None:
            process.kill()
            process.wait()


def main() -> int:
    if len(sys.argv) != 2:
        _emit({"type": "error", "message": "Copilot session worker requires a serialized command payload."})
        return 1
    try:
        command = json.loads(sys.argv[1])
    except json.JSONDecodeError as exc:
        _emit({"type": "error", "message": f"Invalid command payload: {exc}"})
        return 1
    if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
        _emit({"type": "error", "message": "Copilot session worker command payload must be a list of strings."})
        return 1

    while True:
        raw_line = sys.stdin.readline()
        if raw_line == "":
            return 0
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            _emit({"type": "error", "message": f"Invalid request payload: {exc}"})
            continue
        if payload.get("type") != "prompt":
            _emit({"type": "error", "message": f"Unsupported request type: {payload.get('type')}"})
            continue
        try:
            exit_code = _run_prompt(command, str(payload.get("prompt", "")))
        except Exception as exc:  # pragma: no cover - defensive wrapper guard
            _emit({"type": "error", "message": str(exc)})
            continue
        _emit({"type": "done", "exit_code": exit_code})


if __name__ == "__main__":
    raise SystemExit(main())
