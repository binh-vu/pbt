from dataclasses import dataclass
from itertools import chain
import networkx as nx
from typing import Dict, List

from pbt.package.package import Package, ThirdPartyPackage


class PkgGraph:
    """Representing the dependencies between packages in the project."""

    def __init__(self, g: nx.DiGraph = None) -> None:
        self.g = g or nx.DiGraph()
        self.pkgs = {}

    @staticmethod
    def from_pkgs(pkgs: Dict[str, Package]) -> None:
        g = nx.DiGraph()
        for pkg in pkgs.values():
            g.add_node(pkg.name, pkg=pkg)

        for pkg in pkgs.values():
            for dep, version in chain(
                pkg.dependencies.items(), pkg.dev_dependencies.items()
            ):
                if not g.has_node(dep):
                    if dep in pkgs:
                        g.add_node(dep, pkg=pkgs[dep])
                    else:
                        g.add_node(dep, pkg=ThirdPartyPackage(dep, version["version"]))
                else:
                    g.add_edge(dep, pkg.name)

    def toposort(self) -> List[str]:
        """Return the list of packages sorted in topological order."""
        return []
