"""Validated global settings, project inheritance, and conflict-safe saves."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from typing import Literal, Protocol

from pydantic import Field, ValidationError

from relay.config import RelayConfig, load_config, validate_config
from relay.errors import ConfigError, PersistenceError, SettingsConflictError
from relay.manage import MigrationLock
from relay.paths import config_dir, ensure_private_dir, safe_resolve, settings_path
from relay.workflows.defaults import WorkflowDefaults
from relay.workflows.schema import StrictModel


class ProjectDefaults(StrictModel):
    """Omitted project fields inherit the corresponding installation setting."""

    agent_preferences: list[str] = Field(default_factory=list)
    cleanup_policy: Literal["clean_on_success", "retain", "merge_on_success"] = "clean_on_success"
    workflow_defaults: WorkflowDefaults = Field(default_factory=WorkflowDefaults)


class SettingsStore(Protocol):
    def project_defaults(self, project_id: str) -> dict[str, object]: ...
    def save_project_defaults(
        self, project_id: str, values: dict[str, object], expected_revision: str
    ) -> None: ...


def revision(values: Mapping[str, object]) -> str:
    return sha256(json.dumps(dict(values), sort_keys=True).encode("utf-8")).hexdigest()


def validate_project_defaults(raw: object) -> dict[str, object]:
    try:
        values = ProjectDefaults.model_validate(raw).model_dump(mode="json", exclude_unset=True)
        # Reuse owner settings validation for the legacy agent-order contract.
        validate_config({key: value for key, value in values.items() if key != "workflow_defaults"})
    except ValidationError as error:
        issues = [
            f"{'.'.join(str(p) for p in row['loc'])}: {row['msg'].removeprefix('Value error, ')}"
            for row in error.errors(include_url=False, include_context=False)
        ]
        message = "Invalid project defaults:\n" + "\n".join(issues)
        raise ConfigError(message) from None
    else:
        return values


def _merge(base: Mapping[str, object], overrides: Mapping[str, object]) -> dict[str, object]:
    result = dict(base)
    if "model" in overrides and overrides["model"] != base.get("model"):
        # Provider options are bound to the model for which they were chosen.
        result.pop("effort", None)
        result.pop("permission_mode", None)
    for key, value in overrides.items():
        old = result.get(key)
        # Complete maps let a project remove inherited commands or variables.
        result[key] = (
            _merge(old, value)
            if key not in {"commands", "env"} and isinstance(old, dict) and isinstance(value, dict)
            else value
        )
    return result


def effective_config(
    store: SettingsStore, project_id: str, overrides: object | None = None
) -> RelayConfig:
    global_config = load_config()
    values = validate_project_defaults(
        store.project_defaults(project_id) if overrides is None else overrides
    )
    return validate_config(_merge(global_config.to_dict(), values))


def read_settings() -> dict[str, object]:
    path = safe_resolve(config_dir(), settings_path().name)
    try:
        exists = path.exists()
        content = path.read_bytes() if exists else b""
        config = validate_config(json.loads(content)) if exists else RelayConfig()
    except (OSError, UnicodeError, json.JSONDecodeError):
        message = "Relay could not read the settings file."
        raise PersistenceError(message) from None
    return {
        "settings": {
            **config.to_dict(),
            "workflow_defaults": config.workflow_defaults.model_dump(mode="json"),
        },
        "revision": sha256(content).hexdigest(),
    }


def save_settings(raw: object, expected_revision: str) -> dict[str, object]:
    config = validate_config(raw)
    path = safe_resolve(config_dir(), settings_path().name)
    temporary: Path | None = None
    try:
        ensure_private_dir(path.parent)
        # A concurrent browser must reload rather than overwrite another saved choice.
        with MigrationLock(path.parent / "settings.lock", timeout=0, purpose="settings"):
            current = read_settings()
            if current["revision"] != expected_revision:
                message = "Settings changed in another window. Reload before saving."
                raise SettingsConflictError(message)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent, prefix=".settings-", delete=False
            ) as stream:
                temporary = Path(stream.name)
                stream.write(json.dumps(config.to_dict(), indent=2, sort_keys=True) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            temporary = None
            return read_settings()
    except OSError:
        message = "Relay could not save settings. Previous settings remain on disk."
        raise PersistenceError(message) from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_project_settings(store: SettingsStore, project_id: str) -> dict[str, object]:
    overrides = validate_project_defaults(store.project_defaults(project_id))
    effective = effective_config(store, project_id)
    return {
        "overrides": overrides,
        "revision": revision(overrides),
        "effective": {
            **effective.to_dict(),
            "workflow_defaults": effective.workflow_defaults.model_dump(mode="json"),
        },
    }


def save_project_settings(
    store: SettingsStore, project_id: str, raw: object, expected_revision: str
) -> dict[str, object]:
    values = validate_project_defaults(raw)
    effective_config(store, project_id, values)
    store.save_project_defaults(project_id, values, expected_revision)
    return read_project_settings(store, project_id)
