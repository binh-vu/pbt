import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Set, Union
from loguru import logger

import orjson
from pbt.package.package import Package
from pbt.misc import cache_method, exec


PBT_CONFIG_FILE_NAME = "pbtconfig.json"
PBT_LOCK_FILE_NAME = "pbt.lock"


@dataclass
class PBTConfig:
    # current working directory
    cwd: Path
    # directory
    cache_dir: Path
    # set of packages that we ignore
    ignore_packages: Set[str] = field(default_factory=set)
    # packages that do not contain any code with sole purpose for installing dependencies or creating working environment
    phantom_packages: Set[str] = field(default_factory=set)
    # use pre-built binaries for the package if available (i.e., rely on the package registry to find an installable version)
    use_prebuilt_binaries: Set[str] = field(default_factory=set)
    # directory to store the built artifacts for release (relative to each package's location)
    distribution_dir: Path = Path("./dist")
    # the virtualenv directory (default is .venv in the project root directory)
    python_virtualenvs_path: str = "./.venv"
    # python executable to use for building and installing packages, default (None) is the first one on PATH
    python_path: Optional[Path] = None

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

        if "python_path" not in cfg:
            # try use python_path from the environment variable: `PBT_PYTHON`
            python_path = os.environ.get("PBT_PYTHON", None)
        else:
            python_path = cfg["python_path"]

        return PBTConfig(
            cwd=cwd,
            cache_dir=cache_dir,
            ignore_packages=set(cfg.get("ignore_packages", [])),
            phantom_packages=set(cfg.get("phantom_packages", [])),
            use_prebuilt_binaries=set(cfg.get("use_prebuilt_binaries", [])),
            distribution_dir=Path(cfg.get("distribution_dir", "./dist")),
            python_virtualenvs_path=cfg.get("python_virtualenvs_path", "./.venv"),
            python_path=Path(python_path) if python_path is not None else None,
        )

    def pkg_cache_dir(self, pkg: Package) -> Path:
        """Get the cache directory for a package that we can use for storing temporary files
        during building and installing packages
        """
        pkg_dir = self.cache_dir / pkg.name
        pkg_dir.mkdir(exist_ok=True, parents=True)
        return pkg_dir

    @cache_method()
    def get_python_path(self) -> str:
        if self.python_path is not None:
            if not self.python_path.exists():
                raise ValueError("Python does not exist: {}".format(self.python_path))
            return str(self.python_path)
        else:
            return "python"
