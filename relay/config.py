"""Owner settings loaded from Relay's platform-specific config directory."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path

from .constants import DEFAULT_HOST, DEFAULT_PORT, DEFAULT_WORKERS
from .errors import ConfigError
from .paths import global_prompts_dir, settings_path

_ALLOWED_KEYS = {
    "agent_preferences",
    "cleanup_policy",
    "host",
    "port",
    "workers",
}


@dataclass(frozen=True, slots=True)
class RelayConfig:
    """Validated owner settings with conservative local-only defaults."""

    agent_preferences: tuple[str, ...] = ()
    cleanup_policy: str = "clean_on_success"
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    workers: int = DEFAULT_WORKERS

    def to_dict(self) -> dict[str, object]:
        """Return JSON-compatible settings for diagnostics and UI reads."""
        values = asdict(self)
        values["agent_preferences"] = list(self.agent_preferences)
        return values


def _validate_config(raw: object) -> RelayConfig:
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
    if cleanup_policy not in {"clean_on_success", "retain"}:
        message = "cleanup_policy must be clean_on_success or retain."
        raise ConfigError(message)
    host = raw.get("host", DEFAULT_HOST)
    if host not in {"127.0.0.1", "localhost", "::1"}:
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
    return RelayConfig(tuple(preferences), cleanup_policy, host, port, workers)


def load_config(path: Path | None = None) -> RelayConfig:
    """Load settings without creating files or directories."""
    source = path or settings_path()
    if not source.exists():
        return RelayConfig()
    try:
        raw: object = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        message = f"Could not read Relay settings at {source}."
        raise ConfigError(
            message,
            next_action="Fix or remove the settings file and run the command again.",
        ) from None
    return _validate_config(raw)


def prompt_root(*, create: bool = False) -> Path:
    """Return the configured global-prompt root."""
    return global_prompts_dir(create=create)
