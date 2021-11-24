from pathlib import Path
from pbt.pkg_manager.poetry import Poetry


def test_env_path(repo1):
    lib0 = repo1.packages["lib0"]
    poetry = Poetry()

    pippath = poetry.pip_path(lib0)
    pythonpath = poetry.pip_path(lib0)

    assert pippath.parent.parent.name.startswith(lib0.name)
    assert pythonpath.parent.parent.name.startswith(lib0.name)
    assert pippath.exists()
    assert pythonpath.exists()


def test_load():
    poetry = Poetry()
    pkg = poetry.load(Path(__file__).parent.parent.parent)
    from tomlkit.api import loads, dumps

    # with open(pkg.dir / "pyproject.toml", "r") as f:
    #     doc = loads(f.read())

    # from poetry.core.factory import Factory

    # p = Factory().create_poetry(pkg.dir)
    # with open(pkg.dir / "test.toml", "w") as f:
    #     f.write(dumps(p.pyproject.data))

    pkg.location = Path("/tmp/test2")
    poetry.save(pkg)
    # toml.dump(toml.load(pkg.dir / "pyproject.toml"), f)
