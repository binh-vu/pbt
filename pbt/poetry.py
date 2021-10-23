import os
import re
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, List, Literal, Optional

import semver
from loguru import logger

if TYPE_CHECKING:
    from pbt.package import Package

from functools import cached_property


class Poetry:
    def __init__(self, package: "Package"):
        self.package = package

    @cached_property
    def env_path(self) -> Path:
        """Get environment path of the package, create it if doesn't exist"""
        output = (
            subprocess.check_output(
                ["poetry", "env", "list", "--full-path"], cwd=self.package.dir
            )
            .decode()
            .strip()
        )

        if output == "":
            # environment doesn't exist, create it
            temp_output = (
                subprocess.check_output(
                    ["poetry", "run", "python", "-m", "__hello__"], cwd=self.package.dir
                )
                .decode()
                .strip()
            )
            assert temp_output.endswith("Hello world!")
            output = (
                subprocess.check_output(
                    ["poetry", "env", "list", "--full-path"], cwd=self.package.dir
                )
                .decode()
                .strip()
            )

        lines = output.split("\n")
        if len(lines) > 1:
            logger.warning(
                "There are multiple virtual environments for package {}, and we pick the first one (maybe incorrect)",
                self.package.name,
            )

        if lines[0].endswith(" (Activated)"):
            path = lines[0].split(" ")[0]
        else:
            path = lines[0]

        assert os.path.exists(path)
        return Path(path)

    @cached_property
    def pip_path(self) -> Path:
        return self.env_path / "bin/pip"

    @cached_property
    def python_path(self) -> Path:
        return self.env_path / "bin/python"

    def install(self, without_inter_dependency: bool = True, verbose: bool = False):
        if verbose:
            call = subprocess.check_call
        else:
            call = subprocess.check_output

        if without_inter_dependency:
            with self.temporary_mask(
                [dep_pkg.name for dep_pkg in self.package.inter_dependencies]
            ):
                call(["poetry", "install"], cwd=self.package.dir)
        else:
            call(["poetry", "install"], cwd=self.package.dir)

    def publish(self):
        subprocess.check_output(["poetry", "publish", "--build"], cwd=self.package.dir)

    def destroy(self):
        """Remove the virtual environment"""
        try:
            subprocess.check_output(
                ["poetry", "env", "remove", "python"], cwd=self.package.dir
            )
        except subprocess.CalledProcessError as e:
            pass

    def update_version(self, rule: Literal["major", "minor", "patch"]):
        subprocess.check_output(["poetry", "version", rule], cwd=self.package.dir)

    def replace_version(self, version: Optional[str] = None):
        version = version or self.package.version
        with open(os.path.join(self.package.dir, "pyproject.toml"), "r") as f:
            lines = f.readlines()
            for i, line in enumerate(lines):
                if re.match("version *= *", line) is not None:
                    lines[i] = f'version = "{version}"\n'
                    break
            else:
                raise Exception(
                    "Can not find the version of the package in pyproject.toml"
                )

        with open(os.path.join(self.package.dir, "pyproject.toml"), "w") as f:
            for line in lines:
                f.write(line)

    @classmethod
    def is_version_compatible(cls, version: str, constraint: str) -> bool:
        """Check if version is compatible"""
        m = re.match(
            r"(?P<op>[\^\~]?)(?P<major>\d+)\.((?P<minor>\d+)\.(?P<patch>\d+)?)?",
            constraint,
        )
        assert m is not None, "The constraint is too complicated to handle for now"

        lowerbound = semver.VersionInfo(
            major=int(m.group("major")),
            minor=int(m.group("minor") or "0"),
            patch=int(m.group("patch") or "0"),
        )
        if m.group("op") == "^":
            # special case for 0 following the nodejs way (I can't believe why)
            # see more: https://nodesource.com/blog/semver-tilde-and-caret/
            if lowerbound.major == 0:
                if lowerbound.minor == 0:
                    upperbound = lowerbound.bump_patch()
                else:
                    upperbound = lowerbound.bump_minor()
            else:
                upperbound = lowerbound.bump_major()
        elif m.group("op") == "~":
            if m.group("patch") is not None:
                upperbound = lowerbound.bump_minor()
            elif m.group("minor") is not None:
                upperbound = lowerbound.bump_minor()
            else:
                upperbound = lowerbound.bump_major()
        else:
            upperbound = lowerbound.bump_patch()
        return lowerbound <= version < upperbound

    def update_inter_dependency(self, pkg_name: str, pkg_version: str):
        should_update = False
        with open(os.path.join(self.package.dir, "pyproject.toml"), "r") as f:
            lines = f.readlines()
            match_lines = [
                (i, line)
                for i, line in enumerate(lines)
                if re.match(f"{pkg_name} *= *", line) is not None
            ]
            assert len(match_lines) == 1
            idx, line = match_lines[0]
            m = re.match(
                rf"""({pkg_name} *= *)(?:['"])([^0-9]*)([^'"]+)(?:['"])(.*)""",
                line,
                flags=re.DOTALL,
            )
            if m is not None:
                groups = m.groups()
                prev_version = groups[2]
                if prev_version != pkg_version:
                    should_update = True
                    logger.info(
                        f"In {self.package.name}, bump {pkg_name} from `{prev_version}` to `{pkg_version}`"
                    )
                    lines[idx] = f'{groups[0]}"{groups[1]}{pkg_version}"{groups[3]}'
            else:
                raise NotImplementedError(f"Do not know how to parse `{line}` yet")

        if should_update:
            with open(os.path.join(self.package.dir, "pyproject.toml"), "w") as f:
                for line in lines:
                    f.write(line)

    @contextmanager
    def temporary_mask(self, deps: List[str]):
        """Temporary mask out selected dependencies of the package. This is usually used for installing the package"""
        with open(self.package.dir / "pyproject.toml", "r") as f:
            lines = f.readlines()
        for i, line in enumerate(lines):
            if any([re.match(f"{dep} *=", line) is not None for dep in deps]):
                lines[i] = "# " + lines[i]
        try:
            os.rename(
                self.package.dir / "pyproject.toml",
                self.package.dir / "pyproject.toml.backup",
            )
            with open(self.package.dir / "pyproject.toml", "w") as f:
                f.write("".join(lines))
            yield None
        finally:
            os.rename(
                self.package.dir / "pyproject.toml.backup",
                self.package.dir / "pyproject.toml",
            )
