"""The setup and administration command surface for Relay."""

from dataclasses import asdict
import json
import logging
from pathlib import Path

import click
from click.core import ParameterSource

from . import __version__ as _version
from .constants import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_WORKERS,
    EXIT_ALREADY_INITIALIZED,
    EXIT_DOCTOR_FAILED,
    EXIT_NOT_A_REPOSITORY,
    EXIT_NOTHING_TO_CLEAN,
    EXIT_PROJECT_NOT_FOUND,
    EXIT_SUPERVISOR,
    EXIT_UP_CONFIG,
)
from .errors import (
    ConfigError,
    PersistenceError,
    ProjectDiscoveryError,
    ProjectRelinkError,
    RelayError,
)

LOGGER = logging.getLogger(__name__)


def _render_error(error: RelayError) -> str:
    """Render the shared envelope as stable, machine-readable CLI JSON."""
    return json.dumps(error.to_envelope(), sort_keys=True)


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(_version, "-v", "--version")
def main() -> None:
    """Run Relay setup and local administration commands.

    \b
    Workflow authoring and run control are available in the browser started by
    `relay up`.
    """


@main.command("init")
@click.pass_context
def init_command(context: click.Context) -> None:
    """Create a blank .relay project surface in the current Git repository."""
    from .projects.service import initialize_project

    try:
        result = initialize_project()
    except ProjectDiscoveryError as error:
        click.echo(_render_error(error), err=True)
        context.exit(EXIT_NOT_A_REPOSITORY)
    if not result.created:
        click.echo(f"Relay is already initialized at {result.relay_root}.", err=True)
        context.exit(EXIT_ALREADY_INITIALIZED)
    click.echo(f"Initialized blank Relay project at {result.relay_root}.")


@main.command("up")
@click.option("--host", default=DEFAULT_HOST, show_default=True)
@click.option("--port", default=DEFAULT_PORT, show_default=True, type=click.IntRange(1, 65_535))
@click.option("--no-browser", is_flag=True, help="Do not open the browser after startup.")
@click.option("--workers", default=DEFAULT_WORKERS, show_default=True, type=click.IntRange(min=1))
@click.pass_context
def up_command(
    context: click.Context,
    host: str,
    port: int,
    no_browser: bool,
    workers: int,
) -> None:
    """Start the loopback web application and local worker."""
    from .config import RelayConfig, load_config
    from .web.supervisor import run_supervisor

    try:
        stored = load_config()
        effective = RelayConfig(
            stored.agent_preferences,
            stored.cleanup_policy,
            (
                stored.host
                if context.get_parameter_source("host") is ParameterSource.DEFAULT
                else host
            ),
            (
                stored.port
                if context.get_parameter_source("port") is ParameterSource.DEFAULT
                else port
            ),
            (
                stored.workers
                if context.get_parameter_source("workers") is ParameterSource.DEFAULT
                else workers
            ),
        )
        run_supervisor(
            effective,
            open_browser=not no_browser,
            on_ready=lambda url: click.echo(f"Relay is ready at {url}"),
        )
    except ConfigError as error:
        click.echo(_render_error(error), err=True)
        context.exit(EXIT_UP_CONFIG)
    except RelayError as error:
        click.echo(_render_error(error), err=True)
        context.exit(EXIT_SUPERVISOR)
    except Exception:
        LOGGER.exception("Unhandled Relay supervisor failure")
        error = PersistenceError(
            "Relay's local runtime failed unexpectedly.",
            next_action="Inspect the local Relay log before restarting.",
        )
        click.echo(_render_error(error), err=True)
        context.exit(EXIT_SUPERVISOR)
    click.echo("Relay stopped cleanly.")


@main.command("doctor")
@click.pass_context
def doctor_command(context: click.Context) -> None:
    """Check local storage, assets, Git, and coding-agent readiness."""
    from .agents.discovery import discover_agents
    from .agents.driver import probe_installed_agents
    from .agents.registry import load_registry
    from .manage import apply_migrations
    from .projects.discovery import discover_relay_root, git_root
    from .vcs.cleanliness import status_porcelain

    checks: list[dict[str, object]] = []
    repository = Path.cwd().resolve()
    try:
        repository = git_root()
        relay_root = discover_relay_root()
        changes = status_porcelain(repository)
        checks.append(
            {
                "id": "git",
                "ok": not changes,
                "code": "ok" if not changes else "git_dirty",
                "repository": str(repository),
                "relay_root": str(relay_root),
                "changes": list(changes),
            }
        )
    except RelayError as error:
        checks.append({"id": "git", "ok": False, **error.to_envelope()})

    database_ready = False
    try:
        apply_migrations()
        from .web.repositories import DjangoAgentStore
        from .web.settings import DATABASES

        database_ready = True
        checks.append(
            {
                "id": "database",
                "ok": True,
                "code": "ok",
                "path": str(DATABASES["default"]["NAME"]),
                "migrations": "current",
            }
        )
    except RelayError as error:
        checks.append({"id": "database", "ok": False, **error.to_envelope()})

    from .web.static_view import STATIC_ROOT

    index = STATIC_ROOT / "index.html"
    asset_files = tuple(path for path in (STATIC_ROOT / "assets").glob("**/*") if path.is_file())
    assets_ready = index.is_file() and bool(asset_files)
    checks.append(
        {
            "id": "wheel_assets",
            "ok": assets_ready,
            "code": "ok" if assets_ready else "wheel_assets_missing",
            "index": str(index),
            "asset_count": len(asset_files),
        }
    )

    registry = None
    registry_payload: dict[str, object]
    try:
        registry = load_registry()
        registry_ready = not registry.stale
        registry_payload = {
            "source_url": registry.source_url,
            "fetched_at": registry.fetched_at.isoformat(),
            "cache_age_seconds": round(registry.cache_age_seconds, 3),
            "stale": registry.stale,
            "warning": registry.warning,
        }
        checks.append(
            {
                "id": "registry",
                "ok": registry_ready,
                "code": "ok" if registry_ready else "registry_stale",
                **registry_payload,
            }
        )
    except RelayError as error:
        registry_payload = error.to_envelope()
        checks.append({"id": "registry", "ok": False, **registry_payload})

    try:
        rows = probe_installed_agents(
            repository,
            registry=registry,
            observation_store=DjangoAgentStore() if database_ready else None,
        )
    except RelayError as error:
        LOGGER.exception("Relay agent readiness probing failed")
        checks.append({"id": "agents", "ok": False, **error.to_envelope()})
        rows = tuple((item, None) for item in discover_agents(registry))
    except Exception:
        LOGGER.exception("Unexpected Relay agent readiness probing failure")
        error = PersistenceError("Relay could not complete agent readiness probes.")
        checks.append({"id": "agents", "ok": False, **error.to_envelope()})
        rows = tuple((item, None) for item in discover_agents(registry))

    agents: list[dict[str, object]] = []
    for discovered, result in rows:
        models = [] if result is None else [item.model_value for item in result.models]
        ready = (
            discovered.installed
            and result is not None
            and result.general_error is None
            and bool(models)
        )
        registry_metadata = (
            registry.agents.get(discovered.profile.registry_id)
            if registry is not None and discovered.profile.registry_id is not None
            else None
        )
        row: dict[str, object] = {
            "id": discovered.profile.agent_id,
            "installed": discovered.installed,
            "ready": ready,
            "command": (
                list(discovered.command.argv()) if discovered.command is not None else None
            ),
            "detected_version": discovered.detected_version,
            "models": models,
            "reason": (
                result.general_error
                if result is not None and result.general_error is not None
                else discovered.reason
            ),
            "cleanup_warning": result.cleanup_warning if result is not None else None,
            "install_url": discovered.profile.install_url,
            "registry": (
                {
                    "id": registry_metadata.agent_id,
                    "version": registry_metadata.version,
                    "distributions": [
                        {
                            "manager": item.manager,
                            "package": item.package,
                            "version": item.version,
                            "args": list(item.args),
                        }
                        for item in registry_metadata.distributions
                    ],
                }
                if registry_metadata is not None
                else None
            ),
        }
        agents.append(row)
        checks.append(
            {
                "id": f"agent:{discovered.profile.agent_id}",
                "ok": ready,
                "code": "ok" if ready else "agent_not_ready",
                "models": models,
                "reason": row["reason"],
            }
        )
    all_ready = all(bool(check["ok"]) for check in checks)
    click.echo(
        json.dumps(
            {
                "ok": all_ready,
                "temporary_sessions": True,
                "checks": checks,
                "registry": registry_payload,
                "agents": agents,
            },
            sort_keys=True,
        )
    )
    if not all_ready:
        context.exit(EXIT_DOCTOR_FAILED)


@main.group("project")
def project_group() -> None:
    """Inspect or relink registered projects."""


@project_group.command("list")
@click.pass_context
def project_list_command(context: click.Context) -> None:
    """List projects registered in central Relay storage."""
    from .manage import apply_migrations

    try:
        apply_migrations()
        from .projects.service import list_registered_projects
        from .web.repositories import DjangoProjectStore

        records = list_registered_projects(DjangoProjectStore())
    except RelayError as error:
        click.echo(_render_error(error), err=True)
        context.exit(error.cli_exit_code)
    click.echo(json.dumps({"projects": [asdict(record) for record in records]}, sort_keys=True))


@project_group.command("relink")
@click.argument("path", type=click.Path(path_type=Path))
@click.argument(
    "newpath", type=click.Path(path_type=Path, exists=True, file_okay=False, resolve_path=True)
)
@click.pass_context
def project_relink_command(context: click.Context, path: Path, newpath: Path) -> None:
    """Relink a registered project after it moves on disk."""
    from .manage import apply_migrations

    try:
        apply_migrations()
        from .projects.service import relink_project
        from .web.repositories import DjangoProjectStore

        record = relink_project(DjangoProjectStore(), path, newpath)
    except ProjectRelinkError as error:
        click.echo(_render_error(error), err=True)
        context.exit(EXIT_PROJECT_NOT_FOUND)
    except RelayError as error:
        click.echo(_render_error(error), err=True)
        context.exit(error.cli_exit_code)
    click.echo(json.dumps({"project": asdict(record)}, sort_keys=True))


@main.group("data")
def data_group() -> None:
    """Inspect or delete retained local Relay data."""


@data_group.command("clean")
@click.option("--runs", is_flag=True, help="Delete selected run records and snapshots.")
@click.option("--worktrees", is_flag=True, help="Remove preserved run worktrees.")
@click.option("--branches", is_flag=True, help="Delete retained Relay run branches.")
@click.option("--all", "clean_all", is_flag=True, help="Select every cleanup category.")
@click.pass_context
def data_clean_command(
    context: click.Context,
    runs: bool,
    worktrees: bool,
    branches: bool,
    clean_all: bool,
) -> None:
    """Delete confirmed local run data and retained Git state."""
    from .manage import apply_migrations
    from .projects.service import register_current_project

    selected = (
        ("all",)
        if clean_all
        else tuple(
            scope
            for scope, enabled in (
                ("worktrees", worktrees),
                ("branches", branches),
                ("runs", runs),
            )
            if enabled
        )
    )
    if not selected:
        click.echo(json.dumps({"deleted": {}}, sort_keys=True))
        context.exit(EXIT_NOTHING_TO_CLEAN)
    if clean_all and (runs or worktrees or branches):
        error = ConfigError("Use --all by itself or select individual cleanup categories.")
        click.echo(_render_error(error), err=True)
        context.exit(error.cli_exit_code)
    selection = ", ".join(selected)
    if not click.confirm(f"Delete retained Relay {selection} data for this project?"):
        raise click.Abort()
    try:
        apply_migrations()
        from .web.repositories import DjangoExecutionStore, DjangoProjectStore

        project = register_current_project(DjangoProjectStore(), Path.cwd())
        store = DjangoExecutionStore()
        deleted = {
            "runs": 0,
            "worktrees": 0,
            "branches": 0,
            "attempt_refs": 0,
            "artifact_roots": 0,
            "logs": 0,
        }
        for scope in selected:
            result = store.clean_project_data(project.id, scope)
            for key, value in result.items():
                deleted[key] += value
    except RelayError as error:
        click.echo(_render_error(error), err=True)
        context.exit(error.cli_exit_code)
    click.echo(json.dumps({"deleted": deleted}, sort_keys=True))
    if not any(deleted.values()):
        context.exit(EXIT_NOTHING_TO_CLEAN)
