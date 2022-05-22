import importlib.metadata

import click
from loguru import logger

from pbt.console.pbt import install, clean, update, publish, create_setuppy, list
from pbt.console.git import git
from pbt.package.registry.pypi import PyPI


try:
    version = importlib.metadata.version("pab")
except importlib.metadata.PackageNotFoundError:
    version = "0.0.0"


def check_latest():
    latest_version = PyPI.get_instance().get_latest_version("pab")
    if latest_version is not None and version != latest_version:
        logger.warning(
            f"You are using an outdated version of pab. The latest version is {latest_version}, while you are using {version}."
        )


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
cli.add_command(create_setuppy)
cli.add_command(git)
cli.add_command(list)


if __name__ == "__main__":
    check_latest()
    cli()
