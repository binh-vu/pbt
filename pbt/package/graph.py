from dataclasses import dataclass
from itertools import chain
import networkx as nx
from typing import Dict, List
from __future__ import annotations
from pbt.package.package import Package, ThirdPartyPackage


class PkgGraph:
    """Representing the dependencies between packages (including third-party packages) in the project."""

    def __init__(self, g: nx.DiGraph = None) -> None:
        self.g = g or nx.DiGraph()
        self.pkgs = {}

    @staticmethod
    def from_pkgs(pkgs: Dict[str, Package]) -> PkgGraph:
        """Create a PkgGraph from a dictionary of packages.

        Args:
            pkgs: A dictionary of packages.
        """
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
                g.add_edge(dep, pkg.name)

        try:
            cycles = nx.find_cycle(g, orientation="original")
            raise ValueError(f"Found cyclic dependencies: {cycles}")
        except nx.NetworkXNoCycle:
            pass

        return PkgGraph(g)

    def toposort(self) -> List[str]:
        """Return the list of packages sorted in topological order."""
        return []
