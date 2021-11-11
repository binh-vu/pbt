import os
import shutil
import subprocess
import tarfile
from dataclasses import dataclass
from enum import Enum
from functools import cached_property
from glob import glob
from operator import attrgetter
from pathlib import Path
from typing import Dict, Literal, Optional, Union, List, Iterable

import orjson
import toml
from graphlib import TopologicalSorter
from loguru import logger

from pbt.config import PBTConfig
from pbt.diff import diff_db, Diff, remove_diff_db
from pbt.poetry import Poetry
from pbt.version import parse_version


class PackageType(str, Enum):
    Poetry = "poetry"


@dataclass
class Package:
    name: str
    type: PackageType
    dir: Path
    version: str
    # a list of patterns to be included in the final package
    include: List[str]
    # a list of patterns to be excluded in the final package
    exclude: List[str]
    dependencies: Dict[str, str]
    # list of packages that this package uses
    inter_dependencies: List["Package"]
    # list of packages that use the current package
    invert_inter_dependencies: List["Package"]

    def clean(self, cfg: PBTConfig):
        """Clean built & lock files for a fresh install"""
        for eggdir in glob(str(self.dir / "*.egg-info")):
            shutil.rmtree(eggdir)
        if (self.dir / "dist").exists():
            shutil.rmtree(str(self.dir / "dist"))
        if (self.dir / "poetry.lock").exists():
            os.remove(str(self.dir / "poetry.lock"))
        remove_diff_db(self, cfg)

    def build(self, cfg: PBTConfig, verbose: bool = False) -> bool:
        """Build the package if needed"""
        # check if package has been modified since the last built
        whl_file = self.get_wheel_file()
        with diff_db(self, cfg) as db:
            diff = Diff.from_local(db, self)
            if whl_file is not None:
                if not diff.is_modified(db):
                    logger.info(
                        "Skip package {} as the content does not change", self.name
                    )
                    return False

            try:
                self._build(verbose=verbose)
            finally:
                diff.save(db)
            return True

    def _build(self, verbose: bool = False):
        logger.info("Build package {}", self.name)
        if (self.dir / "dist").exists():
            shutil.rmtree(str(self.dir / "dist"))

        if verbose:
            call = subprocess.check_call
        else:
            call = subprocess.check_output

        call(["poetry", "build"], cwd=str(self.dir))

    def publish(self):
        self.pkg_handler.publish()

    def compute_pip_hash(self, cfg: PBTConfig, no_build: bool = False) -> str:
        """Compute hash of the content of the package"""
        if not no_build:
            self.build(cfg)
        output = (
            subprocess.check_output(["pip", "hash", self.get_wheel_file()])
            .decode()
            .strip()
        )
        output = output[output.find("--hash=") + len("--hash=") :]
        assert output.startswith("sha256:")
        return output[len("sha256:") :]

    def install_dep(
        self,
        package: "Package",
        cfg: PBTConfig,
        editable: bool = False,
        no_build: bool = False,
        verbose: bool = False,
    ):
        """Install the `package` in the virtual environment of this package (`self`) (i.e., install dependency)"""
        if not no_build:
            package.build(cfg, verbose)

        if verbose:
            call = subprocess.check_call
        else:
            call = subprocess.check_output

        logger.info(
            "Current package {}: install dependency {}", self.name, package.name
        )
        pipfile = self.pkg_handler.pip_path
        # need to remove the `.egg-info` folders first as it will interfere with the version (ContextualVersionConflict)
        for eggdir in glob(str(self.dir / "*.egg-info")):
            shutil.rmtree(eggdir)
        call([pipfile, "uninstall", "-y", package.name])

        if editable:
            with tarfile.open(package.get_tar_file(), "r") as g:
                member = g.getmember(f"{package.name}-{package.version}/setup.py")
                with open(package.dir / "setup.py", "wb") as f:
                    f.write(g.extractfile(member).read())
            rename = (package.dir / "pyproject.toml").exists()
            if rename:
                os.rename(
                    package.dir / "pyproject.toml", package.dir / "pyproject.toml.tmp"
                )
            try:
                call([pipfile, "install", "-e", "."], cwd=package.dir)
            finally:
                if rename:
                    os.rename(
                        package.dir / "pyproject.toml.tmp",
                        package.dir / "pyproject.toml",
                    )
                os.remove(package.dir / "setup.py")
        else:
            call([pipfile, "install", package.get_wheel_file()])

    def install(self, without_inter_dependency: bool = True, verbose: bool = False):
        self.pkg_handler.install(without_inter_dependency, verbose)

    def reload(self):
        pkg = load_package(self.dir)
        self.name = pkg.name
        self.version = pkg.version
        self.dependencies = pkg.dependencies
        self.include = pkg.include
        self.exclude = pkg.exclude
        assert all(dep.name in self.dependencies for dep in self.inter_dependencies)

    def is_package_compatible(self, package: "Package") -> bool:
        return self.pkg_handler.is_version_compatible(
            package.version, self.dependencies[package.name]
        )

    def all_inter_dependencies(self) -> Dict[str, "Package"]:
        """Get all inter dependencies of a package. It won't warn if there is any cycle."""
        stack = [self]
        deps = {}
        while len(stack) > 0:
            ptr = stack.pop()
            for dep in ptr.inter_dependencies:
                if dep.name not in deps:
                    stack.append(dep)
                    deps[dep.name] = dep
        return deps

    def next_version(self, rule: Literal["major", "minor", "patch"]):
        self.version = str(parse_version(self.version).next_version(rule))
        self.pkg_handler.replace_version()

    def update_package_version(self, package: "Package"):
        """Update the version of another package in this package"""
        assert package.name in self.dependencies
        self.pkg_handler.update_inter_dependency(package.name, package.version)

    @cached_property
    def pkg_handler(self):
        if self.type == PackageType.Poetry:
            return Poetry(self)
        raise NotImplementedError(self.type)

    def get_tar_file(self) -> Optional[str]:
        tar_file = self.dir / "dist" / f"{self.name}-{self.version}.tar.gz"
        if tar_file.exists():
            return str(tar_file)
        return None

    def get_wheel_file(self) -> Optional[str]:
        whl_files = glob(str(self.dir / f"dist/{self.name.replace('-', '_')}*.whl"))
        if len(whl_files) == 0:
            return None
        return whl_files[0]

    def filter_included_files(self, files: List[str]) -> List[str]:
        """Filter files that will be included in the final distributed packages"""
        dir_paths = []
        patterns = []

        for pattern in self.include:
            pattern = os.path.join(self.dir, pattern)
            # TODO: detect the pattern better
            if "*" in pattern or "?" in pattern or ("[" in pattern and "]" in pattern):
                patterns.append(pattern)
            else:
                dir_paths.append(pattern)

        for depfile in ["pyproject.toml", "requirements.txt"]:
            dir_paths.append(str(self.dir / depfile))

        if len(patterns) > 0:
            raise NotImplementedError()

        output = []
        for file in files:
            if any(file.startswith(dpath) for dpath in dir_paths):
                output.append(file)
        return output

    def to_dict(self):
        return {
            "name": self.name,
            "type": self.type,
            "dir": self.dir,
            "version": self.version,
            "dependencies": self.dependencies,
            "inter_dependencies": [p.name for p in self.inter_dependencies],
            "invert_inter_dependencies": [
                p.name for p in self.invert_inter_dependencies
            ],
        }

    @staticmethod
    def save(packages: Dict[str, "Package"], outfile: Union[str, Path]):
        with open(str(outfile), "wb") as f:
            f.write(
                orjson.dumps(
                    {package.name: package.to_dict() for package in packages.values()}
                )
            )

    @staticmethod
    def load(infile: str) -> Dict[str, "Package"]:
        with open(infile, "r") as f:
            raw_packages = orjson.loads(f.read())
        packages = {name: Package(**o) for name, o in raw_packages}
        for package in packages:
            package.type = PackageType(package.type)
            packages.inter_dependencies = [
                packages[name] for name in package.inter_dependencies
            ]
            packages.invert_inter_dependencies = [
                packages[name] for name in package.invert_inter_dependencies
            ]
        return packages

    def __repr__(self) -> str:
        return f"{self.name}={self.version}"


def search_packages(pbt_cfg: PBTConfig) -> Dict[str, Package]:
    logger.info("Search packages...")
    pkgs = {}

    for poetry_file in glob(str(pbt_cfg.cwd / "*/pyproject.toml")):
        pkg = load_package(Path(poetry_file).parent)
        logger.info("Found package {}", pkg.name)
        pkgs[pkg.name] = pkg

    pkg_names = set(pkgs.keys())
    pkg_similar_names = {pkgname.replace("-", "_") for pkgname in pkg_names}

    for pkg in pkgs.values():
        inter_deps = pkg_names.intersection(pkg.dependencies.keys())

        # check for inconsistent naming '-', '_'
        sim_inter_deps = pkg_similar_names.intersection(
            (pkgname.replace("-", "_") for pkgname in pkg.dependencies.keys())
        )
        if len(inter_deps) != len(sim_inter_deps):
            invalid_pkg_names = sim_inter_deps.difference(
                [name.replace("-", "_") for name in inter_deps]
            )
            raise Exception(f"Packages {invalid_pkg_names} use inconsistent name")

        for pname in inter_deps:
            pkg.inter_dependencies.append(pkgs[pname])
            pkgs[pname].invert_inter_dependencies.append(pkg)
    for pkg in pkgs.values():
        pkg.inter_dependencies.sort(key=attrgetter("name"))
        pkg.invert_inter_dependencies.sort(key=attrgetter("name"))
    return pkgs


def load_package(pkg_dir: Path) -> Package:
    poetry_file = pkg_dir / "pyproject.toml"
    try:
        with open(poetry_file, "r") as f:
            project_cfg = toml.loads(f.read())
            pkg_name = project_cfg["tool"]["poetry"]["name"]
            pkg_version = project_cfg["tool"]["poetry"]["version"]
            pkg_dependencies = project_cfg["tool"]["poetry"]["dependencies"]
            pkg_dependencies.update(project_cfg["tool"]["poetry"]["dev-dependencies"])

            # see https://python-poetry.org/docs/pyproject/#include-and-exclude
            # and https://python-poetry.org/docs/pyproject/#packages
            pkg_include = project_cfg["tool"]["poetry"].get("include", [])
            pkg_exclude = project_cfg["tool"]["poetry"].get("exclude", [])
            pkg_include.append(pkg_name)
            for pkg_cfg in project_cfg["tool"]["poetry"].get("packages", []):
                pkg_include.append(
                    os.path.join(pkg_cfg.get("from", ""), pkg_cfg["include"])
                )
            pkg_include = sorted(set(pkg_include))
    except:
        logger.error("Error while parsing configuration in {}", pkg_dir)
        raise

    return Package(
        name=pkg_name,
        type=PackageType.Poetry,
        version=pkg_version,
        dir=pkg_dir,
        include=pkg_include,
        exclude=pkg_exclude,
        dependencies=pkg_dependencies,
        inter_dependencies=[],
        invert_inter_dependencies=[],
    )


def topological_sort(packages: Dict[str, Package]) -> List[str]:
    """Sort the packages so that the first item is always leaf node in the dependency graph (i.e., it doesn't use any
    package in the repository.
    """
    graph = {}
    for package in packages.values():
        graph[package.name] = {child.name for child in package.inter_dependencies}
    return list(TopologicalSorter(graph).static_order())


def update_versions(
    updated_pkg_names: Iterable[str], packages: Dict[str, Package], force: bool = False
):
    for pkg_name in updated_pkg_names:
        pkg = packages[pkg_name]
        for parent_pkg in pkg.invert_inter_dependencies:
            if force or not parent_pkg.is_package_compatible(pkg):
                parent_pkg.update_package_version(pkg)
