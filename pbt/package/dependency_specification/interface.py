from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Generic, Optional, TypeVar

from pbt.package.package import VersionSpec

I = TypeVar("I")
O = TypeVar("O")
M = TypeVar("M")


class VersionComparisonMode(str, Enum):
    STRICT = "strict"
    COMPATIBLE = "compatible"


class SpecificationFormat(ABC, Generic[I, O]):
    @abstractmethod
    def deserialize(self, spec: I) -> DependencySpecification:
        """Deserialize the specification according to the given format."""
        pass

    @abstractmethod
    def serialize(self, spec: DependencySpecification) -> O:
        """Serialize the specification according to the given format."""
        pass


class DependencySpecification(ABC):
    """Represent a dependency specification."""

    @abstractmethod
    def get_dep_name(self) -> str:
        """Get the name of the dependency."""
        pass

    @abstractmethod
    def is_version_compatible(self, version: str) -> bool:
        """Test if the version is compatible to the current dependency spec."""
        pass

    @abstractmethod
    def update_version(
        self, version: str, mode: VersionComparisonMode
    ) -> Optional[DependencySpecification]:
        """Update the spec to match with the given version.

        If the mode is strict, the lowerbound is set to the version. Otherwise, the lowerbound
        is set to the minimum version that is compatible with the given version.

        Return None if the spec does not change.
        """
        pass

    @classmethod
    @abstractmethod
    def sync_versions(
        cls, specs: list[DependencySpecification], mode: VersionComparisonMode
    ) -> list[DependencySpecification]:
        """Sync versions of specs to be compatible with each other according to the given mode.

        This function will raise exception when they detect a conflict between versions. If the spec
        contains different versions for different constraints, the function sync versions for each
        constraint separately. Any specs that do not contain the constraint will be ignored.
        """
        pass
