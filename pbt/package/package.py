from __future__ import annotations

from dataclasses import dataclass
from distutils.version import Version
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger
from semver import VersionInfo
from typing_extensions import TypeGuard

from pbt.package.dependency_specification import DependencySpecification


@dataclass
class Package:
    name: str
    version: str
    dependencies: Dict[str, DependencySpecification]
    dev_dependencies: Dict[str, DependencySpecification]

    # below are properties that can be from the package file, but may be modified heavily
    # so that you should never use them to override previous package definition
    type: PackageType
    location: Path
    # list of glob patterns to be included in the final package
    include: List[str]
    # a list of glob patterns to be excluded in the final package
    exclude: List[str]

    def get_all_dependency_names(self) -> List[str]:
        out = list(self.dependencies.keys())
        out.extend(self.dev_dependencies.keys())
        return out


class PackageType(str, Enum):
    Poetry = "poetry"
    Maturin = "maturin"

    def is_compatible(self, other: PackageType) -> bool:
        return (
            self == other
            or (self == PackageType.Poetry and other == PackageType.Maturin)
            or (self == PackageType.Maturin and other == PackageType.Poetry)
        )
