import glob
import os
import re
from abc import ABC, abstractmethod
from contextlib import contextmanager
from email.generator import Generator
from functools import lru_cache
from operator import attrgetter, itemgetter
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple, Union

import semver
from pbt.config import PBTConfig
from pbt.misc import cache_func
from pbt.package.package import DepConstraint, DepConstraints, Package


class PkgManager(ABC):
    """A package manager that is responsible for all tasks related to packages such as dicovering, parsing, installing and publishing."""

    @abstractmethod
    def is_package_directory(self, dir: Path) -> bool:
        """Check if the given directory is a package directory."""
        raise NotImplementedError()

    @abstractmethod
    def glob_query(self, root: Path) -> str:
        """Return glob query to iterate over all (potential) packages in the project

        Example:
            - "{root}/**/package.json" for NodeJs
            - "{root}/**/package.xml" for Maven
            - "{root}/**/pyproject.toml" for Poetry

        Args:
            root_dir: The root directory where we start searching

        Returns:
            A glob query to iterate over all specification files in the project
        """
        raise NotImplementedError()

    @abstractmethod
    def load(self, dir: Path) -> Package:
        """Load a package from the given directory.

        Args:
            dir: The directory where the package is located
        """
        raise NotImplementedError()

    @abstractmethod
    def save(self, package: Package):
        """Save the current configuration of the package

        Args:
            package: The package to save
        """
        raise NotImplementedError()

    @abstractmethod
    def clean(self, package: Package):
        """Remove previously installed dependencies and the environment where the package is installed, for a freshly start.
        In addition, this also cleans built artifacts.

        Args:
            package: The package to clean
        """
        raise NotImplementedError()

    @abstractmethod
    def publish(self, package: Package):
        """Publish the package to the package registry

        Args:
            package: The package to publish
        """
        raise NotImplementedError()

    @abstractmethod
    def build(
        self,
        package: Package,
    ):
        """Build the package. If it has been built before during PBT running, we may skip the build step (i.e., caching results).

        Args:
            package: The package to build
        """
        raise NotImplementedError()

    @abstractmethod
    def install_dependency(
        self,
        package: Package,
        dependency: Package,
        editable: bool = False,
        skip_dep_deps: List[str] = None,
    ):
        """Install the given dependency for the given package.

        Note: don't expect this function will be able to find the local dependencies in the project
        as the manager relies on a package registry. For local dependencies, add them to `skip_deps` anddd use `install_dependency` to install them
        separately instead. Otherwise, you may get an error.

        Args:
            package: The package to install the dependency for
            dependency: The dependency to install
            editable: Whether the dependency is editable (auto-reload)
            skip_dep_deps: The dependencies of the dependency to skip. This option is not guaranteed to compiled language
        """
        raise NotImplementedError()

    @abstractmethod
    def install(
        self,
        package: Package,
        editable: bool = False,
        include_dev: bool = False,
        skip_deps: List[str] = None,
        additional_deps: Dict[str, DepConstraints] = None,
    ):
        """Install the package, assuming the the specification is updated.

        Note: don't expect this function will be able to find the local dependencies in the project
        as the manager relies on a package registry. For local dependencies, add them to `skip_deps` anddd use `install_dependency` to install them
        separately instead. Otherwise, you may get an error.

        Args:
            package: The package to install
            editable: Whether the package is editable (auto-reload)
            include_dev: Whether to install dev dependencies
            skip_deps: The dependencies to skip (usually the local ones we want to install in editable mode separately). This option is not guaranteed to compiled language
            additional_deps: The additional dependencies to install
        """
        raise NotImplementedError()

    @abstractmethod
    def compute_pkg_hash(self, pkg: Package) -> str:
        """Compute hash of package's content.

        Args:
            pkg: The package to compute the hash for
        """
        raise NotImplementedError()

    def filter_included_files(self, pkg: Package, files: List[str]) -> List[str]:
        """Filter out the files that are not included in the package, these are files that
        won't affect the content of the package.

        Args:
            pkg: The package to check against
            files: The files to filter
        """
        dir_paths = []
        patterns = []

        for pattern in pkg.include:
            pattern = os.path.join(pkg.location, pattern)
            # TODO: detect the pattern better
            if "*" in pattern or "?" in pattern or ("[" in pattern and "]" in pattern):
                patterns.append(pattern)
            else:
                dir_paths.append(pattern)

        for depfile in glob.glob(self.glob_query(pkg.location)):
            dir_paths.append(depfile)

        if len(patterns) > 0:
            raise NotImplementedError()

        output = []
        for file in files:
            if any(file.startswith(dpath) for dpath in dir_paths):
                output.append(file)
        return output

    def find_latest_specs(self, lst_specs: List[DepConstraints]) -> DepConstraints:
        """Given a set of specs, some of them may be the same, some of them are older.

        This function finds the latest version for each constraint
        """
        constraints = {}
        for specs in lst_specs:
            for spec in specs:
                lb, ub = self.parse_version_spec(spec.version_spec)
                if spec.constraint not in constraints:
                    constraints[spec.constraint] = (lb, ub, spec)
                else:
                    prev_lb, prev_ub, prev_spec = constraints[spec.constraint]
                    if lb > prev_lb:
                        constraints[spec.constraint] = (lb, ub, spec)
                    elif lb == prev_lb and ub != prev_ub:
                        raise ValueError(
                            f"Uncompatible constraint {spec.version_spec} vs {prev_spec}. Consider fixing it"
                        )

        return [v[2] for k, v in sorted(constraints.items(), key=itemgetter(0))]

    def is_version_compatible(
        self, version: semver.VersionInfo, version_spec: str
    ) -> bool:
        """Check if the given version is compatible with the given rule

        Args:
            version: package version
            version_spec: The version spec to check against
        """
        lowerbound, upperbound = self.parse_version_spec(version_spec)
        if upperbound is not None and version >= upperbound:
            return False
        return version >= lowerbound

    @cache_func()
    def parse_version_spec(
        self, rule: str
    ) -> Tuple[semver.VersionInfo, Optional[semver.VersionInfo]]:
        """Parse the given version rule to get lowerbound and upperbound (exclusive)

        Example:
            - "^1.0.0" -> ">= 1.0.0 < 2.0.0"
            - ">= 1.0.0" -> ">= 1.0.0"
        """
        m = re.match(
            r"(?P<op>[\^\~]?)(?P<major>\d+)\.((?P<minor>\d+)\.(?P<patch>\d+)?)?",
            rule,
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

        return lowerbound, upperbound

    def update_version_spec(
        self, version_spec: str, version: Union[str, semver.VersionInfo]
    ) -> str:
        """Update the given version spec to compatible to the given version

        Args:
            version_spec: The version spec to update
            version: The version to update the version spec with
        """
        m = re.match(r"([\^~>=!] *)([^ ]+)", version_spec)
        if m is None:
            raise NotImplementedError(
                f"Not implementing update complicated version spec `{version_spec}` yet"
            )

        groups = m.groups()
        return f"{groups[0]}{str(version)}"

    @cache_func()
    @staticmethod
    def parse_version(version: str) -> semver.VersionInfo:
        m = re.match(r"^\d+(?P<minor>\.\d+)?$", version)
        if m is not None:
            if m.group("minor") is None:
                version += ".0.0"
            else:
                version += ".0"
        return semver.VersionInfo.parse(version)

    def next_version(self, pkg: Package, rule: Literal["major", "minor", "patch"]):
        """Update version of the package if a valid bump rule is provided

        Args:
            pkg: The package to update
            rule: The rule to update the version with
        """
        pkg.version = str(self.parse_version(pkg.version).next_version(rule))
        self.save(pkg)


@contextmanager
def build_cache(_cache={}):
    """Yield a dictionary that can be used to cache result of the build (whether the package has been built or not)

    Nested call will return the same dictionary.
    """
    if "db" not in _cache:
        _cache["db"] = {}
    if "count" not in _cache:
        _cache["count"] = 0

    try:
        _cache["count"] += 1
        yield _cache["db"]
    finally:
        _cache["count"] -= 1
        if _cache["count"] == 0:
            _cache["db"] = {}
