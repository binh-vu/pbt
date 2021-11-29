import os
from typing import Literal
import click
from loguru import logger
from pbt.config import PBTConfig

from pbt.vcs.git import Git


@click.command()
@click.option(
    "--repo",
    default="",
    help="Specify the multi-repository that we are working with. e.g., https://github.com/binh-vu/pbt",
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
