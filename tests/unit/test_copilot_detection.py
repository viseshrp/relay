from __future__ import annotations

import json
from pathlib import Path

import pytest

from relay.config import Settings
from relay.copilot.detection import _detect_copilot_authentication, detect_copilot_status
from relay.copilot.session import _prepare_copilot_environment, build_agent_command, resolve_copilot_cli_path


def _settings(tmp_path: Path, cli_path: str = "gh") -> Settings:
    return Settings(
        data_dir=tmp_path / "relay-data",
        db_path=tmp_path / "relay.db",
        host="127.0.0.1",
        port=8080,
        copilot_cli_path=cli_path,
        frontend_dist_dir=tmp_path / "dist",
        poll_interval_seconds=0.1,
        process_monitor_interval_seconds=10.0,
        default_retry_limit=5,
        default_review_fix_loop_limit=5,
        default_autopilot=True,
    )


def test_resolve_copilot_cli_path_prefers_direct_binary(monkeypatch) -> None:
    def fake_which(name: str) -> str | None:
        if name == "copilot":
            return r"C:\Users\tester\AppData\Roaming\npm\copilot.cmd"
        if name == "gh":
            return r"C:\Program Files\GitHub CLI\gh.exe"
        return None

    monkeypatch.setattr("relay.copilot.session.shutil.which", fake_which)

    assert resolve_copilot_cli_path("gh") == r"C:\Users\tester\AppData\Roaming\npm\copilot.cmd"


def test_build_agent_command_uses_prompt_mode_flags(monkeypatch) -> None:
    monkeypatch.setattr("relay.copilot.session.resolve_copilot_cli_path", lambda configured: configured)

    command = build_agent_command("copilot", "gpt-4.1")

    assert command == [
        "copilot",
        "--output-format",
        "text",
        "--stream",
        "off",
        "--allow-all-tools",
        "--allow-all-paths",
        "--no-ask-user",
        "--model",
        "gpt-4.1",
    ]


def test_detect_copilot_authentication_reads_logged_in_users(tmp_path: Path, monkeypatch) -> None:
    home_dir = tmp_path / "home"
    config_dir = home_dir / ".copilot"
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "logged_in_users": [
                    {
                        "host": "https://github.com",
                        "login": "viseshrp",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("relay.copilot.detection.Path.home", lambda: home_dir)

    authenticated, details = _detect_copilot_authentication()

    assert authenticated is True
    assert details == "viseshrp @ https://github.com"


def test_prepare_copilot_environment_adds_pwsh_compat_shim(tmp_path: Path, monkeypatch) -> None:
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    expected_shim = home_dir / ".relay" / "bin" / "pwsh.exe"

    def fake_which(name: str, path: str | None = None) -> str | None:
        if name == "pwsh.exe":
            return None
        if name == "powershell.exe":
            return r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
        return None

    monkeypatch.setattr("relay.copilot.session.Path.home", lambda: home_dir)
    monkeypatch.setattr("relay.copilot.session.shutil.which", fake_which)
    monkeypatch.setattr(
        "relay.copilot.session._ensure_pwsh_compat_shim",
        lambda shim_dir, powershell_path: expected_shim,
    )

    prepared_env = _prepare_copilot_environment({"PATH": r"C:\Windows\System32"})

    assert prepared_env["PATH"].startswith(str(home_dir / ".relay" / "bin"))
    assert prepared_env["PATH"].split(";")[0] == str(home_dir / ".relay" / "bin")


@pytest.mark.asyncio
async def test_detect_copilot_status_uses_direct_cli_and_config_auth(tmp_path: Path, monkeypatch) -> None:
    home_dir = tmp_path / "home"
    config_dir = home_dir / ".copilot"
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "logged_in_users": [
                    {
                        "host": "https://github.com",
                        "login": "viseshrp",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("relay.copilot.detection.Path.home", lambda: home_dir)
    monkeypatch.setattr(
        "relay.copilot.detection.resolve_copilot_cli_path",
        lambda configured: r"C:\Users\tester\AppData\Roaming\npm\copilot.cmd",
    )
    monkeypatch.setattr("relay.copilot.detection.shutil.which", lambda value: value)

    async def fake_run_command(*args: str) -> tuple[int, str]:
        assert args == (r"C:\Users\tester\AppData\Roaming\npm\copilot.cmd", "version")
        return 0, "GitHub Copilot CLI 1.0.12"

    monkeypatch.setattr("relay.copilot.detection._run_command", fake_run_command)

    status = await detect_copilot_status(_settings(tmp_path))

    assert status.copilot_available is True
    assert status.authenticated is True
    assert status.gh_path == r"C:\Users\tester\AppData\Roaming\npm\copilot.cmd"
    assert status.message == "GitHub Copilot CLI is available."
