from io import DEFAULT_BUFFER_SIZE
from pathlib import Path
import shutil
from typing import Dict, List, Tuple, cast

import click
from loguru import logger
import orjson

from pbt.config import PBTConfig
from pbt.package.manager.poetry import Poetry
from pbt.package.manager.maturin import Maturin
from pbt.package.manager.python import PythonPkgManager
from pbt.package.package import PackageType
from pbt.package.pipeline import BTPipeline, VersionConsistent
from pbt.package.registry.pypi import PyPI
from pbt.package.manager.manager import PkgManager, build_cache


def init(
    cwd: str, packages: List[str], verbose: bool
) -> Tuple[BTPipeline, PBTConfig, List[str]]:
    cfg = PBTConfig.from_dir(cwd)
    managers: Dict[PackageType, PkgManager] = {
        PackageType.Poetry: Poetry(cfg),
        PackageType.Maturin: Maturin(cfg),
    }
    for k, v in managers.items():
        if isinstance(v, PythonPkgManager):
            v.set_package_managers(managers)

    pl = BTPipeline(cfg, managers=managers)
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
    cwd: str = ".",
    verbose: bool = False,
):
    """Make package"""
    pl, cfg, pkgs = init(cwd, package, verbose)
    pl.enforce_version_consistency()
    pl.install(sorted(pkgs), include_dev=dev)


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
def build(package: List[str], cwd: str = ".", verbose: bool = False):
    """Build packages"""
    pl, cfg, pkgs = init(cwd, package, verbose)
    with build_cache():
        for pkg_name in pkgs:
            pkg = pl.pkgs[pkg_name]
            manager = pl.managers[pkg.type]
            manager.build(pkg)


@click.command()
@click.option(
    "-p",
    "--package",
    help="The parent package",
)
@click.option(
    "-d",
    "--dep",
    help="The dependency package",
)
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help="increase verbosity",
)
def install_local_pydep(
    package: str,
    dep: str,
    cwd: str = ".",
    verbose: bool = False,
):
    """Install a local python package in editable mode without building it. This is a temporary solution
    for package requiring extension binary but we cannot build the binary, so we have to download the prebuilt binary
    and put it to the src directory.
    """
    pl, cfg, pkgs = init(cwd, [package], verbose)
    pl.enforce_version_consistency()

    pkg = pl.pkgs[package]
    dep_pkg = pl.pkgs[dep]

    manager = pl.managers[pkg.type]
    assert isinstance(manager, PythonPkgManager)

    (site_pkg_dir,) = [
        p
        for p in manager.venv_path(pkg.name, pkg.location).glob(
            f"lib/python*/site-packages"
        )
    ]

    if (site_pkg_dir / dep).exists():
        shutil.rmtree(site_pkg_dir / dep)
    for dir in site_pkg_dir.glob(f"{dep}*.dist-info"):
        shutil.rmtree(dir)

    (site_pkg_dir / f"{dep}-{dep_pkg.version}.dist-info").mkdir(parents=True)
    (
        site_pkg_dir / f"{dep}-{dep_pkg.version}.dist-info" / "direct_url.json"
    ).write_bytes(
        orjson.dumps(
            {
                "dir_info": {"editable": True},
                "url": f"file://{dep_pkg.location.absolute()}",
            }
        )
    )
    (site_pkg_dir / f"{dep}.pth").write_text(str(dep_pkg.location.absolute()))
