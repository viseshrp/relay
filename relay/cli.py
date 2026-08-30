"The console script for relay."

import click

from . import __version__ as _version
from .relay import do_stuff


@click.argument(
    "stuff",
    metavar="<what_you_worked_on>",
    nargs=-1,
    required=False,
    type=click.STRING,
)
@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(_version, "-v", "--version")
def main(stuff: tuple[str, ...]) -> None:
    """Relay CLI.

    \b
    Example usages:
    """
    do_stuff(stuff)
