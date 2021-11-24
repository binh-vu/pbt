import importlib.metadata
import os
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import List, Literal

import click
import loguru
from loguru import logger

from pbt.config import PBTConfig
from pbt.diff import RemoteDiff
from pbt.git import Git
from pbt.package import search_packages, topological_sort, update_versions
from pbt.pypi import PyPI


@click.group()
# @click.version_option(importlib.metadata.version("pab"))
def cli():
    pass


@click.command()
@click.option(
    "-p",
    "--package",
    multiple=True,
    help="Specify the package that we want to build. If empty, build all packages",
)
@click.option(
    "-i",
    "--install",
    is_flag=True,
    help="Install other dependencies of the package (not the inter/local dependencies)",
)
@click.option(
    "-e",
    "--editable",
    is_flag=True,
    help="Whether to install dependencies in editable mode",
)
@click.option(
    "-f",
    "--force",
    is_flag=True,
    help="Whether to force reinstall the dependencies",
)
@click.option("--cwd", default="", help="Override current working directory")
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help="increase verbosity",
)
def make(
    package: List[str],
    install: bool = False,
    editable: bool = False,
    force: bool = False,
    cwd: str = "",
    verbose: bool = False,
):
    """Make package"""
    pbt_cfg = PBTConfig.from_dir(cwd)
    packages = search_packages(pbt_cfg)

    if len(package) == 0:
        make_packages = set(packages.keys())
    else:
        make_packages = set(package)

    if len(make_packages.difference(packages.keys())) > 0:
        raise Exception(
            f"Passing unknown packages: {make_packages.difference(packages.keys())}. Available options: {list(packages.keys())}"
        )

    # mapping from package name to whether the content has been changed since the last built
    built_pkgs = {}
    updated_version_pkgs = set()
    for pkg_name in make_packages:
        pkg = packages[pkg_name]
        if install:
            logger.debug("Install {} external dependencies", pkg_name)
            pkg.install(without_inter_dependency=True, verbose=verbose)

        dep_pkgs = pkg.all_inter_dependencies()
        update_versions(set(dep_pkgs.keys()).difference(updated_version_pkgs), packages)
        updated_version_pkgs = updated_version_pkgs.union(dep_pkgs.keys())

        for dep_name in topological_sort(dep_pkgs):
            if dep_name not in built_pkgs:
                # TODO: optimize this code as we don't need to rebuild if we are install in editable mode
                built_pkgs[dep_name] = dep_pkgs[dep_name].build(pbt_cfg)
                if built_pkgs[dep_name] and dep_name in pkg.dependencies:
                    # update if there is a change in the dependency make it no longer compatible,
                    if not pkg.is_package_compatible(dep_pkgs[dep_name]):
                        pkg.update_package_version(dep_pkgs[dep_name])
            if built_pkgs[dep_name] or force:
                pkg.install_dep(
                    dep_pkgs[dep_name],
                    pbt_cfg,
                    editable=editable,
                    no_build=True,
                    verbose=verbose,
                )
    return


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
    pbt_cfg = PBTConfig.from_dir(cwd)
    packages = search_packages(pbt_cfg)

    if len(package) == 0:
        clean_packages = set(packages.keys())
    else:
        clean_packages = set(package)

    if len(clean_packages.difference(packages.keys())) > 0:
        raise Exception(
            f"Passing unknown packages: {clean_packages.difference(packages.keys())}. Available options: {list(packages.keys())}"
        )

    for pkg_name in clean_packages:
        pkg = packages[pkg_name]
        if verbose:
            logger.info("Clean package: {}", pkg.name)
        pkg.clean(pbt_cfg)


@click.command()
@click.option("--cwd", default="", help="Override current working directory")
def update(cwd: str = ""):
    pbt_cfg = PBTConfig.from_dir(cwd)
    packages = search_packages(pbt_cfg)
    update_versions(list(packages.keys()), packages, force=True)


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


@click.command()
@click.option(
    "--repo", default="", help="Specify the poly-repository that we are working with."
)
@click.option("--cwd", default=".", help="Override current working directory")
@click.argument("subcommand")
def git(repo: str, cwd: str, subcommand: Literal["snapshot"]):
    """Execute Git commands in a super-project"""
    cwd = os.path.abspath(cwd)
    
    if subcommand == "clone":
        assert repo.endswith(".git"), f"Invalid repository: `{repo}`"

        # clone repository
        repo_dir = Git.clone_all(repo, cwd)

        # checkout the submodule to the correct branch
        for submodule in Git.find_submodules(repo_dir):
            logger.info("Checkout submodule {}", submodule)
            Git.auto_checkout_branch(submodule)
    elif subcommand == "update":
        Git.pull(cwd, submodules=True)
        # checkout the submodule to the correct branch
        for submodule in Git.find_submodules(cwd):
            logger.info("Checkout submodule {}", submodule)
            Git.auto_checkout_branch(submodule) 
    elif subcommand == "snapshot":
        pbt_cfg = PBTConfig.from_dir(cwd)
        cwd = str(pbt_cfg.cwd.absolute())

        for submodule_dir in Git.find_submodules(cwd):
            # get the current branch
            branch = Git.get_current_branch(submodule_dir)
            print(f"bash -c 'cd {submodule_dir}; git checkout {branch}; git pull'")
    else:
        raise Exception(f"Invalid subcommand: {subcommand}")


cli.add_command(make)
cli.add_command(clean)
cli.add_command(publish)
cli.add_command(update)
cli.add_command(git)

if __name__ == "__main__":
    cli()
