from contextlib import contextmanager
from typing import Optional

from pbt.package2 import Package
from pbt.pypi import PyPI


from pbt.pypi import PyPI


class PyPIMockUp(PyPI):
    def __init__(self, index: str):
        super().__init__(index)
        self.pkgs = {
            "lib0": {
                "releases": {
                    "0.5.1": [
                        {
                            "digests": {
                                "sha256": "9b28e6634400d7ff30c60dc93f2dfe8d036a03ee93fc87ae1c37cda57d085280"
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
                                "sha256": "57f98d7742de61e37c2b82d33edf03b99b20088df2a8de6ce4c4bae2a21fe097"
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
                                "sha256": "6d74cea501cb3ede3a88330be132d77c15a48927e08997e25256c594c0bb5cd0"
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
