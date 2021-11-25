import enum
import glob
from itertools import chain
from pathlib import Path
from typing import Dict, List
from pbt.package.graph import PkgGraph, ThirdPartyPackage
from pbt.package.manager.manager import PkgManager
from pbt.package.manager.poetry import Poetry
from pbt.package.package import Package, PackageType


class VersionConsistent(enum.Enum):
    # it is consistent if it is exact match
    STRICT = "strict"
    # it is consistent if it matches the constraint
    COMPATIBLE = "compatible"


class BTPipeline:
    def __init__(self, root: Path, managers: Dict[PackageType, PkgManager]) -> None:
        self.root = root
        self.managers = managers
        self.graph = PkgGraph()
        self.pkgs: Dict[str, Package] = {}

    def discover(self):
        """Discover packages in the project."""
        pkgs = {}
        for manager in self.managers.values():
            for fpath in manager.glob_query(self.root):
                pkg = manager.load(Path(fpath).parent)
                if pkg.name in pkgs:
                    raise RuntimeError(f"Duplicate package {pkg.name}")
                pkgs[pkg.name] = pkg
        self.graph = PkgGraph.from_pkgs(pkgs)
        self.pkgs = pkgs

    def enforce_version_consistency(
        self, mode: VersionConsistent = VersionConsistent.COMPATIBLE
    ):
        """Update version of packages & third-party packages in the project.

        Args:
            mode: how to enforce version consistency for your OWN packages in the project.
        """
        # resolve the latest version of (third-party) packages
        pkg2version = {}

        for pkg in self.graph.iter_pkg():
            if isinstance(pkg, ThirdPartyPackage):
                manager = self.managers[pkg.type]
                versions = list(pkg.invert_dependencies.values())
                latest_version = manager.find_latest_specs(versions)
                pkg2version[pkg.name] = latest_version

        # iterate over packages and update their dependencies.
        # however, for your own packages, always use the latest version
        for pkg in self.pkgs.values():
            manager = self.managers[pkg.type]
            is_modified = False
            for deps in [pkg.dependencies, pkg.dev_dependencies]:
                for dep, specs in deps.items():
                    if dep in self.pkgs:
                        # update your own packages
                        dep_version = manager.parse_version(self.pkgs[dep].version)
                        if mode == VersionConsistent.COMPATIBLE:
                            for spec in specs:
                                if not manager.is_version_compatible(
                                    dep_version, spec.version_spec
                                ):
                                    spec.version_spec = manager.update_version_spec(
                                        spec.version_spec, dep_version
                                    )
                                    is_modified = True
                        else:
                            assert mode == VersionConsistent.STRICT
                            for spec in specs:
                                lowerbound, upperbound = manager.parse_version_spec(
                                    spec.version_spec
                                )
                                if lowerbound != dep_version:
                                    is_modified = True
                                    spec.version_spec = manager.update_version_spec(
                                        spec.version_spec, dep_version
                                    )
                    elif specs != pkg2version[dep]:
                        deps[dep] = pkg2version[dep]
                        is_modified = True

            if is_modified:
                manager.save(pkg)

    def install(self, pkg_names: List[str] = None, editable: bool = False):
        """Install packages

        Args:
            pkg_names: name of packages to install
            editable: whether to install those packages in editable mode
        """
        if pkg_names is None:
            # ensure consistent ordering
            pkg_names = sorted(self.pkgs.keys())
        pkgs = [self.pkgs[name] for name in pkg_names]

        for pkg in pkgs:
            manager = self.managers[pkg.type]
            # gather all dependencies in one file and install it.
            manager.install(pkg)

    def publish(self, pkg_names: List[str] = None):
        """Publish a package.

        Args:
            pkg_names: name of the package to publish
        """
        pass
