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
            for fpath in manager.glob_query(self.root):
                pkg = manager.load(Path(fpath).parent)
                if pkg.name in pkgs:
                    raise RuntimeError(f"Duplicate package {pkg.name}")
                pkgs[pkg.name] = pkg
        self.graph = PkgGraph.from_pkgs(pkgs)

    def force_version_consistency(self):
        """Update version of packages & third-party packages in the project."""
        pass

    def install(self, pkg_name: str):
        """Install a package."""
        pass
