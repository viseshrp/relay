"""`scripts/docker.sh` exits with the outcome of its work and cleans up after failures."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "docker.sh"
BASH = shutil.which("bash")
DIGEST = "0123abcd"

# Answers the Docker calls the script makes; every call is logged for assertions.
FAKE_DOCKER = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE_DOCKER_LOG"
case "$*" in
  *--metadata-file*)
    previous=""
    for argument in "$@"; do
      if [[ "$previous" == "--metadata-file" ]]; then
        printf '{"containerimage.digest": "sha256:%s"}' "$FAKE_DIGEST" > "$argument"
      fi
      previous="$argument"
    done
    ;;
  "buildx imagetools inspect"*)
    printf '%s' '{"manifests": [
      {"platform": {"os": "linux", "architecture": "arm64"}},
      {"platform": {"os": "linux", "architecture": "amd64"}},
      {"platform": {"os": "unknown", "architecture": "unknown"}}]}'
    ;;
  *--version) echo "relay, version 1.0.0" ;;
  *org.opencontainers.image.revision*) echo "abc123" ;;
  *org.opencontainers.image.version*) echo "1.0.0" ;;
  *.Config.User*) echo "relay:relay" ;;
  *"--entrypoint id "*) id -u ;;
  *" init")
    # `relay init` creates the blank project surface in the working directory.
    previous=""
    for argument in "$@"; do
      if [[ "$previous" == "-w" ]]; then
        mkdir -p "$argument/.relay/workflows"
        printf 'jobs: {}\n' > "$argument/.relay/workflows/workflow.yaml"
      fi
      previous="$argument"
    done
    ;;
  "run -d"*) echo "smoke-container" ;;
  "port "*) exit 1 ;;
esac
"""

pytestmark = pytest.mark.skipif(
    os.name == "nt" or BASH is None, reason="the Docker helper runs under POSIX bash"
)
needs_jq = pytest.mark.skipif(shutil.which("jq") is None, reason="the helper parses JSON with jq")


def _run(tmp_path: Path, command: str, **env: str) -> tuple[subprocess.CompletedProcess[str], str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER, encoding="utf-8")
    docker.chmod(0o755)
    log = tmp_path / "docker.log"
    environment = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "FAKE_DOCKER_LOG": str(log),
        "FAKE_DIGEST": DIGEST,
        "DOCKER_VERSION": "1.0.0",
        "DOCKER_VCS_REF": "abc123",
        **env,
    }
    result = subprocess.run(  # noqa: S603 - fixed interpreter and repository script
        [str(BASH), str(SCRIPT), command],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    return result, log.read_text(encoding="utf-8") if log.exists() else ""


@needs_jq
def test_push_digest_succeeds_after_recording_the_digest(tmp_path: Path) -> None:
    digests = tmp_path / "digests"

    result, _calls = _run(
        tmp_path, "push-digest", DOCKER_PLATFORM="linux/amd64", DIGESTS_DIR=str(digests)
    )

    assert result.returncode == 0, result.stderr
    assert "unbound variable" not in result.stderr
    assert [path.name for path in digests.iterdir()] == [DIGEST]


@needs_jq
def test_publish_manifest_succeeds_after_verifying_both_platforms(tmp_path: Path) -> None:
    digests = tmp_path / "digests"
    digests.mkdir()
    (digests / "aaa").touch()
    (digests / "bbb").touch()

    result, calls = _run(
        tmp_path,
        "publish-manifest",
        DIGESTS_DIR=str(digests),
        TAGS="nightly nightly-20261018-1-1",
        PRIMARY_TAG="nightly",
    )

    assert result.returncode == 0, result.stderr
    assert "buildx imagetools create --tag ghcr.io/viseshrp/relay:nightly" in calls


def test_smoke_removes_its_container_when_readiness_fails(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, "smoke", DOCKER_IMAGE="example.invalid/relay:test")

    assert result.returncode != 0
    assert calls.splitlines()[-1] == "rm -f smoke-container"


def test_smoke_reports_the_mismatched_label(tmp_path: Path) -> None:
    result, _calls = _run(
        tmp_path, "smoke", DOCKER_IMAGE="example.invalid/relay:test", DOCKER_VCS_REF="def456"
    )

    assert result.returncode != 0
    assert "revision label: expected 'def456', got 'abc123'" in result.stderr


def test_up_mounts_the_repository_and_data_at_their_host_paths(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    data_home = tmp_path / "data"

    result, calls = _run(
        tmp_path,
        "up",
        DOCKER_IMAGE="example.invalid/relay:test",
        DOCKER_WORKTREE=str(repository),
        DOCKER_DATA_HOME=str(data_home),
    )

    assert result.returncode == 0, result.stderr
    run = calls.splitlines()[-1]
    # Distinct repositories keep distinct project identities and resolvable worktrees.
    assert f"-v {repository}:{repository} -w {repository}" in run
    assert f"GIT_CONFIG_KEY_0=safe.directory -e GIT_CONFIG_VALUE_0={repository}" in run
    assert f"-v {data_home}:{data_home} -e XDG_DATA_HOME={data_home}" in run
    assert "/workspace" not in run
    assert run.endswith("example.invalid/relay:test up --port 7845")


@pytest.mark.skipif(sys.platform != "linux", reason="only Linux bind mounts keep host ownership")
def test_up_builds_the_local_image_as_the_linux_host_user(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()

    result, calls = _run(
        tmp_path,
        "up",
        DOCKER_IMAGE="",
        DOCKER_UID="",
        DOCKER_GID="",
        DOCKER_WORKTREE=str(repository),
        DOCKER_DATA_HOME=str(tmp_path / "data"),
    )

    assert result.returncode == 0, result.stderr
    build = calls.splitlines()[0].split()
    # The image's useradd accepts only IDs from 1000; lower IDs keep its defaults.
    for argument, value in (("RELAY_UID", os.getuid()), ("RELAY_GID", os.getgid())):
        passed = [token for token in build if token.startswith(f"{argument}=")]
        assert passed == ([f"{argument}={value}"] if value >= 1000 else [])


def _run_e2e_until_the_port_lookup_fails(
    tmp_path: Path,
) -> tuple[subprocess.CompletedProcess[str], list[str], Path, str]:
    temporary = tmp_path / "tmp"
    temporary.mkdir()
    result, calls = _run(
        tmp_path, "e2e", DOCKER_IMAGE="example.invalid/relay:test", TMPDIR=str(temporary)
    )
    lines = calls.splitlines()
    name = next(line.split()[-1] for line in lines if line.startswith("network create "))
    return result, lines, temporary, name


def test_e2e_removes_its_containers_volumes_network_and_files_after_failure(
    tmp_path: Path,
) -> None:
    result, calls, temporary, name = _run_e2e_until_the_port_lookup_fails(tmp_path)

    assert result.returncode != 0
    assert calls[-4:] == [
        f"rm -f -v {name}-sibling",
        f"rm -f -v {name}",
        f"volume rm -f {name}-config {name}-state",
        f"network rm {name}",
    ]
    assert list(temporary.iterdir()) == []


def test_e2e_starts_relay_like_docker_up_with_throwaway_volumes(tmp_path: Path) -> None:
    _result, calls, temporary, name = _run_e2e_until_the_port_lookup_fails(tmp_path)

    run = next(call for call in calls if call.startswith("run -d "))
    repository = Path(run.split(" -w ", 1)[1].split()[0])
    data_home = repository.parent / "data"
    assert repository.parent.parent == temporary.resolve()
    assert f"-v {repository}:{repository} -w {repository}" in run
    assert f"GIT_CONFIG_KEY_0=safe.directory -e GIT_CONFIG_VALUE_0={repository}" in run
    assert f"-v {data_home}:{data_home} -e XDG_DATA_HOME={data_home}" in run
    words = run.split()
    sources = {words[index + 1].split(":")[0] for index, word in enumerate(words) if word == "-v"}
    # The owner's relay-config and relay-state volumes are never mounted.
    assert sources == {str(repository), str(data_home), f"{name}-config", f"{name}-state"}
    assert f"--network {name} -p 127.0.0.1::7845 -v " in run
    # Login stays required, as it is by default.
    assert run.endswith("example.invalid/relay:test up")
    mounts = run.split(" -p 127.0.0.1::7845 ", 1)[1].removesuffix(" up")
    assert f"run --rm {mounts} init" in calls


def test_push_requires_explicit_tags(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, "push", TAGS="")

    assert result.returncode != 0
    assert "TAGS is required" in result.stderr
    assert calls == ""
