import os
import zipfile
from pathlib import Path
import shutil
from typing import Dict, List, Literal, Tuple, cast

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
from pbt.misc import exec


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


@click.command(name="list")
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
def list_(dev: bool = False, cwd: str = ".", verbose: bool = False):
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
    pl.enforce_version_consistency(freeze_packages=cfg.freeze_packages)
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
    pl.enforce_version_consistency(freeze_packages=cfg.freeze_packages)
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
    pl.enforce_version_consistency(
        VersionConsistent.STRICT, freeze_packages=cfg.freeze_packages
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
def publish(package: List[str], cwd: str = ".", verbose: bool = False):
    """Publish packages"""
    pl, cfg, pkgs = init(cwd, package, verbose)
    pl.enforce_version_consistency(freeze_packages=cfg.freeze_packages)
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
@click.option("--cwd", default=".", help="Override current working directory")
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
    """Install a local python package in editable mode without building it. This works by adding .pth file containing the path
    to the package to the site-packages directory.

    This is a temporary solution for package requiring extension binary but we cannot build the binary,
    so we have to download the prebuilt binary and put it to the src directory before running this command.
    """
    pl, cfg, pkgs = init(cwd, [package], verbose)
    pl.enforce_version_consistency(freeze_packages=cfg.freeze_packages)

    pkg = pl.pkgs[package]
    dep_pkg = pl.pkgs[dep]

    manager = pl.managers[pkg.type]
    assert isinstance(manager, PythonPkgManager) and isinstance(
        pl.managers[dep_pkg.type], PythonPkgManager
    )

    if dep_pkg.type == PackageType.Maturin:
        # manually create a pyproject.toml in poetry first
        try:
            os.rename(
                dep_pkg.location / "pyproject.toml",
                dep_pkg.location / "pyproject.origin.toml",
            )
            pl.managers[PackageType.Poetry].save(dep_pkg)
            dep_pkg.type = PackageType.Poetry
            manager.install_dependency(
                pkg, dep_pkg, skip_dep_deps=dep_pkg.get_all_dependency_names()
            )
        finally:
            os.rename(
                dep_pkg.location / "pyproject.origin.toml",
                dep_pkg.location / "pyproject.toml",
            )
    else:
        manager.install_dependency(
            pkg, dep_pkg, skip_dep_deps=dep_pkg.get_all_dependency_names()
        )


@click.command()
@click.option(
    "-p",
    "--package",
    required=True,
    help="The package to extract the binary from",
)
@click.option("--cwd", default=".", help="Override current working directory")
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help="increase verbosity",
)
@click.option(
    "-s",
    "--source",
    type=click.Choice(["build", "pypi", "build-dev"], case_sensitive=False),
    default="build",
    help="source where we can pull/build the dependency",
)
@click.option(
    "-c",
    "--clean",
    is_flag=True,
    help="whether to clean the dist directory after this command",
)
def obtain_prebuilt_binary(
    package: str,
    cwd: str = ".",
    verbose: bool = False,
    source: Literal["build", "pypi"] = "build",
    clean: bool = False,
):
    pl, cfg, pkgs = init(cwd, [package], verbose)
    pl.enforce_version_consistency(freeze_packages=cfg.freeze_packages)

    pkg = pl.pkgs[package]

    manager = pl.managers[pkg.type]
    assert isinstance(manager, PythonPkgManager)

    dist_dir = (pkg.location / cfg.distribution_dir).absolute()
    shutil.rmtree(dist_dir, ignore_errors=True)
    dist_dir.mkdir()

    if source == "build" or source == "build-dev":
        manager._build_command(pkg, release=source == "build")
    else:
        exec(
            ["pip", "download", pkg.name, "--no-deps"],
            cwd=dist_dir,
            env=manager.passthrough_envs,
            redirect_stderr=True,
        )

    (whl_file,) = [x for x in dist_dir.glob("*.whl")]
    with zipfile.ZipFile(whl_file, "r") as zip_ref:
        zip_ref.extractall(dist_dir)

    pkg_name = pkg.name.replace("-", "_")
    for file in (dist_dir / pkg_name).iterdir():
        if file.name.endswith(".so") or file.name.endswith(".dylib"):
            dest_file = pkg.location / pkg_name / file.name
            if dest_file.exists():
                dest_file.unlink()
            shutil.move(file, pkg.location / pkg_name)

    if clean:
        shutil.rmtree(dist_dir)
