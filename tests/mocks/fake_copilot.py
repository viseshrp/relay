from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator


class FakeCopilotSession:
    def __init__(
        self,
        responses: list[str],
        *,
        chunk_size: int = 20,
        delay: float = 0.01,
        fail_on_attempt: list[int] | None = None,
    ) -> None:
        self._responses = list(responses)
        self._chunk_size = chunk_size
        self._delay = delay
        self._fail_on_attempt = set(fail_on_attempt or [])
        self._attempt = 0
        self._alive = False
        self._pid = 99999
        self._exit_code = 0

    async def start(self, cmd: list[str], cwd: str, env: dict | None = None) -> None:
        _ = (cmd, cwd, env)
        self._alive = True

    async def _emit(self) -> AsyncIterator[str]:
        self._attempt += 1
        if self._attempt in self._fail_on_attempt:
            self._alive = False
            self._exit_code = 1
            raise RuntimeError(f"fake copilot failure on attempt {self._attempt}")

        if not self._responses:
            self._alive = False
            return

        response = self._responses.pop(0)
        for index in range(0, len(response), self._chunk_size):
            await asyncio.sleep(self._delay)
            yield response[index : index + self._chunk_size]
        self._exit_code = 0
        if not self._responses:
            self._alive = False

    async def send(self, prompt: str) -> AsyncIterator[str]:
        _ = prompt
        async for chunk in self._emit():
            yield chunk

    async def send_followup(self, prompt: str) -> AsyncIterator[str]:
        _ = prompt
        if not self.is_alive() and self._responses:
            self._alive = True
        async for chunk in self._emit():
            yield chunk

    def is_alive(self) -> bool:
        return self._alive and bool(self._responses or self._attempt == 0)

    async def kill(self) -> None:
        self._alive = False
        self._exit_code = -9

    async def wait(self) -> int:
        return self._exit_code

    @property
    def pid(self) -> int | None:
        return self._pid if self._alive else None
