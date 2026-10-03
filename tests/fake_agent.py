"""Offline executables for the ACP 0.12.1 wire protocol and agy headless NDJSON.

The process responds to real driver requests. Modes change only provider behavior;
Relay's parsing, model proof, routing, persistence, and cleanup remain in use.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys

from acp import PROTOCOL_VERSION, RequestError


def write_line(text: str, *, stderr: bool = False) -> None:
    """Write a protocol line: 'ready' becomes 'ready\n', then flush the pipe."""
    stream = sys.stderr if stderr else sys.stdout
    stream.write(text + "\n")
    stream.flush()


def emit(message: object) -> None:
    write_line(json.dumps(message, ensure_ascii=False))


def trace(message: object) -> None:
    target = os.environ.get("FAKE_AGENT_TRACE")
    if target:
        with Path(target).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(message) + "\n")


def selector(value: str = "m1") -> dict[str, object]:
    """ACP aliases preserve 'currentValue': 'm1' and the exact selectable values."""
    options = [{"value": "m1", "name": "Model One"}, {"value": "m2", "name": "Model Two"}]
    if os.environ.get("FAKE_ACP_MODE") == "grouped":
        options = [{"group": "models", "name": "Models", "options": options}]
    return {
        "id": "model",
        "name": "Model",
        "category": "model",
        "type": "select",
        "currentValue": value,
        "options": options,
    }


@dataclass
class WireAgent:
    mode: str
    authenticated: bool = False
    pending_prompt: int | str | None = None
    selected: str = "m1"

    def reply(self, request_id: object, result: object) -> None:
        emit({"jsonrpc": "2.0", "id": request_id, "result": result})

    def error(self, request_id: object, error: RequestError) -> None:
        emit({"jsonrpc": "2.0", "id": request_id, "error": error.to_error_obj()})

    def update(self, update: dict[str, object]) -> None:
        emit(
            {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {"sessionId": "scratch-session", "update": update},
            }
        )

    def handle(self, message: dict[str, object]) -> None:
        request_id = message.get("id")
        method = message.get("method")
        params = message.get("params")
        params = params if isinstance(params, dict) else {}
        trace(message)
        if method == "initialize":
            if self.mode == "stderr":
                sys.stderr.write("e" * 1_000_000)
                sys.stderr.flush()
            capabilities = {"close": {}}
            if self.mode == "delete-advertised":
                capabilities["delete"] = {}
            self.reply(
                request_id,
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "agentInfo": {"name": "fake", "version": "1.2.3"},
                    "agentCapabilities": {"sessionCapabilities": capabilities},
                    "authMethods": [{"id": "login", "name": "Login"}],
                },
            )
        elif method == "session/new":
            if self.mode == "auth" and not self.authenticated:
                self.error(request_id, RequestError.auth_required())
            else:
                options = [] if self.mode == "no-selector" else [selector()]
                self.reply(request_id, {"sessionId": "scratch-session", "configOptions": options})
        elif method == "authenticate":
            self.authenticated = True
            self.reply(request_id, {})
        elif method == "session/set_config_option":
            if self.mode == "reject":
                self.error(request_id, RequestError.invalid_params())
            else:
                requested = params.get("value")
                self.selected = requested if isinstance(requested, str) else "m1"
                self.reply(
                    request_id,
                    {
                        "configOptions": [
                            selector("m2" if self.mode == "wrong-selection" else self.selected)
                        ]
                    },
                )
        elif method == "session/prompt":
            if self.mode == "drift":
                self.update(
                    {"sessionUpdate": "config_option_update", "configOptions": [selector("m2")]}
                )
            self.update(
                {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": "ready"},
                }
            )
            if self.mode == "hold":
                self.pending_prompt = request_id if isinstance(request_id, (int, str)) else None
            else:
                reason = "refusal" if self.mode == "refusal" else "end_turn"
                self.reply(request_id, {"stopReason": reason})
        elif method == "session/cancel":
            if self.pending_prompt is not None:
                self.reply(self.pending_prompt, {"stopReason": "cancelled"})
                self.pending_prompt = None
        elif method == "session/close":
            if self.mode == "close-error":
                self.error(request_id, RequestError.internal_error())
            else:
                self.reply(request_id, {})


def acp_main() -> None:
    agent = WireAgent(os.environ.get("FAKE_ACP_MODE", "success"))
    for line in sys.stdin:
        message = json.loads(line)
        if isinstance(message, dict):
            agent.handle(message)


def agy_main(arguments: list[str]) -> None:
    mode = os.environ.get("FAKE_AGY_MODE", "success")
    if "models" in arguments:
        if mode == "models-failed":
            write_line("Model discovery unavailable", stderr=True)
            raise SystemExit(2)
        if mode == "models-empty":
            write_line("Available models\nMODEL NAME\n---")
            return
        write_line("Available models\nMODEL NAME\n---\nm1 Model One\nm2 Model Two")
        return
    trace({"argv": arguments})
    model = arguments[arguments.index("--model") + 1]
    if mode == "stdin-backpressure":
        for _index in range(512):
            write_line("startup diagnostics " + "e" * 1_024, stderr=True)
    message = json.loads(sys.stdin.readline())
    trace({"input": message})
    if message.get("event") != "user" or not isinstance(message.get("message"), dict):
        raise SystemExit(2)
    if sys.stdin.read():
        raise SystemExit(2)
    trace({"input_closed": True})
    emit({"event": "init", "init": {"model": "other" if mode == "drift" else model}})
    if mode == "malformed":
        write_line("{")
        return
    if mode == "non-object":
        emit([])
        return
    if mode == "oversized":
        write_line("x" * 1_000_000)
        return
    if mode.startswith("stderr-"):
        if mode == "stderr-denied":
            write_line("denied write_file(report.txt)", stderr=True)
        elif mode == "stderr-outside":
            write_line("denied write_file(../outside.txt)", stderr=True)
        elif mode == "stderr-fragments":
            write_line("denied\nwrite_file(report.txt)", stderr=True)
    text = "denied write_file(report.txt)" if mode == "stdout-denied" else "Ready: Yes"
    emit(
        {
            "event": "step_update",
            "step_update": {"step_type": "agent_response", "text_delta": text, "state": "DONE"},
        }
    )
    if mode == "missing-result":
        return
    result = {"status": "SUCCESS", "response": "private response", "duration_seconds": 1.0}
    if mode in {"timeout", "error-text", "boolean-duration"}:
        result = {
            "status": "ERROR",
            "error": "timeout configuration failed",
            "duration_seconds": True
            if mode == "boolean-duration"
            else (300.0 if mode == "timeout" else 0.1),
        }
    elif mode in {"canceled", "interrupted"}:
        result["status"] = mode.upper()
    emit({"event": "result", "result": result})


def main() -> None:
    # The protocol uses UTF-8 even when a Windows console defaults to a code page.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    if "--version" in sys.argv:
        trace({"version_probe": True})
        write_line("fake-agent 1.2.3")
    elif sys.argv[1] == "acp":
        acp_main()
    else:
        agy_main(sys.argv[2:])


if __name__ == "__main__":
    main()
