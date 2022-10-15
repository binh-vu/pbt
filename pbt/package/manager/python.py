from abc import abstractmethod
from contextlib import contextmanager
import glob
import os
from pathlib import Path
import shutil
from typing import Callable, Dict, List, Literal, Optional, Set, Union, cast

from loguru import logger
from pbt.config import PBTConfig
from pbt.misc import cache_method, exec
from pbt.package.manager.manager import PkgManager, build_cache
from pbt.package.package import DepConstraints, Package, PackageType
from tomlkit.api import loads, dumps
from pbt.diff import Diff, diff_db


class PythonPkgManager(PkgManager):
    """Package Managers for Python should inherit this class."""

    def __init__(self, cfg: PBTConfig, pkg_type: PackageType):
        super().__init__(cfg)
        self.managers: Dict[PackageType, PkgManager] = {pkg_type: self}
        self.fixed_version_pkgs = {"python"}
        self.passthrough_envs = ["PATH", "CC", "CXX"]

    def set_package_managers(self, managers: Dict[PackageType, PkgManager]):
        """Set all package managers, which will be used to retrieve correct package manager
        for a particular python package.
        """
        self.managers = managers

    def get_fixed_version_pkgs(self):
        return self.fixed_version_pkgs

    def compute_pkg_hash(self, pkg: Package, target: Optional[str] = None) -> str:
        """Compute hash of the content of the package"""
        # build the package in release mode
        self.build(pkg, release=True, clean_dist=False)

        # obtain the hash of the package
        whl_path = self.wheel_path(pkg, target)
        assert whl_path is not None, whl_path
        output = exec(["pip", "hash", whl_path])[1]
        output = output[output.find("--hash=") + len("--hash=") :]
        assert output.startswith("sha256:")
        return output[len("sha256:") :]

    def clean(self, package: Package):
        """Remove previously installed dependencies and the environment where the package is installed, for a freshly start.
        In addition, this also cleans built artifacts.

        Args:
            package: The package to clean
        """
        path = (package.location / self.cfg.python_virtualenvs_path).absolute()
        if path.exists():
            shutil.rmtree(path)
        for eggdir in glob.glob(str(package.location / "*.egg-info")):
            shutil.rmtree(eggdir)
        shutil.rmtree(package.location / self.cfg.distribution_dir, ignore_errors=True)

    @cache_method()
    def venv_path(self, name: str, dir: Path) -> Path:
        """Get virtual environment path of the package, create it if doesn't exist.

        For a package manager that manages virtualenvs in different location, it should override this function.

        Arguments:
            name: name of the package
            dir: directory of the package
        """
        if not self.is_package_directory(dir):
            raise ValueError(
                f"{dir} seems to not contain any Python package. This won't return the right path. Please report this issue."
            )

        path = (dir / self.cfg.python_virtualenvs_path).absolute()
        if not path.exists():
            exec(f"{self.cfg.get_python_path()} -m venv {path}", env=["PATH"])

        if not path.exists():
            raise Exception(f"Environment path {path} doesn't exist")
        return Path(path)

    def tar_path(self, pkg: Package) -> Optional[Path]:
        tar_file = pkg.location / "dist" / f"{pkg.name}-{pkg.version}.tar.gz"
        if tar_file.exists():
            return tar_file
        return None

    def wheel_path(
        self,
        pkg: Package,
        target: Optional[str] = None,
    ) -> Optional[Path]:
        dist_dir = self.cfg.distribution_dir
        if target is None:
            whl_files = list((pkg.location / dist_dir).glob(f"{pkg.name}*.whl"))
            if len(whl_files) == 0:
                return None
            if len(whl_files) > 1:
                whl_files = list(
                    (pkg.location / dist_dir).glob(f"{pkg.name}-{pkg.version}*.whl")
                )
                if len(whl_files) != 1:
                    raise Exception(
                        "Multiple wheels found at: {}".format(
                            (pkg.location / dist_dir).absolute()
                        )
                    )

            return whl_files[0]

        whl_file = (
            pkg.location
            / dist_dir
            / f"{pkg.name.replace('-', '_')}-{pkg.version}-{target}.whl"
        )
        if whl_file.exists():
            return whl_file
        return None

    def pip_path(self, pkg: Package) -> Path:
        """Get Pip executable from the virtual environment of the package."""
        return self.venv_path(pkg.name, pkg.location) / "bin/pip"

    def python_path(self, pkg: Package) -> Path:
        """Get Python executable from the virtual environment of the package."""
        return self.venv_path(pkg.name, pkg.location) / "bin/python"

    def build(
        self,
        pkg: Package,
        skip_deps: Optional[List[str]] = None,
        additional_deps: Optional[Dict[str, DepConstraints]] = None,
        release: bool = True,
        clean_dist: bool = True,
    ):
        """Build the package. Support ignoring some dependencies to avoid installing and solving
        dependencies multiple times (not in the super interface as compiled languages will complain).
        """
        with build_cache() as built_pkgs:
            skip_deps = skip_deps or []
            additional_deps = additional_deps or {}

            build_ident = (pkg.name, pkg.version)
            build_opts = (tuple(skip_deps), tuple(sorted(additional_deps.keys())))
            if built_pkgs.get(build_ident, None) == build_opts:
                return

            with diff_db(pkg, self.cfg) as db:
                with self.change_dependencies(pkg, skip_deps, additional_deps):
                    diff = Diff.from_local(db, self, pkg)
                    if (
                        self.wheel_path(pkg) is not None
                        and self.tar_path(pkg) is not None
                    ):
                        if not diff.is_modified(db):
                            built_pkgs[build_ident] = build_opts
                            return

                    try:
                        dist_dir = pkg.location / self.cfg.distribution_dir
                        if clean_dist and (dist_dir).exists():
                            shutil.rmtree(str(dist_dir))
                        self._build_command(pkg, release)
                    finally:
                        diff.save(db)

                    built_pkgs[build_ident] = build_opts

    @abstractmethod
    def install(
        self,
        package: Package,
        include_dev: bool = False,
        skip_deps: Optional[List[str]] = None,
        additional_deps: Optional[Dict[str, DepConstraints]] = None,
        virtualenv: Optional[Path] = None,
    ):
        """Install the package, assuming the the specification is updated. Note that if the package is phantom, only the dependencies are installed.

        Note: don't expect this function will be able to find the local dependencies in the project
        as the manager relies on a package registry. For local dependencies, add them to `skip_deps` anddd use `install_dependency` to install them
        separately instead. Otherwise, you may get an error.

        Args:
            package: The package to install
            include_dev: Whether to install dev dependencies
            skip_deps: The dependencies to skip (usually the local ones we want to install in editable mode separately). This option is not guaranteed to compiled language
            additional_deps: The additional dependencies to install
            virtualenv: The virtual environment to install the package in. By default it is the virtual environment of the package
        """
        raise NotImplementedError()

    def install_dependency(
        self,
        pkg: Package,
        dependency: Package,
        skip_dep_deps: Optional[List[str]] = None,
    ):
        assert dependency.name not in self.cfg.phantom_packages, dependency.name
        assert self.managers is not None
        dep_manager = self.managers[dependency.type]
        assert isinstance(dep_manager, PythonPkgManager)

        dep_manager.install(
            dependency,
            skip_deps=skip_dep_deps or [],
            virtualenv=self.venv_path(pkg.name, pkg.location),
        )

    def publish(self, pkg: Package):
        self.build(pkg, release=True)
        exec("twine upload --skip-existing dist/*", cwd=pkg.location, env=["PATH"])

    def get_virtualenv_environment_variables(self, virtualenv: Path) -> dict:
        return {
            "VIRTUAL_ENV": str(virtualenv),
            "PATH": str(virtualenv / "bin") + os.pathsep + os.environ.get("PATH", ""),
        }

    @contextmanager  # type: ignore
    @abstractmethod
    def change_dependencies(
        self,
        pkg: Package,
        skip_deps: List[str],
        additional_deps: Dict[str, DepConstraints],
        disable: bool = False,
    ):
        """Temporary change the dependencies of the package.

        When skip_deps and additional_deps are both empty, this is a no-op.

        Args:
            pkg: The package to mask
            skip_deps: The dependencies to skip
            additional_deps: Additional dependencies to add
            disable: Whether to manually disable the mask or not
        """
        pass

    @abstractmethod
    def _build_command(self, pkg: Package, release: bool):
        """Run the build command for the package.

        Arguments:
            pkg: The package to build
            release: whether to build in release mode
        """
        pass


class Pep518PkgManager(PythonPkgManager):
    """A package manager for Python packages that use PEP 518 (pyproject.toml)

    Arguments:
        cfg: pbt's configuration
        backend: name of the building backend
    """

    def __init__(self, cfg: PBTConfig, pkg_type: PackageType, backend: str):
        super().__init__(cfg, pkg_type)
        self.backend = backend

        self.cache_pyprojects = {}

    def glob_query(self, root: Path) -> str:
        return str(root.absolute() / "**/pyproject.toml")

    def discover(
        self, root: Path, ignore_dirs: Set[Path], ignore_dirnames: Set[str]
    ) -> List[Path]:
        outs = []
        root = root.resolve()

        stack = [root]
        while len(stack) > 0:
            dir = stack.pop()
            if (
                dir.name.startswith(".")
                or dir.name in ignore_dirnames
                or dir in ignore_dirs
            ):
                continue
            if (dir / "pyproject.toml").exists():
                outs.append(dir)
            stack.extend([subdir for subdir in dir.iterdir() if subdir.is_dir()])

        return outs

    def is_package_directory(self, dir: Path) -> bool:
        if not (dir / "pyproject.toml").exists():
            return False

        return (
            self.parse_pyproject(dir / "pyproject.toml")["build-system"][
                "build-backend"
            ]
            == self.backend
        )

    def parse_pyproject(self, pyproject_file: Path) -> dict:
        """Parse project metadata from the directory.

        Arguments:
            pyproject_file: path to the pyproject.toml file

        Returns: dict, force the type to dictionary to silence the annoying type checker due to tomlkit
        """
        infile = str(pyproject_file.absolute())
        if infile not in self.cache_pyprojects:
            try:
                with open(infile, "r") as f:
                    self.cache_pyprojects[infile] = cast(dict, loads(f.read()))
            except:
                logger.error("Inavlid TOML file: {}", infile)
                raise
        return self.cache_pyprojects[infile]

    def update_pyproject(self, pyproject_file: Path, update_fn: Callable[[dict], bool]):
        """Update project metadata.

        Arguments:
            pyproject_file: path to the pyproject.toml file
            update_fn: function to update the document, return true if the document is modified
        """
        doc = self.parse_pyproject(pyproject_file)
        if update_fn(doc):
            success = False
            pyproject_file_backup = pyproject_file.parent / "pyproject.toml.backup"
            shutil.move(
                pyproject_file,
                pyproject_file_backup,
            )
            try:
                with open(pyproject_file, "w") as f:
                    f.write(dumps(doc))  # type: ignore
                del self.cache_pyprojects[str(pyproject_file.absolute())]
                success = True
            finally:
                if not success:
                    shutil.move(pyproject_file_backup, pyproject_file)
                else:
                    os.remove(pyproject_file_backup)
