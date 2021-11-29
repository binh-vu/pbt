import importlib.metadata
import os
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import List, Literal, Tuple

import click
from loguru import logger

from pbt.config import PBTConfig
from pbt.diff import RemoteDiff
from pbt.git import Git
from pbt.package.manager.poetry import Poetry
from pbt.package.package import PackageType
from pbt.package.pipeline import BTPipeline, VersionConsistent

from pbt.pypi import PyPI


def preprocessing(
    cwd: str, packages: List[str]
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
@click.option("--cwd", default="", help="Override current working directory")
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
    cwd: str = "",
    verbose: bool = False,
):
    """Make package"""
    pl, cfg, pkgs = preprocessing(cwd, package)

    pl.enforce_version_consistency()
    pl.install(sorted(pkgs), include_dev=dev, editable=editable)


@click.command()
@click.option(
    "-p",
    "--package",
    multiple=True,
    help="Specify the package that we want to build. If empty, build all packages",
)
@click.option("--cwd", default="", help="Override current working directory")
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help="increase verbosity",
)
def clean(package: List[str], cwd: str = "", verbose: bool = False):
    """Clean packages' build & lock files"""
    pl, cfg, pkgs = preprocessing(cwd, package)

    pl.enforce_version_consistency()
    for pkg_name in pkgs:
        pkg = pl.pkgs[pkg_name]
        pl.managers[pkg.type].clean(pkg)


@click.command()
@click.option("--cwd", default="", help="Override current working directory")
def update(cwd: str = ""):
    pl, cfg, pkgs = preprocessing(cwd, [])
    pl.enforce_version_consistency(VersionConsistent.STRICT)


@click.command()
@click.option(
    "-p",
    "--package",
    multiple=True,
    help="Specify the package that we want to build. If empty, build all packages",
)
@click.option("--cwd", default="", help="Override current working directory")
def publish(package: str, cwd: str = ""):
    pbt_cfg = PBTConfig.from_dir(cwd)
    packages = search_packages(pbt_cfg)

    if len(package) == 0:
        publish_packages = set(packages.keys())
    else:
        publish_packages = set(package)

    if len(publish_packages.difference(packages.keys())) > 0:
        raise Exception(
            f"Passing unknown packages: {publish_packages.difference(packages.keys())}. Available options: {list(packages.keys())}"
        )

    all_pub_pkgs = {}
    for pkg_name in publish_packages:
        pkg = packages[pkg_name]
        dep_pkgs = pkg.all_inter_dependencies()

        all_pub_pkgs[pkg.name] = pkg
        all_pub_pkgs.update(dep_pkgs)

    update_versions(all_pub_pkgs.keys(), packages)
    pypi = PyPI.get_instance()
    has_error = False

    all_pub_pkgs = [
        all_pub_pkgs[pkg_name] for pkg_name in topological_sort(all_pub_pkgs)
    ]
    pkg2diff = {}

    for pkg in all_pub_pkgs:
        remote_pkg_version, remote_pkg_hash = pypi.get_latest_version_and_hash(
            pkg.name
        ) or (None, None)
        diff = RemoteDiff.from_pkg(pkg, pbt_cfg, remote_pkg_version, remote_pkg_hash)
        if not diff.is_version_diff and diff.is_content_changed:
            logger.error(
                "Package {} has been modified, but its version hasn't been updated",
                pkg.name,
            )
            has_error = True
        pkg2diff[pkg.name] = diff

    if has_error:
        raise Exception(
            "Stop publishing because some packages have been modified but their versions haven't been updated. Please see the logs for more information"
        )

    for pkg in all_pub_pkgs:
        if pkg2diff[pkg.name].is_version_diff:
            logger.info("Publish package {}", pkg.name)
            pkg.publish()
