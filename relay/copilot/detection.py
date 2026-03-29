from __future__ import annotations

import asyncio
import json
import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from relay.config import Settings
from relay.copilot.session import resolve_copilot_cli_path


@dataclass(slots=True)
class CopilotStatus:
    gh_available: bool
    copilot_available: bool
    authenticated: bool
    gh_path: str | None
    copilot_version: str | None
    auth_details: str | None
    message: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


async def _run_command(*args: str) -> tuple[int, str]:
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await process.communicate()
    return process.returncode or 0, stdout.decode("utf-8", errors="replace").strip()


async def detect_copilot_status(settings: Settings) -> CopilotStatus:
    resolved_cli_path = resolve_copilot_cli_path(settings.copilot_cli_path)
    cli_path = shutil.which(resolved_cli_path) or resolved_cli_path
    if shutil.which(cli_path) is None and not Path(cli_path).exists():
        return CopilotStatus(
            gh_available=False,
            copilot_available=False,
            authenticated=False,
            gh_path=None,
            copilot_version=None,
            auth_details=None,
            message="GitHub Copilot CLI was not found in PATH.",
        )

    version_code, version_output = await _run_command(cli_path, "version")
    authenticated, auth_output = _detect_copilot_authentication()
    copilot_available = version_code == 0
    if not copilot_available:
        message = "GitHub Copilot CLI is unavailable."
    elif not authenticated:
        message = "GitHub Copilot CLI is installed but not authenticated."
    else:
        message = "GitHub Copilot CLI is available."
    return CopilotStatus(
        gh_available=True,
        copilot_available=copilot_available,
        authenticated=authenticated,
        gh_path=cli_path,
        copilot_version=version_output if version_output else None,
        auth_details=auth_output if auth_output else None,
        message=message,
    )


def _detect_copilot_authentication() -> tuple[bool, str | None]:
    # Headless environments can authenticate purely through environment
    # variables, so honor those before consulting the local Copilot config.
    for token_name in ("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
        if os.getenv(token_name):
            return True, f"Authenticated via environment token: {token_name}"

    config_path = Path.home() / ".copilot" / "config.json"
    if not config_path.exists():
        return False, None
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, None

    logged_in_users = payload.get("logged_in_users")
    if not isinstance(logged_in_users, list) or not logged_in_users:
        return False, None

    details: list[str] = []
    for user in logged_in_users:
        if not isinstance(user, dict):
            continue
        host = str(user.get("host", "https://github.com"))
        login = str(user.get("login", "unknown"))
        details.append(f"{login} @ {host}")
    if not details:
        return False, None
    return True, "\n".join(details)
