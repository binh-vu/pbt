from pbt.package.graph import PkgGraph
from pbt.package.package import DepConstraint
from tests.conftest import Repo, pylib


def test_from_pkgs(repo1: Repo):
    packages = repo1.packages
    packages["lib0"].extra_dependencies["black"] = [
        DepConstraint(
            version_spec="^21.11b1",
            constraint="allow-prereleases=true",
            version_spec_field="version",
            origin_spec={
                "allow-prereleases": True,
            },
        )
    ]

    graph = PkgGraph.from_pkgs(packages)
    assert sorted(graph.g.nodes) == ["black", "lib0", "lib1", "lib2", "lib3", "python"]
    assert sorted(graph.g.edges(data="is_dev")) == [
        ("lib0", "black", True),
        ("lib0", "python", False),
        ("lib1", "lib0", False),
        ("lib1", "python", False),
        ("lib2", "lib1", False),
        ("lib2", "python", False),
        ("lib3", "lib0", False),
        ("lib3", "lib1", False),
        ("lib3", "python", False),
    ]


def test_dependencies(repo1: Repo):
    packages = repo1.packages
    packages["lib0"].extra_dependencies["black"] = [
        DepConstraint(
            version_spec="^21.11b1",
            constraint="allow-prereleases=true",
            version_spec_field="version",
            origin_spec={
                "allow-prereleases": True,
            },
        )
    ]

    graph = PkgGraph.from_pkgs(packages)

    def dependencies(pkg_name, dev=False):
        return sorted(
            [pkg.name for pkg in graph.dependencies(pkg_name, include_dev=dev)]
        )

    assert dependencies("lib0") == ["python"]
    assert dependencies("lib1") == ["lib0", "python"]
    assert dependencies("lib2") == ["lib0", "lib1", "python"]
    assert dependencies("lib3") == ["lib0", "lib1", "python"]

    assert dependencies("lib0", True) == ["black", "python"]
    assert dependencies("lib1", True) == ["black", "lib0", "python"]
    assert dependencies("lib2", True) == ["black", "lib0", "lib1", "python"]
    assert dependencies("lib3", True) == ["black", "lib0", "lib1", "python"]
