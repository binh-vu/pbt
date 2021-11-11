import glob
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Union, NamedTuple


class GitFileStatus(NamedTuple):
    is_deleted: bool
    fpath: str


class GitBranch(NamedTuple):
    local: Optional[str]
    remote: Optional[str]
    is_active: bool

    def get_name(self) -> str:
        if self.local is not None:
            return self.local.rsplit("/", 1)[-1]
        assert self.remote is not None
        return self.remote.rsplit("/", 1)[-1]

    def is_local(self) -> bool:
        return self.local is not None and self.local.find("/") == -1


PathOrStr = Union[str, Path]


class Git:
    @classmethod
    def get_new_modified_deleted_files(cls, cwd: PathOrStr):
        git_dir = (
            subprocess.check_output(["git", "rev-parse", "--show-toplevel"], cwd=cwd)
            .decode()
            .strip()
        )
        output = subprocess.check_output(
            ["git", "status", "-uall", "--porcelain=v1", "--no-renames", "."], cwd=cwd
        ).decode()
        # rstrip as the first line can have empty character
        output = output.rstrip()
        if len(output) == 0:
            return []

        lines = output.split("\n")
        results = []

        # TODO: take a look at this document and implement it correctly
        #  https://git-scm.com/docs/git-status
        for line in lines:
            code = line[:2]
            rel_file_path = line[3:].strip()
            assert " -> " not in rel_file_path and "R" not in code
            results.append(
                GitFileStatus(
                    is_deleted="D" in code, fpath=os.path.join(git_dir, rel_file_path)
                )
            )
        return results

    @classmethod
    def get_current_commit(cls, cwd: PathOrStr):
        return (
            subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=cwd)
            .decode()
            .strip()
        )

    @classmethod
    def get_current_branch(cls, cwd: PathOrStr):
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd
            )
            .decode()
            .strip()
        )

    @classmethod
    def checkout_branch(cls, cwd: PathOrStr, branch: str, create: bool = False):
        if not create:
            # exist local branch
            cmd = ["git", "checkout", branch]
        else:
            cmd = ["git", "checkout", "-b", branch]
        subprocess.check_call(cmd, cwd=cwd)

    @classmethod
    def get_branches_contain_commit(cls, cwd: PathOrStr, commit_id: str):
        output = subprocess.check_output(
            ["git", "branch", "-a", "--contains", commit_id], cwd=cwd
        ).decode()
        branches = []

        for x in output.split("\n"):
            x = x.strip()
            if x == "":
                continue

            is_active = False
            if x[0] == "*":
                is_active = True
                x = x[2:]

            if x.startswith("(HEAD detached"):
                # detached head, so no branch
                continue

            if x.find(" -> ") != -1:
                remote, local = x.split(" -> ")
            elif x.startswith("remotes/"):
                remote = x
                local = None
            else:
                remote = None
                local = x

            branch = GitBranch(local=local, remote=remote, is_active=is_active)
            if branch.get_name() == "HEAD":
                continue
            branches.append(branch)

        return branches

    @classmethod
    def init(cls, cwd: PathOrStr):
        subprocess.check_output(["git", "init"], cwd=cwd)

    @classmethod
    def commit_all(cls, cwd: PathOrStr, msg: str = "add all files"):
        subprocess.check_output(["git", "add", "-A"], cwd=cwd)
        subprocess.check_output(["git", "commit", "-m", f"'{msg}'"], cwd=cwd)

    @classmethod
    def clone_all(cls, repo: str, cwd: PathOrStr) -> Path:
        """Clone a repository and its submodules. Then, return the cloned directory"""
        # get repo name to create directory to clone the repo into
        repo_name = repo.rsplit("/", 1)[-1].replace(".git", "")
        repo_dir = Path(cwd) / repo_name
        if repo_dir.exists():
            raise Exception(
                f"Directory {repo_dir} already exists. Can't clone the repository"
            )
        if not repo_dir.parent.exists():
            raise Exception(
                f"Directory {repo_dir.parent} does not exist. Can't clone the repository into it"
            )

        subprocess.check_call(
            [
                "git",
                "clone",
                "--recurse-submodules",
                "-j8",
                repo,
            ],
            cwd=cwd,
        )

        return repo_dir

    @classmethod
    def find_submodules(cls, repo_dir: PathOrStr) -> List[Path]:
        submodules = []
        repo_dir = os.path.abspath(repo_dir)

        for dir in Path(repo_dir).iterdir():
            if not dir.is_dir():
                continue
            superdir = (
                subprocess.check_output(
                    ["git", "rev-parse", "--show-superproject-working-tree"],
                    cwd=str(dir),
                )
                .decode()
                .strip()
            )
            # only consider submodules that are of the current project
            if superdir == repo_dir:
                submodules.append(dir)

        return submodules


if __name__ == "__main__":
    res = Git.get_new_modified_deleted_files("/workspace/sm-dev/osin")
    print("\n".join([str(x) for x in res]))
