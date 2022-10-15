import enum
from operator import itemgetter
from typing import Dict, List, Optional, Set

from loguru import logger
from pbt.config import PBTConfig
from pbt.diff import RemoteDiff
from pbt.package.graph import PkgGraph, ThirdPartyPackage
from pbt.package.manager.manager import PkgManager, build_cache
from pbt.package.package import (
    Package,
    PackageType,
    DepConstraint,
)
from pbt.package.registry.registry import PkgRegistry
from loguru import logger


class VersionConsistent(enum.Enum):
    # it is consistent if it is exact match
    STRICT = "strict"
    # it is consistent if it matches the constraint
    COMPATIBLE = "compatible"
    # no consistent check is performed, and the latest version is preferred
    NO_CHECK = "no_check"


class BTPipeline:
    def __init__(self, cfg: PBTConfig, managers: Dict[PackageType, PkgManager]) -> None:
        self.root = cfg.cwd
        self.cfg = cfg
        self.managers = managers
        self.graph = PkgGraph()
        self.pkgs: Dict[str, Package] = {}

    def discover(self):
        """Discover packages in the project."""
        logger.debug("Discovering packages in the project...")
        pkgs = {}
        for manager in self.managers.values():
            for fpath in manager.discover(
                self.root, self.cfg.ignore_directories, self.cfg.ignore_directory_names
            ):
                if not manager.is_package_directory(fpath):
                    continue
                pkg = manager.load(fpath)
                if pkg.name in pkgs:
                    raise RuntimeError(f"Duplicate package {pkg.name}")
                pkgs[pkg.name] = pkg
        self.graph = PkgGraph.from_pkgs(pkgs)
        self.pkgs = pkgs
        logger.debug("Discovering packages in the project... Done!")

    def enforce_version_consistency(
        self,
        mode: VersionConsistent = VersionConsistent.COMPATIBLE,
        thirdparty_mode: VersionConsistent = VersionConsistent.COMPATIBLE,
        freeze_packages: Optional[Set[str]] = None,
    ):
        """Update version of packages & third-party packages in the project.

        Args:
            mode: how to enforce version consistency for your OWN packages in the project.
            thirdparty_mode: how to enforce version consistency for third-party packages in the project.
        """
        # resolve the latest version specs of (third-party) packages
        thirdparty_pkgs = {}
        freeze_packages = freeze_packages or set()

        for pkg in self.graph.iter_pkg():
            if isinstance(pkg, ThirdPartyPackage):
                manager = self.managers[pkg.type]

                try:
                    pkg_spec = manager.find_latest_specs(
                        [
                            v
                            for k, v in pkg.invert_dependencies.items()
                            if k not in freeze_packages
                        ],
                        mode="strict"
                        if thirdparty_mode == VersionConsistent.STRICT
                        else (
                            "compatible"
                            if thirdparty_mode == VersionConsistent.COMPATIBLE
                            else None
                        ),
                    )
                except ValueError as e:
                    raise ValueError(
                        f"Package {pkg.name} has different versions used in those packages: {list(pkg.invert_dependencies.keys())}. Consider fixing it"
                    ) from e

                thirdparty_pkgs[pkg.name] = pkg_spec

                # update graph
                for key in pkg.invert_dependencies:
                    if key not in freeze_packages:
                        pkg.invert_dependencies[key] = pkg_spec

        # iterate over packages and update their dependencies.
        # however, for your own packages, always use the latest version or make sure it
        # is compatible according to the mode
        for pkg in self.pkgs.values():
            if pkg.name in freeze_packages:
                continue
            manager = self.managers[pkg.type]
            is_modified = False
            for deps in [pkg.dependencies, pkg.dev_dependencies]:
                for dep, specs in deps.items():
                    if dep in manager.get_fixed_version_pkgs():
                        # skip fixed version packages
                        continue

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
                                version_spec = manager.parse_version_spec(
                                    spec.version_spec
                                )
                                if version_spec.lowerbound != dep_version:
                                    is_modified = True
                                    spec.version_spec = manager.update_version_spec(
                                        spec.version_spec, dep_version
                                    )
                    elif specs != thirdparty_pkgs[dep]:
                        deps[dep] = thirdparty_pkgs[dep]
                        is_modified = True

            if is_modified:
                manager.save(pkg)

    def install(
        self,
        pkg_names: List[str],
        include_dev: bool = False,
    ):
        """Install packages

        Args:
            pkg_names: name of packages to install
            include_dev: whether to install development dependencies
        """
        pkgs = [self.pkgs[name] for name in pkg_names]

        with build_cache():
            for pkg in pkgs:
                manager = self.managers[pkg.type]
                # gather all dependencies in one file and install it.
                deps = self.graph.dependencies(pkg.name, include_dev=include_dev)

                skip_deps = [
                    dep.name
                    for dep in deps
                    if isinstance(dep, Package)
                    and (dep.name not in self.cfg.use_prebuilt_binaries)
                ]
                additional_deps = {
                    dep.name: next(iter(dep.invert_dependencies.values()))
                    if isinstance(dep, ThirdPartyPackage)
                    else [DepConstraint(version_spec=dep.version)]
                    for dep in deps
                    if (
                        isinstance(dep, ThirdPartyPackage)
                        and dep.name not in pkg.dependencies
                        and dep.name not in pkg.dev_dependencies
                    )
                    or (
                        isinstance(dep, Package)
                        and dep.name not in pkg.dependencies
                        and dep.name not in pkg.dev_dependencies
                        and dep.name in self.cfg.use_prebuilt_binaries
                    )
                }

                logger.info("Installing package: {}", pkg.name)
                manager.install(
                    pkg,
                    include_dev=include_dev,
                    skip_deps=skip_deps,
                    additional_deps=additional_deps,
                )

                for dep in deps:
                    if (
                        isinstance(dep, Package)
                        and dep.name not in self.cfg.use_prebuilt_binaries
                    ):
                        logger.info("Installing local dependency: {}", dep.name)
                        skip_dep_deps = list(dep.dependencies.keys()) + list(
                            dep.dev_dependencies.keys()
                        )
                        manager.install_dependency(
                            pkg, dep, skip_dep_deps=skip_dep_deps
                        )

    def publish(self, pkg_names: List[str], registries: Dict[PackageType, PkgRegistry]):
        """Publish a package. Check if the package is modified but the version is not changed so
        that we don't forget to update the version of the package.

        Args:
            pkg_names: name of the package to publish
            registries: registries to publish to
        """
        pkgs = [self.pkgs[name] for name in pkg_names]

        with build_cache():
            publishing_pkgs = {}

            for pkg in pkgs:
                publishing_pkgs[pkg.name] = pkg
                for dep in self.graph.dependencies(pkg.name, include_dev=False):
                    if isinstance(dep, Package):
                        publishing_pkgs[dep.name] = dep

            diffs = {}

            has_error = False
            for pkg in publishing_pkgs.values():
                remote_pkg_version, remote_pkg_hash = registries[
                    pkg.type
                ].get_latest_version_and_hash(pkg.name) or (None, None)
                diff = RemoteDiff.from_pkg(
                    self.managers[pkg.type], pkg, remote_pkg_version, remote_pkg_hash
                )
                if not diff.is_version_diff and diff.is_content_changed:
                    logger.error(
                        "Package {} has been modified, but its version hasn't been updated",
                        pkg.name,
                    )
                    has_error = True
                diffs[pkg.name] = diff
            if has_error:
                raise Exception(
                    "Stop publishing because some packages have been modified but their versions haven't been updated. Please see the logs for more information"
                )

            for name, pkg in sorted(publishing_pkgs.items(), key=itemgetter(0)):
                if diffs[name].is_version_diff:
                    self.managers[pkg.type].publish(pkg)
