from pathlib import Path
from tempfile import TemporaryDirectory

from click import edit
import glob
from pbt.config import PBTConfig
from pbt.package.manager.poetry import Poetry
from tests.conftest import (
    PipFreezePkgInfo,
    Repo,
    get_dependencies,
    get_dependency,
    pylib,
)


def test_env_path(repo1):
    lib0 = repo1.packages["lib0"]
    poetry = Poetry(repo1.cfg)

    pippath = poetry.pip_path(lib0)
    pythonpath = poetry.pip_path(lib0)

    assert pippath.parent.parent.name.startswith(lib0.name)
    assert pythonpath.parent.parent.name.startswith(lib0.name)
    assert pippath.exists()
    assert pythonpath.exists()


def test_build(repo1: Repo):
    lib0 = repo1.packages["lib0"]
    dist_dir = lib0.location / "dist"
    flag_file = dist_dir / "flag.txt"

    # no previous build, create a flag file to ensure that call build
    # the first time will **remove** dist directory and put the package there
    assert not (lib0.location / "dist").exists()
    dist_dir.mkdir()
    flag_file.touch()
    assert flag_file.exists()

    repo1.poetry.build(lib0)

    assert (
        not flag_file.exists()
    ), "If the package is built, previous files should be wiped out"
    whl_files = glob.glob(str(lib0.location / "dist/*.whl"))
    tar_files = glob.glob(str(lib0.location / "dist/*.tar.gz"))
    assert [str(repo1.poetry.wheel_path(lib0))] == whl_files
    assert [str(repo1.poetry.tar_path(lib0))] == tar_files

    # re-build the package won't trigger a build
    # to test this, we rely on the fact that the function deletes the whole dist folder
    flag_file.touch()
    repo1.poetry.build(lib0)
    assert (
        flag_file.exists()
    ), "dist folder should not be deleted and the flag file lives"


def test_install_dependency(repo2: Repo):
    lib0 = repo2.packages["lib0"]
    lib1 = repo2.packages["lib1"]
    lib2 = repo2.packages["lib2"]
    lib3 = repo2.packages["lib3"]
    lib4 = repo2.packages["lib4"]
    lib5 = repo2.packages["lib5"]

    lib0_latest_pypi = "0.5.2"
    assert lib0.version != lib0_latest_pypi

    # install lib1 should not install lib0 if skipping dependencies is set.
    repo2.poetry.install_dependency(lib2, lib1, skip_dep_deps=[lib0.name])
    assert get_dependencies(repo2.poetry.pip_path(lib2)) == [
        PipFreezePkgInfo(lib1.name, editable=False, version=lib1.version)
    ]

    repo2.poetry.install_dependency(
        lib3, lib1, editable=True, skip_dep_deps=[lib0.name]
    )
    assert get_dependencies(repo2.poetry.pip_path(lib3)) == [
        PipFreezePkgInfo(lib1.name, editable=True, version=lib1.version)
    ]

    # install lib1 should also install lib0 if no skipping dependencies
    repo2.poetry.install_dependency(lib4, lib1)
    assert get_dependencies(repo2.poetry.pip_path(lib4)) == [
        PipFreezePkgInfo(lib0.name, editable=False, version=lib0_latest_pypi),
        PipFreezePkgInfo(lib1.name, editable=False, version=lib1.version),
    ]

    repo2.poetry.install_dependency(lib5, lib1, editable=True)
    assert get_dependencies(repo2.poetry.pip_path(lib5)) == [
        PipFreezePkgInfo(lib0.name, editable=False, version=lib0_latest_pypi),
        PipFreezePkgInfo(lib1.name, editable=True, version=lib1.version),
    ]


def test_save():
    with TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        (tmpdir / ".cache").mkdir(parents=True, exist_ok=True)

        cfg = PBTConfig(cwd=tmpdir, cache_dir=tmpdir / ".cache", ignore_packages=set())
        poetry = Poetry(cfg)

        lib = pylib(
            tmpdir,
            name="test-lib",
            version="1.0.0",
            deps={
                "numpy": "1.21.4",
                "networkx": "2.6.3",
                "foo": [
                    {"version": "<=1.9", "python": "^2.7"},
                    {"version": "^2.0", "python": "^3.4"},
                ],
            },
            dev_deps={"black": "21.11b1"},
        )

        for i in range(2):
            poetry.save(lib)

            with open(lib.location / "pyproject.toml", "r") as f:
                pyproject = f.read()
                assert (
                    pyproject
                    == """
[tool.poetry]
name = "test-lib"
version = "1.0.0"
description = ""
authors = []


[tool.poetry.dependencies]
python = "^3.8"
numpy = "1.21.4"
networkx = "2.6.3"
foo = [
    {version = "<=1.9", python = "^2.7"},
    {version = "^2.0", python = "^3.4"},
]


[tool.poetry.dev-dependencies]
black = "21.11b1"


[build-system]
requires = ["poetry-core>=1.0.0"]
build-backend = "poetry.core.masonry.api"\n""".lstrip()
                )
