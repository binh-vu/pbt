from dataclasses import dataclass
from itertools import chain
import networkx as nx
from typing import Dict, Iterable, List, Type, Union
from __future__ import annotations
from pbt.package.package import Package, DepConstraints, PackageType


@dataclass
class ThirdPartyPackage:
    name: str
    type: PackageType
    # mapping from source package that use this package to the version the source package depends on
    invert_dependencies: Dict[str, DepConstraints]


class PkgGraph:
    """Representing the dependencies between packages (including third-party packages) in the project.
    The edge between (A, B) represents a dependency relationship that package A uses package B.
    """

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
            for deps, is_dev in [
                (pkg.dependencies, False),
                (pkg.dev_dependencies, True),
            ]:
                deps: Dict[str, DepConstraints]
                for dep, specs in deps.items():
                    if not g.has_node(dep):
                        assert dep not in pkgs
                        g.add_node(
                            dep,
                            pkg=ThirdPartyPackage(dep, pkg.type, {pkg.name: specs}),
                        )
                    else:
                        dep_pkg = g.nodes[dep]["pkg"]
                        if isinstance(dep_pkg, ThirdPartyPackage):
                            assert dep_pkg.type == pkg.type
                            dep_pkg.invert_dependencies[pkg.name] = specs
                    g.add_edge(pkg.name, dep, is_dev=is_dev)

        try:
            cycles = nx.find_cycle(g, orientation="original")
            raise ValueError(f"Found cyclic dependencies: {cycles}")
        except nx.NetworkXNoCycle:
            pass

        return PkgGraph(g)

    def iter_pkg(self) -> Iterable[Union[ThirdPartyPackage, Package]]:
        """Iterate over all packages in the graph."""
        return (self.g.nodes[pkg]["pkg"] for pkg in self.g.nodes)

    def dependencies(
        self, pkg_name: str, include_dev: bool = False
    ) -> List[Union[ThirdPartyPackage, Package]]:
        """Return the list of packages that are dependency of the input package.

        Args:
            pkg_name: The package to get the dependencies of.
            include_dev: Whether to include dev dependencies.
        """
        successors = nx.dfs_successors(self.g, pkg_name)
        if include_dev:
            return [self.g[uid]["pkg"] for uid in successors.keys()]

        lst = []
        for vid, parents in successors.items():
            if all(self.g[uid][vid]["is_dev"] for uid in parents):
                continue
            lst.append(self.g[vid]["pkg"])
        return lst
