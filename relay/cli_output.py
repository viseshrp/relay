"""Human descriptions of administration checks; machine payloads stay in the CLI."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from relay.agents.profiles import PROFILES


def doctor_lines(
    checks: Sequence[Mapping[str, object]],
    agents: Sequence[Mapping[str, object]],
    ready: bool,
    allowed_changes: tuple[str, ...],
) -> list[str]:
    """Explain core failures and optional agents without changing their verdicts."""
    names = {
        "git": "Git repository",
        "database": "Local database",
        "wheel_assets": "Browser application",
        "registry": "Agent registry",
        "agents": "Agent checks",
        "agent_readiness": "At least one ready agent",
    }
    fixes = {
        "git": "Run git status --short. Commit or set aside blocking files, then run relay doctor.",
        "database": "Check disk space and folder permissions, then run relay doctor.",
        "wheel_assets": "Reinstall Relay: pip install --force-reinstall relay-app",
        "registry": "Check your internet connection, then run relay doctor.",
        "agents": "Follow the agent guidance below, then run relay doctor.",
        "agent_readiness": "Install and sign in to one agent below, then run relay doctor.",
    }
    reasons = {
        "git_dirty": "Uncommitted code or staged files block a run.",
        "wheel_assets_missing": "The browser application files are missing.",
        "registry_stale": "The agent registry cache is out of date.",
        "agent_not_ready": "No supported agent is ready.",
    }
    lines = ["Relay checks"]
    for check in checks:
        key = str(check["id"])
        if key.startswith("agent:"):
            continue
        ok = bool(check["ok"])
        lines.append(f"{'✓' if ok else '✗'} {names.get(key, key)}")
        if not ok:
            message = (
                check.get("message")
                or check.get("warning")
                or reasons.get(str(check.get("code")), "This check failed.")
            )
            lines.append(f"  {message}")
            changes = check.get("changes")
            if isinstance(changes, list):
                lines.extend(f"  {change}" for change in changes)
            lines.append(f"  Next: {check.get('next_action') or fixes[key]}")
    if allowed_changes:
        lines.append("Warning: These uncommitted starter files or reports do not block launch:")
        lines.extend(f"  {change}" for change in allowed_changes)
    lines.append("Agents (one ready agent is enough)")
    for agent in agents:
        profile = PROFILES[str(agent["id"])]
        if agent["ready"]:
            lines.append(f"✓ {profile.display_name}: Ready")
        else:
            installed = bool(agent["installed"])
            lines.append(
                f"✗ {profile.display_name}: {'Not ready' if installed else 'Not installed'}"
            )
            if agent.get("reason"):
                lines.append(f"  {agent['reason']}")
            lines.append(
                f"  Next: {profile.login_guidance} Run relay doctor again."
                if installed
                else f"  Install: {profile.install_url}"
            )
        if agent.get("cleanup_warning"):
            lines.append(f"  Warning: {agent['cleanup_warning']}")
    lines.append("Ready. Run relay up to open Relay." if ready else "Fix the failed checks above.")
    return lines
