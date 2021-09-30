from pbt.poetry import Poetry


def test_env_path(repo1):
    lib0 = repo1.packages["lib0"]
    poetry = Poetry(lib0)
    assert poetry.env_path.name.startswith(lib0.name)


def test_pip_path(repo1):
    assert Poetry(repo1.packages["lib0"]).pip_path.exists()
