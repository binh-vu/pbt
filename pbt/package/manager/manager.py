from functools import lru_cache
from operator import attrgetter
import semver, re

from abc import ABC, abstractmethod
from contextlib import contextmanager
from pathlib import Path
from typing import List, Optional, Tuple, Union
from pbt.package.package import DepConstraints, Package
from pbt.misc import cache_func


class PkgManager(ABC):
    """A package manager that is responsible for all tasks related to packages such as dicovering, parsing, installing and publishing."""

    @abstractmethod
    def is_package_directory(self, dir: Path) -> bool:
        """Check if the given directory is a package directory."""
        raise NotImplementedError()

    @abstractmethod
    def glob_query(self, root: Path) -> str:
        """Return glob query to iterate over all (potential) packages in the project

        Args:
            root_dir: The root directory where we start searching
        """
        raise NotImplementedError()

    @contextmanager
    def mask(self, package: Package, deps: List[str]):
        """Temporary mask out selected dependencies of the package. This is usually used for installing the package

        Args:
            package: The package to mask
            deps: The dependencies to mask
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
    def install(self, package: Package, skip_deps: List[str] = None):
        """Install the package

        Args:
            package: The package to install
            skip_deps: The dependencies to skip (usually the ones we want to install in linked mode).
        """
        raise NotImplementedError()

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

        return sorted(list(constraints.values()), key=attrgetter("constraint"))

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
        """Update the given version spec to compatible  the given version

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
    def parse_version(self, version: str) -> semver.VersionInfo:
        m = re.match(r"^\d+(?P<minor>\.\d+)?$", version)
        if m is not None:
            if m.group("minor") is None:
                version += ".0.0"
            else:
                version += ".0"
        return semver.VersionInfo.parse(version)
