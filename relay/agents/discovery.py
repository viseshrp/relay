"""Read-only executable discovery for Relay's fixed agent set."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

from .models import AgentCommand, DiscoveredAgent, RegistrySnapshot
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
    results: list[DiscoveredAgent] = []
    for profile in PROFILES.values():
        executable = _find_executable(profile.executable_names)
        if executable is None:
            results.append(
                DiscoveredAgent(
                    profile,
                    None,
                    reason=f"No executable named {', '.join(profile.executable_names)} is on PATH.",
                )
            )
            continue
        command = AgentCommand(executable, profile.adapter_args)
        detected_version = _version(command)
        reason = None
        if profile.registry_id is not None and registry is not None:
            metadata = registry.agents.get(profile.registry_id)
            if metadata is None:
                reason = f"Registry metadata {profile.registry_id!r} is unavailable."
        results.append(DiscoveredAgent(profile, command, detected_version, reason))
    return tuple(results)


def discovered_by_id(
    agent_id: str, registry: RegistrySnapshot | None = None
) -> DiscoveredAgent | None:
    """Return one read-only detection result by stable Relay profile id."""
    return next(
        (item for item in discover_agents(registry) if item.profile.agent_id == agent_id),
        None,
    )


__all__ = ["discover_agents", "discovered_by_id"]
