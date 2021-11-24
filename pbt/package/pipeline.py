import glob
from pathlib import Path
from typing import List
from pbt.package.graph import PkgGraph
from pbt.package.manager.manager import PkgManager
from pbt.package.manager.poetry import Poetry


class BTPipeline:
    def __init__(self, root: Path, managers: List[PkgManager]) -> None:
        self.root = root
        self.managers = managers
        self.graph = PkgGraph()

    def discover(self):
        """Discover packages in the project."""
        pkgs = {}
        for manager in self.managers:
            for pkg in manager.iter_package(self.root):
                if pkg.name in pkgs:
                    raise RuntimeError(f"Duplicate package {pkg.name}")
                pkgs[pkg.name] = pkg
        self.graph = PkgGraph.from_pkgs(pkgs)

    def install(self, pkg_name: str):
        """Install a package."""
        pass

    def update(self):
        """Update packages in the project."""
        pass
