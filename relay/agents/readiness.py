"""Advisory readiness for local setup, without running an agent prompt."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .driver import AgentObservationStore, probe_installed_agents
from .models import DiscoveredAgent, ProbeResult

_LOGIN_COMMANDS = {
    "codex": "codex login",
    "claude": "claude auth login",
    "copilot": "copilot login",
    "cursor": "cursor-agent login",
    "antigravity": "agy",
}


def probe_is_ready(discovered: DiscoveredAgent, result: ProbeResult | None) -> bool:
    """A model inventory proves connectivity; launch still proves its exact route."""
    return bool(
        discovered.installed
        and result is not None
        and result.general_error is None
        and result.models
    )


@dataclass(frozen=True, slots=True)
class AgentReadiness:
    """Public setup facts from one fresh, bounded probe."""

    id: str
    display_name: str
    install_url: str
    installed: bool
    ready: bool
    error_code: str | None
    reason: str | None
    cleanup_warning: str | None
    models: tuple[str, ...]
    login_command: str
    login_guidance: str


def check_agent_readiness(
    cwd: Path,
    *,
    observation_store: AgentObservationStore | None = None,
) -> tuple[AgentReadiness, ...]:
    """Use doctor's probe; never authenticate or send a task during setup."""
    return tuple(
        AgentReadiness(
            id=discovered.profile.agent_id,
            display_name=discovered.profile.display_name,
            install_url=discovered.profile.install_url,
            installed=discovered.installed,
            ready=probe_is_ready(discovered, result),
            error_code=result.general_error.code if result and result.general_error else None,
            reason=result.general_error.message
            if result and result.general_error
            else discovered.reason,
            cleanup_warning=result.cleanup_warning if result else None,
            models=tuple(item.model_value for item in result.models) if result else (),
            login_command=_LOGIN_COMMANDS[discovered.profile.agent_id],
            login_guidance=discovered.profile.login_guidance,
        )
        for discovered, result in probe_installed_agents(cwd, observation_store=observation_store)
    )
