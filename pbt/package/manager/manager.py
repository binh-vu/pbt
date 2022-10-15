import glob
import os
import re
from abc import ABC, abstractmethod
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, List, Literal, Optional, Sequence, Set, Tuple, Union

import semver
from pbt.config import PBTConfig
from pbt.misc import cache_func, cache_method
from pbt.package.package import DepConstraint, DepConstraints, Package, VersionSpec


class PkgManager(ABC):
    """A package manager that is responsible for all tasks related to packages such as dicovering, parsing, building, installing, and publishing."""

    def __init__(self, cfg: PBTConfig) -> None:
        self.cfg = cfg

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

    def discover(
        self, root: Path, ignore_dirs: Set[Path], ignore_dirnames: Set[str]
    ) -> List[Path]:
        """Discover potential packages in the project

        Args:
            root: The root directory to start searching
            ignore_dirs: Do not search in these directories
        """
        out = [Path(f) for f in glob.glob(self.glob_query(root.resolve()))]
        if len(ignore_dirs) > 0:
            out = [
                f for f in out if not f in ignore_dirs and f.name not in ignore_dirnames
            ]
        return out

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
        skip_deps: Optional[List[str]] = None,
        additional_deps: Optional[Dict[str, DepConstraints]] = None,
        release: bool = True,
        clean_dist: bool = True,
    ):
        """Build the package. If it has been built before during PBT running, we may skip the build step (i.e., caching results).

        Args:
            package: The package to build
            skip_deps: The optional list of dependencies to skip
            additional_deps: additional dependencies to add to the build
            release: whether to build in release mode
            clean_dist: Whether to clean the dist directory before building
        """
        raise NotImplementedError()

    @abstractmethod
    def install_dependency(
        self,
        package: Package,
        dependency: Package,
        skip_dep_deps: Optional[List[str]] = None,
    ):
        """Install the given dependency for the given package.

        The dependency must not be the phantom package as it does not containing any code to build or install.

        Note: don't expect this function will be able to find the local dependencies in the project
        as the manager relies on a package registry. For local dependencies, add them to `skip_deps` and use `install_dependency` to install them
        separately instead. Otherwise, you may get an error or the local dependencies from the package registry (the content may be different from the current ones on disk).

        Args:
            package: The package to install the dependency for
            dependency: The dependency to install
            skip_dep_deps: The dependencies of the dependency to skip. This option is not guaranteed to compiled language
        """
        raise NotImplementedError()

    @abstractmethod
    def install(
        self,
        package: Package,
        include_dev: bool = False,
        skip_deps: Optional[List[str]] = None,
        additional_deps: Optional[Dict[str, DepConstraints]] = None,
    ):
        """Install the package, assuming the the specification is updated. Note that if the package is phantom, only the dependencies are installed.

        Note: don't expect this function will be able to find the local dependencies in the project
        as the manager relies on a package registry. For local dependencies, add them to `skip_deps` and use `install_dependency` to install them
        separately instead. Otherwise, you may get an error.

        Args:
            package: The package to install
            include_dev: Whether to install dev dependencies
            skip_deps: The dependencies to skip (usually the local ones we want to install in editable mode separately). This option is not guaranteed to compiled language
            additional_deps: The additional dependencies to install
        """
        raise NotImplementedError()

    @abstractmethod
    def compute_pkg_hash(self, pkg: Package, target: Optional[str] = None) -> str:
        """Compute hash of package's content.

        Args:
            pkg: The package to compute the hash for
            target: (optional) a specific target that this package is built for. The format and value depends on the kind of package.
                For example, in Python it is: `(-{build tag})?-{python tag}-{abi tag}-{platform tag}.whl` (pep-491)
        """
        raise NotImplementedError()

    @abstractmethod
    def get_fixed_version_pkgs(self) -> Set[str]:
        """Get set of packages which versions are fixed and never should updated."""
        raise NotImplementedError()

    @contextmanager  # type: ignore
    def mask_file(
        self,
        file_path: Union[str, Path],
    ):
        """Temporary mask out a file

        Arguments:
            file_path: The path to the file to mask
        """
        file_path = str(file_path)
        assert os.path.isfile(file_path)
        try:
            os.rename(file_path, file_path + ".tmp")
            yield None
        finally:
            os.rename(file_path + ".tmp", file_path)

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

        # include nested packages
        for depfile in glob.glob(self.glob_query(pkg.location)):
            dir_paths.append(depfile)

        if len(patterns) > 0:
            for pattern in patterns:
                if not (pattern.endswith("/**/*") and pattern[:-5].find("*") == -1):
                    raise NotImplementedError()
                dir_paths.append(pattern[:-5])

        output = []
        for file in files:
            if any(file.startswith(dpath) for dpath in dir_paths):
                output.append(file)
        return output

    def find_latest_specs(
        self,
        lst_specs: List[DepConstraints],
        mode: Optional[Literal["strict", "compatible"]] = None,
    ) -> DepConstraints:
        """Given a set of specs, some of them may be the same, some of them are older.

        This function finds the latest version for each constraint based on the lowerbound

        Args:
            lst_specs: list of list of specs
            mode: 'strict' or 'compatible' or None.
                'strict' means all versions must be the same.
                'compatible' means all versions must be compatible.
                None means we don't check
        """
        constraints: Dict[Optional[str], Tuple[VersionSpec, DepConstraint]] = {}
        for specs in lst_specs:
            for spec in specs:
                version_spec = self.parse_version_spec(spec.version_spec)
                if spec.constraint not in constraints:
                    constraints[spec.constraint] = (version_spec, spec)
                else:
                    prev_version_spec, prev_spec = constraints[spec.constraint]
                    if version_spec == prev_version_spec:
                        continue

                    has_recent_version = False

                    # determine if the current spec is newer than the previous one
                    if (
                        version_spec.lowerbound is None
                        or prev_version_spec.lowerbound is None
                    ):
                        raise ValueError(
                            f"Uncompatible constraint {spec.version_spec} vs {prev_spec}. Consider fixing it"
                        )

                    if mode == "strict":
                        raise ValueError()
                    elif mode == "compatible":
                        # they are incompatible if either the same or one is stricter
                        try:
                            version_spec.intersect(prev_version_spec)
                        except ValueError:
                            # they are incompatible
                            raise

                    if version_spec.lowerbound > prev_version_spec.lowerbound:
                        has_recent_version = True
                    elif version_spec.upperbound is not None and (
                        prev_version_spec.upperbound is None
                        or version_spec.upperbound < prev_version_spec.upperbound
                    ):
                        has_recent_version = True

                    if has_recent_version:
                        constraints[spec.constraint] = (version_spec, spec)

        # sort to make the order consistent
        return [v[1] for k, v in sorted(constraints.items(), key=lambda x: x[0] or "")]

    def is_version_compatible(
        self, version: semver.VersionInfo, version_spec: str
    ) -> bool:
        """Check if the given version is compatible with the given rule

        Args:
            version: package version
            version_spec: The version spec to check against
        """
        return self.parse_version_spec(version_spec).is_version_compatible(version)

    @classmethod
    @cache_func()
    def parse_version_spec(
        cls,
        rule: str,
    ) -> VersionSpec:
        """Parse the given version rule to get lowerbound and upperbound (exclusive)

        Example:
            - "^1.0.0" -> (1.0.0, 2.0.0)
            - ">= 1.0.0" -> (1.0.0, None)
            - ">= 1.0.0, < 2.1.3" -> (1.0.0, 2.1.3)
        """
        m = re.match(
            r"(?P<op1>\^|~|>|>=|==|<|<=)? *(?P<version1>[^ ,\^\~>=<]+)(?:(?:(?: *, *)|(?: +))(?P<op2>\^|~|>|>=|==|<|<=) *(?P<version2>[^ ,\^\~>=<]+))?",
            rule,
        )
        assert (
            m is not None
        ), f"The constraint is too complicated to handle for now: `{rule}`"

        op1, version1 = m.group("op1"), m.group("version1")
        op2, version2 = m.group("op2"), m.group("version2")

        if op1 == "":
            op1 = "=="

        lowerbound = cls.parse_version(version1)
        if op1 == "^":
            assert version2 is None
            # special case for 0 following the nodejs way (I can't believe why)
            # see more: https://nodesource.com/blog/semver-tilde-and-caret/
            if lowerbound.major == 0:
                if lowerbound.minor == 0:
                    upperbound = lowerbound.bump_patch()
                else:
                    upperbound = lowerbound.bump_minor()
            else:
                upperbound = lowerbound.bump_major()
            spec = VersionSpec(
                lowerbound=lowerbound,
                upperbound=upperbound,
                is_lowerbound_inclusive=True,
                is_upperbound_inclusive=False,
            )
        elif op1 == "~":
            assert version2 is None
            if m.group("version1").isdigit():
                # only contains major version
                upperbound = lowerbound.bump_major()
            else:
                upperbound = lowerbound.bump_minor()
            spec = VersionSpec(
                lowerbound=lowerbound,
                upperbound=upperbound,
                is_lowerbound_inclusive=True,
                is_upperbound_inclusive=False,
            )
        elif op1 == "==":
            assert version2 is None
            upperbound = lowerbound
            spec = VersionSpec(
                lowerbound=lowerbound,
                upperbound=upperbound,
                is_lowerbound_inclusive=True,
                is_upperbound_inclusive=True,
            )
        else:
            upperbound = cls.parse_version(version2) if version2 is not None else None
            if op1 == "<" or op1 == "<=":
                op1, op2 = op2, op1
                lowerbound, upperbound = upperbound, lowerbound
            spec = VersionSpec(
                lowerbound=lowerbound,
                upperbound=upperbound,
                is_lowerbound_inclusive=op1 == ">=",
                is_upperbound_inclusive=op2 == "<=",
            )
        return spec

    def update_version_spec(
        self, version_spec: str, version: Union[str, semver.VersionInfo]
    ) -> str:
        """Update the given version spec to compatible to the given version

        Args:
            version_spec: The version spec to update
            version: The version to update the version spec with
        """
        m = re.match(r"(\^|~|>|>=|==|<|<=) *([^ ]+)", version_spec)
        if m is None:
            raise NotImplementedError(
                f"Not implementing update complicated version spec `{version_spec}` yet"
            )

        groups = m.groups()
        return f"{groups[0]}{str(version)}"

    @classmethod
    @cache_func()
    def parse_version(cls, version: str) -> semver.VersionInfo:
        m = re.match(
            r"^(?P<major>\d+)(?P<minor>\.\d+)?(?P<patch>\.\d+)?(?P<rest>[^\d].*)?$",
            version,
        )
        assert (
            m is not None
        ), f"Current parser is not able to parse version: `{version}` yet"

        if m is not None:
            parts = [
                m.group("major"),
                m.group("minor") or ".0",
                m.group("patch") or ".0",
                m.group("rest") or "",
            ]
            if not parts[-1].startswith("-") and parts[-1] != "":
                # add hyphen to make it compatible with semver package.
                # e.g. 21.11b1 -> 21.11.0-b1
                parts[-1] = "-" + parts[-1]
            version = "".join(parts)

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
