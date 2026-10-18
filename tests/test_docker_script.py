"""`scripts/docker.sh` exits with the outcome of its work and cleans up after failures."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

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
  "run -d"*) echo "smoke-container" ;;
  "port "*) exit 1 ;;
esac
"""

pytestmark = [
    pytest.mark.skipif(
        os.name == "nt" or BASH is None, reason="the Docker helper runs under POSIX bash"
    ),
    pytest.mark.skipif(shutil.which("jq") is None, reason="the Docker helper parses JSON with jq"),
]


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


def test_push_digest_succeeds_after_recording_the_digest(tmp_path: Path) -> None:
    digests = tmp_path / "digests"

    result, _calls = _run(
        tmp_path, "push-digest", DOCKER_PLATFORM="linux/amd64", DIGESTS_DIR=str(digests)
    )

    assert result.returncode == 0, result.stderr
    assert "unbound variable" not in result.stderr
    assert [path.name for path in digests.iterdir()] == [DIGEST]


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
