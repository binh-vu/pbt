from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger


class PackageType(str, Enum):
    Poetry = "poetry"


@dataclass
class DepConstraint:
    """Constraint of a dependency.

    The two important fields are rule (for comparing between versions) and constraint
    (for distinguish between different platforms/os).

    To reconstruct/save the constraint,
    back to the original package specification, update the `origin_spec` with the a new key
    stored in `version_field` and value from `version`. The reason for this behaviour is to
    support cases such as where the dependency is from git (`version_field` = 'git').
    """

    # rule for matching version of dependency, e.g. "^1.0.0" or ">= 1.0.0"
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
