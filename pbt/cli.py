import importlib.metadata

import click
from loguru import logger

from pbt.console.pbt import install, clean, update, publish, build_editable, list
from pbt.console.git import git


try:
    version = importlib.metadata.version("pab")
except importlib.metadata.PackageNotFoundError:
    version = "0.0.0"


@click.group(
    help=f"PBT ({version}) -- a build tool for multi-projects that leverages package registries (pypi, npmjs, etc.)"
)
@click.version_option(version)
def cli():
    pass


cli.add_command(install)
cli.add_command(clean)
cli.add_command(publish)
cli.add_command(update)
cli.add_command(build_editable)
cli.add_command(git)
cli.add_command(list)

if __name__ == "__main__":
    cli()
