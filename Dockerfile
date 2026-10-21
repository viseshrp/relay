# syntax=docker/dockerfile:1.7

ARG NODE_IMAGE=node:24.21.0-trixie-slim
ARG PYTHON_IMAGE=python:3.14-slim-trixie

FROM ${NODE_IMAGE} AS node

FROM ${PYTHON_IMAGE} AS builder

ARG DEBIAN_FRONTEND=noninteractive
ARG UV_VERSION=0.13.4

ENV PATH=/opt/relay/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
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

# Declared late so a new version reuses the dependency layers above.
ARG VERSION=0.0.0
ENV SETUPTOOLS_SCM_PRETEND_VERSION=${VERSION}

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
ARG RELAY_UID=1000
ARG RELAY_GID=1000

ENV HOME=/home/relay \
    PATH=/usr/local/sbin:/usr/local/bin:/opt/relay/venv/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    XDG_CONFIG_HOME=/home/relay/.config \
    XDG_DATA_HOME=/home/relay/.local/share \
    XDG_STATE_HOME=/home/relay/.local/state

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        git \
        procps \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/relay/venv /opt/relay/venv

COPY --chmod=0755 scripts/container_entrypoint.py /usr/local/bin/relay

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

ARG VERSION=0.0.0
ARG VCS_REF=unknown

LABEL org.opencontainers.image.title="Relay" \
      org.opencontainers.image.description="Local workflow orchestration for coding agents." \
      org.opencontainers.image.source="https://github.com/viseshrp/relay" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}"

STOPSIGNAL SIGTERM

ENTRYPOINT ["relay"]
CMD ["--help"]
