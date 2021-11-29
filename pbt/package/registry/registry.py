from abc import ABC, abstractmethod
from typing import Optional, Tuple


class PkgRegistry(ABC):
    @abstractmethod
    def get_latest_version_and_hash(self, pkg_name: str) -> Optional[Tuple[str, str]]:
        """Get the latest version of the package and its hash

        Args:
            pkg_name: Name of the package

        Returns:
            Tuple[str, str]: (version, hash)
        """
        raise NotImplementedError()
