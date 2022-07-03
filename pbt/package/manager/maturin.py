from dataclasses import dataclass
import os, glob
from operator import attrgetter
from pathlib import Path
import shutil
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional, Tuple, Union, cast

from loguru import logger
from pbt.package.manager.python import Pep518PkgManager, PythonPkgManager,
from pbt.package.package import DepConstraint
from pbt.config import PBTConfig
from pbt.diff import Diff, diff_db
from pbt.misc import exec
from pbt.package.manager.manager import DepConstraints, PkgManager, build_cache
from pbt.package.package import Package, PackageType
from tomlkit.api import document, dumps, inline_table, loads, nl, table, array

if TYPE_CHECKING:
    from pbt.package.manager.poetry import Poetry


@dataclass
class MaturinPackage(Package):
    """Temporary class until we fix the optionals dependency"""

    optional_dep_name: Optional[str] = None


class Maturin(Pep518PkgManager):
    def __init__(self, cfg: PBTConfig) -> None:
        super().__init__(cfg, backend="maturin")

    def load(self, dir: Path) -> MaturinPackage:
        try:
            with open(dir / "pyproject.toml", "r") as f:
                # just force the type to dictionary to silence the annoying type checker
                project_cfg = cast(dict, loads(f.read()))

                name = project_cfg["project"]["name"]
                version = project_cfg["project"]["version"]

                dependencies = {}
                for item in project_cfg["project"]["dependencies"]:
                    k, specs = self.parse_dep_spec(item)
                    dependencies[k] = specs

                dev_dependencies = {}
                opt = self.get_optional_dependency_name(project_cfg)
                if opt is not None:
                    for item in project_cfg["project"]["optional-dependencies"][opt]:
                        k, specs = self.parse_dep_spec(item)
                        dev_dependencies[k] = specs

                # not supported yet in pep-621
                # https://peps.python.org/pep-0621/#specify-files-to-include-when-building
                include = []
                exclude = []
        except:
            logger.error("Error while parsing configuration in {}", dir)
            raise

        return MaturinPackage(
            name=name,
            version=version,
            dependencies=dependencies,
            dev_dependencies=dev_dependencies,
            type=PackageType.Maturin,
            location=dir,
            include=include,
            exclude=exclude,
            optional_dep_name=opt,
        )

    def save(self, pkg: Package):
        tomlfile = pkg.location / "pyproject.toml"
        if not tomlfile.exists():
            raise NotImplementedError(
                "Don't support creating new pyproject.toml file yet"
            )

        old_pkg = self.load(pkg.location)

        with open(tomlfile, "r") as f:
            doc = cast(Any, loads(f.read()))
            is_modified = False

            if pkg.name != doc["project"]["name"]:
                doc["project"]["name"] = pkg.name
                is_modified = True

            if pkg.version != doc["project"]["version"]:
                doc["project"]["version"] = pkg.version
                is_modified = True

            for dependencies, old_dependencies, corr_key in [
                (pkg.dependencies, old_pkg.dependencies, "dependencies"),
                (
                    pkg.dev_dependencies,
                    old_pkg.dev_dependencies,
                    "optional-dependencies",
                ),
            ]:
                dependencies: Dict[str, DepConstraints]
                is_dep_modified = False
                for dep, specs in dependencies.items():
                    if dep not in old_dependencies or old_dependencies[dep] != specs:
                        is_dep_modified = True
                        break
                if is_dep_modified:
                    is_modified = True
                    lst = array(
                        [
                            dep + " " + self.serialize_dep_specs(specs)
                            for dep, specs in dependencies.items()
                        ]  # type: ignore
                    )
                    lst.multiline(True)
                    if corr_key == "dependencies":
                        doc["project"][corr_key] = lst
                    else:
                        opt = self.get_optional_dependency_name(doc)
                        assert (
                            opt is not None
                        ), "The dep is modified, we should have optional-dependencies"
                        doc["project"][corr_key][opt] = lst

        if is_modified:
            success = False
            os.rename(
                pkg.location / "pyproject.toml",
                pkg.location / "pyproject.toml.backup",
            )
            try:
                with open(tomlfile, "w") as f:
                    f.write(dumps(doc))
                success = True
            finally:
                if not success:
                    os.rename(
                        pkg.location / "pyproject.toml.backup",
                        pkg.location / "pyproject.toml",
                    )
                else:
                    os.remove(pkg.location / "pyproject.toml.backup")

    def parse_dep_spec(self, v: str) -> Tuple[str, DepConstraints]:
        """Parse a dependency specification.

        It does not support PEP508 but only a simple syntax: `<name> <version_rule>`.
        Note: the space is important.
        """
        name, version = v.split(" ", 1)
        # do it here to make sure we can parse this version
        self.parse_version_spec(version)
        constraint = f"python=* markers="
        return name, [DepConstraint(version_spec=version, constraint=constraint)]

    def serialize_dep_specs(self, specs: DepConstraints) -> str:
        # not implement all cases yet
        assert len(specs) == 1
        (spec,) = specs
        assert spec.origin_spec is None
        version_spec = self.parse_version_spec(spec.version_spec)
        return version_spec.to_pep508_string()

    def clean(self, pkg: Package):
        # run cargo clean to clean up rust build artifacts
        exec(
            "cargo clean",
            cwd=pkg.location,
            check_returncode=True,
            **self.exec_options("clean"),
        )
        shutil.rmtree(pkg.location / "dist", ignore_errors=True)

    def publish(self, pkg: Package):
        exec(
            "maturin publish -r",
            cwd=pkg.location,
            check_returncode=True,
            **self.exec_options("publish"),
        )

    def install_dependency(
        self,
        pkg: Package,
        dependency: Package,
        editable: bool = False,
        skip_dep_deps: Optional[List[str]] = None,
    ):
        assert dependency.name not in self.cfg.phantom_packages, dependency.name
        skip_dep_deps = skip_dep_deps or []

        # load pip_path outside of mask_file as without pyproject.toml, it is not a poetry package
        # and we may get pip path from the wrong environment
        pip_path = self.pip_path(pkg)
        exec([pip_path, "uninstall", "-y", dependency.name])

        dep_manager = self.managers[dependency.type]
        if editable:
            if dependency.type == PackageType.Poetry:
                manager = cast("Poetry", dep_manager)
                manager.create_setup_py(dependency, skip_deps=skip_dep_deps)
                with manager.mask_file(dependency.location / "pyproject.toml"):
                    exec([pip_path, "install", "-e", "."], cwd=dependency.location)
                (dependency.location / "setup.py").unlink()  # remove the setup.py file
            if dependency.type == PackageType.Maturin:
                manager = cast("Maturin", dep_manager)
                manager.install(
                    cast("MaturinPackage", dependency),
                    editable=editable,
                    skip_deps=skip_dep_deps,
                    virtualenv=self.venv_path(pkg.name, pkg.location),
                )
            else:
                raise NotImplementedError(type(dep_manager))
        else:
            dep_manager.build(dependency, skip_deps=skip_dep_deps)
            whl_path = self.wheel_path(dependency)
            assert whl_path is not None
            exec([pip_path, "install", whl_path])

    def install(
        self,
        pkg: MaturinPackage,
        editable: bool = False,
        include_dev: bool = False,
        skip_deps: Optional[List[str]] = None,
        additional_deps: Optional[Dict[str, DepConstraints]] = None,
        virtualenv: Optional[Path] = None,
    ):
        skip_deps = skip_deps or []
        additional_deps = additional_deps or {}
        options = ""
        if include_dev and pkg.optional_dep_name is not None:
            options += " --extras=" + pkg.optional_dep_name

        exc_options = self.exec_options("install")
        if virtualenv is None:
            virtualenv = self.venv_path(pkg.name, pkg.location)

        # set the virtual environment which the package will be installed to
        if "env" not in exc_options:
            exc_options["env"] = {"VIRTUAL_ENV": str(virtualenv)}
        elif isinstance(exc_options["env"], list):
            exc_options["env"].append({"name": "VIRTUAL_ENV", "value": str(virtualenv)})
        else:
            exc_options["env"]["VIRTUAL_ENV"] = str(virtualenv)

        if editable:
            with self.mask_dependencies(pkg, skip_deps, additional_deps):
                exec(f"maturin develop -r {options}", cwd=pkg.location, **exc_options)
        else:
            with self.mask_dependencies(pkg, skip_deps, additional_deps):
                exec(f"maturin build -r", cwd=pkg.location, **exc_options)
                exec(
                    f"pip install {self.wheel_path(pkg)}",
                    cwd=pkg.location,
                    **exc_options,
                )

    def build(
        self,
        pkg: Package,
        skip_deps: Optional[List[str]] = None,
        additional_deps: Optional[Dict[str, DepConstraints]] = None,
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
                with self.mask_dependencies(pkg, skip_deps, additional_deps):
                    diff = Diff.from_local(db, self, pkg)
                    if (
                        self.wheel_path(pkg) is not None
                        and self.tar_path(pkg) is not None
                    ):
                        if not diff.is_modified(db):
                            built_pkgs[build_ident] = build_opts
                            return

                    try:
                        if clean_dist and (pkg.location / "dist").exists():
                            shutil.rmtree(str(pkg.location / "dist"))
                        exec(
                            "maturin build -r -o dist",
                            cwd=pkg.location,
                            **self.exec_options("build"),
                        )
                    finally:
                        diff.save(db)

                    built_pkgs[build_ident] = build_opts

    def get_optional_dependency_name(self, doc: dict) -> Optional[str]:
        """Get the name of the optional dependency (i.e., extras) in the pyproject.toml."""
        opts = list(doc["project"]["optional-dependencies"].keys())
        if len(opts) == 1:
            return opts[0]

        if len(opts) > 1:
            raise NotImplementedError(
                "Haven't support multiple options-dependencies yet"
            )

        return None

    def exec_options(
        self,
        cmd: Literal["publish", "install", "build", "clean", "env.create"],
    ) -> dict:
        return {"env": ["PATH", "CC", "CXX"]}

    @contextmanager  # type: ignore
    def mask_dependencies(
        self,
        pkg: Package,
        skip_deps: List[str],
        additional_deps: Dict[str, DepConstraints],
        disable: bool = False,
    ):
        """Temporary mask out selected dependencies of the package. This is usually used for installing the package.

        When skip_deps and additional_deps are both empty, this is a no-op.

        Args:
            pkg: The package to mask
            skip_deps: The dependencies to skip
            additional_deps: Additional dependencies to add
            disable: Whether to manually disable the mask or not
        """
        if disable or (len(skip_deps) + len(additional_deps)) == 0:
            yield None
            return

        with open(pkg.location / "pyproject.toml", "r") as f:
            doc = cast(dict, loads(f.read()))

        dep_name2lineno = {}
        optdep_name2lineno = {}
        for i, item in enumerate(doc["project"]["dependencies"]):
            name, specs = self.parse_dep_spec(item)
            dep_name2lineno[name] = i

        removed_lines = {
            dep_name2lineno[dep] for dep in skip_deps if dep in dep_name2lineno
        }
        doc["project"]["dependencies"] = [
            line
            for i, line in enumerate(doc["project"]["dependencies"])
            if i not in removed_lines
        ]

        opt = self.get_optional_dependency_name(doc)
        if opt is not None:
            for i, item in enumerate(doc["project"]["optional-dependencies"][opt]):
                name, specs = self.parse_dep_spec(item)
                optdep_name2lineno[name] = i

            removed_lines = {
                optdep_name2lineno[dep]
                for dep in skip_deps
                if dep in optdep_name2lineno
            }
            doc["project"]["optional-dependencies"][opt] = [
                line
                for i, line in enumerate(doc["project"]["optional-dependencies"][opt])
                if i not in removed_lines
            ]

        for dep, specs in additional_deps.items():
            if dep not in dep_name2lineno:
                doc["project"]["dependencies"].append(
                    dep + " " + self.serialize_dep_specs(specs)
                )

        try:
            os.rename(
                pkg.location / "pyproject.toml",
                self.cfg.pkg_cache_dir(pkg) / "pyproject.toml",
            )
            with open(pkg.location / "pyproject.toml", "w") as f:
                f.write(dumps(cast(Any, doc)))
            yield None
        except:
            # write down the failed project so that we can debug it
            with open(self.cfg.pkg_cache_dir(pkg) / "pyproject.failed.toml", "w") as f:
                f.write(dumps(cast(Any, doc)))
            raise
        finally:
            os.rename(
                self.cfg.pkg_cache_dir(pkg) / "pyproject.toml",
                pkg.location / "pyproject.toml",
            )

    @contextmanager  # type: ignore
    def mask_file(
        self,
        file_path: Union[str, Path],
    ):
        """Temporary mask out a file"""
        file_path = str(file_path)
        assert os.path.isfile(file_path)
        try:
            os.rename(file_path, file_path + ".tmp")
            yield None
        finally:
            os.rename(file_path + ".tmp", file_path)
