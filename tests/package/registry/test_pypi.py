from uuid import uuid4

from pbt.package.registry.pypi import PyPI


def test_does_package_exist():
    package_name = str(uuid4()).replace("-", "")
    pypi = PyPI.get_instance()

    assert not pypi.does_package_exist(package_name)
    assert pypi.does_package_exist("sem-desc")
    assert pypi.does_package_exist("sem-desc", "0.1.1")
    assert not pypi.does_package_exist("sem-desc", "0.0.1")
