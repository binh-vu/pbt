import glob
import os
import subprocess
from operator import attrgetter

from pbt.package import search_packages, topological_sort
from tests.conftest import get_dependencies, PipFreezePkgInfo


def test_scan_packages(repo1):
    packages = search_packages(repo1.cfg)
    assert packages.keys() == repo1.packages.keys()


def test_topological_sort(repo1):
    packages = search_packages(repo1.cfg)
    packages = dict(
        [(name, packages[name]) for name in ["lib3", "lib1", "lib2", "lib0"]]
    )
    package_order = topological_sort(packages)
    assert package_order == ["lib0", "lib1", "lib2", "lib3"] or package_order == [
        "lib0",
        "lib1",
        "lib3",
        "lib2",
    ]


def test_build(repo1):
    lib0 = repo1.packages["lib0"]
    dist_dir = lib0.dir / "dist"
    flag_file = dist_dir / "flag.txt"

    # no previous build, create a flag file to ensure that call build
    # the first time will **remove** dist directory and put the package there
    assert not (lib0.dir / "dist").exists()
    dist_dir.mkdir()
    flag_file.touch()
    assert flag_file.exists()

    lib0.build(repo1.cfg)

    assert (
        not flag_file.exists()
    ), "If the package is built, previous files should be wiped out"
    whl_files = glob.glob(str(lib0.dir / "dist/*.whl"))
    tar_files = glob.glob(str(lib0.dir / "dist/*.tar.gz"))
    assert [lib0.get_wheel_file()] == whl_files
    assert [lib0.get_tar_file()] == tar_files

    # re-build the package won't trigger a build
    # to test this, we rely on the fact that the function deletes the whole dist folder
    flag_file.touch()
    lib0.build(repo1.cfg)
    assert (
        flag_file.exists()
    ), "dist folder should not be deleted and the flag file lives"


def test_install(repo1):
    lib0 = repo1.packages["lib0"]
    lib1 = repo1.packages["lib1"]
    lib2 = repo1.packages["lib2"]

    lib2.install(without_inter_dependency=True)
    lib2.install_dep(lib0, repo1.cfg)
    lib2.install_dep(lib1, repo1.cfg, editable=True)

    deps = get_dependencies(lib2.pkg_handler.pip_path)
    deps = sorted(
        [dep for dep in deps if dep.name in [lib0.name, lib1.name]],
        key=attrgetter("name"),
    )
    assert deps[0] == PipFreezePkgInfo(name=lib0.name)
    assert deps[1] == PipFreezePkgInfo(name=lib1.name, editable=True)
