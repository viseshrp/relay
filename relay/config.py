from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from relay.copilot.models import DEFAULT_MODEL


PHASE_TYPES = (
    "exploration",
    "planning",
    "plan_critique",
    "plan_correction",
    "execution",
    "review",
)


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def default_phase_model_mapping() -> dict[str, str]:
    return {phase: DEFAULT_MODEL for phase in PHASE_TYPES}


@dataclass(slots=True)
class Settings:
    data_dir: Path
    db_path: Path
    host: str
    port: int
    copilot_cli_path: str
    frontend_dist_dir: Path
    poll_interval_seconds: float
    process_monitor_interval_seconds: float
    default_retry_limit: int
    default_review_fix_loop_limit: int
    default_autopilot: bool

    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.db_path.as_posix()}"


def get_settings() -> Settings:
    root_dir = Path(__file__).resolve().parent.parent
    data_dir = Path(os.getenv("RELAY_DATA_DIR", Path.home() / ".relay")).expanduser()
    db_path = Path(os.getenv("RELAY_DB_PATH", data_dir / "relay.db")).expanduser()
    frontend_dist_dir = Path(os.getenv("RELAY_FRONTEND_DIST", root_dir / "frontend" / "dist"))
    return Settings(
        data_dir=data_dir,
        db_path=db_path,
        host=os.getenv("RELAY_HOST", "127.0.0.1"),
        port=int(os.getenv("RELAY_PORT", "8080")),
        # New Relay installs should target the standalone Copilot CLI directly.
        # The session layer still accepts legacy `gh` overrides and resolves
        # them to `copilot` when possible.
        copilot_cli_path=os.getenv("RELAY_COPILOT_CLI_PATH", "copilot"),
        frontend_dist_dir=frontend_dist_dir,
        poll_interval_seconds=float(os.getenv("RELAY_POLL_INTERVAL", "1.0")),
        process_monitor_interval_seconds=float(os.getenv("RELAY_PROCESS_MONITOR_INTERVAL", "10.0")),
        default_retry_limit=int(os.getenv("RELAY_DEFAULT_RETRY_LIMIT", "5")),
        default_review_fix_loop_limit=int(os.getenv("RELAY_DEFAULT_REVIEW_FIX_LOOP_LIMIT", "5")),
        default_autopilot=_as_bool(os.getenv("RELAY_DEFAULT_AUTOPILOT"), True),
    )
