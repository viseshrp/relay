"""Only the approved starter sources may pass the distribution template gate."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import tarfile
import zipfile

import pytest

from scripts.check_distribution_contents import check_distribution


@pytest.mark.parametrize(
    "name,allowed",
    [
        ("relay/workflows/starters/ask-agent.yaml", True),
        ("relay/workflows/starters/ask-agent.md", True),
        ("relay/workflows/starters/ai-coding-workflow.yaml", True),
        ("relay/workflows/starters/ai-coding-workflow/action.yaml", True),
        ("relay/workflows/starters/ai-coding-workflow/LICENSE", True),
        ("relay/workflows/starters/ai-coding-workflow/provenance.json", True),
        ("relay/workflows/starters/ai-coding-workflow/01_initial_exploration_any_model.md", True),
        ("relay/workflows/starters/ai-coding-workflow/unknown.md", False),
        ("relay/workflows/starters/unknown.yaml", False),
        ("relay/workflows/starters/unknown.md", False),
        ("relay/templates/ask-agent.yaml", False),
        ("relay/other.yaml", False),
        ("relay/secret_prompt.md", False),
    ],
)
def test_distribution_template_allow_list_is_exact(
    tmp_path: Path, name: str, allowed: bool
) -> None:
    archive = tmp_path / "test.whl"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("relay/static/index.html", "index")
        bundle.writestr("relay/static/assets/app.js", "app")
        bundle.writestr(name, "source")
    if allowed:
        check_distribution(archive)
    else:
        with pytest.raises(RuntimeError, match="forbidden workflow or prompt templates"):
            check_distribution(archive)


@pytest.mark.parametrize(
    "extra,missing",
    [
        (None, None),
        (None, "docs/getting-started.md"),
        ("frontend/node_modules/dependency/index.js", None),
        ("frontend/test-results/result.json", None),
        ("frontend/playwright-report/index.html", None),
        ("relay/static/assets/app.js", None),
    ],
)
def test_sdist_requires_the_guides_imported_by_the_frontend(
    tmp_path: Path, extra: str | None, missing: str | None
) -> None:
    archive = tmp_path / "relay.tar.gz"
    names = {
        "frontend/package.json",
        "frontend/package-lock.json",
        "hatch_build.py",
        "docs/getting-started.md",
        "docs/coming-from-github-actions.md",
        "docs/keyboard-shortcuts.md",
    }
    if extra is not None:
        names.add(extra)
    with tarfile.open(archive, "w:gz") as bundle:
        for name in sorted(names - {missing}):
            member = tarfile.TarInfo(f"relay/{name}")
            member.size = 5
            bundle.addfile(member, BytesIO(b"input"))
    if extra is not None:
        with pytest.raises(RuntimeError, match="generated frontend"):
            check_distribution(archive)
    elif missing is None:
        check_distribution(archive)
    else:
        with pytest.raises(RuntimeError, match=missing):
            check_distribution(archive)


def test_container_packaging_preserves_wheel_gate_and_ghcr_tags() -> None:
    from ruamel.yaml import YAML

    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (root / ".dockerignore").read_text(encoding="utf-8").splitlines()
    makefile = (root / "Makefile").read_text(encoding="utf-8")
    docker_script = (root / "scripts/docker.sh").read_text(encoding="utf-8")
    workflow_text = (root / ".github/workflows/docker.yml").read_text("utf-8")
    workflow = YAML(typ="safe").load(workflow_text)

    assert "scripts/check_distribution_contents.py /dist/relay_app-*.whl" in dockerfile
    assert "--require-hashes -r /dist/requirements.txt" in dockerfile
    assert "scripts/container_entrypoint.py /usr/local/bin/relay" in dockerfile
    assert "USER relay:relay" in dockerfile
    assert 'ENTRYPOINT ["relay"]' in dockerfile

    assert dockerignore[0] == "*"
    for required_rule in (
        "!pyproject.toml",
        "!uv.lock",
        "!hatch_build.py",
        "!frontend/package-lock.json",
        "!scripts/check_distribution_contents.py",
        "!scripts/container_entrypoint.py",
        "relay/static/**",
    ):
        assert required_rule in dockerignore

    for target in (
        "docker-build:",
        "docker-smoke:",
        "docker-up:",
        "docker-run:",
        "docker-push:",
        "docker-push-digest:",
        "docker-publish-manifest:",
    ):
        assert target in makefile

    for subcommand in (
        "cmd_build()",
        "cmd_smoke()",
        "cmd_up()",
        "cmd_push()",
        "cmd_push_digest()",
        "cmd_publish_manifest()",
    ):
        assert subcommand in docker_script

    assert workflow["env"]["IMAGE"] == "ghcr.io/viseshrp/relay"
    triggers = workflow["on"]
    assert triggers["schedule"] == [{"cron": "17 7 * * *"}]
    assert "pull_request" in triggers
    assert "push" not in triggers
    assert triggers["release"]["types"] == ["published"]
    platforms = [
        item["platform"] for item in workflow["jobs"]["build"]["strategy"]["matrix"]["include"]
    ]
    assert platforms == ["linux/amd64", "linux/arm64"]
    for make_cmd in (
        "make docker-build",
        "make docker-smoke",
        "make docker-push-digest",
        "make docker-publish-manifest",
    ):
        assert make_cmd in workflow_text
