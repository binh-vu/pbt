from pbt.package.package import PackageType
from pbt.package.pipeline import BTPipeline
from pbt.package.manager.poetry import Poetry
from tests.conftest import PipFreezePkgInfo, Repo, get_dependencies, setup_dir
from pbt.misc import exec


def test_discover(repo1: Repo):
    pl = BTPipeline(repo1.cfg.cwd, managers={PackageType.Poetry: repo1.poetry})

    assert pl.pkgs == {}
    pl.discover()
    assert pl.pkgs == repo1.packages


def test_install(repo1: Repo):
    lib0 = repo1.packages["lib0"]
    lib1 = repo1.packages["lib1"]
    lib2 = repo1.packages["lib2"]

    poetry = repo1.poetry
    python = poetry.python_path(lib2)

    pl = BTPipeline(repo1.cfg.cwd, managers={PackageType.Poetry: poetry})
    pl.discover()

    assert get_dependencies(poetry.pip_path(lib2)) == []
    pl.install([lib2.name], editable=False)
    assert get_dependencies(poetry.pip_path(lib2)) == [
        PipFreezePkgInfo(name=lib0.name, editable=False, version="0.5.1"),
        PipFreezePkgInfo(name=lib1.name, editable=False, version="0.2.1"),
        PipFreezePkgInfo(name=lib2.name, editable=False, version="0.6.7"),
    ]

    assert exec(f"{python} -m {lib0.name}")[0] == lib0.name

    # make some changes and get it build correctly
    setup_dir({"lib0": {"__main__.py": "print('lib0 - update 1')"}}, lib0.location)
    assert (
        exec(f"{python} -m {lib0.name}")[0] == lib0.name
    ), "Change should not be reflected immediately before we build again"

    pl.install([lib2.name], editable=False)
    # now we should see the changes
    assert exec(f"{python} -m {lib0.name}")[0] == "lib0 - update 1"


def test_install_editable(repo1: Repo):
    lib0 = repo1.packages["lib0"]
    lib1 = repo1.packages["lib1"]
    lib2 = repo1.packages["lib2"]

    poetry = repo1.poetry
    python = poetry.python_path(lib2)

    pl = BTPipeline(repo1.cfg.cwd, managers={PackageType.Poetry: poetry})
    pl.discover()

    assert get_dependencies(poetry.pip_path(lib2)) == []
    pl.install([lib2.name], editable=True)
    assert get_dependencies(poetry.pip_path(lib2)) == [
        PipFreezePkgInfo(name=lib0.name, editable=True, version="0.5.1"),
        PipFreezePkgInfo(name=lib1.name, editable=True, version="0.2.1"),
        PipFreezePkgInfo(name=lib2.name, editable=True, version="0.6.7"),
    ]

    assert exec(f"{python} -m {lib0.name}")[0] == lib0.name

    # make some changes and should see it immediately
    setup_dir({"lib0": {"__main__.py": "print('lib0 - update 1')"}}, lib0.location)
    assert exec(f"{python} -m {lib0.name}")[0] == "lib0 - update 1"


def test_enforce_version_consistency(repo1: Repo):
    lib0 = repo1.packages["lib0"]
    lib1 = repo1.packages["lib1"]
    lib2 = repo1.packages["lib2"]
    lib3 = repo1.packages["lib3"]

    pl = BTPipeline(repo1.cfg.cwd, managers={PackageType.Poetry: repo1.poetry})

    # first update doesn't change anything
    pl.discover()
    pl.enforce_version_consistency()

    assert [
        lib1.dependencies[lib0.name][0].version_spec,
        lib2.dependencies[lib1.name][0].version_spec,
        lib3.dependencies[lib0.name][0].version_spec,
        lib3.dependencies[lib1.name][0].version_spec,
    ] == ["^0.5.1", "~0.2.1", "~0.5.1", "~0.2.1"]

    # bump major of lib0 should update lib1 and lib3
    repo1.poetry.next_version(lib0, "major")
    repo1.reload_pkgs()
    assert [
        lib0.version,
        lib1.dependencies[lib0.name][0].version_spec,
        lib2.dependencies[lib1.name][0].version_spec,
        lib3.dependencies[lib0.name][0].version_spec,
    ] == ["1.0.0", "^0.5.1", "~0.2.1", "~0.5.1"]
    pl.discover()
    pl.enforce_version_consistency()
    repo1.reload_pkgs()
    assert [
        lib0.version,
        lib1.dependencies[lib0.name][0].version_spec,
        lib2.dependencies[lib1.name][0].version_spec,
        lib3.dependencies[lib0.name][0].version_spec,
    ] == ["1.0.0", "^1.0.0", "~0.2.1", "~1.0.0"]

    # patch of lib0 should not effect the project
    repo1.poetry.next_version(lib0, "patch")
    repo1.reload_pkgs()
    assert [
        lib0.version,
        lib1.dependencies[lib0.name][0].version_spec,
        lib2.dependencies[lib1.name][0].version_spec,
        lib3.dependencies[lib0.name][0].version_spec,
    ] == ["1.0.1", "^1.0.0", "~0.2.1", "~1.0.0"]
    pl.discover()
    pl.enforce_version_consistency()
    repo1.reload_pkgs()
    assert [
        lib0.version,
        lib1.dependencies[lib0.name][0].version_spec,
        lib2.dependencies[lib1.name][0].version_spec,
        lib3.dependencies[lib0.name][0].version_spec,
    ] == ["1.0.1", "^1.0.0", "~0.2.1", "~1.0.0"]

    # bump minor of lib0 should update lib3 after rebuilt
    repo1.poetry.next_version(lib0, "minor")
    repo1.reload_pkgs()
    assert [
        lib0.version,
        lib1.dependencies[lib0.name][0].version_spec,
        lib2.dependencies[lib1.name][0].version_spec,
        lib3.dependencies[lib0.name][0].version_spec,
    ] == ["1.1.0", "^1.0.0", "~0.2.1", "~1.0.0"]
    pl.discover()
    pl.enforce_version_consistency()
    repo1.reload_pkgs()
    assert [
        lib0.version,
        lib1.dependencies[lib0.name][0].version_spec,
        lib2.dependencies[lib1.name][0].version_spec,
        lib3.dependencies[lib0.name][0].version_spec,
    ] == ["1.1.0", "^1.0.0", "~0.2.1", "~1.1.0"]
