import os
from dataclasses import dataclass
from pathlib import Path
from typing import Set, Union
from loguru import logger

import orjson
from pbt.package.package import Package
from pbt.misc import exec


PBT_CONFIG_FILE_NAME = "pbtconfig.json"
PBT_LOCK_FILE_NAME = "pbt.lock"


@dataclass
class PBTConfig:
    cwd: Path
    cache_dir: Path
    ignore_packages: Set[str]
    # packages that do not contain any code with sole purpose for installing dependencies or creating working environment
    phantom_packages: Set[str]

    @staticmethod
    def from_dir(cwd: Union[Path, str]) -> "PBTConfig":
        # get git top module
        # TODO: replace me
        try:
            output = exec(
                "git rev-parse --show-superproject-working-tree --show-toplevel",
                cwd="." if cwd == "" else cwd,
            )
            if len(output) == 1:
                cwd = output[0]
            else:
                for i in range(len(output)):
                    if all(
                        output[j].startswith(output[i])
                        for j in range(i + 1, len(output))
                    ):
                        cwd = output[i]
                        break
                else:
                    raise Exception(
                        "Unreachable error. Can't figure out which folder contains your project. Congrat! You found a bug.\nAvailable options:\n"
                        + "\n\t".join(output)
                    )
        except Exception as e:
            if not str(e).startswith("fatal: not a git repository"):
                # another error not related to git
                raise
            else:
                cwd = cwd

        cwd = Path(cwd).absolute()
        cache_dir = cwd / ".cache"
        cache_dir.mkdir(exist_ok=True, parents=True)

        if (cwd / PBT_CONFIG_FILE_NAME).exists():
            with open(cwd / PBT_CONFIG_FILE_NAME, "r") as f:
                cfg = orjson.loads(f.read())
        else:
            cfg = {}

        logger.info("Root directory: {}", cwd)
        return PBTConfig(
            cwd=cwd,
            ignore_packages=set(cfg.get("ignore_packages", [])),
            phantom_packages=set(cfg.get("phantom_packages", [])),
            cache_dir=cache_dir,
        )

    def pkg_cache_dir(self, pkg: Package) -> Path:
        """Get the cache directory for a package that we can use for storing temporary files
        during building and installing packages
        """
        pkg_dir = self.cache_dir / pkg.name
        pkg_dir.mkdir(exist_ok=True, parents=True)
        return pkg_dir
