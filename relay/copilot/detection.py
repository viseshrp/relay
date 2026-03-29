from __future__ import annotations

import asyncio
import shutil
from dataclasses import asdict, dataclass

from relay.config import Settings


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
    gh_path = shutil.which(settings.copilot_cli_path)
    if gh_path is None:
        return CopilotStatus(
            gh_available=False,
            copilot_available=False,
            authenticated=False,
            gh_path=None,
            copilot_version=None,
            auth_details=None,
            message="GitHub CLI was not found in PATH.",
        )

    version_code, version_output = await _run_command(settings.copilot_cli_path, "copilot", "--version")
    auth_code, auth_output = await _run_command(settings.copilot_cli_path, "auth", "status")
    copilot_available = version_code == 0
    authenticated = auth_code == 0
    if not copilot_available:
        message = "GitHub Copilot CLI extension is unavailable."
    elif not authenticated:
        message = "GitHub CLI is installed but not authenticated."
    else:
        message = "GitHub Copilot CLI is available."
    return CopilotStatus(
        gh_available=True,
        copilot_available=copilot_available,
        authenticated=authenticated,
        gh_path=gh_path,
        copilot_version=version_output if version_output else None,
        auth_details=auth_output if auth_output else None,
        message=message,
    )
