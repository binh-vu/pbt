from abc import ABC, abstractmethod
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, List
from pbt.package.package import Package


class PkgManager(ABC):
    """A package manager that is responsible for all tasks related to packages such as dicovering, parsing, installing and publishing."""

    @abstractmethod
    def is_package_directory(self, dir: Path) -> bool:
        """Check if the given directory is a package directory."""
        raise NotImplementedError()

    @abstractmethod
    def iter_package(self, root_dir: Path) -> Iterable[Package]:
        """Iterate over all packages in the project

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
