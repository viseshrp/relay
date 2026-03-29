from __future__ import annotations

import asyncio
from contextlib import suppress

import typer
import uvicorn

from relay.api.app import create_app
from relay.config import get_settings
from relay.worker.main import run_worker

app = typer.Typer(add_completion=False)


async def _serve() -> None:
    settings = get_settings()
    application = create_app(settings)
    config = uvicorn.Config(application, host=settings.host, port=settings.port, lifespan="on")
    server = uvicorn.Server(config)
    await server.serve()


@app.command()
def serve() -> None:
    asyncio.run(_serve())


@app.command()
def worker() -> None:
    asyncio.run(run_worker())


@app.command()
def dev() -> None:
    async def _run() -> None:
        worker_task = asyncio.create_task(run_worker())
        try:
            await _serve()
        finally:
            worker_task.cancel()
            with suppress(asyncio.CancelledError):
                await worker_task

    asyncio.run(_run())
