from functools import partial
import os
import re
import shutil
import sys
from dataclasses import asdict, dataclass
from operator import attrgetter
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Dict, List, Optional, Union, cast

import pytest
from loguru import logger
from pbt.config import PBTConfig
from pbt.package.manager.maturin import Maturin
from pbt.vcs.git import Git
from pbt.package import manager
from pbt.package.registry.pypi import PyPI

from pbt.package.package import DepConstraint, Package, PackageType
from pbt.package.manager.poetry import Poetry
from pbt.package.manager.manager import PkgManager

from pbt.misc import exec
from tests.mockups import PyPIMockUp

File = str
Directory = Dict[str, Union[File, "Directory"]]


@dataclass
class Repo:
    cfg: PBTConfig
    packages: Dict[str, Package]
    poetry: Poetry

    def reload_pkgs(self):
        for pkg in self.packages.values():
            tmp = self.poetry.load(pkg.location)
            pkg.name = tmp.name
            pkg.version = tmp.version
            pkg.dependencies = tmp.dependencies
            pkg.dev_dependencies = tmp.dev_dependencies
            pkg.include = tmp.include
            pkg.exclude = tmp.exclude


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


def get_dependencies(pip_file: Union[str, Path]) -> List[PipFreezePkgInfo]:
    lines = exec([pip_file, "freeze"])

    managers: List[PkgManager] = []

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
            path = path[7:]
            if path.find("-") != -1:
                version = Path(path).name.split("-")[1]
            else:
                if len(managers) == 0:
                    cfg = PBTConfig(cwd=Path("/tmp"), cache_dir=Path("/tmp/cache"))
                    managers += [Poetry(cfg), Maturin(cfg)]

                for manager in managers:
                    if manager.is_package_directory(Path(path)):
                        version = manager.load(Path(path)).version
                        break
                else:
                    raise ValueError(
                        "Unknown package {} located at: {}".format(m.group("pkg"), path)
                    )
            pkgs.append(
                PipFreezePkgInfo(
                    name=m.group("pkg"), version=version, editable=True, path=path
                )
            )
        else:
            m = re.match(rf"{pkg_name}==(?P<version>.+)", line)
            assert m is not None, f"`{line}`"
            pkgs.append(
                PipFreezePkgInfo(name=m.group("pkg"), version=m.group("version"))
            )
        i += 1

    return sorted(pkgs, key=attrgetter("name"))


def get_dependency(pip_file: Union[str, Path], name: str) -> Optional[PipFreezePkgInfo]:
    deps = get_dependencies(pip_file)
    for dep in deps:
        if dep.name == name:
            return dep
    return None


def pylib(cwd, name, version, deps=None, dev_deps=None):
    def dcon(version):
        if isinstance(version, list):
            return [
                DepConstraint(
                    version_spec=v["version"],
                    constraint=v["python"],
                    version_spec_field="version",
                    origin_spec={x: y for x, y in v.items() if x != "version"},
                )
                for v in version
            ]
        return [DepConstraint(version, constraint="python=* markers=")]

    (cwd / name).mkdir(exist_ok=True, parents=True)

    dependencies = {k: dcon(v) for k, v in (deps or {}).items()}
    if "python" not in dependencies:
        dependencies["python"] = dcon(
            f"^{sys.version_info.major}.{sys.version_info.minor}"
        )

    return Package(
        name=name,
        type=PackageType.Poetry,
        location=cwd / name,
        version=version,
        dependencies=dependencies,
        dev_dependencies={k: dcon(v) for k, v in (dev_deps or {}).items()},
        include=[name],
        exclude=[],
    )


@pytest.fixture()
def mockup_pypi():
    pypi = PyPI.get_instance()
    default_index = pypi.index

    if "mockup" not in PyPI.instances:
        mockpypi = PyPIMockUp(default_index)
        PyPI.instances["mockup"] = mockpypi

        # re-calculate packages' hash as different environments create different hash...
        with TemporaryDirectory(dir="/tmp") as tmpdir:
            cwd = tmpdir2path(tmpdir)
            setup_dir(
                {
                    "scripts": {"helloworld.py": "print('hello world')"},
                    "pbtconfig.json": "{}",
                },
                cwd,
            )
            get_lib = partial(pylib, cwd)
            lib0 = get_lib("lib0", "0.5.1")
            lib1 = get_lib("lib1", "0.2.1", {lib0.name: "^" + lib0.version})
            lib2 = get_lib("lib2", "0.6.7", {lib1.name: "~" + lib1.version})
            lib3 = get_lib(
                "lib3",
                "0.1.4",
                {lib0.name: "~" + lib0.version, lib1.name: "~" + lib1.version},
            )

            repo = make_pyrepo(
                cwd,
                libs=[lib0, lib1, lib2, lib3],
                submodules=[lib0, lib1, lib2],
            )

            for pkg in repo.packages.values():
                mockpypi.update_pkg_hash(
                    pkg.name, pkg.version, repo.poetry.compute_pkg_hash(pkg)
                )

    PyPI.instances[default_index] = PyPI.instances["mockup"]
    yield PyPI.instances[default_index]
    PyPI.instances[default_index] = pypi


def make_pyrepo(cwd: Path, libs: List[Package], submodules: List[Package]):
    if cwd.exists():
        shutil.rmtree(cwd)

    cache_dir = cwd / ".cache"
    cache_dir.mkdir(parents=True)

    cfg = PBTConfig(cwd, cache_dir)

    # setup project directory
    tree = {}
    for lib in libs:
        tree[lib.name] = {
            lib.name: {"__init__.py": "", "__main__.py": f"print('{lib.name}')"}
        }
    setup_dir(tree, cwd)

    poetry = Poetry(cfg)

    for lib in libs:
        poetry.save(lib)
        poetry.clean(lib)

    # setup git
    Git.init(cwd)
    for lib in submodules:
        Git.init(lib.location)
        Git.commit_all(lib.location)
        exec(["git", "submodule", "add", "./" + lib.name, lib.name], cwd=cwd)
    Git.commit_all(cwd)

    return Repo(
        cfg=cfg,
        packages={lib.name: lib for lib in libs},
        poetry=poetry,
    )


def tmpdir2path(tmpdir: str) -> Path:
    """Convert directory returned from TemporaryDirectory to Path.
    For MacOS, it is a subdirectory of /private/, and git returns that directory so we need to add /private/ to it.
    """
    if sys.platform == "darwin" and tmpdir.startswith("/tmp"):
        return Path("/private/" + tmpdir)
    return Path(tmpdir)


@pytest.fixture
def repo1(mockup_pypi):
    """
    Dependency graph
        lib 1 -> lib 0
        lib 2 -> lib 1
        lib 3 -> lib 1 & lib 0
        lib 4 -> lib

    only lib 0 & lib 1 & lib 2 are git submodules

    """
    with TemporaryDirectory(dir="/tmp") as tmpdir:
        cwd = tmpdir2path(tmpdir)

        setup_dir(
            {
                "scripts": {"helloworld.py": "print('hello world')"},
                "pbtconfig.json": "{}",
            },
            cwd,
        )

        get_lib = partial(pylib, cwd)
        lib0 = get_lib("lib0", "0.5.1")
        lib1 = get_lib("lib1", "0.2.1", {lib0.name: "^" + lib0.version})
        lib2 = get_lib("lib2", "0.6.7", {lib1.name: "~" + lib1.version})
        lib3 = get_lib(
            "lib3",
            "0.1.4",
            {lib0.name: "~" + lib0.version, lib1.name: "~" + lib1.version},
        )

        yield make_pyrepo(
            cwd,
            libs=[lib0, lib1, lib2, lib3],
            submodules=[lib0, lib1, lib2],
        )


@pytest.fixture
def repo2(mockup_pypi):
    """
    Dependency graph
        lib 1 -> lib 0
        lib 2 -> lib 1
        lib 3 -> lib 1
        lib 4 -> lib 1
        lib 5 -> lib 1
        lib 10 -> lib 1 (however, it's impossible to fulfill version requirement)

    no libraries are submodules

    """
    with TemporaryDirectory(dir="/tmp") as tmpdir:
        cwd = tmpdir2path(tmpdir)

        setup_dir(
            {
                "scripts": {"helloworld.py": "print('hello world')"},
                "pbtconfig.json": "{}",
            },
            cwd,
        )

        get_lib = partial(pylib, cwd)
        lib0 = get_lib("lib0", "0.5.5")
        lib1 = get_lib(
            "lib1", "0.2.1", {lib0.name: "^0.5.1"}
        )  # do not change lib0 version requirement
        lib2 = get_lib("lib2", "0.6.7", {lib1.name: "^" + lib1.version})
        lib3 = get_lib("lib3", "1.6.7", {lib1.name: "^" + lib1.version})
        lib4 = get_lib("lib4", "1.6.7", {lib1.name: "^" + lib1.version})
        lib5 = get_lib("lib5", "1.6.7", {lib1.name: "^" + lib1.version})
        lib10 = get_lib("lib10", "9.0.0", {lib1.name: ">= 1.1.2"})

        libs = [lib0, lib1, lib2, lib3, lib4, lib5, lib10]
        yield make_pyrepo(cwd, libs=libs, submodules=[])
