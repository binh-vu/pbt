import glob
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Union, NamedTuple
from pbt.misc import exec


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

    def get_remote(self) -> Optional[str]:
        if self.local is not None:
            if self.local.find("/") != -1:
                return self.local.split("/")[0]
            if self.remote is None:
                return None
        assert self.remote is not None
        return self.remote.rsplit("/")[1]


PathOrStr = Union[str, Path]


class Git:
    @classmethod
    def get_new_modified_deleted_files(cls, cwd: PathOrStr):
        (git_dir,) = exec("git rev-parse --show-toplevel", cwd=cwd)
        assert Path(git_dir).exists()

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
    def does_branch_exist(cls, cwd: PathOrStr, branch: str) -> bool:
        return (
            subprocess.check_output(["git", "branch", "--list", branch], cwd=cwd)
            .decode()
            .strip()
            == branch
        )

    @classmethod
    def checkout_branch(
        cls,
        cwd: PathOrStr,
        branch: str,
        create: bool = False,
        remote: Optional[str] = None,
    ):
        if not create:
            # exist local branch
            cmd = ["git", "checkout", branch]
        else:
            cmd = ["git", "checkout", "-b", branch]
            if remote is not None:
                cmd += ["--track", f"{remote}/{branch}"]
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
                assert (
                    remote.startswith("remotes/") and len(remote.split("/")) == 3
                ), f"Invalid remote: {remote}"
            elif x.startswith("remotes/") and len(x.split("/")) == 3:
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
    def auto_checkout_branch(cls, cwd: PathOrStr):
        commit_id = Git.get_current_commit(cwd)
        branches = Git.get_branches_contain_commit(cwd, commit_id)

        # select branch to checkout to, prefer development branch as we want to
        # resume previous work
        names = {branch.get_name() for branch in branches}
        if len(names.difference(["master", "main"])) > 0:
            name = list(names.difference(["master", "main"]))[0]
        else:
            name = "master" if "master" in names else "main"

        brs = [branch for branch in branches if branch.get_name() == name]
        has_local = any(br.is_local() for br in brs)
        if has_local:
            Git.checkout_branch(cwd, name)
        else:
            # try to identify the remote of this branch in case the branch is not tracked
            # prefer origin as it is the most common
            remotes = [r for r in {br.get_remote() for br in brs} if r is not None]
            if len(remotes) == 0:
                remote = None
            elif len(remotes) == 1:
                remote = remotes[0]
            elif "origin" in remotes:
                remote = "origin"
            else:
                raise Exception(
                    f"Cannot identify remote for branch {name} as there are multiple remotes: {remotes}"
                )

            if Git.does_branch_exist(cwd, name):
                # the local branch does exist, so we only need to checkout and pull
                Git.checkout_branch(cwd, name)
                Git.pull(cwd, remote=remote)
            else:
                Git.checkout_branch(cwd, name, create=True, remote=remote)

    @classmethod
    def init(cls, cwd: PathOrStr):
        subprocess.check_output(["git", "init"], cwd=cwd)

    @classmethod
    def push(cls, cwd: PathOrStr):
        exec("git push", cwd=cwd)

    @classmethod
    def pull(
        cls,
        cwd: PathOrStr,
        submodules: bool = False,
        remote: Optional[str] = None,
        verbose: bool = False,
    ):
        if verbose:
            fn = subprocess.check_call
        else:
            fn = subprocess.check_output

        try:
            fn(["git", "pull"], cwd=cwd)
        except:
            handle = False

            # if the the upstream branch does not set, we set it to the current remote
            try:
                r = subprocess.check_output(
                    [
                        "git",
                        "rev-parse",
                        "--abbrev-ref",
                        "--symbolic-full-name",
                        "@{u}",
                    ],
                    cwd=cwd,
                )
            except:
                branch = Git.get_current_branch(cwd)
                if remote is None:
                    # try to identify the remote
                    remotes = (
                        subprocess.check_output(["git", "remote", "-v"], cwd=cwd)
                        .decode()
                        .strip()
                        .split("\n")
                    )
                    if len(remotes) == 1:
                        remote = remotes[0]
                    elif "origin" in remotes:
                        remote = "origin"
                    else:
                        raise Exception(
                            f"Can't determine the correct remote for the branch as we have multiple remotes: {remotes}"
                        )

                subprocess.check_output(
                    [
                        "git",
                        "branch",
                        "--set-upstream-to",
                        f"{remote}/{branch}",
                        branch,
                    ],
                    cwd=cwd,
                )
                fn(["git", "pull"], cwd=cwd)
                handle = True

            if not handle:
                raise

        if submodules:
            fn(["git", "submodule", "update", "--init", "--recursive"], cwd=cwd)

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
        """Find submodules of a repository."""
        repo_dir = Path(os.path.abspath(repo_dir))

        submodules = [
            repo_dir / line.split(" ")[-1]
            for line in exec(
                "git config --file .gitmodules --get-regexp path", cwd=repo_dir
            )
        ]
        return submodules


if __name__ == "__main__":
    res = Git.get_new_modified_deleted_files("/workspace/sm-dev/osin")
    print("\n".join([str(x) for x in res]))
