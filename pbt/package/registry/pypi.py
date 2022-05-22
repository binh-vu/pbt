from typing import Any, Optional, Dict, Tuple
import requests
import semver
from pbt.package.manager.manager import PkgManager

from pbt.package.registry.registry import PkgRegistry

PYPI_INDEX = "https://pypi.org"


class PyPI(PkgRegistry):
    instances: Dict[str, "PyPI"] = {}

    def __init__(self, index: str):
        self.index = index
        self.pkgs: Dict[str, Optional[dict]] = {}

    @staticmethod
    def get_instance(index: str = PYPI_INDEX) -> "PyPI":
        if index not in PyPI.instances:
            PyPI.instances[index] = PyPI(index)
        return PyPI.instances[index]

    def does_package_exist(
        self, pkg_name: str, package_version: Optional[str] = None
    ) -> bool:
        """Check if a package exist in pypi index"""
        pkg_info = self.fetch_pkg_info(pkg_name)
        if pkg_info is None:
            return False
        return package_version is None or package_version in pkg_info["releases"]

    def get_whl_hash(self, pkg_name: str, pkg_version: str) -> Optional[str]:
        """Get hash of a package (wheel distribution) at specific version"""
        pkg_info = self.fetch_pkg_info(pkg_name)
        if pkg_info is None:
            return None
        releases = pkg_info["releases"]
        if pkg_version not in releases:
            return None

        lst = [
            release
            for release in releases[pkg_version]
            if release["filename"].endswith(".whl")
        ]
        if len(lst) != 1:
            raise Exception(
                "Can't obtain hash of package %s as it does not have wheel release"
                % (pkg_name)
            )
        return lst[0]["digests"]["sha256"]

    def get_latest_version(self, pkg_name: str) -> Optional[str]:
        pkg_info = self.fetch_pkg_info(pkg_name)
        if pkg_info is None:
            return None

        releases: Dict[str, Any] = pkg_info["releases"]
        latest_version = max(releases.keys(), key=PkgManager.parse_version)
        return latest_version

    def get_latest_version_and_hash(self, pkg_name: str) -> Optional[Tuple[str, str]]:
        pkg_info = self.fetch_pkg_info(pkg_name)
        if pkg_info is None:
            return None

        releases: Dict[str, Any] = pkg_info["releases"]
        latest_version = max(releases.keys(), key=PkgManager.parse_version)
        whl_hash = self.get_whl_hash(pkg_name, latest_version)
        assert whl_hash is not None
        return latest_version, whl_hash

    def fetch_pkg_info(self, pkg_name: str) -> Optional[dict]:
        if pkg_name not in self.pkgs:
            resp = requests.get(self.index + f"/pypi/{pkg_name}/json")
            if resp.status_code == 404:
                self.pkgs[pkg_name] = None
            else:
                assert resp.status_code == 200
                self.pkgs[pkg_name] = resp.json()

        return self.pkgs[pkg_name]
