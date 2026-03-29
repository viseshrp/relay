from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable


SessionFactory = Callable[[], "CopilotSession"]
_session_factory: SessionFactory | None = None


def set_session_factory(factory: SessionFactory | None) -> None:
    global _session_factory
    _session_factory = factory


def create_session() -> "CopilotSession":
    if _session_factory is not None:
        return _session_factory()
    return CopilotSession()


def build_exploration_command(copilot_cli_path: str, model: str) -> list[str]:
    command = [copilot_cli_path, "copilot", "suggest", "--type", "chat"]
    if model:
        command.extend(["--model", model])
    return command


def build_agent_command(copilot_cli_path: str, model: str) -> list[str]:
    command = [copilot_cli_path, "copilot", "agent"]
    if model:
        command.extend(["--model", model])
    return command


class CopilotSession:
    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._cmd: list[str] | None = None
        self._cwd: str | None = None
        self._env: dict[str, str] | None = None
        self._stdout_lock = asyncio.Lock()

    async def start(self, cmd: list[str], cwd: str, env: dict | None = None) -> None:
        self._cmd = cmd
        self._cwd = cwd
        self._env = {str(key): str(value) for key, value in (env or {}).items()}
        self._process = await asyncio.create_subprocess_exec(
            *cmd,
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

    async def _write_prompt(self, prompt: str) -> None:
        process = await self._ensure_started()
        if process.stdin is None:
            raise RuntimeError("CopilotSession stdin is not available.")
        process.stdin.write(prompt.encode("utf-8"))
        process.stdin.write(b"\n")
        await process.stdin.drain()

    async def _stream_output(self) -> AsyncIterator[str]:
        process = await self._ensure_started()
        if process.stdout is None:
            return
        async with self._stdout_lock:
            received_anything = False
            while True:
                try:
                    chunk = await asyncio.wait_for(process.stdout.readline(), timeout=0.3)
                except TimeoutError:
                    if process.returncode is not None:
                        break
                    if received_anything:
                        break
                    continue
                if not chunk:
                    if process.returncode is not None:
                        break
                    continue
                received_anything = True
                yield chunk.decode("utf-8", errors="replace")
                if process.returncode is not None:
                    break

    async def send(self, prompt: str) -> AsyncIterator[str]:
        await self._write_prompt(prompt)
        async for chunk in self._stream_output():
            yield chunk

    async def send_followup(self, prompt: str) -> AsyncIterator[str]:
        if not self.is_alive():
            if self._cmd is None or self._cwd is None:
                raise RuntimeError("Cannot recover a CopilotSession without prior start metadata.")
            await self.start(self._cmd, self._cwd, self._env)
        async for chunk in self.send(prompt):
            yield chunk

    def is_alive(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def kill(self) -> None:
        if self._process is None or self._process.returncode is not None:
            return
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
