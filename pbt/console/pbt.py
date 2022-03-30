from io import DEFAULT_BUFFER_SIZE
from typing import List, Tuple

import click
from loguru import logger

from pbt.config import PBTConfig
from pbt.package.manager.poetry import Poetry
from pbt.package.package import PackageType
from pbt.package.pipeline import BTPipeline, VersionConsistent
from pbt.package.registry.pypi import PyPI


def init(
    cwd: str, packages: List[str], verbose: bool
) -> Tuple[BTPipeline, PBTConfig, List[str]]:
    cfg = PBTConfig.from_dir(cwd)
    pl = BTPipeline(
        cfg.cwd,
        managers={
            PackageType.Poetry: Poetry(cfg),
        },
    )
    pl.discover()

    if len(packages) == 0:
        pkgs = set(pl.pkgs.keys())
    else:
        pkgs = set(packages)

    if len(pkgs.difference(pl.pkgs.keys())) > 0:
        raise Exception(
            f"Passing unknown packages: {pkgs.difference(pl.pkgs.keys())}. Available options: {list(pl.pkgs.keys())}"
        )

    return pl, cfg, sorted(pkgs)


@click.command()
@click.option(
    "-d",
    "--dev",
    is_flag=True,
    help="Whether to print to the local (inter-) dependencies",
)
@click.option("--cwd", default=".", help="Override current working directory")
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help="increase verbosity",
)
def list(dev: bool = False, cwd: str = ".", verbose: bool = False):
    """List all packages in the current project, and their dependencies if required."""
    pl, cfg, pkgs = init(cwd, [], verbose)
    for pkg in pl.pkgs.values():
        print_children = (
            dev and any(True for dep in pkg.dependencies.keys() if dep in pl.pkgs) > 0
        )
        print(f"{pkg.name} ({pkg.version})" + (":" if print_children else ""))
        if dev:
            for dep in pkg.dependencies.keys():
                if dep in pkgs:
                    print(f"\t- {dep} ({pl.pkgs[dep].version})")


@click.command()
@click.option(
    "-p",
    "--package",
    multiple=True,
    help="Specify the package that we want to build. If empty, build all packages",
)
@click.option(
    "-d",
    "--dev",
    is_flag=True,
    help="Whether to install dev-dependencies as well",
)
@click.option(
    "-e",
    "--editable",
    is_flag=True,
    help="Whether to install the package and its local dependencies in editable mode",
)
@click.option("--cwd", default=".", help="Override current working directory")
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help="increase verbosity",
)
def install(
    package: List[str],
    dev: bool = False,
    editable: bool = False,
    cwd: str = ".",
    verbose: bool = False,
):
    """Make package"""
    pl, cfg, pkgs = init(cwd, package, verbose)
    pl.enforce_version_consistency()
    pl.install(sorted(pkgs), include_dev=dev, editable=editable)


@click.command()
@click.option(
    "-p",
    "--package",
    multiple=True,
    help="Specify the package that we want to build. If empty, build all packages",
)
@click.option("--cwd", default=".", help="Override current working directory")
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help="increase verbosity",
)
def clean(package: List[str], cwd: str = ".", verbose: bool = False):
    """Clean packages' build & lock files"""
    pl, cfg, pkgs = init(cwd, package, verbose)
    pl.enforce_version_consistency()
    for pkg_name in pkgs:
        pkg = pl.pkgs[pkg_name]
        pl.managers[pkg.type].clean(pkg)


@click.command()
@click.option("--cwd", default=".", help="Override current working directory")
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help="increase verbosity",
)
def update(cwd: str = ".", verbose: bool = False):
    """Update all package inter-dependencies"""
    pl, cfg, pkgs = init(cwd, [], verbose)
    pl.enforce_version_consistency(VersionConsistent.STRICT)


@click.command()
@click.option(
    "-p",
    "--package",
    multiple=True,
    help="Specify the package that we want to build. If empty, build all packages",
)
@click.option("--cwd", default=".", help="Override current working directory")
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help="increase verbosity",
)
def publish(package: List[str], cwd: str = ".", verbose: bool = False):
    """Publish packages"""
    pl, cfg, pkgs = init(cwd, package, verbose)
    pl.enforce_version_consistency()
    pl.publish(
        pkgs,
        {
            PackageType.Poetry: PyPI.get_instance(),
        },
    )


@click.command()
@click.option(
    "-p",
    "--package",
    multiple=True,
    help="Specify the package that we want to build. If empty, build all packages",
)
@click.option("--cwd", default=".", help="Override current working directory")
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help="increase verbosity",
)
def build_editable(package: List[str], cwd: str = ".", verbose: bool = False):
    """Build packages in editable mode"""
    pl, cfg, pkgs = init(cwd, package, verbose)
    pl.build_editable(package)
