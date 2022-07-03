from dataclasses import dataclass
from pathlib import Path
import re
from typing import List, Optional, Union
from pbt.config import PBTConfig
from pbt.package.manager.maturin import Maturin
from pbt.package.manager.poetry import Poetry
from pbt.misc import exec
from operator import attrgetter


class PipDependencyQuery:
    instance = None

    def __init__(self) -> None:
        cfg = PBTConfig(cwd=Path("/tmp"), cache_dir=Path("/tmp/cache"))
        self.managers = [Poetry(cfg), Maturin(cfg)]

    @staticmethod
    def get_instance():
        if PipDependencyQuery.instance is None:
            PipDependencyQuery.instance = PipDependencyQuery()
        return PipDependencyQuery.instance

    def get_dependencies(self, pip_file: Union[str, Path]) -> List["PipFreezePkgInfo"]:
        """Get installed packages from pip freeze.

        Arguments:
            pip_file: pip executable
        """
        lines = exec([pip_file, "freeze"])

        pkg_name = r"(?P<pkg>[a-zA-Z0-9-_]+)"
        pkgs = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if line.startswith("#"):
                # expect the next one is editable
                m = re.match(
                    rf"# Editable(?: Git)? install with no (?:remote|version control) \({pkg_name}==(?P<version>[^)]+)\)",
                    line,
                )
                assert m is not None, f"`{line}`"
                i += 1
                line = lines[i]
                m2 = re.match(rf"-e (?P<path>.+)", line)
                assert m2 is not None, f"`{line}`"
                pkgs.append(
                    PipFreezePkgInfo(
                        name=m.group("pkg"),
                        editable=True,
                        version=m.group("version"),
                        path=m2.group("path"),
                    )
                )
            elif line.find(" @ ") != -1:
                m = re.match(rf"{pkg_name} @ (?P<path>.+)", line)
                assert m is not None, f"`{line}`"
                path = m.group("path")
                assert path.startswith("file:///"), path
                name = m.group("pkg")

                version = self.get_version(pip_file, name)
                editable = self.is_editable_by_poetry(pip_file, name, version)

                pkgs.append(
                    PipFreezePkgInfo(
                        name=name, version=version, editable=editable, path=path[7:]
                    )
                )
            else:
                m = re.match(rf"{pkg_name}==(?P<version>.+)", line)
                assert m is not None, f"`{line}`"

                name = m.group("pkg")
                version = m.group("version")
                # for package installed by poetry before 1.2, it may be still installed in editable mode
                # but is not configured correctly to reflect that in pip freeze.
                editable = self.is_editable_by_poetry(pip_file, name, version)

                pkgs.append(
                    PipFreezePkgInfo(
                        name=name,
                        version=version,
                        editable=editable,
                    )
                )
            i += 1

        return sorted(pkgs, key=attrgetter("name"))

    def read_pkg_version(self, name: str, dir: Path) -> str:
        """Read the package version from disk."""
        for manager in self.managers:
            if manager.is_package_directory(dir):
                return manager.load(dir).version
        raise ValueError("Unknown package {} located at: {}".format(name, dir))

    def get_version(self, pip_file: Union[str, Path], name: str):
        lines = exec([pip_file, "show", name])
        assert lines[0] == f"Name: {name}"
        assert lines[1].startswith("Version: ")
        return lines[1][9:].strip()

    def is_editable_by_poetry(
        self, pip_file: Union[str, Path], name: str, version: Optional[str] = None
    ):
        """Find if a package is installed by poetry and is editable or not"""
        lines = exec([pip_file, "show", name])
        assert lines[0] == f"Name: {name}"
        site_pkg_dir = Path(
            next(line[10:] for line in lines if line.startswith("Location: "))
        )

        # check if is installed by poetry
        if version is None:
            lst = [
                item
                for item in site_pkg_dir.iterdir()
                if item.name.startswith(name) and item.name.endswith("dist-info")
            ]
            if len(lst) != 1:
                raise Exception(
                    "Version is required to locate the package: {}".format(name)
                )
            distinfo = lst[0]
        else:
            distinfo = f"{name}-{version}.dist-info"

        installer = site_pkg_dir / distinfo / "INSTALLER"
        if installer.read_text() != "poetry":
            return False

        # the package content is not copied to the site-packages directory
        # and only the .pth file containing the path is added
        if (site_pkg_dir / name).exists() or not (
            site_pkg_dir / f"{name}.pth"
        ).exists():
            return False

        return True


@dataclass
class PipFreezePkgInfo:
    name: str
    editable: bool = False
    version: Optional[str] = None
    path: Optional[str] = None

    def __eq__(self, other):
        return (
            isinstance(other, PipFreezePkgInfo)
            and self.name == other.name
            and self.editable == other.editable
            and self.version == other.version
        )
