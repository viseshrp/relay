"""Read-only executable discovery for Relay's fixed agent set."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

from .models import AgentCommand, AgentProfile, DiscoveredAgent, RegistrySnapshot
from .profiles import PROFILES

_VERSION_TIMEOUT_SECONDS = 5.0


def _find_executable(names: tuple[str, ...]) -> str | None:
    for name in names:
        resolved = shutil.which(name)
        if resolved is not None:
            return str(Path(resolved).resolve())
    return None


def _version(command: AgentCommand) -> str:
    try:
        result = subprocess.run(  # noqa: S603
            [command.executable, "--version"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=_VERSION_TIMEOUT_SECONDS,
            check=False,
            env=os.environ.copy(),
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    line = (result.stdout or result.stderr).strip().splitlines()
    return line[0] if line and result.returncode == 0 else ""


def discover_agents(registry: RegistrySnapshot | None = None) -> tuple[DiscoveredAgent, ...]:
    """Detect installed commands without invoking package managers or login flows."""
    return tuple(_detect_profile(profile, registry) for profile in PROFILES.values())


def _detect_profile(profile: AgentProfile, registry: RegistrySnapshot | None) -> DiscoveredAgent:
    executable = _find_executable(profile.executable_names)
    if executable is None:
        return DiscoveredAgent(
            profile,
            None,
            reason=f"No executable named {', '.join(profile.executable_names)} is on PATH.",
        )
    command = AgentCommand(executable, profile.adapter_args)
    reason = None
    if (
        profile.registry_id is not None
        and registry is not None
        and profile.registry_id not in registry.agents
    ):
        reason = f"Registry metadata {profile.registry_id!r} is unavailable."
    return DiscoveredAgent(profile, command, _version(command), reason)


def discovered_by_id(
    agent_id: str, registry: RegistrySnapshot | None = None
) -> DiscoveredAgent | None:
    """Return one read-only detection result by stable Relay profile id."""
    profile = PROFILES.get(agent_id)
    return _detect_profile(profile, registry) if profile is not None else None


__all__ = ["discover_agents", "discovered_by_id"]
