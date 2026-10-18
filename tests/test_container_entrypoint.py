"""The container `relay` command bridges only Docker's published-port traffic."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
import contextlib
import gc
import os
from pathlib import Path
import signal
import socket
import subprocess

import pytest

from relay.config import RelayConfig
from scripts import container_entrypoint
from scripts.container_entrypoint import (
    UpInvocation,
    default_gateway,
    forward_connection,
    parse_up_invocation,
    run_up,
    start_bridge,
)


@pytest.mark.parametrize(
    "argv",
    [["init"], ["--help"], ["up", "--help"], ["-v"], ["doctor", "--json"], []],
)
def test_non_up_commands_pass_through(argv: list[str]) -> None:
    assert parse_up_invocation(argv, RelayConfig) is None


def test_up_uses_saved_host_and_port_when_flags_are_defaults() -> None:
    invocation = parse_up_invocation(["up"], lambda: RelayConfig(host="::1", port=9000))

    assert invocation == UpInvocation("::1", 9000, ("up", "--no-browser"))


@pytest.mark.parametrize(
    "argv",
    [
        ["--json", "up", "--port", "9100", "--host", "localhost"],
        ["up", "--port=9100", "--host=localhost", "--no-browser"],
    ],
)
def test_explicit_flags_override_saved_settings(argv: list[str]) -> None:
    invocation = parse_up_invocation(argv, lambda: RelayConfig(port=9000))

    assert invocation is not None
    assert (invocation.host, invocation.port) == ("localhost", 9100)
    assert invocation.argv.count("--no-browser") == 1


def test_default_gateway_reads_the_default_route(tmp_path: Path) -> None:
    table = tmp_path / "route"
    table.write_text(
        "Iface\tDestination\tGateway\tFlags\n"
        "eth0\t000011AC\t00000000\t0001\n"
        "eth0\t00000000\t010011AC\t0003\n",
        encoding="ascii",
    )

    assert default_gateway(table) == "172.17.0.1"
    assert default_gateway(tmp_path / "missing") is None


async def _read_reply(reader: asyncio.StreamReader) -> bytes:
    try:
        return await reader.read()
    except ConnectionResetError:
        # A refused peer may see a reset because its request was never read.
        return b""


async def _exchange_through_bridge(gateway: str) -> tuple[bytes, list[bytes]]:
    received: list[bytes] = []
    arrived = asyncio.Event()
    release = asyncio.Event()

    async def reply(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        received.append(await reader.read())
        arrived.set()
        await release.wait()
        writer.write(b"got:" + received[-1])
        await writer.drain()
        writer.close()

    upstream = await asyncio.start_server(reply, "127.0.0.1", 0)
    upstream_port = upstream.sockets[0].getsockname()[1]
    bridge = await asyncio.start_server(
        lambda reader, writer: forward_connection(
            reader, writer, "127.0.0.1", upstream_port, gateway
        ),
        "127.0.0.1",
        0,
    )
    bridge_port = bridge.sockets[0].getsockname()[1]
    async with upstream, bridge:
        reader, writer = await asyncio.open_connection("127.0.0.1", bridge_port)
        writer.write(b"ping")
        writer.write_eof()
        reply_task = asyncio.create_task(_read_reply(reader))
        arrival = asyncio.create_task(arrived.wait())
        await asyncio.wait({reply_task, arrival}, return_when=asyncio.FIRST_COMPLETED)
        arrival.cancel()
        # The bridge now waits only on Relay's reply; it must survive a collection.
        gc.collect()
        release.set()
        response = await asyncio.wait_for(reply_task, timeout=5)
        writer.close()
        with contextlib.suppress(ConnectionResetError):
            await writer.wait_closed()
    return response, received


def test_gateway_connections_reach_relay_and_keep_half_close() -> None:
    reply, received = asyncio.run(_exchange_through_bridge("127.0.0.1"))

    assert received == [b"ping"]
    assert reply == b"got:ping"


def test_connections_from_other_peers_are_refused() -> None:
    reply, received = asyncio.run(_exchange_through_bridge("192.0.2.1"))

    assert reply == b""
    assert received == []


def test_bridge_bind_failure_is_reported(capsys: pytest.CaptureFixture[str]) -> None:
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        port = occupied.getsockname()[1]

        server = asyncio.run(start_bridge("127.0.0.1", port, "127.0.0.1", "127.0.0.1"))

    assert server is None
    assert f"127.0.0.1:{port}" in capsys.readouterr().err


class _FinishedProcess:
    def __init__(self, argv: Sequence[str], **options: object) -> None:
        self.argv = list(argv)
        self.options = options
        self.signals: list[int] = []

    def wait(self) -> int:
        return 0

    def poll(self) -> int | None:
        return 0

    def send_signal(self, signum: int) -> None:
        self.signals.append(signum)


@pytest.mark.skipif(os.name == "nt", reason="the container entry point runs on Linux")
def test_relay_runs_in_its_own_session(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[_FinishedProcess] = []

    def popen(argv: Sequence[str], **options: object) -> _FinishedProcess:
        started.append(_FinishedProcess(argv, **options))
        return started[-1]

    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(container_entrypoint, "container_address", lambda: None)
    previous = signal.getsignal(signal.SIGINT)

    status = asyncio.run(run_up(UpInvocation("127.0.0.1", 7845, ("up", "--no-browser"))))

    assert status == 0
    assert started[0].argv == [container_entrypoint.REAL_RELAY, "up", "--no-browser"]
    # Terminal Ctrl+C must reach only the entry point, which forwards it once.
    assert started[0].options == {"start_new_session": True}
    assert signal.getsignal(signal.SIGINT) == previous
