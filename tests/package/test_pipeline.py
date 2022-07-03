from pytest_mock import MockerFixture
from pbt.package.package import Package, PackageType
from pbt.package.pipeline import BTPipeline, VersionConsistent
from pbt.package.manager.poetry import Poetry
from pbt.package.registry.registry import PkgRegistry
from tests.conftest import Repo, setup_dir
from tests.python_helper import PipFreezePkgInfo, PipDependencyQuery
from pbt.misc import exec


def test_discover(repo1: Repo):
    pl = BTPipeline(repo1.cfg, managers={PackageType.Poetry: repo1.poetry})

    assert pl.pkgs == {}
    pl.discover()
    assert pl.pkgs == repo1.packages


def test_python_install(repo1: Repo):
    lib0 = repo1.packages["lib0"]
    lib1 = repo1.packages["lib1"]
    lib2 = repo1.packages["lib2"]

    poetry = repo1.poetry
    python = poetry.python_path(lib2)

    pl = BTPipeline(repo1.cfg, managers={PackageType.Poetry: poetry})
    pl.discover()

    assert (
        PipDependencyQuery.get_instance().get_dependencies(poetry.pip_path(lib2)) == []
    )
    pl.install([lib2.name])

    assert PipDependencyQuery.get_instance().get_dependencies(
        poetry.pip_path(lib2)
    ) == [
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

    pl = BTPipeline(repo1.cfg, managers={PackageType.Poetry: repo1.poetry})

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
    pl.discover()
    pl.enforce_version_consistency()
    repo1.reload_pkgs()
    assert [
        lib0.version,
        lib1.dependencies[lib0.name][0].version_spec,
        lib2.dependencies[lib1.name][0].version_spec,
        lib3.dependencies[lib0.name][0].version_spec,
    ] == ["1.1.0", "^1.0.0", "~0.2.1", "~1.1.0"]

    # strict mode will force updating lib0 even when it's only patched
    repo1.poetry.next_version(lib0, "patch")
    pl.discover()
    pl.enforce_version_consistency(VersionConsistent.STRICT)
    repo1.reload_pkgs()
    assert [
        lib0.version,
        lib1.dependencies[lib0.name][0].version_spec,
        lib2.dependencies[lib1.name][0].version_spec,
        lib3.dependencies[lib0.name][0].version_spec,
    ] == ["1.1.1", "^1.1.1", "~0.2.1", "~1.1.1"]


def test_publish(repo1: Repo, mockup_pypi: PkgRegistry, mocker: MockerFixture):
    pl = BTPipeline(repo1.cfg, managers={PackageType.Poetry: repo1.poetry})
    registries = {PackageType.Poetry: mockup_pypi}
    pl.discover()

    # mock
    stub = mocker.stub(name="publish")
    mocker.patch.object(repo1.poetry, "publish", stub)

    # call publish for the first time, nothing should happen
    pl.publish(["lib2"], registries=registries)
    stub.assert_not_called()

    # any change will return in publish
    repo1.poetry.next_version(pl.pkgs["lib2"], "patch")
    pl.publish(["lib2"], registries=registries)
    stub.assert_called_once_with(pl.pkgs["lib2"])

    stub.reset_mock()
    stub.assert_not_called()

    # change in lib0 will get published as well, but lib1 is not because the version
    # does not get updated
    repo1.poetry.next_version(pl.pkgs["lib0"], "patch")
    pl.publish(["lib2"], registries=registries)
    stub.assert_has_calls(
        [
            mocker.call(pl.pkgs["lib0"]),
            mocker.call(pl.pkgs["lib2"]),
        ]  # type: ignore
    )
