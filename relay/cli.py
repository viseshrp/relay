"""The setup and administration command surface for Relay."""

from dataclasses import asdict
import json
from pathlib import Path

import click

from . import __version__ as _version
from .constants import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_WORKERS,
    EXIT_ALREADY_INITIALIZED,
    EXIT_NOT_A_REPOSITORY,
    EXIT_PROJECT_NOT_FOUND,
)
from .errors import ProjectDiscoveryError, ProjectRelinkError, RelayError


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
def up_command(host: str, port: int, no_browser: bool, workers: int) -> None:
    """Start the loopback web application and local worker."""
    del host, port, no_browser, workers
    click.echo("The local runtime is not available in this implementation slice.")


@main.command("doctor")
def doctor_command() -> None:
    """Check local storage, assets, Git, and coding-agent readiness."""
    click.echo("Readiness checks are not available in this implementation slice.")


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
def data_clean_command(
    runs: bool,
    worktrees: bool,
    branches: bool,
    clean_all: bool,
) -> None:
    """Delete confirmed local run data and retained Git state."""
    del runs, worktrees, branches, clean_all
    click.echo("Data cleanup is not available in this implementation slice.")
