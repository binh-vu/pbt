import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Union, Optional

import orjson

from pbt.config import PBT_LOCK_FILE_NAME
from pbt.package import Package
from pbt.pypi import PyPI


@dataclass(eq=True)
class PkgIdent:
    version: str
    hash: str


@dataclass
class PBTLock:
    packages_hash: Dict[str, Dict[str, str]]
    # mapping from package => dependency => (version, hash)
    package_dependencies: Dict[str, Dict[str, PkgIdent]]

    is_stale: bool = False

    def get_hash(self, pkg: Package) -> Optional[str]:
        """Obtain hash of a package currently stored in the lock. It will look in the lock first, if not found, it will look
        in PyPI.
        """
        if (
            pkg.name not in self.packages_hash
            or pkg.version not in self.packages_hash[pkg.name]
        ):
            # fetch the package from the server to get the hash
            pkg_hash = PyPI.get_instance().get_whl_hash(pkg.name, pkg.version)
            if pkg_hash is None:
                return None
            self.update_pkg_version(pkg, pkg_hash)
            return pkg_hash
        return self.packages_hash[pkg.name][pkg.version]

    def save(self, cwd: Union[str, Path]):
        if not self.is_stale:
            return

        lock_file = os.path.join(cwd, PBT_LOCK_FILE_NAME)
        with open(lock_file, "wb") as f:
            f.write(
                orjson.dumps(
                    {
                        "packages_hash": self.packages_hash,
                        "package_dependencies": self.package_dependencies,
                    },
                    option=orjson.OPT_INDENT_2,
                )
            )

    @staticmethod
    def from_dir(cwd: Union[str, Path]) -> "PBTLock":
        lock_file = os.path.join(cwd, PBT_LOCK_FILE_NAME)
        if os.path.exists(lock_file):
            with open(lock_file, "r") as f:
                object = orjson.loads(f.read())
                package_dependencies = object["package_dependencies"]
                for pkg_dep in package_dependencies.values():
                    for k in pkg_dep:
                        pkg_dep[k] = PkgIdent(**pkg_dep[k])

            return PBTLock(
                packages_hash=object["packages_hash"],
                package_dependencies=package_dependencies,
            )
        return PBTLock(packages_hash={}, package_dependencies={})

    def update_pkg_version(self, pkg: Package, pkg_hash: str):
        """Update the package with new hash. If there is a package of the same version in the lock and its hash is
        different from the provided hash, we will create a new item of the same package version but mark it as stale"""
        if pkg.name not in self.packages_hash:
            self.packages_hash[pkg.name] = {pkg.version: pkg_hash}
            self.is_stale = True
        elif pkg.version not in self.packages_hash[pkg.name]:
            self.packages_hash[pkg.name][pkg.version] = pkg_hash
            self.is_stale = True
        elif self.packages_hash[pkg.name][pkg.version] != pkg_hash:
            if self.packages_hash[pkg.name].get(pkg.version + ".dev", None) != pkg_hash:
                self.is_stale = True
            self.packages_hash[pkg.name][pkg.version + ".dev"] = pkg_hash

    def update_pkg_dependency(
        self, pkg: Package, dep_pkg: Package, dep_pkg_ident: PkgIdent
    ):
        if pkg.name not in self.package_dependencies:
            self.package_dependencies[pkg.name] = {}
        self.package_dependencies[pkg.name][dep_pkg.name] = dep_pkg_ident
        self.is_stale = True

    def get_pkg_dependency_ident(
        self, pkg: Package, dep_pkg: Package
    ) -> Optional[PkgIdent]:
        return self.package_dependencies.get(pkg.name, {}).get(dep_pkg.name, None)
