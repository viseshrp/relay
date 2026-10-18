#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/docker.sh <command>

Commands:
  build             Build the Relay container image locally
  smoke             Run end-to-end smoke checks against DOCKER_IMAGE
  up                Start Relay in Docker on 127.0.0.1:DOCKER_PORT
  push              Build and push a multi-arch image to GHCR
  push-digest       Push a single-platform image by digest to GHCR
  publish-manifest  Create and verify a multi-arch GHCR manifest from digests
EOF
}

resolve_version() {
  if [[ -n "${DOCKER_VERSION:-}" ]]; then
    printf '%s\n' "$DOCKER_VERSION"
  elif command -v uv >/dev/null 2>&1; then
    uv run hatch version
  else
    python3 -c 'import pathlib, re; print(re.search(r"^version = \"([^\"]+)\"", pathlib.Path("pyproject.toml").read_text(), re.M).group(1))'
  fi
}

resolve_revision() {
  if [[ -n "${DOCKER_VCS_REF:-}" ]]; then
    printf '%s\n' "$DOCKER_VCS_REF"
  else
    git rev-parse HEAD
  fi
}

cmd_build() {
  local image="${DOCKER_IMAGE:-ghcr.io/viseshrp/relay:local}"
  local version
  version="$(resolve_version)"
  local revision
  revision="$(resolve_revision)"
  local created="${DOCKER_CREATED:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}"

  local args=(
    --load
    --build-arg "VERSION=${version}"
    --build-arg "VCS_REF=${revision}"
    --label "org.opencontainers.image.created=${created}"
    --tag "${image}"
  )
  if [[ -n "${DOCKER_PLATFORM:-}" ]]; then
    args+=(--platform "${DOCKER_PLATFORM}")
  fi
  if [[ "${DOCKER_NO_CACHE:-0}" == "1" ]]; then
    args+=(--pull --no-cache)
  fi

  echo "🐳 Building ${image} (version=${version}, revision=${revision:0:12})..."
  docker buildx build "${args[@]}" .
}

cmd_smoke() {
  local image="${DOCKER_IMAGE:-ghcr.io/viseshrp/relay:local}"
  if [[ "${image}" == "ghcr.io/viseshrp/relay:local" ]] && ! docker image inspect "${image}" >/dev/null 2>&1; then
    cmd_build
  fi

  local expected_revision
  expected_revision="$(resolve_revision)"
  local expected_version="${DOCKER_VERSION:-}"
  if [[ -z "${expected_version}" ]]; then
    expected_version="$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.version" }}' "${image}")"
  fi
  local expected_arch="${EXPECTED_ARCH:-}"

  echo "🧪 Smoke-testing ${image} (version=${expected_version})..."
  local actual_version
  actual_version="$(docker run --rm "${image}" --version)"
  test "${actual_version}" = "relay, version ${expected_version}"

  docker run --rm "${image}" --help >/dev/null

  local actual_revision
  actual_revision="$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "${image}")"
  test "${actual_revision}" = "${expected_revision}"

  local label_version
  label_version="$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.version" }}' "${image}")"
  test "${label_version}" = "${expected_version}"

  local actual_user
  actual_user="$(docker image inspect --format '{{ .Config.User }}' "${image}")"
  test "${actual_user}" = "relay:relay"

  docker run --rm --entrypoint /bin/sh "${image}" -ec '
    test "$(id -u)" -ne 0
    if [ -n "$1" ]; then
      test "$(uname -m)" = "$1"
    fi
    command -v git >/dev/null
    command -v ps >/dev/null
    ! command -v node >/dev/null 2>&1
    ! command -v npm >/dev/null 2>&1
    repo="$(mktemp -d)"
    cd "$repo"
    git init -q
    git config user.name "Relay Container Smoke"
    git config user.email "smoke@example.invalid"
    git commit --allow-empty -q -m "initial"
    relay init >/dev/null
    test -f .relay/workflows/workflow.yaml
    relay up --no-browser --no-login >"$repo/up.log" 2>&1 &
    up_pid="$!"
    python - <<PY
import time
import urllib.request

deadline = time.monotonic() + 20.0
while time.monotonic() < deadline:
    try:
        with urllib.request.urlopen("http://127.0.0.1:7845/api/auth", timeout=1.0) as auth:
            if auth.status == 200:
                break
    except Exception:
        time.sleep(0.1)
else:
    raise SystemExit("Relay web API did not become ready in container smoke test")

with urllib.request.urlopen("http://127.0.0.1:7845/", timeout=2.0) as root:
    body = root.read().decode("utf-8")
    assert root.status == 200
    assert "<div id=\"root\"></div>" in body
PY
    kill -TERM "$up_pid"
    wait "$up_pid"
    grep -F "Relay stopped cleanly." "$repo/up.log" >/dev/null
  ' sh "${expected_arch}"

  echo "✅ Smoke test passed: ${image}"
}

cmd_up() {
  local image="${DOCKER_IMAGE:-ghcr.io/viseshrp/relay:local}"
  local port="${DOCKER_PORT:-7845}"
  local worktree="${DOCKER_WORKTREE:-$(pwd)}"

  if ! docker image inspect "${image}" >/dev/null 2>&1; then
    cmd_build
  fi

  local tty_flags=()
  if [[ -t 0 && -t 1 ]]; then
    tty_flags+=(-it)
  fi

  echo "▶️ Starting Relay container at http://127.0.0.1:${port}/ for ${worktree}..."
  exec docker run --rm ${tty_flags[@]+"${tty_flags[@]}"} \
    --init \
    -p "127.0.0.1:${port}:${port}" \
    -v "${worktree}:/workspace" \
    -v relay-config:/home/relay/.config/relay \
    -v relay-data:/home/relay/.local/share/relay \
    -v relay-state:/home/relay/.local/state/relay \
    --entrypoint python \
    "${image}" \
    -u -c '
import asyncio
import contextlib
import signal
import socket
import subprocess
import sys

port = int(sys.argv[1])
extra_args = sys.argv[2:]


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


async def handle(client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter) -> None:
    try:
        upstream_reader, upstream_writer = await asyncio.open_connection("127.0.0.1", port)
    except OSError:
        client_writer.close()
        with contextlib.suppress(Exception):
            await client_writer.wait_closed()
        return
    await asyncio.gather(
        pipe(client_reader, upstream_writer),
        pipe(upstream_reader, client_writer),
    )


async def main() -> int:
    subprocess.run(["git", "config", "--global", "--add", "safe.directory", "/workspace"], check=False)
    process = subprocess.Popen(["relay", "up", "--host", "127.0.0.1", "--port", str(port), "--no-browser", *extra_args])
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: process.send_signal(s) if process.poll() is None else None)

    server = None
    container_ip = socket.gethostbyname(socket.gethostname())
    if container_ip and not container_ip.startswith("127."):
        server = await asyncio.start_server(handle, host=container_ip, port=port)

    try:
        return await asyncio.to_thread(process.wait)
    finally:
        if server is not None:
            server.close()
            await server.wait_closed()


raise SystemExit(asyncio.run(main()))
' "${port}" ${DOCKER_UP_ARGS:-}
}

cmd_push() {
  local repo="${DOCKER_REPO:-ghcr.io/viseshrp/relay}"
  local version
  version="$(resolve_version)"
  local revision
  revision="$(resolve_revision)"
  local created="${DOCKER_CREATED:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}"
  local platforms="${DOCKER_PLATFORMS:-linux/amd64,linux/arm64}"
  local tags="${TAGS:-nightly}"

  if [[ -n "${GH_TOKEN:-}" ]]; then
    printf '%s\n' "${GH_TOKEN}" | docker login ghcr.io -u "${DOCKER_USERNAME:-viseshrp}" --password-stdin
  elif command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    gh auth token | docker login ghcr.io -u "${DOCKER_USERNAME:-viseshrp}" --password-stdin
  fi

  local tag_args=()
  for tag in ${tags}; do
    tag_args+=(--tag "${repo}:${tag}")
  done

  echo "📤 Building and pushing ${repo} (${tags}) for ${platforms}..."
  docker buildx build \
    --platform "${platforms}" \
    --build-arg "VERSION=${version}" \
    --build-arg "VCS_REF=${revision}" \
    --label "org.opencontainers.image.created=${created}" \
    "${tag_args[@]}" \
    --push \
    .
}

cmd_push_digest() {
  local repo="${DOCKER_REPO:-ghcr.io/viseshrp/relay}"
  local version
  version="$(resolve_version)"
  local revision
  revision="$(resolve_revision)"
  local created="${DOCKER_CREATED:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}"
  local platform="${DOCKER_PLATFORM:?DOCKER_PLATFORM is required}"
  local digests_dir="${DIGESTS_DIR:?DIGESTS_DIR is required}"

  local metadata_file
  metadata_file="$(mktemp)"
  trap 'rm -f "${metadata_file}"' EXIT

  echo "📤 Pushing verified ${platform} image by digest to ${repo}..."
  docker buildx build \
    --platform "${platform}" \
    --build-arg "VERSION=${version}" \
    --build-arg "VCS_REF=${revision}" \
    --label "org.opencontainers.image.created=${created}" \
    --output "type=image,name=${repo},push-by-digest=true,name-canonical=true,push=true" \
    --metadata-file "${metadata_file}" \
    .

  local digest
  digest="$(jq -r '."containerimage.digest"' "${metadata_file}")"
  test -n "${digest}" && test "${digest}" != "null"
  mkdir -p "${digests_dir}"
  touch "${digests_dir}/${digest#sha256:}"
  echo "✅ Pushed ${repo}@${digest}"
}

cmd_publish_manifest() {
  local repo="${DOCKER_REPO:-ghcr.io/viseshrp/relay}"
  local digests_dir="${DIGESTS_DIR:?DIGESTS_DIR is required}"
  local tags="${TAGS:?TAGS is required}"
  local primary_tag="${PRIMARY_TAG:?PRIMARY_TAG is required}"

  local sources=()
  for digest in "${digests_dir}"/*; do
    sources+=("${repo}@sha256:$(basename "${digest}")")
  done
  test "${#sources[@]}" -eq 2

  local tag_args=()
  for tag in ${tags}; do
    tag_args+=(--tag "${repo}:${tag}")
  done

  docker buildx imagetools create "${tag_args[@]}" "${sources[@]}"
  local manifest_file
  manifest_file="$(mktemp)"
  trap 'rm -f "${manifest_file}"' EXIT
  docker buildx imagetools inspect "${repo}:${primary_tag}" --raw > "${manifest_file}"
  jq -e '[.manifests[].platform | select(.os == "linux") | .architecture] | sort == ["amd64", "arm64"]' \
    "${manifest_file}" >/dev/null
  echo "✅ Published multi-arch manifest for ${repo} (${tags})"
}

command_name="${1:-}"
case "${command_name}" in
  build)
    cmd_build
    ;;
  smoke)
    cmd_smoke
    ;;
  up|run)
    cmd_up
    ;;
  push)
    cmd_push
    ;;
  push-digest)
    cmd_push_digest
    ;;
  publish-manifest)
    cmd_publish_manifest
    ;;
  *)
    usage >&2
    exit 1
    ;;
esac
