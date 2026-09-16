"""The fixed Phase 1 compatibility profiles for Relay's five agents."""

from __future__ import annotations

from .models import AgentProfile

_NO_CLIENT_MEDIATION = frozenset()
_ACP_PERMISSION_PROFILES = frozenset({"interactive"})

PROFILES: dict[str, AgentProfile] = {
    "codex": AgentProfile(
        agent_id="codex",
        display_name="Codex",
        driver="acp",
        registry_id="codex-acp",
        executable_names=("codex-acp",),
        adapter_args=(),
        model_config_id="model",
        required_client_methods=_NO_CLIENT_MEDIATION,
        permission_profiles=_ACP_PERMISSION_PROFILES,
        install_url="https://github.com/agentclientprotocol/codex-acp",
        login_guidance="Authenticate the Codex CLI before launching its ACP adapter.",
    ),
    "claude": AgentProfile(
        agent_id="claude",
        display_name="Claude Code",
        driver="acp",
        registry_id="claude-acp",
        executable_names=("claude-agent-acp",),
        adapter_args=(),
        model_config_id="model",
        required_client_methods=_NO_CLIENT_MEDIATION,
        permission_profiles=_ACP_PERMISSION_PROFILES,
        install_url="https://github.com/agentclientprotocol/claude-agent-acp",
        login_guidance="Authenticate Claude Code before launching its ACP adapter.",
    ),
    "copilot": AgentProfile(
        agent_id="copilot",
        display_name="GitHub Copilot CLI",
        driver="acp",
        registry_id="github-copilot-cli",
        executable_names=("copilot",),
        adapter_args=("--acp",),
        model_config_id="model",
        required_client_methods=_NO_CLIENT_MEDIATION,
        permission_profiles=_ACP_PERMISSION_PROFILES,
        install_url="https://docs.github.com/en/copilot/how-tos/set-up/install-copilot-cli",
        login_guidance="Run copilot login and complete GitHub authentication first.",
    ),
    "cursor": AgentProfile(
        agent_id="cursor",
        display_name="Cursor CLI",
        driver="acp",
        registry_id="cursor",
        executable_names=("cursor-agent",),
        adapter_args=("acp",),
        model_config_id="model",
        required_client_methods=_NO_CLIENT_MEDIATION,
        permission_profiles=_ACP_PERMISSION_PROFILES,
        install_url="https://cursor.com/docs/cli/acp",
        login_guidance="Run cursor-agent login before starting Relay.",
    ),
    "antigravity": AgentProfile(
        agent_id="antigravity",
        display_name="Antigravity",
        driver="antigravity",
        registry_id=None,
        executable_names=("agy",),
        adapter_args=(),
        model_config_id=None,
        required_client_methods=_NO_CLIENT_MEDIATION,
        permission_profiles=frozenset({"respect_settings", "auto_approve"}),
        install_url="https://antigravity.google/docs/cli/install/",
        login_guidance="Authenticate once in an interactive agy session or configure its API key.",
    ),
}


def profile_for(agent_id: str) -> AgentProfile | None:
    """Return compatibility metadata only for the locked five-agent scope."""
    return PROFILES.get(agent_id)


__all__ = ["PROFILES", "profile_for"]
