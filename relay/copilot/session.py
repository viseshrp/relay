from __future__ import annotations

import asyncio
import json
import os
import subprocess
import shutil
import sys
import textwrap
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import psutil


SessionFactory = Callable[[], "CopilotSession"]
_session_factory: SessionFactory | None = None


def set_session_factory(factory: SessionFactory | None) -> None:
    global _session_factory
    _session_factory = factory


def create_session() -> "CopilotSession":
    if _session_factory is not None:
        return _session_factory()
    return CopilotSession()


def resolve_copilot_cli_path(configured_cli_path: str) -> str:
    # Relay previously targeted legacy `gh copilot ...` subcommands. The
    # current Copilot CLI ships as a standalone `copilot` executable, so when a
    # legacy `gh` path is configured we prefer the direct binary if it exists.
    direct_path = shutil.which("copilot")
    configured_path = shutil.which(configured_cli_path) or configured_cli_path
    configured_name = os.path.basename(configured_path).lower()
    if configured_name in {"gh", "gh.exe"} and direct_path is not None:
        return direct_path
    return configured_path


def _build_prompt_command(copilot_cli_path: str, model: str) -> list[str]:
    command = [
        resolve_copilot_cli_path(copilot_cli_path),
        "--output-format",
        "text",
        "--stream",
        "off",
        "--allow-all-tools",
        "--allow-all-paths",
        "--no-ask-user",
    ]
    if model:
        command.extend(["--model", model])
    return command


def _prepare_copilot_environment(env: dict[str, str]) -> dict[str, str]:
    prepared_env = dict(env)
    current_path = prepared_env.get("PATH", "")
    if shutil.which("pwsh.exe", path=current_path):
        return prepared_env

    powershell_path = shutil.which("powershell.exe", path=current_path)
    if powershell_path is None:
        return prepared_env

    shim_dir = Path.home() / ".relay" / "bin"
    shim_dir.mkdir(parents=True, exist_ok=True)
    shim_path = _ensure_pwsh_compat_shim(shim_dir, powershell_path)
    if shim_path is not None:
        prepared_env["PATH"] = str(shim_dir) + os.pathsep + current_path
    return prepared_env


def _ensure_pwsh_compat_shim(shim_dir: Path, powershell_path: str) -> Path | None:
    shim_path = shim_dir / "pwsh.exe"
    if shim_path.exists():
        return shim_path

    dotnet_path = shutil.which("dotnet")
    if dotnet_path is None:
        return None

    project_dir = shim_dir / "pwsh-shim"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "pwsh-shim.csproj").write_text(
        textwrap.dedent(
            """\
            <Project Sdk="Microsoft.NET.Sdk">
              <PropertyGroup>
                <OutputType>Exe</OutputType>
                <TargetFramework>net10.0</TargetFramework>
                <ImplicitUsings>enable</ImplicitUsings>
                <Nullable>enable</Nullable>
              </PropertyGroup>
            </Project>
            """
        ),
        encoding="utf-8",
    )
    (project_dir / "Program.cs").write_text(
        textwrap.dedent(
            f"""\
            using System.Diagnostics;

            var forwardedArgs = args.Length == 1 && args[0] == "--version"
                ? new[] {{ "-NoLogo", "-NoProfile", "-Command", "$PSVersionTable.PSVersion.ToString()" }}
                : args;

            var startInfo = new ProcessStartInfo
            {{
                FileName = @"{powershell_path}",
                UseShellExecute = false,
            }};

            foreach (var argument in forwardedArgs)
            {{
                startInfo.ArgumentList.Add(argument);
            }}

            using var process = Process.Start(startInfo);
            if (process is null)
            {{
                Console.Error.WriteLine("Failed to start Windows PowerShell.");
                return 1;
            }}

            process.WaitForExit();
            return process.ExitCode;
            """
        ),
        encoding="utf-8",
    )

    publish_dir = project_dir / "publish"
    result = subprocess.run(
        [
            dotnet_path,
            "publish",
            str(project_dir / "pwsh-shim.csproj"),
            "-c",
            "Release",
            "-o",
            str(publish_dir),
            "-p:UseAppHost=true",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None

    published_shim = publish_dir / "pwsh-shim.exe"
    if not published_shim.exists():
        return None
    shutil.copy2(published_shim, shim_path)
    return shim_path


def build_exploration_command(copilot_cli_path: str, model: str) -> list[str]:
    return _build_prompt_command(copilot_cli_path, model)


def build_agent_command(copilot_cli_path: str, model: str) -> list[str]:
    return _build_prompt_command(copilot_cli_path, model)


class CopilotSession:
    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._cmd: list[str] | None = None
        self._cwd: str | None = None
        self._env: dict[str, str] | None = None
        self._stdout_lock = asyncio.Lock()
        self._history: list[tuple[str, str]] = []
        self._last_response_exit_code: int | None = None

    async def start(self, cmd: list[str], cwd: str, env: dict | None = None) -> None:
        self._cmd = cmd
        self._cwd = cwd
        # The Copilot CLI relies on the inherited environment for PATH,
        # credential lookup, and its persisted login state. Merge overrides into
        # the parent environment instead of replacing it with a mostly empty map.
        merged_env = os.environ.copy()
        if env is not None:
            merged_env.update({str(key): str(value) for key, value in env.items()})
        self._env = _prepare_copilot_environment(merged_env)
        worker_command = [sys.executable, "-m", "relay.copilot.session_worker", json.dumps(cmd)]
        self._process = await asyncio.create_subprocess_exec(
            *worker_command,
            cwd=cwd,
            env=self._env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

    async def _ensure_started(self) -> asyncio.subprocess.Process:
        if self._process is None:
            raise RuntimeError("CopilotSession has not been started.")
        return self._process

    def _build_followup_prompt(self, prompt: str) -> str:
        if not self._history:
            return prompt
        conversation_lines = [
            "Continue the existing Relay Copilot conversation.",
            "Use the prior turns as context and answer only the latest user request.",
            "",
            "Previous conversation:",
        ]
        for user_prompt, assistant_reply in self._history:
            conversation_lines.extend(
                [
                    "User:",
                    user_prompt,
                    "",
                    "Assistant:",
                    assistant_reply,
                    "",
                ]
            )
        conversation_lines.extend(["Latest user request:", prompt])
        return "\n".join(conversation_lines)

    async def _write_prompt(self, prompt: str) -> None:
        process = await self._ensure_started()
        if process.stdin is None:
            raise RuntimeError("CopilotSession stdin is not available.")
        process.stdin.write(json.dumps({"type": "prompt", "prompt": prompt}).encode("utf-8"))
        process.stdin.write(b"\n")
        await process.stdin.drain()

    async def _stream_output(self) -> AsyncIterator[str]:
        process = await self._ensure_started()
        if process.stdout is None:
            raise RuntimeError("CopilotSession stdout is not available.")
        async with self._stdout_lock:
            self._last_response_exit_code = None
            while True:
                line = await process.stdout.readline()
                if not line:
                    if process.returncode is not None:
                        break
                    continue
                try:
                    payload = json.loads(line.decode("utf-8", errors="replace"))
                except json.JSONDecodeError as exc:
                    raise RuntimeError(f"Invalid response from Copilot session worker: {exc}") from exc
                event_type = payload.get("type")
                if event_type == "chunk":
                    yield str(payload.get("data", ""))
                    continue
                if event_type == "done":
                    self._last_response_exit_code = int(payload.get("exit_code", 1))
                    break
                if event_type == "error":
                    message = str(payload.get("message", "Copilot session worker failed."))
                    raise RuntimeError(message)
                raise RuntimeError(f"Unknown Copilot session worker event: {event_type}")
            if self._last_response_exit_code is None:
                raise RuntimeError("Copilot session worker exited unexpectedly.")

    async def _run_prompt(self, prompt: str) -> AsyncIterator[str]:
        response_chunks: list[str] = []
        await self._write_prompt(prompt)
        async for chunk in self._stream_output():
            response_chunks.append(chunk)
            yield chunk
        response_text = "".join(response_chunks)
        if self._last_response_exit_code != 0:
            message = response_text.strip() or f"Copilot CLI exited with code {self._last_response_exit_code}."
            raise RuntimeError(message)
        self._history.append((prompt, response_text))

    async def send(self, prompt: str) -> AsyncIterator[str]:
        async for chunk in self._run_prompt(prompt):
            yield chunk

    async def send_followup(self, prompt: str) -> AsyncIterator[str]:
        if not self.is_alive():
            if self._cmd is None or self._cwd is None:
                raise RuntimeError("Cannot recover a CopilotSession without prior start metadata.")
            await self.start(self._cmd, self._cwd, self._env)
        async for chunk in self._run_prompt(self._build_followup_prompt(prompt)):
            yield chunk

    def is_alive(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def kill(self) -> None:
        if self._process is None or self._process.returncode is not None:
            return
        # Kill the wrapper and any prompt subprocesses it spawned so cancelled
        # workflows do not leave background Copilot commands running.
        try:
            parent = psutil.Process(self._process.pid)
            children = parent.children(recursive=True)
            for child in reversed(children):
                child.kill()
            parent.kill()
        except (psutil.Error, ProcessLookupError):
            self._process.kill()
        await self._process.wait()

    async def wait(self) -> int:
        process = await self._ensure_started()
        return await process.wait()

    @property
    def pid(self) -> int | None:
        if self._process is None:
            return None
        return self._process.pid

    @property
    def process(self) -> asyncio.subprocess.Process | None:
        return self._process

    @property
    def last_response_exit_code(self) -> int | None:
        return self._last_response_exit_code
