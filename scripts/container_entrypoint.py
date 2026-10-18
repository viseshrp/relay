#!/opt/relay/venv/bin/python
"""Container `relay` command that lets published ports reach Relay's loopback server."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
import contextlib
from dataclasses import dataclass
import os
from pathlib import Path
import signal
import socket
import struct
import subprocess
import sys

from relay.config import RelayConfig, load_config
from relay.errors import ConfigError

REAL_RELAY = "/opt/relay/venv/bin/relay"
ROUTE_TABLE = Path("/proc/net/route")
_PASSTHROUGH_FLAGS = frozenset({"-h", "--help", "-v", "--version"})
_CHUNK_BYTES = 65_536


@dataclass(frozen=True, slots=True)
class UpInvocation:
    """The effective `relay up` address and the arguments forwarded to it."""

    host: str
    port: int
    argv: tuple[str, ...]


def _stored_config() -> RelayConfig:
    try:
        return load_config()
    except ConfigError:
        # `relay up` reports invalid settings itself; the bridge just uses defaults.
        return RelayConfig()


def parse_up_invocation(
    argv: Sequence[str], load: Callable[[], RelayConfig] = _stored_config
) -> UpInvocation | None:
    """Return the `relay up` address, honoring saved settings like the CLI does."""
    if any(token in _PASSTHROUGH_FLAGS for token in argv):
        return None
    index = 0
    while index < len(argv) and argv[index].startswith("-"):
        index += 1
    if index >= len(argv) or argv[index] != "up":
        return None

    options = argv[index + 1 :]
    explicit: dict[str, str] = {}
    for position, token in enumerate(options):
        name, separator, inline = token.partition("=")
        if name not in {"--host", "--port"}:
            continue
        if separator:
            explicit[name] = inline
        elif position + 1 < len(options):
            explicit[name] = options[position + 1]

    stored = load()
    port = stored.port
    if "--port" in explicit:
        with contextlib.suppress(ValueError):
            port = int(explicit["--port"])
    forwarded = [*argv] if "--no-browser" in options else [*argv, "--no-browser"]
    return UpInvocation(explicit.get("--host", stored.host), port, tuple(forwarded))


def default_gateway(route_table: Path = ROUTE_TABLE) -> str | None:
    """Return the IPv4 default gateway, where Docker delivers published ports."""
    try:
        rows = route_table.read_text(encoding="ascii").splitlines()[1:]
    except OSError:
        return None
    for row in rows:
        fields = row.split()
        if len(fields) > 2 and fields[1] == "00000000":
            return socket.inet_ntoa(struct.pack("<L", int(fields[2], 16)))
    return None


def container_address() -> str | None:
    """Return the container interface address, or None when only loopback exists."""
    try:
        address = socket.gethostbyname(socket.gethostname())
    except OSError:
        return None
    return None if address.startswith("127.") else address


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Copy one direction and pass its end of stream on as a half-close."""
    try:
        while chunk := await reader.read(_CHUNK_BYTES):
            writer.write(chunk)
            await writer.drain()
        if writer.can_write_eof():
            writer.write_eof()
    except OSError:
        # A reset ends both directions: closing this side unblocks the other copy.
        writer.close()


async def _close(writer: asyncio.StreamWriter) -> None:
    writer.close()
    with contextlib.suppress(OSError):
        await writer.wait_closed()


async def forward_connection(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    host: str,
    port: int,
    gateway: str,
) -> None:
    """Relay one connection from the Docker gateway to Relay's loopback server."""
    peer = client_writer.get_extra_info("peername")
    # Other containers on the network connect from their own addresses; only the
    # gateway carries the host's published port.
    if not peer or peer[0] != gateway:
        await _close(client_writer)
        return
    try:
        upstream_reader, upstream_writer = await asyncio.open_connection(host, port)
    except OSError:
        await _close(client_writer)
        return
    try:
        await asyncio.gather(
            pipe(client_reader, upstream_writer),
            pipe(upstream_reader, client_writer),
        )
    finally:
        await _close(upstream_writer)
        await _close(client_writer)


async def start_bridge(host: str, port: int, address: str, gateway: str) -> asyncio.Server | None:
    """Listen on the container interface, reporting rather than hiding failures."""
    try:
        return await asyncio.start_server(
            lambda reader, writer: forward_connection(reader, writer, host, port, gateway),
            host=address,
            port=port,
        )
    except OSError as error:
        print(
            f"Relay cannot accept published-port connections on {address}:{port}: {error}",
            file=sys.stderr,
        )
        return None


def _forward_signal(process: subprocess.Popen[bytes], signum: signal.Signals) -> None:
    if process.poll() is None:
        process.send_signal(signum)


async def run_up(invocation: UpInvocation) -> int:
    """Run `relay up` and bridge the container interface until it exits."""
    # A separate session keeps a terminal Ctrl+C from reaching Relay directly, so
    # the forwarded signal is the only one it receives during orderly shutdown.
    process = subprocess.Popen(  # noqa: S603 - fixed executable with an argument vector
        [REAL_RELAY, *invocation.argv], start_new_session=True
    )
    loop = asyncio.get_running_loop()
    for stop_signal in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(stop_signal, _forward_signal, process, stop_signal)

    server = None
    address = container_address()
    gateway = default_gateway()
    if address is not None and gateway is not None:
        server = await start_bridge(invocation.host, invocation.port, address, gateway)
    try:
        return await asyncio.to_thread(process.wait)
    finally:
        if server is not None:
            server.close()
            await server.wait_closed()


def main(argv: Sequence[str] | None = None) -> int:
    """Bridge `relay up`; run every other command as the installed `relay`."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    invocation = parse_up_invocation(arguments)
    if invocation is None:
        os.execv(REAL_RELAY, [REAL_RELAY, *arguments])  # noqa: S606 - fixed executable
    return asyncio.run(run_up(invocation))


if __name__ == "__main__":
    raise SystemExit(main())
