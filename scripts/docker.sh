#!/usr/bin/env bash
set -euo pipefail

# Git Bash would otherwise rewrite container paths such as /bin/sh and mount specs.
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'

DEFAULT_IMAGE="ghcr.io/viseshrp/relay:local"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'EOF'
Usage: scripts/docker.sh <command>

Commands:
  build             Build the Relay container image locally
  smoke             Run end-to-end smoke checks against DOCKER_IMAGE
  e2e               Run browser flows against DOCKER_IMAGE and check host Git
  up                Start Relay in Docker on 127.0.0.1:DOCKER_PORT
  push              Smoke-test, then push a multi-arch image to GHCR as TAGS
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
    # The package version comes from Git tags through hatch; label a dev build without it.
    printf '0.0.0.dev%s\n' "$(date -u +%Y%m%d%H%M%S)"
  fi
}

resolve_revision() {
  if [[ -n "${DOCKER_VCS_REF:-}" ]]; then
    printf '%s\n' "$DOCKER_VCS_REF"
  else
    git rev-parse HEAD
  fi
}

expect_equal() {
  if [[ "$2" != "$3" ]]; then
    echo "❌ $1: expected '$3', got '$2'" >&2
    return 1
  fi
}

host_path() {
  # Docker Desktop on Windows takes drive-letter paths; the container keeps /c/...
  if [[ "${OSTYPE:-}" == msys* ]]; then
    (cd "$1" && pwd -W)
  else
    printf '%s\n' "$1"
  fi
}

use_host_ids() {
  if [[ "$(uname -s)" == "Linux" ]]; then
    # Linux bind mounts keep host ownership, so the container user must match it.
    local uid gid
    uid="$(id -u)"
    gid="$(id -g)"
    if ((uid >= 1000)); then
      export DOCKER_UID="${DOCKER_UID:-${uid}}"
    fi
    if ((gid >= 1000)); then
      export DOCKER_GID="${DOCKER_GID:-${gid}}"
    fi
  fi
}

set_relay_mounts() {
  local worktree="$1" data_home="$2" config_volume="$3" state_volume="$4"
  local worktree_source data_source
  worktree_source="$(host_path "${worktree}")"
  data_source="$(host_path "${data_home}")"
  # The repository and Relay's data keep their host paths in the container, so each
  # repository keeps its own project identity and host Git can still resolve the run
  # worktrees that Relay registers in the repository. Docker Desktop reports the
  # mount root as root-owned, so Git needs that path marked safe.
  RELAY_MOUNTS=(
    -v "${worktree_source}:${worktree}"
    -w "${worktree}"
    -e GIT_CONFIG_COUNT=1
    -e GIT_CONFIG_KEY_0=safe.directory
    -e "GIT_CONFIG_VALUE_0=${worktree}"
    -v "${data_source}:${data_home}"
    -e "XDG_DATA_HOME=${data_home}"
    -v "${config_volume}:/home/relay/.config/relay"
    -v "${state_volume}:/home/relay/.local/state/relay"
  )
}

cmd_build() {
  local image="${DOCKER_IMAGE:-${DEFAULT_IMAGE}}"
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
  if [[ -n "${DOCKER_UID:-}" ]]; then
    args+=(--build-arg "RELAY_UID=${DOCKER_UID}")
  fi
  if [[ -n "${DOCKER_GID:-}" ]]; then
    args+=(--build-arg "RELAY_GID=${DOCKER_GID}")
  fi
  if [[ "${DOCKER_NO_CACHE:-0}" == "1" ]]; then
    args+=(--pull --no-cache)
  fi

  echo "🐳 Building ${image} (version=${version}, revision=${revision:0:12})..."
  docker buildx build "${args[@]}" .
}

cmd_smoke() {
  local image="${DOCKER_IMAGE:-${DEFAULT_IMAGE}}"
  if [[ "${image}" == "${DEFAULT_IMAGE}" ]]; then
    # Rebuild so the smoke test covers the current sources; unchanged layers are cached.
    cmd_build
  elif ! docker image inspect "${image}" >/dev/null 2>&1; then
    docker pull "${image}"
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
  expect_equal "CLI version" "${actual_version}" "relay, version ${expected_version}"

  docker run --rm "${image}" --help >/dev/null

  local actual_revision
  actual_revision="$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "${image}")"
  expect_equal "revision label" "${actual_revision}" "${expected_revision}"

  local label_version
  label_version="$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.version" }}' "${image}")"
  expect_equal "version label" "${label_version}" "${expected_version}"

  local actual_user
  actual_user="$(docker image inspect --format '{{ .Config.User }}' "${image}")"
  expect_equal "image user" "${actual_user}" "relay:relay"

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

  local cid
  cid="$(
    docker run -d \
      --init \
      -p 127.0.0.1::7845 \
      --entrypoint /bin/sh \
      "${image}" \
      -ec '
        git init -q /workspace
        git -C /workspace config user.name "Relay Container Smoke"
        git -C /workspace config user.email "smoke@example.invalid"
        git -C /workspace commit --allow-empty -q -m "initial"
        exec relay up --no-login
      '
  )"
  # An EXIT trap also runs when `set -e` aborts the script; a RETURN trap does not.
  trap "docker rm -f $(printf '%q' "${cid}") >/dev/null 2>&1 || true" EXIT

  local host_addr
  host_addr="$(docker port "${cid}" 7845/tcp | head -n 1)"
  python3 - "${host_addr}" <<'PY'
import sys
import time
import urllib.request

addr = sys.argv[1].strip()
deadline = time.monotonic() + 20.0
while time.monotonic() < deadline:
    try:
        with urllib.request.urlopen(f"http://{addr}/api/auth", timeout=1.0) as auth:
            if auth.status == 200:
                break
    except Exception:
        time.sleep(0.1)
else:
    raise SystemExit(f"Published container port {addr} did not become ready")
PY
  docker stop --time 15 "${cid}" >/dev/null
  docker rm -f "${cid}" >/dev/null 2>&1 || true
  trap - EXIT

  echo "✅ Smoke test passed: ${image}"
}

e2e_cleanup() {
  local status="$1" name="$2" root="$3"
  if [[ "${status}" != "0" ]] && docker container inspect "${name}" >/dev/null 2>&1; then
    echo "Container log for ${name}:" >&2
    docker logs --tail 200 "${name}" >&2 || true
  fi
  docker rm -f -v "${name}-sibling" >/dev/null 2>&1 || true
  docker rm -f -v "${name}" >/dev/null 2>&1 || true
  docker volume rm -f "${name}-config" "${name}-state" >/dev/null 2>&1 || true
  docker network rm "${name}" >/dev/null 2>&1 || true
  rm -rf -- "${root}"
}

cmd_e2e() {
  local image="${DOCKER_IMAGE:-${DEFAULT_IMAGE}}"
  if [[ "${image}" == "${DEFAULT_IMAGE}" ]]; then
    use_host_ids
    # Rebuild so the run covers the current sources; unchanged layers are cached.
    cmd_build
  elif ! docker image inspect "${image}" >/dev/null 2>&1; then
    docker pull "${image}"
  fi
  local user_args=()
  if [[ "$(uname -s)" == "Linux" ]]; then
    local host_uid image_uid
    host_uid="$(id -u)"
    image_uid="$(docker run --rm --entrypoint id "${image}" -u)"
    if [[ "${host_uid}" == "0" ]]; then
      # The image user cannot take UID 0, so root hosts, such as CI and
      # development containers, run the disposable containers as root to
      # write the root-owned mounts.
      user_args=(--user 0:0)
    elif [[ "${image_uid}" != "${host_uid}" ]]; then
      echo "❌ ${image} runs as UID ${image_uid} and cannot write files owned by UID ${host_uid}." >&2
      echo "   Use the default image, which docker-e2e builds as a host user from UID 1000." >&2
      return 1
    fi
  fi

  local name="relay-e2e-$$-${RANDOM}"
  local temporary="${TMPDIR:-/tmp}"
  local root
  # BSD mktemp ignores TMPDIR without a template.
  root="$(mktemp -d "${temporary%/}/relay-e2e.XXXXXXXX")"
  # An EXIT trap also runs when `set -e` aborts the script; a RETURN trap does not.
  # Expand now: the locals are out of scope when the trap runs under `set -u`.
  trap "e2e_cleanup \$? $(printf '%q ' "${name}" "${root}")" EXIT
  # Mount the resolved path; macOS temporary directories sit behind a symlink.
  root="$(cd "${root}" && pwd -P)"
  local repo="${root}/repository"
  local data_home="${root}/data"
  mkdir "${data_home}"

  # Host Git ignores the owner's global and system settings, such as hooks and signing.
  local -x GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
  git init -q -b main "${repo}"
  git -C "${repo}" config user.name "Relay Container E2E"
  git -C "${repo}" config user.email "e2e@example.invalid"
  printf '# Relay container end-to-end\n' >"${repo}/README.md"
  git -C "${repo}" add README.md
  git -C "${repo}" commit -q -m "initial"

  # Throwaway volumes keep the owner's relay-config and relay-state untouched.
  set_relay_mounts "${repo}" "${data_home}" "${name}-config" "${name}-state"
  docker run --rm ${user_args[@]+"${user_args[@]}"} "${RELAY_MOUNTS[@]}" "${image}" init >/dev/null
  git -C "${repo}" add .relay
  git -C "${repo}" commit -q -m "Initialize Relay"

  echo "🧪 Running browser flows against ${image}..."
  docker network create "${name}" >/dev/null
  # Login stays required, as it is by default, so sign-in crosses the bridge.
  docker run -d \
    --name "${name}" \
    --init \
    --network "${name}" \
    -p 127.0.0.1::7845 \
    ${user_args[@]+"${user_args[@]}"} \
    "${RELAY_MOUNTS[@]}" \
    "${image}" \
    up >/dev/null

  local host_addr
  host_addr="$(docker port "${name}" 7845/tcp | head -n 1)"
  local frontend="${SCRIPT_DIR}/../frontend"
  if [[ ! -d "${frontend}/node_modules/@playwright/test" ]]; then
    echo "❌ docker-e2e drives a browser. Run: npm --prefix frontend ci" >&2
    echo "   and: npm --prefix frontend exec playwright install chromium" >&2
    return 1
  fi
  RELAY_CONTAINER_URL="http://${host_addr}" \
    RELAY_CONTAINER_NAME="${name}" \
    RELAY_CONTAINER_REPOSITORY="${repo}" \
    RELAY_CONTAINER_DATA_HOME="${data_home}" \
    npm --prefix "${frontend}" run test:container

  # The entrypoint starts the installed relay in a new session, so only the
  # signal it forwards reaches Relay during shutdown.
  local processes
  processes="$(docker exec "${name}" ps -eo pid=,sid=,args=)"
  local relay_process bridge_process
  relay_process="$(awk '$3 == "/opt/relay/venv/bin/python" && $4 == "/opt/relay/venv/bin/relay" && $5 == "up"' <<<"${processes}")"
  bridge_process="$(awk '$4 == "/usr/local/bin/relay" && $5 == "up"' <<<"${processes}")"
  if [[ -z "${relay_process}" || -z "${bridge_process}" ]]; then
    echo "❌ Expected the bridge and installed relay up processes in:" >&2
    printf '%s\n' "${processes}" >&2
    return 1
  fi
  local relay_pid relay_sid bridge_sid
  read -r relay_pid relay_sid _ <<<"${relay_process}"
  read -r _ bridge_sid _ <<<"${bridge_process}"
  expect_equal "installed relay up session" "${relay_sid}" "${relay_pid}"
  if [[ "${bridge_sid}" == "${relay_sid}" ]]; then
    echo "❌ The installed relay up shares the bridge's session ${bridge_sid}." >&2
    return 1
  fi

  # A sibling reaches the bridge on the container interface, which closes every
  # connection that does not come from the gateway carrying the published port.
  docker run --rm -i \
    --name "${name}-sibling" \
    --network "${name}" \
    --entrypoint python \
    "${image}" - "${name}" <<'PY'
import socket
import sys

reply = b""
with socket.create_connection((sys.argv[1], 7845), timeout=5.0) as connection:
    try:
        connection.sendall(b"GET /api/auth HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
        reply = connection.recv(1)
    except (BrokenPipeError, ConnectionResetError):
        pass
if reply:
    raise SystemExit("A sibling container reached Relay through the published-port bridge.")
PY

  docker stop --time 15 "${name}" >/dev/null
  local logs
  # Capture first: `grep -q` can close the pipe early and fail it under pipefail.
  logs="$(docker logs "${name}" 2>&1)"
  if ! grep -Fq "Relay stopped cleanly." <<<"${logs}"; then
    echo "❌ docker stop did not stop Relay cleanly." >&2
    return 1
  fi
  local exit_code
  exit_code="$(docker inspect --format '{{ .State.ExitCode }}' "${name}")"
  expect_equal "container exit code" "${exit_code}" "0"

  e2e_cleanup 0 "${name}" "${root}"
  trap - EXIT
  echo "✅ End-to-end test passed: ${image}"
}

cmd_up() {
  local image="${DOCKER_IMAGE:-${DEFAULT_IMAGE}}"
  local port="${DOCKER_PORT:-7845}"
  local worktree
  worktree="$(cd "${DOCKER_WORKTREE:-.}" && pwd)"
  local data_home="${DOCKER_DATA_HOME:-${XDG_DATA_HOME:-${HOME}/.local/share}/relay-docker}"
  mkdir -p "${data_home}"
  data_home="$(cd "${data_home}" && pwd)"

  if [[ "${image}" == "${DEFAULT_IMAGE}" ]]; then
    use_host_ids
    # Rebuild so the container serves the current sources; unchanged layers are cached.
    cmd_build
  fi

  set_relay_mounts "${worktree}" "${data_home}" relay-config relay-state

  local tty_flags=()
  if [[ -t 0 && -t 1 ]]; then
    tty_flags+=(-it)
  fi

  echo "▶️ Starting Relay container at http://127.0.0.1:${port}/ for ${worktree}..."
  exec docker run --rm ${tty_flags[@]+"${tty_flags[@]}"} \
    --init \
    -p "127.0.0.1:${port}:${port}" \
    "${RELAY_MOUNTS[@]}" \
    "${image}" \
    up --port "${port}" ${DOCKER_UP_ARGS:-}
}

cmd_push() {
  local repo="${DOCKER_REPO:-ghcr.io/viseshrp/relay}"
  local tags="${TAGS:?TAGS is required, for example TAGS=\"0.1.0 latest\"}"
  if [[ -n "$(git status --porcelain)" ]]; then
    echo "❌ docker-push publishes the committed revision; commit or remove local changes first." >&2
    git status --short >&2
    return 1
  fi
  local version
  version="$(resolve_version)"
  local revision
  revision="$(resolve_revision)"
  local created="${DOCKER_CREATED:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}"
  local platforms="${DOCKER_PLATFORMS:-linux/amd64,linux/arm64}"

  # Smoke-test this platform with the same version, revision, and creation labels.
  DOCKER_IMAGE="${DEFAULT_IMAGE}" DOCKER_VERSION="${version}" DOCKER_VCS_REF="${revision}" \
    DOCKER_CREATED="${created}" cmd_smoke

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
  # Expand now: the local is out of scope when the EXIT trap runs under `set -u`.
  trap "rm -f -- $(printf '%q' "${metadata_file}")" EXIT

  local cache_args=()
  if [[ "${DOCKER_NO_CACHE:-0}" == "1" ]]; then
    cache_args+=(--pull --no-cache)
  fi

  echo "📤 Pushing ${platform} image by digest to ${repo}..."
  docker buildx build \
    --platform "${platform}" \
    --build-arg "VERSION=${version}" \
    --build-arg "VCS_REF=${revision}" \
    --label "org.opencontainers.image.created=${created}" \
    ${cache_args[@]+"${cache_args[@]}"} \
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
  docker buildx imagetools inspect "${repo}:${primary_tag}" --raw \
    | jq -e '[.manifests[].platform | select(.os == "linux") | .architecture] | sort == ["amd64", "arm64"]' \
      >/dev/null
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
  e2e)
    cmd_e2e
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
