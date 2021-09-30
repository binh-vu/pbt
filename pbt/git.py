import glob
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Union, NamedTuple


class GitFileStatus(NamedTuple):
    is_deleted: bool
    fpath: str


class Git:
    @classmethod
    def get_new_modified_deleted_files(cls, cwd: Union[str, Path]):
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
    def get_current_commit(cls, cwd: Union[str, Path]):
        return (
            subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=cwd)
            .decode()
            .strip()
        )

    @classmethod
    def init(cls, cwd: Union[str, Path]):
        subprocess.check_output(["git", "init"], cwd=cwd)

    @classmethod
    def commit_all(cls, cwd: Union[str, Path], msg: str = "add all files"):
        subprocess.check_output(["git", "add", "-A"], cwd=cwd)
        subprocess.check_output(["git", "commit", "-m", f"'{msg}'"], cwd=cwd)


if __name__ == "__main__":
    res = Git.get_new_modified_deleted_files("/workspace/sm-dev/osin")
    print("\n".join([str(x) for x in res]))
