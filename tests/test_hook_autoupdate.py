"""Hook maintenance must not turn the nearest upstream tag into a downgrade."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

from scripts.autoupdate_hooks import main, preserve_releases, update_hooks


def test_downgrade_restores_exact_pin_and_keeps_other_updates() -> None:
    original = """repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: 'v8.30.1'  # retain this release
    hooks: [{id: gitleaks}]
  - repo: https://example.com/other
    rev: v1.2.3
    hooks: [{id: other}]
"""
    candidate = original.replace("'v8.30.1'", "v8.30.0").replace("v1.2.3", "v1.2.4")
    updated, notices = preserve_releases(original, candidate)
    assert updated == original.replace("v1.2.3", "v1.2.4")
    assert notices == ["https://github.com/gitleaks/gitleaks: retained v8.30.1 instead of v8.30.0"]


@pytest.mark.parametrize(
    "before,after",
    [("v1.9.0", "v1.10.0"), ("v1.2", "v1.2.0"), ("abc123", "def456")],
)
def test_upgrades_equal_versions_and_nonrelease_refs_are_kept(before: str, after: str) -> None:
    original = f"repos:\n  - repo: example\n    rev: {before}\n"
    candidate = original.replace(before, after)
    assert preserve_releases(original, candidate) == (candidate, [])


def test_local_hooks_and_multiple_downgrades_keep_yaml_positions() -> None:
    original = """repos:
  - repo: local
    hooks: [{id: local}]
  - repo: example
    rev: v10.2.3
  - repo: example
    rev: v2.3.4
"""
    candidate = original.replace("v10.2.3", "v9.0.0").replace("v2.3.4", "v1.0.0")
    updated, notices = preserve_releases(original, candidate)
    assert updated == original
    assert len(notices) == 2


def test_update_calls_precommit_and_restores_a_downgrade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "hooks.yaml"
    original = "repos:\n  - repo: example\n    rev: v8.30.1\n"
    config.write_text(original, encoding="utf-8")

    def autoupdate(command: list[str], *, check: bool) -> subprocess.CompletedProcess[str]:
        assert command == [
            sys.executable,
            "-m",
            "pre_commit",
            "autoupdate",
            "--config",
            str(config),
        ]
        assert check is False
        config.write_text(original.replace("v8.30.1", "v8.30.0"), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", autoupdate)
    assert update_hooks(config) == 0
    assert config.read_text(encoding="utf-8") == original


def test_failed_autoupdate_keeps_its_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "hooks.yaml"
    config.write_text("repos: []\n", encoding="utf-8")

    def fail(command: list[str], *, check: bool) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1)

    monkeypatch.setattr(subprocess, "run", fail)
    assert update_hooks(config) == 1


@pytest.mark.parametrize("source", ["[]", "repos: {}", "repos: [3]"])
def test_invalid_configuration_stops_the_guard(source: str) -> None:
    with pytest.raises(TypeError, match="Hook"):
        preserve_releases(source, source)


def test_changed_repositories_stop_the_guard() -> None:
    source = "repos:\n  - repo: example\n    rev: v1.2.3\n"
    with pytest.raises(ValueError, match="ordering"):
        preserve_releases(source, source.replace("example", "other"))
    with pytest.raises(ValueError, match="zip"):
        preserve_releases(source, "repos: []\n")


def test_cli_updates_the_selected_config_without_reverting_an_upgrade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "selected.yaml"
    original = "repos:\n  - repo: example\n    rev: v1.2.3\n"
    config.write_text(original, encoding="utf-8")

    def upgrade(command: list[str], *, check: bool) -> subprocess.CompletedProcess[str]:
        assert command[-1] == str(config)
        config.write_text(original.replace("v1.2.3", "v1.3.0"), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", upgrade)
    assert main(["--config", str(config)]) == 0
    assert config.read_text(encoding="utf-8") == original.replace("v1.2.3", "v1.3.0")
