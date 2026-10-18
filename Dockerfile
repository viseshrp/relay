# syntax=docker/dockerfile:1.7

ARG NODE_IMAGE=node:24.21.0-trixie-slim
ARG PYTHON_IMAGE=python:3.14-slim-trixie

FROM ${NODE_IMAGE} AS node

FROM ${PYTHON_IMAGE} AS builder

ARG DEBIAN_FRONTEND=noninteractive
ARG UV_VERSION=0.13.0
ARG VERSION=0.0.0

ENV PATH=/opt/relay/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SETUPTOOLS_SCM_PRETEND_VERSION=${VERSION} \
    UV_NO_CACHE=1

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

RUN python3 -m venv /opt/build-venv \
    && /opt/build-venv/bin/python -m pip install "uv==${UV_VERSION}" \
    && python3 -m venv /opt/relay/venv

WORKDIR /build

COPY pyproject.toml uv.lock ./

RUN mkdir -p /dist \
    && /opt/build-venv/bin/uv export --frozen --no-dev --no-emit-project --output-file /dist/requirements.txt \
    && /opt/relay/venv/bin/python -m pip install --require-hashes -r /dist/requirements.txt

COPY hatch_build.py README.md LICENSE CHANGELOG.md ./
COPY docs/getting-started.md docs/coming-from-github-actions.md docs/keyboard-shortcuts.md docs/
COPY frontend/ frontend/
COPY relay/ relay/
COPY scripts/check_distribution_contents.py scripts/check_distribution_contents.py

RUN python3 - <<'PY'
import os
from pathlib import Path
import re

version = os.environ["SETUPTOOLS_SCM_PRETEND_VERSION"]
match = re.fullmatch(r"(.+)\.dev([0-9]+)", version)
if match is not None:
    pyproject = Path("pyproject.toml")
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8")
        .replace('validate-bump = true', 'validate-bump = false', 1)
        .replace('timestamp_format = "long"', f'timestamp_format = "{match.group(2)}"', 1),
        encoding="utf-8",
    )
PY
RUN /opt/build-venv/bin/uv build --wheel --out-dir /dist \
    && python3 scripts/check_distribution_contents.py /dist/relay_app-*.whl \
    && /opt/relay/venv/bin/python -m pip install --no-deps /dist/relay_app-*.whl \
    && /opt/relay/venv/bin/python -m pip check \
    && EXPECTED_VERSION="${VERSION}" \
        /opt/relay/venv/bin/python -c "import os; from importlib.metadata import version; assert version('relay-app') == os.environ['EXPECTED_VERSION']"


FROM ${PYTHON_IMAGE} AS runtime

ARG DEBIAN_FRONTEND=noninteractive
ARG VERSION=0.0.0
ARG VCS_REF=unknown
ARG RELAY_UID=1000
ARG RELAY_GID=1000

ENV HOME=/home/relay \
    PATH=/usr/local/sbin:/usr/local/bin:/opt/relay/venv/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    XDG_CONFIG_HOME=/home/relay/.config \
    XDG_DATA_HOME=/home/relay/.local/share \
    XDG_STATE_HOME=/home/relay/.local/state

LABEL org.opencontainers.image.title="Relay" \
      org.opencontainers.image.description="Local workflow orchestration for coding agents." \
      org.opencontainers.image.source="https://github.com/viseshrp/relay" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}"

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        git \
        procps \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/relay/venv /opt/relay/venv

RUN cat <<'PY' > /usr/local/bin/relay \
    && chmod 0755 /usr/local/bin/relay
#!/opt/relay/venv/bin/python
from __future__ import annotations

import asyncio
import contextlib
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys

REAL_RELAY = "/opt/relay/venv/bin/relay"


def parse_up_invocation(argv: list[str]) -> tuple[bool, int, list[str]]:
    if any(flag in argv for flag in ("-h", "--help", "-v", "--version")):
        return False, 7845, argv
    idx = 0
    while idx < len(argv) and argv[idx].startswith("-"):
        idx += 1
    if idx >= len(argv) or argv[idx] != "up":
        return False, 7845, argv

    port = 7845
    has_browser_flag = False
    sub_args = argv[idx + 1 :]
    for i, token in enumerate(sub_args):
        if token in ("--browser", "--no-browser"):
            has_browser_flag = True
        elif token == "--port" and i + 1 < len(sub_args):
            with contextlib.suppress(ValueError):
                port = int(sub_args[i + 1])
        elif token.startswith("--port="):
            with contextlib.suppress(ValueError):
                port = int(token.split("=", 1)[1])

    forwarded = list(argv)
    if not has_browser_flag:
        forwarded.append("--no-browser")
    return True, port, forwarded


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while chunk := await reader.read(65536):
            writer.write(chunk)
            await writer.drain()
    except OSError:
        pass
    finally:
        with contextlib.suppress(Exception):
            writer.close()
            await writer.wait_closed()


async def forward_connection(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    port: int,
) -> None:
    try:
        upstream_reader, upstream_writer = await asyncio.open_connection(
            "127.0.0.1", port
        )
    except OSError:
        client_writer.close()
        with contextlib.suppress(Exception):
            await client_writer.wait_closed()
        return
    await asyncio.gather(
        pipe(client_reader, upstream_writer),
        pipe(upstream_reader, client_writer),
    )


async def run_up(port: int, forwarded_args: list[str]) -> int:
    if Path("/workspace/.git").exists():
        subprocess.run(
            ["git", "config", "--global", "--add", "safe.directory", "/workspace"],
            check=False,
        )
    process = subprocess.Popen([REAL_RELAY, *forwarded_args])
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(
            sig,
            lambda s=sig: process.send_signal(s) if process.poll() is None else None,
        )

    server = None
    with contextlib.suppress(OSError):
        container_ip = socket.gethostbyname(socket.gethostname())
        if container_ip and not container_ip.startswith("127."):
            server = await asyncio.start_server(
                lambda r, w: forward_connection(r, w, port),
                host=container_ip,
                port=port,
            )

    try:
        return await asyncio.to_thread(process.wait)
    finally:
        if server is not None:
            server.close()
            await server.wait_closed()


def main() -> int:
    is_up, port, forwarded = parse_up_invocation(sys.argv[1:])
    if not is_up:
        os.execv(REAL_RELAY, [REAL_RELAY, *sys.argv[1:]])
    return asyncio.run(run_up(port, forwarded))


if __name__ == "__main__":
    raise SystemExit(main())
PY

RUN set -eux; \
    test "${RELAY_UID}" -ge 1000; \
    test "${RELAY_GID}" -ge 1000; \
    existing_group="$(getent group "${RELAY_GID}" | cut -d: -f1 || true)"; \
    if [ -z "${existing_group}" ]; then \
        groupadd --gid "${RELAY_GID}" relay; \
    elif [ "${existing_group}" != "relay" ]; then \
        groupmod --new-name relay "${existing_group}"; \
    fi; \
    existing_user="$(getent passwd "${RELAY_UID}" | cut -d: -f1 || true)"; \
    if [ -z "${existing_user}" ]; then \
        useradd \
            --create-home \
            --gid relay \
            --home-dir /home/relay \
            --shell /usr/sbin/nologin \
            --uid "${RELAY_UID}" \
            relay; \
    elif [ "${existing_user}" != "relay" ]; then \
        usermod \
            --gid relay \
            --home /home/relay \
            --login relay \
            --move-home \
            --shell /usr/sbin/nologin \
            "${existing_user}"; \
    fi; \
    install \
        --directory \
        --group relay \
        --mode 0700 \
        --owner relay \
        /home/relay/.config/relay \
        /home/relay/.local/share/relay \
        /home/relay/.local/state/relay \
        /home/relay/.local/state/relay/log; \
    install \
        --directory \
        --group relay \
        --mode 0755 \
        --owner relay \
        /workspace

VOLUME ["/home/relay/.config/relay", "/home/relay/.local/share/relay", "/home/relay/.local/state/relay", "/workspace"]

EXPOSE 7845

USER relay:relay
WORKDIR /workspace
RUN git config --global --add safe.directory /workspace

STOPSIGNAL SIGTERM

ENTRYPOINT ["relay"]
CMD ["--help"]
