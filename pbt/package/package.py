import os
import shutil
import subprocess
import tarfile
from dataclasses import dataclass
from enum import Enum
from functools import cached_property
from glob import glob
from operator import attrgetter
from pathlib import Path
from typing import Dict, Literal, Optional, Union, List, Iterable
from typing_extensions import TypedDict

import orjson
import toml
from graphlib import TopologicalSorter
from loguru import logger

from pbt.config import PBTConfig
from pbt.diff import diff_db, Diff, remove_diff_db
from pbt.poetry import Poetry
from pbt.version import parse_version


class PackageType(str, Enum):
    Poetry = "poetry"


DependencyInfoBase = TypedDict("DependencyInfoBased", version=str)


class DependencyInfo(DependencyInfoBase, total=False):
    pass


@dataclass
class Package:
    name: str
    version: str
    dependencies: Dict[str, DependencyInfo]
    dev_dependencies: Dict[str, DependencyInfo]

    # below are properties that can be from the package file, but may be modified heavily
    # so that you should never use them to override previous package definition
    type: PackageType
    location: Path

    # list of glob patterns to be included in the final package
    include: List[str]
    # a list of glob patterns to be excluded in the final package
    exclude: List[str]


@dataclass
class ThirdPartyPackage:
    name: str
    version: str
