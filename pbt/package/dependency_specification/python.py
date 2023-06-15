from __future__ import annotations

import copy
from abc import abstractmethod
from copy import deepcopy
from dataclasses import dataclass
from typing import Generic, Optional, TypeVar

from semver import VersionInfo

from pbt.package.dependency_specification.interface import (
    DependencySpecification,
    SpecificationFormat,
    VersionComparisonMode,
)
from pbt.package.dependency_specification.version import (
    IncompatibleVersionSpecError,
    VersionSpec,
    parse_version_info,
)

T = TypeVar("T")


@dataclass(frozen=True)
class PyVersionSpec:
    url: Optional[str] = None
    version: Optional[VersionSpec] = None

    def is_version_compatible(self, version: VersionInfo) -> bool:
        """Check if a version is compatible with the current version spec."""
        if self.url is not None:
            """URL is always incompatible to any version"""
            return False
        assert self.version is not None
        return self.version.is_version_compatible(version)

    def update_version(self, version: VersionInfo) -> Optional[PyVersionSpec]:
        """Update this version spec so that the given version is compatible with it. Note that if the version
        isn't compatible with the current spec, an example will be raised since this requires the user to verify
        it as there is no way to guarantee the new spec won't break the code.

        Arguments:
            version: The minimum version that this spec needs to match.

        Returns:
            The new version spec if the version has been updated. None otherwise.
        """
        if self.url is not None:
            raise Exception("Cannot update version for a URL dependency spec")
        versionspec = self.version
        assert versionspec is not None
        versionspec = versionspec.update_version(version)
        if versionspec is None:
            return None
        return PyVersionSpec(url=self.url, version=versionspec)

    def intersect(self, spec: PyVersionSpec) -> PyVersionSpec:
        if self.url is not None:
            if spec.url != self.url:
                raise IncompatibleVersionSpecError()
            return self

        assert self.version is not None and spec.version is not None
        versionspec = self.version.intersect(spec.version)
        return PyVersionSpec(url=self.url, version=versionspec)

    def clone(self) -> PyVersionSpec:
        return PyVersionSpec(url=self.url, version=self.version)


@dataclass
class PySingleDepSpec(Generic[T]):
    version_or_url: PyVersionSpec
    extras: list[str]
    marker: T

    def clone(self) -> PySingleDepSpec[T]:
        return PySingleDepSpec(
            version_or_url=self.version_or_url.clone(),
            extras=deepcopy(self.extras),
            marker=deepcopy(self.marker),
        )


@dataclass
class PyDepSpec(Generic[T], DependencySpecification):
    name: str
    constraints: list[PySingleDepSpec[T]]

    def get_dep_name(self) -> str:
        return self.name

    @abstractmethod
    def clone(self) -> PyDepSpec:
        pass


class Pep508DependencySpec(PyDepSpec[str]):
    def is_version_compatible(self, version: str) -> bool:
        """Test if the version is compatible to the current dependency spec."""
        parsed_version = parse_version_info(version)
        return any(
            c.version_or_url.is_version_compatible(parsed_version)
            for c in self.constraints
        )

    def update_version(self, version: str) -> Optional[DependencySpecification]:
        """Update the spec to match with the given version.

        If the mode is strict, the lowerbound is set to the version. Otherwise, the lowerbound
        is set to the minimum version that is compatible with the given version.

        Return None if the spec does not change.
        """
        if len(self.constraints) > 1:
            raise Exception("Cannot update version for a complex dependency spec")

        parsed_version = parse_version_info(version)

        version_or_url = self.constraints[0].version_or_url.clone()
        if version_or_url.update_version(parsed_version):
            newself = self.clone()
            newself.constraints[0].version_or_url = version_or_url
            return newself

        return None

    @classmethod
    def resolve(cls, specs: list[DependencySpecification]) -> DependencySpecification:
        name = ""
        constraints = {}
        for spec in specs:
            assert isinstance(spec, PyDepSpec)
            if len(constraints) == 0:
                name = spec.name
                constraints = {c.marker: c.clone() for c in spec.constraints}
            else:
                for constraint in spec.constraints:
                    if constraint.marker not in constraints:
                        raise Exception(
                            "Cannot resolve two dependency specifications with different constraints"
                        )

                    newconstraint = constraints[constraint.marker]
                    newconstraint.extras.extend(
                        [e for e in constraint.extras if e not in newconstraint.extras]
                    )
                    newconstraint.version_or_url = (
                        newconstraint.version_or_url.intersect(
                            constraint.version_or_url
                        )
                    )

        return cls(name=name, constraints=list(constraints.values()))

    @classmethod
    def sync_versions(
        cls, specs: list[DependencySpecification]
    ) -> list[DependencySpecification]:
        marker2version: dict[str, PyVersionSpec] = {}
        for spec in specs:
            assert isinstance(spec, PyDepSpec)
            for c in spec.constraints:
                if c.marker not in marker2version:
                    marker2version[c.marker] = c.version_or_url.clone()
                else:
                    marker2version[c.marker] = marker2version[c.marker].intersect(
                        c.version_or_url
                    )

        newspecs = []
        for spec in specs:
            assert isinstance(spec, PyDepSpec)
            newspec = spec.clone()
            for c in newspec.constraints:
                c.version_or_url = marker2version[c.marker]
        return newspecs

    def clone(self) -> Pep508DependencySpec:
        return Pep508DependencySpec(
            name=self.name,
            constraints=[c.clone() for c in self.constraints],
        )


class Pep508SpecFormat(SpecificationFormat[str, str]):
    def deserialize(self, spec: str) -> Pep508DependencySpec:
        pass
