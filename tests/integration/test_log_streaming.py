import asyncio

import pytest

from relay.realtime.log_tailer import ensure_file, tail_file


@pytest.mark.asyncio
async def test_tail_file_reads_new_lines(tmp_path) -> None:
    log_path = ensure_file(tmp_path / "test.log")
    generator = tail_file(str(log_path))

    async def writer() -> None:
        await asyncio.sleep(0.2)
        log_path.write_text("hello\n", encoding="utf-8")

    writer_task = asyncio.create_task(writer())
    line = await asyncio.wait_for(generator.__anext__(), timeout=2)
    await writer_task
    assert line == "hello\n"
