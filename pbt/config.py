import os
from dataclasses import dataclass
from pathlib import Path
from typing import Set, Union
from loguru import logger

import orjson

PBT_CONFIG_FILE_NAME = "pbtconfig.json"
PBT_LOCK_FILE_NAME = "pbt.lock"


@dataclass
class PBTConfig:
    cwd: Path
    cache_dir: Path
    ignore_packages: Set[str]

    @staticmethod
    def from_dir(cwd: Union[Path, str]) -> "PBTConfig":
        def is_valid_cwd(wd: Union[Path, str]):
            pbt_file = os.path.join(wd, PBT_CONFIG_FILE_NAME)
            return os.path.exists(pbt_file)

        error = True
        if cwd == "":
            cwd = os.path.abspath(".")
            if is_valid_cwd(cwd):
                error = False
            else:
                root_dir = Path(os.path.abspath(__file__)).parent.parent.parent
                if is_valid_cwd(str(root_dir)):
                    error = False
                    cwd = root_dir
        else:
            if is_valid_cwd(cwd):
                error = False

        if error:
            raise Exception(
                "Invalid current working directory. It should contains the file `pbtconfig.json`"
            )

        cwd = Path(cwd)
        cache_dir = cwd / ".cache"
        cache_dir.mkdir(exist_ok=True, parents=True)

        with open(str(cwd / PBT_CONFIG_FILE_NAME), "r") as f:
            cfg = orjson.loads(f.read())

        logger.info("Root directory: {}", cwd)
        return PBTConfig(
            cwd=cwd,
            ignore_packages=set(cfg.get("ignore_packages", [])),
            cache_dir=cache_dir,
        )
