from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Generic, Optional, TypeVar

from semver import VersionInfo

from pbt.package.dependency_specification.interface import VersionComparisonMode

T = TypeVar("T")


@dataclass(frozen=True)
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

    def update_version(self, version: VersionInfo) -> Optional[VersionSpec]:
        """Update this version spec so that the given version is compatible with it. Note that if the version
        isn't compatible with the current spec, an example will be raised since this requires the user to verify
        it as there is no way to guarantee the new spec won't break the code.

        Arguments:
            version: The minimum version that this spec needs to match.

        Returns:
            The new version spec if the version has been updated. None otherwise.
        """
        if not self.is_version_compatible(version):
            raise VersionIncompatibleToSpecError()

        if self.lowerbound is None or self.lowerbound < version:
            return VersionSpec(
                lowerbound=version,
                upperbound=self.upperbound,
                is_lowerbound_inclusive=True,
                is_upperbound_inclusive=self.is_upperbound_inclusive,
            )

        return None

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

    def clone(self) -> VersionSpec:
        return VersionSpec(
            lowerbound=self.lowerbound,
            upperbound=self.upperbound,
            is_lowerbound_inclusive=self.is_lowerbound_inclusive,
            is_upperbound_inclusive=self.is_upperbound_inclusive,
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


@lru_cache(maxsize=None)
def parse_version_info(version: str) -> VersionInfo:
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

    return VersionInfo.parse(version)


class VersionIncompatibleToSpecError(Exception):
    pass


class IncompatibleVersionSpecError(Exception):
    pass
