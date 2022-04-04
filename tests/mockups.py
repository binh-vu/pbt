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
                            "digests": {
                                "sha256": "1f10879eff34826eef6f06af274d288016d664c9780ac81a2b39ec3e1575bae2"
                            },
                            "filename": "lib0-0.5.1-py3-none-any.whl",
                        }
                    ]
                }
            },
            "lib1": {
                "releases": {
                    "0.2.1": [
                        {
                            "digests": {
                                "sha256": "34d4e3e9a79ee752f5e6e6c79327b0d18d2ae5685600c8ef0e5ea90564492071"
                            },
                            "filename": "lib1-0.2.1-py3-none-any.whl",
                        }
                    ]
                }
            },
            "lib2": {
                "releases": {
                    "0.6.7": [
                        {
                            "digests": {
                                "sha256": "12dd7633b4879a4743d4175fa4e6fa5934279368effa75b3b6083a6269e3d4f4"
                            },
                            "filename": "lib2-0.6.7-py3-none-any.whl",
                        }
                    ]
                }
            },
            "lib3": {
                "releases": {
                    "0.1.4": [
                        {
                            "digests": {
                                "sha256": "f622e1172490a684366cd5fca8be5ed2cafc104442032aed35ef8ec9a081d5fa"
                            },
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
