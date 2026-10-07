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
import time

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
    effort: str = "high"
    permission_mode: str = "ask"
    model_selections: int = 0
    prompt_count: int = 0
    cwd: str = ""

    def configuration(self) -> list[dict[str, object]]:
        options = [selector(self.selected)]
        if not self.mode.startswith("configuration"):
            return options
        efforts = ["low", "high"] if self.selected == "m1" else ["low", "medium"]
        if self.effort not in efforts:
            self.effort = efforts[-1]
        effort = {
            "id": "reasoning_effort",
            "name": "Reasoning effort",
            "type": "select",
            "currentValue": self.effort,
            "options": [
                {"value": value, "name": value.capitalize(), "description": f"Use {value} effort."}
                for value in efforts
            ],
        }
        if self.mode != "configuration-no-categories":
            effort["category"] = "thought_level"
        if self.mode == "configuration-grouped":
            effort["options"] = [
                {"group": "efforts", "name": "Efforts", "options": effort["options"]}
            ]
        options.append(effort)
        if self.mode != "configuration-legacy":
            options.append(
                {
                    "id": "mode",
                    "name": "Permission mode",
                    "category": "mode",
                    "type": "select",
                    "currentValue": self.permission_mode,
                    "options": [{"value": "ask", "name": "Ask"}, {"value": "auto", "name": "Auto"}],
                }
            )
        return options

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
        if request_id in {"owner-permission", "owner-question"} and "result" in message:
            self.reply(self.pending_prompt, {"stopReason": "end_turn"})
            self.pending_prompt = None
            return
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
            cwd = params.get("cwd")
            self.cwd = cwd if isinstance(cwd, str) else ""
            if self.mode == "auth" and not self.authenticated:
                self.error(request_id, RequestError.auth_required())
            else:
                self.selected, self.effort, self.permission_mode = "m1", "high", "ask"
                options = [] if self.mode == "no-selector" else self.configuration()
                result = {"sessionId": "scratch-session", "configOptions": options}
                if self.mode == "configuration-legacy":
                    result["modes"] = {
                        "currentModeId": "ask",
                        "availableModes": [
                            {"id": "ask", "name": "Ask"},
                            {"id": "auto", "name": "Auto"},
                        ],
                    }
                self.reply(request_id, result)
        elif method == "authenticate":
            self.authenticated = True
            self.reply(request_id, {})
        elif method == "session/set_config_option":
            config_id = params.get("configId")
            if self.mode == "reject" or (
                self.mode == "configuration-reject" and config_id != "model"
            ):
                self.error(request_id, RequestError.invalid_params())
            else:
                requested = params.get("value")
                if config_id == "model":
                    self.selected = requested if isinstance(requested, str) else "m1"
                    self.model_selections += 1
                elif config_id == "reasoning_effort":
                    self.effort = requested if isinstance(requested, str) else "high"
                elif config_id == "mode":
                    self.permission_mode = requested if isinstance(requested, str) else "ask"
                if self.mode == "configuration-wrong" and config_id != "model":
                    self.effort, self.permission_mode = "high", "ask"
                if self.mode == "configuration-model-drift" and config_id != "model":
                    self.selected = "m2"
                configuration = self.configuration()
                if self.mode == "wrong-selection":
                    configuration = [selector("m2")]
                elif (
                    self.mode == "configuration-default-reject"
                    and config_id == "model"
                    and self.model_selections == 1
                ):
                    configuration[0] = selector("m2")
                elif self.mode == "configuration-drop-mode" and config_id == "reasoning_effort":
                    configuration = [item for item in configuration if item["id"] != "mode"]
                self.reply(request_id, {"configOptions": configuration})
        elif method == "session/set_mode":
            self.permission_mode = str(params.get("modeId"))
            self.update(
                {"sessionUpdate": "current_mode_update", "currentModeId": self.permission_mode}
            )
            self.reply(request_id, {})
        elif method == "session/prompt":
            self.prompt_count += 1
            if self.mode == "configuration-starters":
                blocks = params.get("prompt", [])
                text = (
                    "\n".join(
                        str(block.get("text", "")) for block in blocks if isinstance(block, dict)
                    )
                    if isinstance(blocks, list)
                    else ""
                )
                if "Edit only REVIEW.md." in text:
                    (Path(self.cwd) / "REVIEW.md").write_text(
                        "Ready: Yes\nNo blocking findings in the fake review.\n", encoding="utf-8"
                    )
            if self.mode == "configuration-recovery":
                blocks = params.get("prompt", [])
                text = (
                    "\n".join(
                        str(block.get("text", "")) for block in blocks if isinstance(block, dict)
                    )
                    if isinstance(blocks, list)
                    else ""
                )
                recovering = "Recover only this failed step." in text
                content = "Created by: Fake provider\nReady: No\n" if recovering else "Ready: No\n"
                (Path(self.cwd) / "PLAN_CRITIQUE.md").write_text(content, encoding="utf-8")
            if self.mode in {"quota", "quota-unknown"}:
                self.update(
                    {
                        "sessionUpdate": "agent_message_chunk",
                        "content": {"type": "text", "text": "Usage limit reached."},
                    }
                )
                if self.mode == "quota":
                    self.update(
                        {
                            "sessionUpdate": "usage_update",
                            "used": 10,
                            "size": 100,
                            "_meta": {
                                "_claude/rateLimit": {
                                    "status": "rejected",
                                    "resetsAt": time.time() + 3600,
                                    "rateLimitType": "five_hour",
                                }
                            },
                        }
                    )
                    # Context accounting after the rejection must not erase its reset.
                    self.update({"sessionUpdate": "usage_update", "used": 10, "size": 100})
                self.error(
                    request_id, RequestError.internal_error(data={"errorKind": "rate_limit"})
                )
                return
            if self.mode == "elicitation" and self.prompt_count == 1:
                self.pending_prompt = request_id if isinstance(request_id, (int, str)) else None
                emit(
                    {
                        "jsonrpc": "2.0",
                        "id": "owner-question",
                        "method": "elicitation/create",
                        "params": {
                            "sessionId": "scratch-session",
                            "message": "Which component should I check?",
                            "mode": "form",
                            "requestedSchema": {
                                "type": "object",
                                "properties": {
                                    "component": {"type": "string", "title": "Component"}
                                },
                                "required": ["component"],
                            },
                        },
                    }
                )
                return
            if self.mode == "feedback" and self.prompt_count == 1:
                self.pending_prompt = request_id if isinstance(request_id, (int, str)) else None
                emit(
                    {
                        "jsonrpc": "2.0",
                        "id": "owner-permission",
                        "method": "session/request_permission",
                        "params": {
                            "sessionId": "scratch-session",
                            "toolCall": {"toolCallId": "read", "title": "Inspect project"},
                            "options": [
                                {"optionId": "allow", "name": "Allow once", "kind": "allow_once"},
                                {"optionId": "deny", "name": "Deny once", "kind": "reject_once"},
                            ],
                        },
                    }
                )
                return
            if self.mode == "drift":
                self.update(
                    {"sessionUpdate": "config_option_update", "configOptions": [selector("m2")]}
                )
            elif self.mode == "configuration-late-effort-drift":
                self.effort = "high"
                self.update(
                    {"sessionUpdate": "config_option_update", "configOptions": self.configuration()}
                )
            elif self.mode == "configuration-late-mode-drift":
                self.update({"sessionUpdate": "current_mode_update", "currentModeId": "ask"})
            self.update(
                {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": "ready"},
                }
            )
            if self.mode.startswith("configuration"):
                self.update(
                    {
                        "sessionUpdate": "agent_message_chunk",
                        "content": {
                            "type": "text",
                            "text": (
                                f"config: model={self.selected};effort={self.effort};"
                                f"mode={self.permission_mode}"
                            ),
                        },
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
        extra = "\ngemini-test-low Gemini Test (Low)" if mode == "configuration" else ""
        write_line("Available models\nMODEL NAME\n---\nm1 Model One\nm2 Model Two" + extra)
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
