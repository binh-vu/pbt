from contextlib import contextmanager
from typing import Optional

from pbt.package.registry.pypi import PyPI


class PyPIMockUp(PyPI):
    def __init__(self, index: str):
        super().__init__(index)
        self.pkgs = {
            "lib0": {
                "releases": {
                    "0.5.1": [
                        {
                            "digests": {"sha256": ""},
                            "filename": "lib0-0.5.1-py3-none-any.whl",
                        }
                    ]
                }
            },
            "lib1": {
                "releases": {
                    "0.2.1": [
                        {
                            "digests": {"sha256": ""},
                            "filename": "lib1-0.2.1-py3-none-any.whl",
                        }
                    ]
                }
            },
            "lib2": {
                "releases": {
                    "0.6.7": [
                        {
                            "digests": {"sha256": ""},
                            "filename": "lib2-0.6.7-py3-none-any.whl",
                        }
                    ]
                }
            },
            "lib3": {
                "releases": {
                    "0.1.4": [
                        {
                            "digests": {"sha256": ""},
                            "filename": "lib3-0.1.4-py3-none-any.whl",
                        }
                    ]
                }
            },
        }

    def fetch_pkg_info(self, pkg_name: str) -> Optional[dict]:
        return self.pkgs[pkg_name]

    def update_pkg_hash(self, pkg_name: str, pkg_version: str, pkg_hash: str):
        pkg = self.pkgs[pkg_name]
        assert pkg is not None
        (item,) = pkg["releases"][pkg_version]
        item["digests"]["sha256"] = pkg_hash
