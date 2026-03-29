from __future__ import annotations

import asyncio
import json
from pathlib import Path

import aiofiles


async def tail_file(path: str):
    """Async generator that yields new lines as they are appended to a file."""
    async with aiofiles.open(path, mode="r") as f:
        await f.seek(0, 2)
        while True:
            line = await f.readline()
            if line:
                yield line
            else:
                await asyncio.sleep(0.1)


async def tail_jsonl(path: str):
    async for line in tail_file(path):
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def ensure_file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("", encoding="utf-8")
    return path
