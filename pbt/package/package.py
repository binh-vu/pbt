from __future__ import annotations
from dataclasses import dataclass
from distutils.version import Version
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional
from typing_extensions import TypeGuard

from semver import VersionInfo
from loguru import logger


@dataclass
class Package:
    name: str
    version: str
    dependencies: Dict[str, DepConstraints]
    dev_dependencies: Dict[str, DepConstraints]

    # below are properties that can be from the package file, but may be modified heavily
    # so that you should never use them to override previous package definition
    type: PackageType
    location: Path
    # list of glob patterns to be included in the final package
    include: List[str]
    # a list of glob patterns to be excluded in the final package
    exclude: List[str]


class PackageType(str, Enum):
    Poetry = "poetry"
    Maturin = "maturin"

    def is_compatible(self, other: PackageType) -> bool:
        return (
            self == other
            or (self == PackageType.Poetry and other == PackageType.Maturin)
            or (self == PackageType.Maturin and other == PackageType.Poetry)
        )


@dataclass(eq=True)
class DepConstraint:
    """Constraint of a dependency.

    The two important fields are rule (for comparing between versions) and constraint
    (for distinguish between different platforms/os).

    To reconstruct/save the constraint,
    back to the original package specification, update the `origin_spec` with the a new key
    stored in `version_field` and value from `version`. The reason for this behaviour is to
    support cases such as where the dependency is from git (`version_field` = 'git').
    """

    # rule for matching version of dependency, e.g. "^1.0.0" or ">= 1.0.0", the rule sometimes depends on what package's type
    version_spec: str
    # an identifier for the condition that this version is applicable to.
    # none mean there is no other constraint.
    constraint: Optional[str] = None
    # name of the rule field in origin specification
    # none if the spec is just a string
    version_spec_field: Optional[str] = None
    # the original specification without the version
    # none if the spec is just a string
    origin_spec: Optional[dict] = None


# see: https://python-poetry.org/docs/dependency-specification/
# the constraints always sorted by constraint
DepConstraints = List[DepConstraint]


@dataclass
class VersionSpec:
    lowerbound: Optional[VersionInfo]
    upperbound: Optional[VersionInfo]
    is_lowerbound_inclusive: bool
    is_upperbound_inclusive: bool

    def is_version_compatible(self, version: VersionInfo) -> bool:
        """Check if the given version is compatible with the given rule

        Args:
            version: the version to check
        """
        incompatible = (
            self.lowerbound is not None
            and (
                (self.is_lowerbound_inclusive and self.lowerbound > version)
                or (not self.is_lowerbound_inclusive and self.lowerbound >= version)
            )
        ) or (
            self.upperbound is not None
            and (
                (self.is_upperbound_inclusive and self.upperbound < version)
                or (not self.is_upperbound_inclusive and self.upperbound <= version)
            )
        )
        return not incompatible

    def intersect(self, version_spec: VersionSpec) -> VersionSpec:
        """Intersect two version specs. Result in a stricter version spec.

        Raise exception if the intersection is empty.

        Examples:
            - "^1.0.0" and "^2.0.0" -> Exception
            - "^1.1.0" and "^1.2.0" -> "^1.2.0"
        """
        lb = self.lowerbound
        is_lb_inclusive = self.is_lowerbound_inclusive

        if version_spec.lowerbound is not None:
            if lb is None:
                lb = version_spec.lowerbound
                is_lb_inclusive = version_spec.is_lowerbound_inclusive
            elif version_spec.lowerbound > lb:
                lb = version_spec.lowerbound
                is_lb_inclusive = version_spec.is_lowerbound_inclusive
            elif version_spec.lowerbound == lb:
                is_lb_inclusive = (
                    is_lb_inclusive and version_spec.is_lowerbound_inclusive
                )

        ub = self.upperbound
        is_ub_inclusive = self.is_upperbound_inclusive

        if version_spec.upperbound is not None:
            if ub is None:
                ub = version_spec.upperbound
                is_ub_inclusive = version_spec.is_upperbound_inclusive
            elif version_spec.upperbound < ub:
                ub = version_spec.upperbound
                is_ub_inclusive = version_spec.is_upperbound_inclusive
            elif version_spec.upperbound == ub:
                is_ub_inclusive = (
                    is_ub_inclusive and version_spec.is_upperbound_inclusive
                )

        if lb is not None and ub is not None and lb > ub:
            raise ValueError(
                "Can't intersect two version specs: {} and {} because it results in empty spec".format(
                    self, version_spec
                )
            )

        return VersionSpec(
            lowerbound=lb,
            upperbound=ub,
            is_lowerbound_inclusive=is_lb_inclusive,
            is_upperbound_inclusive=is_ub_inclusive,
        )

    def to_pep508_string(self):
        s = f">{'=' if self.is_lowerbound_inclusive else ''} {str(self.lowerbound)}"
        if self.upperbound is not None:
            s += f", <{'=' if self.is_upperbound_inclusive else ''} {str(self.upperbound)}"
        return s

    def __eq__(self, other: VersionSpec):
        if other is None or not isinstance(other, VersionSpec):
            return False

        return (
            (
                (
                    self.lowerbound is not None
                    and other.lowerbound is not None
                    and self.lowerbound == other.lowerbound
                )
                or (self.lowerbound is None and other.lowerbound is None)
            )
            and (
                (
                    self.upperbound is not None
                    and other.upperbound is not None
                    and self.upperbound == other.upperbound
                )
                or (self.upperbound is None and other.upperbound is None)
            )
            and (self.is_lowerbound_inclusive == other.is_lowerbound_inclusive)
            and (self.is_upperbound_inclusive == other.is_upperbound_inclusive)
        )
