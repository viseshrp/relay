"""The setup and administration command surface for Relay."""

import click

from . import __version__ as _version
from .constants import DEFAULT_HOST, DEFAULT_PORT, DEFAULT_WORKERS


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(_version, "-v", "--version")
def main() -> None:
    """Run Relay setup and local administration commands.

    \b
    Workflow authoring and run control are available in the browser started by
    `relay up`.
    """


@main.command("init")
def init_command() -> None:
    """Create a blank .relay project surface in the current Git repository."""
    click.echo("Project initialization is not available in this implementation slice.")


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
def project_list_command() -> None:
    """List projects registered in central Relay storage."""
    click.echo("Project registration is not available in this implementation slice.")


@project_group.command("relink")
@click.argument("path", type=click.Path(path_type=str))
@click.argument("newpath", type=click.Path(path_type=str))
def project_relink_command(path: str, newpath: str) -> None:
    """Relink a registered project after it moves on disk."""
    del path, newpath
    click.echo("Project relinking is not available in this implementation slice.")


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
