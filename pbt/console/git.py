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
@click.argument("command", type=click.Choice(["clone", "update", "push", "snapshot"]))
def git(repo: str, cwd: str, command: Literal["snapshot"]):
    """Execute Git command in a super-project"""
    cwd = os.path.abspath(cwd)

    if command == "clone":
        assert repo.endswith(".git"), f"Invalid repository: `{repo}`"

        # clone repository
        repo_dir = Git.clone(repo, cwd, submodules=True)

        # checkout the submodule to the correct branch
        for submodule in Git.find_submodules(repo_dir):
            logger.info("Checkout submodule {}", submodule)
            Git.auto_checkout_branch(submodule)
        sync_dependencies(PBTConfig.from_dir(repo_dir))
    elif command == "update":
        Git.pull(cwd, submodules=True)
        # checkout the submodule to the correct branch
        for submodule in Git.find_submodules(cwd):
            logger.info("Checkout submodule {}", submodule)
            Git.auto_checkout_branch(submodule)
        sync_dependencies(PBTConfig.from_dir(cwd))
    elif command == "push":
        pbt_cfg = PBTConfig.from_dir(cwd)
        cwd = str(pbt_cfg.cwd.absolute())
        Git.push(cwd)
        for submodule_dir in Git.find_submodules(cwd):
            Git.push(submodule_dir)
    elif command == "snapshot":
        pbt_cfg = PBTConfig.from_dir(cwd)
        cwd = str(pbt_cfg.cwd.absolute())

        for submodule_dir in Git.find_submodules(cwd):
            # get the current branch
            branch = Git.get_current_branch(submodule_dir)
            print(f"bash -c 'cd {submodule_dir}; git checkout {branch}; git pull'")
    else:
        raise Exception(f"Invalid command: {command}")


def sync_dependencies(cfg: PBTConfig):
    """Sync package dependencies specified in `cfg` to a library directory."""
    if not cfg.library_path.exists() and len(cfg.dependency_repos) == 0:
        return

    cfg.library_path.mkdir(exist_ok=True, parents=True)

    sync_repos = set(cfg.dependency_repos)
    for subdir in cfg.library_path.iterdir():
        if not Git.is_git_dir(subdir):
            continue
        repo = Git.get_repo(subdir)
        if repo not in sync_repos:
            logger.warning(
                "Found and skip a git directory in libraries that isn't in the list of dependencies: {}",
                subdir,
            )
            continue
        sync_repos.remove(repo)
        logger.info("Pull dependency {}", repo)
        Git.pull(subdir, submodules=False)
    for repo in sync_repos:
        logger.info("Clone dependency {}", repo)
        Git.clone(repo, cfg.library_path)
