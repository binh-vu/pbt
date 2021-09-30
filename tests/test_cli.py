import subprocess

from pytest_mock import MockerFixture

from pbt.cli import make, update, publish
from tests.conftest import get_dependencies, setup_dir, PipFreezePkgInfo

from pbt.package import search_packages


def invoke_lib0(lib, lib0):
    return (
        subprocess.check_output(
            [
                lib.pkg_handler.python_path,
                "-m",
                lib0.name + ".main",
            ]
        )
        .decode()
        .strip()
    )


def test_make(repo1):
    lib0 = repo1.packages["lib0"]
    lib2 = repo1.packages["lib2"]
    lib2_deps = set(lib2.all_inter_dependencies().keys())

    installed_deps = [
        dep
        for dep in get_dependencies(lib2.pkg_handler.pip_path)
        if dep.name in lib2_deps
    ]
    assert installed_deps == []
    make(["-p", lib2.name, "--cwd", repo1.cfg.cwd], standalone_mode=False)
    installed_deps = [
        dep
        for dep in get_dependencies(lib2.pkg_handler.pip_path)
        if dep.name in lib2_deps
    ]
    assert installed_deps == [
        PipFreezePkgInfo(name=repo1.packages["lib0"].name, editable=False),
        PipFreezePkgInfo(name=repo1.packages["lib1"].name, editable=False),
    ]
    assert invoke_lib0(lib2, lib0) == "lib0"

    # make some changes without updating the version, and get it build correctly
    setup_dir({"lib0": {"main.py": "print('lib0 - update 1')"}}, lib0.dir)
    assert (
        invoke_lib0(lib2, lib0) == "lib0"
    ), "Change should not be reflected immediately before we build again"
    make(["-p", lib2.name, "--cwd", repo1.cfg.cwd], standalone_mode=False)
    # now we should see the changes
    assert invoke_lib0(lib2, lib0) == "lib0 - update 1"


def test_make_editable(repo1):
    lib0 = repo1.packages["lib0"]
    lib2 = repo1.packages["lib2"]
    lib2_deps = set(lib2.all_inter_dependencies().keys())

    installed_deps = [
        dep
        for dep in get_dependencies(lib2.pkg_handler.pip_path)
        if dep.name in lib2_deps
    ]
    assert installed_deps == []
    make(["-p", lib2.name, "-e", "--cwd", repo1.cfg.cwd], standalone_mode=False)
    installed_deps = [
        dep
        for dep in get_dependencies(lib2.pkg_handler.pip_path)
        if dep.name in lib2_deps
    ]
    assert installed_deps == [
        PipFreezePkgInfo(name=repo1.packages["lib0"].name, editable=True),
        PipFreezePkgInfo(name=repo1.packages["lib1"].name, editable=True),
    ]

    assert invoke_lib0(lib2, lib0) == "lib0"
    setup_dir({"lib0": {"main.py": "print('lib0 - update 1')"}}, lib0.dir)
    assert (
        invoke_lib0(lib2, lib0) == "lib0 - update 1"
    ), "Changes should reflect immediately"


def test_make_should_pump_version_automatically(repo1):
    lib0 = repo1.packages["lib0"]
    lib1 = repo1.packages["lib1"]
    lib2 = repo1.packages["lib2"]
    lib3 = repo1.packages["lib3"]

    def reload_libs():
        for lib in [lib0, lib1, lib2, lib3]:
            lib.reload()

    lib2_deps = set(lib2.all_inter_dependencies().keys())
    assert [lib0.version, lib1.version] == ["0.5.1", "0.2.1"]

    installed_deps = [
        dep
        for dep in get_dependencies(lib2.pkg_handler.pip_path)
        if dep.name in lib2_deps
    ]
    assert installed_deps == []
    make(["-p", lib2.name, "-e", "--cwd", repo1.cfg.cwd], standalone_mode=False)

    # first make doesn't change anything
    lib2.reload()
    assert [
        lib1.dependencies[lib0.name],
        lib2.dependencies[lib1.name],
        lib3.dependencies[lib0.name],
        lib3.dependencies[lib1.name],
    ] == ["^0.5.1", "~0.2.1", "~0.5.1", "~0.2.1"]

    # patch of lib0 should not effect the project
    lib0.next_version("patch")
    reload_libs()
    assert [
        lib0.version,
        lib1.dependencies[lib0.name],
        lib2.dependencies[lib1.name],
        lib3.dependencies[lib0.name],
    ] == ["0.5.2", "^0.5.1", "~0.2.1", "~0.5.1"]
    make(["-p", lib2.name, "-e", "--cwd", repo1.cfg.cwd], standalone_mode=False)
    reload_libs()
    assert [
        lib0.version,
        lib1.dependencies[lib0.name],
        lib2.dependencies[lib1.name],
        lib3.dependencies[lib0.name],
    ] == ["0.5.2", "^0.5.1", "~0.2.1", "~0.5.1"]

    # bump minor of lib0 should update lib3 after rebuilt
    lib0.next_version("minor")
    reload_libs()
    assert [
        lib0.version,
        lib1.dependencies[lib0.name],
        lib2.dependencies[lib1.name],
        lib3.dependencies[lib0.name],
    ] == ["0.6.0", "^0.5.1", "~0.2.1", "~0.5.1"]
    make(["-p", lib2.name, "-e", "--cwd", repo1.cfg.cwd], standalone_mode=False)
    reload_libs()
    assert [
        lib0.version,
        lib1.dependencies[lib0.name],
        lib2.dependencies[lib1.name],
        lib3.dependencies[lib0.name],
    ] == ["0.6.0", "^0.5.1", "~0.2.1", "~0.6.0"]

    # bump major of lib0 should update lib1 and lib3
    lib0.next_version("major")
    reload_libs()
    assert [
        lib0.version,
        lib1.dependencies[lib0.name],
        lib2.dependencies[lib1.name],
        lib3.dependencies[lib0.name],
    ] == ["1.0.0", "^0.5.1", "~0.2.1", "~0.6.0"]
    make(["-p", lib2.name, "-e", "--cwd", repo1.cfg.cwd], standalone_mode=False)
    reload_libs()
    assert [
        lib0.version,
        lib1.dependencies[lib0.name],
        lib2.dependencies[lib1.name],
        lib3.dependencies[lib0.name],
    ] == ["1.0.0", "^1.0.0", "~0.2.1", "~1.0.0"]


def test_update(repo1):
    lib0 = repo1.packages["lib0"]
    lib1 = repo1.packages["lib1"]
    lib3 = repo1.packages["lib3"]

    assert [
        lib0.version,
        lib1.dependencies[lib0.name],
        lib3.dependencies[lib0.name],
    ] == ["0.5.1", "^0.5.1", "~0.5.1"]

    lib0.next_version("patch")
    update(["--cwd", repo1.cfg.cwd], standalone_mode=False)
    [lib.reload() for lib in [lib0, lib1, lib3]]
    update(["--cwd", repo1.cfg.cwd], standalone_mode=False)

    assert [
        lib0.version,
        lib1.dependencies[lib0.name],
        lib3.dependencies[lib0.name],
    ] == ["0.5.2", "^0.5.2", "~0.5.2"]


def test_publish(repo1, mocker: MockerFixture):
    # stub = mocker.stub(name="publish")
    mock_publish_funcs = {}
    for lib in ["lib0", "lib1", "lib2", "lib3"]:
        pkg_handler = repo1.packages[lib].pkg_handler
        mock_publish_funcs[lib] = mocker.patch.object(pkg_handler, "publish")

    # note: patch in the place where the function is used
    mocker.patch("pbt.cli.search_packages", return_value=repo1.packages)
    # call publish for the first time, nothing should happen
    publish([
        "-p", repo1.packages["lib2"].name,
        "--cwd", repo1.cfg.cwd
    ], standalone_mode=False)
    for lib in ["lib0", "lib1", "lib2", "lib3"]:
        mock_publish_funcs[lib].assert_not_called()

    # update version can call again, they should be publish
    for lib in ["lib0", "lib1", "lib2"]:
        repo1.packages[lib].next_version("patch")
    publish([
        "-p", repo1.packages["lib2"].name,
        "--cwd", repo1.cfg.cwd
    ], standalone_mode=False)
    for lib in ["lib0", "lib1", "lib2"]:
        mock_publish_funcs[lib].assert_called_once()
    mock_publish_funcs["lib3"].assert_not_called()
