from contextlib import contextmanager
from typing import Optional

from pbt.package import Package
from pbt.pypi import PyPI


from pbt.pypi import PyPI


class PyPIMockUp(PyPI):
    def __init__(self, index: str):
        super().__init__(index)
        self.pkgs = {
            "polyrepo-bt": {
                "releases": {
                    "0.2.0": [
                        {
                            "digests": {
                                "sha256": "dc4aa3ab5277b0c61b252728c2a1b46d0ab9bb061a1e5eaddfb5bd8507b500bf"
                            },
                            "filename": "polyrepo_bt-0.2.0-py3-none-any.whl",
                        }
                    ]
                }
            },
            "lib0": {
                "releases": {
                    "0.5.1": [
                        {
                            "digests": {
                                "sha256": "992ba88cd81bd02920127f6e7dd990f220bbfa2464bfedcb4baa44df249ea07e"
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
                                "sha256": "896b0077c72e2a484a72417f466d45ee93ccd90ca3753b0f5966b0ee1b932f03"
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
                                "sha256": "e9bf7fe86f099636dfe13f9bb11d60ddb0095ac3ac967d2254cc6c3bfbf477bd"
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
                                "sha256": "8a11e02f318621fcc5aad5605b075b05dd0c3e10a282bece06ba547f0a818073"
                            },
                            "filename": "lib3-0.1.4-py3-none-any.whl",
                        }
                    ]
                }
            }
        }

    def fetch_pkg_info(self, pkg_name: str) -> Optional[dict]:
        return self.pkgs[pkg_name]
