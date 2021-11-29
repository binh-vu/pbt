import importlib.metadata

import click
from loguru import logger

from pbt.console.pbt import install, clean, update, publish
from pbt.console.git import git


@click.group()
@click.version_option(importlib.metadata.version("pab"))
def cli():
    pass


cli.add_command(install)
cli.add_command(clean)
cli.add_command(publish)
cli.add_command(update)
cli.add_command(git)


if __name__ == "__main__":
    cli()
