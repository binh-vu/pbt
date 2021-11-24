import os
import re
import sys
from operator import attrgetter

from pbt.poetry import Poetry
from pbt.pypi import PyPI
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

import pytest
from typing import Dict, Union, List, Optional
import toml
from loguru import logger

from pbt.config import PBTConfig
from pbt.git import Git
from pbt.package import Package, PackageType, load_package
from tests.mockups import PyPIMockUp

File = str
Directory = Dict[str, Union[File, "Directory"]]


@dataclass
class Repo:
    cfg: PBTConfig
    packages: Dict[str, Package]


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
        )


def setup_dir(dir: Directory, cwd: Union[Path, str]):
    """Create a directory tree with files and folder"""
    cwd = Path(cwd)
    cwd.mkdir(exist_ok=True, parents=True)
    for name, item in dir.items():
        if isinstance(item, str):
            if item == "":
                if (cwd / name).exists():
                    with open(cwd / name, "w") as f:
                        pass
                else:
                    (cwd / name).touch()
            else:
                with open(cwd / name, "w") as f:
                    f.write(item)
        else:
            assert isinstance(item, dict)
            (cwd / name).mkdir(exist_ok=True)
            setup_dir(item, cwd / name)


def setup_poetry(pkg: Package):
    with open(pkg.dir / "pyproject.toml", "w") as f:
        toml.dump(
            {
                "tool": {
                    "poetry": {
                        "name": pkg.name,
                        "description": "",
                        "authors": ["Tester <tester@pbt.com>"],
                        "version": pkg.version,
                        "dependencies": pkg.dependencies,
                    }
                }
            },
            f,
        )


def get_dependencies(pip_file: Union[str, Path]) -> List[PipFreezePkgInfo]:
    lines = subprocess.check_output([pip_file, "freeze"]).decode().strip().split("\n")
    if len(lines) == 1 and lines[0] == "":
        return []

    pkg_name = r"(?P<pkg>[a-zA-Z0-9-_]+)"
    pkgs = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("#"):
            # expect the next one is editable
            m = re.match(
                rf"# Editable Git install with no remote \({pkg_name}==(?P<version>[^)]+)\)",
                line,
            )
            assert m is not None, f"`{line}`"
            i += 1
            line = lines[i]
            m2 = re.match(rf"-e (?P<path>.+)", line)
            assert m2 is not None, f"`{line}`"
            pkgs.append(
                PipFreezePkgInfo(
                    name=m.group("pkg"), editable=True, path=m2.group("path")
                )
            )
        elif line.find(" @ ") != -1:
            m = re.match(rf"{pkg_name} @ (?P<path>.+)", line)
            assert m is not None, f"`{line}`"
            pkgs.append(PipFreezePkgInfo(name=m.group("pkg"), path=m.group("path")))
        else:
            m = re.match(rf"{pkg_name}==(?P<version>.+)", line)
            assert m is not None, f"`{line}`"
            pkgs.append(
                PipFreezePkgInfo(name=m.group("pkg"), version=m.group("version"))
            )
        i += 1

    return sorted(pkgs, key=attrgetter("name"))


@pytest.fixture
def mockup_pypi():
    pypi = PyPI.get_instance()
    default_index = pypi.index
    PyPI.instances[default_index] = PyPIMockUp(default_index)
    yield
    PyPI.instances[default_index] = pypi


@pytest.fixture(scope="session")
def pbt_lib() -> Package:
    cwd = Path("/tmp/pbt-0.2.0/polyrepo-bt-0.2.0")
    if not cwd.exists():
        cwd.parent.mkdir(exist_ok=True)
        pkg = PyPI.get_instance().fetch_pkg_info("polyrepo-bt")
        for release in pkg["releases"]["0.2.0"]:
            if release["filename"].endswith(".tar.gz"):
                url = release["url"]
                subprocess.check_output(["wget", url], cwd=cwd.parent)
                subprocess.check_output(
                    ["tar", "-xzf", "polyrepo-bt-0.2.0.tar.gz"], cwd=cwd.parent
                )
        os.remove(cwd / "PKG-INFO")
    return load_package(cwd)


@pytest.fixture
def repo1(pbt_lib, mockup_pypi):
    """
    Dependency graph
        lib 1 -> lib 0
        lib 2 -> lib 1
        lib 3 -> lib 1 & lib 0

    lib 0 & lib 1 & lib 2 are git submodules

    """
    cwd = Path("/tmp/pbt/repo1")
    cache_dir = Path("/tmp/pbt/repo1.cache")

    if cwd.exists():
        shutil.rmtree(cwd)

    if cache_dir.exists():
        shutil.rmtree(cache_dir)

    cwd.mkdir(parents=True)
    cache_dir.mkdir(parents=True)

    shutil.copytree(pbt_lib.dir, cwd / "pbt")
    pbt_lib = Package(**asdict(pbt_lib))
    pbt_lib.dir = cwd / "pbt"

    Git.init(cwd)

    def get_lib(name, version, deps):
        return Package(
            name=name,
            type=PackageType.Poetry,
            dir=cwd / name,
            version=version,
            dependencies=dict(
                python=f"^{sys.version_info.major}.{sys.version_info.minor}", **deps
            ),
            include=[name],
            exclude=[],
            inter_dependencies=[],
            invert_inter_dependencies=[],
        )

    lib0 = get_lib("lib0", "0.5.1", {})
    lib1 = get_lib("lib1", "0.2.1", {lib0.name: "^" + lib0.version})
    lib2 = get_lib("lib2", "0.6.7", {lib1.name: "~" + lib1.version})
    lib3 = get_lib(
        "lib3", "0.1.4", {lib0.name: "~" + lib0.version, lib1.name: "~" + lib1.version}
    )

    lib0.invert_inter_dependencies = [lib1, lib3]
    lib1.invert_inter_dependencies = [lib2]
    lib1.inter_dependencies = [lib0]
    lib2.inter_dependencies = [lib1]
    lib3.inter_dependencies = [lib0, lib1]

    setup_dir(
        {
            "lib0": {
                "lib0": {"__init__.py": "", "main.py": "print('lib0')"},
            },
            "lib1": {
                "lib1": {"__init__.py": "", "main.py": "print('lib1')"},
            },
            "lib2": {
                "lib2": {"__init__.py": "", "main.py": "print('lib2')"},
            },
            "lib3": {
                "lib3": {"__init__.py": "", "main.py": "print('lib3')"},
            },
            "scripts": {"helloworld.py": "print('hello world')"},
            "pbtconfig.json": "{}",
        },
        cwd,
    )

    for lib in [lib0, lib1, lib2, lib3]:
        setup_poetry(lib)
        # clean installed virtual env if have
        Poetry(lib).destroy()

    for lib in [lib0, lib1, lib2]:
        Git.init(lib.dir)
        Git.commit_all(lib.dir)
        subprocess.check_output(
            ["git", "submodule", "add", "./" + lib.name, lib.name], cwd=cwd
        )

    Git.commit_all(cwd)
    yield Repo(
        cfg=PBTConfig(cwd, cache_dir, ignore_packages=set()),
        packages={lib.name: lib for lib in [lib0, lib1, lib2, lib3, pbt_lib]},
    )
