"""Owner settings loaded from Relay's platform-specific config directory."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path

from .constants import DEFAULT_HOST, DEFAULT_PORT, DEFAULT_WORKERS, LOOPBACK_HOSTS
from .errors import ConfigError
from .execution.state import CleanupPolicy
from .paths import settings_path
from .workflows.defaults import WorkflowDefaults, validate_defaults

_ALLOWED_KEYS: set[str] = {
    "agent_preferences",
    "cleanup_policy",
    "host",
    "login_required",
    "port",
    "workers",
    "workflow_defaults",
}


@dataclass(frozen=True, slots=True)
class RelayConfig:
    """Validated owner settings with conservative local-only defaults."""

    agent_preferences: tuple[str, ...] = ()
    cleanup_policy: str = "clean_on_success"
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    workers: int = DEFAULT_WORKERS
    login_required: bool = True
    workflow_defaults: WorkflowDefaults = field(default_factory=WorkflowDefaults)

    def to_dict(self) -> dict[str, object]:
        """Return JSON-compatible settings for diagnostics and UI reads."""
        values = asdict(self)
        values.pop("workflow_defaults")
        if self.workflow_defaults.model_fields_set:
            values["workflow_defaults"] = self.workflow_defaults.model_dump(
                mode="json", exclude_unset=True
            )
        values["agent_preferences"] = list(self.agent_preferences)
        return values


def validate_config(raw: object) -> RelayConfig:
    if not isinstance(raw, dict):
        message = "Relay settings must be a JSON object."
        raise ConfigError(message)
    unknown = sorted(set(raw) - _ALLOWED_KEYS)
    if unknown:
        message = f"Unknown Relay setting: {', '.join(unknown)}."
        raise ConfigError(
            message,
            next_action="Remove the unknown setting and run the command again.",
        )

    preferences = raw.get("agent_preferences", [])
    if not isinstance(preferences, list) or not all(
        isinstance(value, str) and value for value in preferences
    ):
        message = "agent_preferences must be a list of non-empty strings."
        raise ConfigError(message)
    cleanup_policy = raw.get("cleanup_policy", "clean_on_success")
    if cleanup_policy not in {policy.value for policy in CleanupPolicy}:
        message = "cleanup_policy must be clean_on_success, retain, or merge_on_success."
        raise ConfigError(message)
    host = raw.get("host", DEFAULT_HOST)
    if host not in LOOPBACK_HOSTS:
        message = "Relay may bind only to a loopback address."
        raise ConfigError(message)
    port = raw.get("port", DEFAULT_PORT)
    workers = raw.get("workers", DEFAULT_WORKERS)
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65_535:
        message = "port must be an integer from 1 through 65535."
        raise ConfigError(message)
    if not isinstance(workers, int) or isinstance(workers, bool) or workers < 1:
        message = "workers must be a positive integer."
        raise ConfigError(message)
    login_required = raw.get("login_required", True)
    if not isinstance(login_required, bool):
        message = "login_required must be true or false."
        raise ConfigError(message)
    return RelayConfig(
        tuple(preferences),
        cleanup_policy,
        host,
        port,
        workers,
        login_required,
        validate_defaults(raw.get("workflow_defaults", {})),
    )


def load_config(path: Path | None = None) -> RelayConfig:
    """Load settings without creating files or directories."""
    source = path or settings_path()
    if not source.exists():
        return RelayConfig()
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        message = f"Could not read Relay settings at {source}."
        raise ConfigError(
            message,
            next_action="Fix or remove the settings file and run the command again.",
        ) from None
    return validate_config(raw)
