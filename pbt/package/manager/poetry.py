import re
import glob
import os
import shutil
from sys import version
import tarfile
from contextlib import contextmanager
from operator import attrgetter
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union, cast

from loguru import logger
from pbt.config import PBTConfig
from pbt.diff import Diff, diff_db
from pbt.misc import ExecProcessError, cache_func, exec
from pbt.package.manager.manager import PkgManager, build_cache
from pbt.package.package import DepConstraint, DepConstraints, Package, PackageType
from tomlkit.api import document, dumps, inline_table, loads, nl, table
from tomlkit.items import Array, Key, KeyType, Trivia


class Poetry(PkgManager):
    def __init__(self, cfg: PBTConfig) -> None:
        super().__init__()
        self.cfg = cfg
        self.fixed_version_pkgs = {"python"}

    def is_package_directory(self, dir: Path) -> bool:
        return (dir / "pyproject.toml").exists()

    def glob_query(self, root: Path) -> str:
        return str(root.absolute() / "**/pyproject.toml")

    @contextmanager  # type: ignore
    def mask(
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

        for dep in skip_deps:
            if dep in doc["tool"]["poetry"]["dependencies"]:
                r = doc["tool"]["poetry"]["dependencies"].remove(dep)
            elif dep in doc["tool"]["poetry"]["dev-dependencies"]:
                doc["tool"]["poetry"]["dev-dependencies"].remove(dep)

        for dep, specs in additional_deps.items():
            if dep not in doc["tool"]["poetry"]["dependencies"]:
                doc["tool"]["poetry"]["dependencies"][dep] = self.serialize_dep_specs(
                    specs
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

    def load(self, dir: Path) -> Package:
        poetry_file = dir / "pyproject.toml"
        try:
            with open(poetry_file, "r") as f:
                # just force the type to dictionary to silence the annoying type checker
                project_cfg = cast(dict, loads(f.read()))

                name = project_cfg["tool"]["poetry"]["name"]
                version = project_cfg["tool"]["poetry"]["version"]

                dependencies = {}
                dev_dependencies = {}

                for deps, cfg_key in [
                    (dependencies, "dependencies"),
                    (dev_dependencies, "dev-dependencies"),
                ]:
                    for k, vs in project_cfg["tool"]["poetry"][cfg_key].items():
                        if not isinstance(vs, list):
                            vs = [vs]
                        deps[k] = sorted(
                            (self.parse_dep_spec(v) for v in vs),
                            key=attrgetter("constraint"),
                        )

                # see https://python-poetry.org/docs/pyproject/#include-and-exclude
                # and https://python-poetry.org/docs/pyproject/#packages
                include = project_cfg["tool"]["poetry"].get("include", [])
                include.append(name)
                for pkg_cfg in project_cfg["tool"]["poetry"].get("packages", []):
                    include.append(
                        os.path.join(pkg_cfg.get("from", ""), pkg_cfg["include"])
                    )
                include = sorted(set(include))

                exclude = project_cfg["tool"]["poetry"].get("exclude", [])
        except:
            logger.error("Error while parsing configuration in {}", dir)
            raise

        return Package(
            name=name,
            version=version,
            dependencies=dependencies,
            dev_dependencies=dev_dependencies,
            type=PackageType.Poetry,
            location=dir,
            include=include,
            exclude=exclude,
        )

    def save(self, pkg: Package):
        poetry_file = pkg.location / "pyproject.toml"
        if not poetry_file.exists():
            with open(pkg.location / "pyproject.toml", "w") as f:
                doc = document()

                tbl = table()
                tbl.add("name", pkg.name)
                tbl.add("version", pkg.version)
                tbl.add("description", "")
                tbl.add("authors", [])

                doc.add(Key("tool.poetry", t=KeyType.Bare), tbl)

                tbl = table()
                for dep, specs in pkg.dependencies.items():
                    tbl.add(dep, self.serialize_dep_specs(specs))
                doc.add(nl())
                doc.add(Key("tool.poetry.dependencies", t=KeyType.Bare), tbl)

                tbl = table()
                for dep, specs in pkg.dev_dependencies.items():
                    tbl.add(dep, self.serialize_dep_specs(specs))
                doc.add(nl())
                doc.add(Key("tool.poetry.dev-dependencies", t=KeyType.Bare), tbl)

                tbl = table()
                tbl.add("requires", ["poetry-core>=1.0.0"])
                tbl.add("build-backend", "poetry.core.masonry.api")
                doc.add(nl())
                doc.add("build-system", tbl)

                f.write(dumps(doc))
            return

        with open(poetry_file, "r") as f:
            doc = cast(Any, loads(f.read()))
            is_modified = False

            if pkg.name != doc["tool"]["poetry"]["name"]:
                doc["tool"]["poetry"]["name"] = pkg.name
                is_modified = True

            if pkg.version != doc["tool"]["poetry"]["version"]:
                doc["tool"]["poetry"]["version"] = pkg.version
                is_modified = True

            for dependencies, corr_key in [
                (pkg.dependencies, "dependencies"),
                (pkg.dev_dependencies, "dev-dependencies"),
            ]:
                dependencies: Dict[str, DepConstraints]
                for dep, specs in dependencies.items():
                    is_dep_modified = False
                    if dep not in doc["tool"]["poetry"][corr_key]:
                        is_dep_modified = True
                    else:
                        other_vers = doc["tool"]["poetry"][corr_key][dep]
                        if not isinstance(other_vers, list):
                            other_vers = [other_vers]
                        other_specs = [self.parse_dep_spec(v) for v in other_vers]
                        if specs != other_specs:
                            is_dep_modified = True

                    if is_dep_modified:
                        doc["tool"]["poetry"][corr_key][dep] = self.serialize_dep_specs(
                            specs
                        )
                        is_modified = True

        if is_modified:
            success = False
            os.rename(
                pkg.location / "pyproject.toml",
                pkg.location / "pyproject.toml.backup",
            )
            try:
                with open(poetry_file, "w") as f:
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

    def clean(self, pkg: Package):
        exec(
            "poetry env remove python",
            cwd=pkg.location,
            check_returncode=False,
            **self.exec_options("env.remove"),
        )
        for eggdir in glob.glob(str(pkg.location / "*.egg-info")):
            shutil.rmtree(eggdir)
        shutil.rmtree(pkg.location / "dist", ignore_errors=True)

    def publish(self, pkg: Package):
        exec(
            "poetry publish --build --no-interaction",
            cwd=pkg.location,
            **self.exec_options("publish"),
        )

    def install(
        self,
        pkg: Package,
        editable: bool = False,
        include_dev: bool = False,
        skip_deps: Optional[List[str]] = None,
        additional_deps: Optional[Dict[str, DepConstraints]] = None,
    ):
        skip_deps = skip_deps or []
        additional_deps = additional_deps or {}
        options = "--no-dev" if not include_dev else ""

        with self.mask(pkg, skip_deps, additional_deps):
            try:
                exec(
                    f"poetry install {options}",
                    cwd=pkg.location,
                    **self.exec_options("install"),
                )
            except ExecProcessError as e:
                if str(e).find(
                    "Warning: The lock file is not up to date with the latest changes in pyproject.toml. You may be getting outdated dependencies. Run update to update them."
                ):
                    # try to update the lock file without upgrade previous packages, and retry
                    exec(
                        "poetry lock --no-update",
                        cwd=pkg.location,
                        **self.exec_options("install"),
                    )
                    exec(
                        f"poetry install {options}",
                        cwd=pkg.location,
                        **self.exec_options("install"),
                    )

        if editable and pkg.name not in self.cfg.phantom_packages:
            self.build_editable(pkg, skip_deps=skip_deps)
            exec(
                [self.python_path(pkg), "setup.py", "develop"],
                cwd=pkg.location,
            )
            (pkg.location / "setup.py").unlink()  # remove the setup.py file

    def build(
        self,
        pkg: Package,
        skip_deps: Optional[List[str]] = None,
        additional_deps: Optional[Dict[str, DepConstraints]] = None,
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
                with self.mask(pkg, skip_deps, additional_deps):
                    diff = Diff.from_local(db, self, pkg)
                    if (
                        self.wheel_path(pkg) is not None
                        and self.tar_path(pkg) is not None
                    ):
                        if not diff.is_modified(db):
                            built_pkgs[build_ident] = build_opts
                            return

                    try:
                        if (pkg.location / "dist").exists():
                            shutil.rmtree(str(pkg.location / "dist"))
                        exec(
                            "poetry build",
                            cwd=pkg.location,
                            **self.exec_options("build"),
                        )
                    finally:
                        diff.save(db)

                    built_pkgs[build_ident] = build_opts

    def build_editable(
        self,
        pkg: Package,
        skip_deps: Optional[List[str]] = None,
    ):
        """Build egg package that can be used to install in editable mode as poetry does not
        provide it out of the box.

        Args:
            pkg: Package to build
            skip_deps: The dependencies to ignore when building the package
        """
        # need to remove the `.egg-info` folders first as it will interfere with the version (ContextualVersionConflict)
        for eggdir in glob.glob(str(pkg.location / "*.egg-info")):
            shutil.rmtree(eggdir)

        self.build(pkg, skip_deps)

        tar_path = self.tar_path(pkg)
        assert tar_path is not None
        with tarfile.open(tar_path, "r") as g:
            member = g.getmember(f"{pkg.name}-{pkg.version}/setup.py")
            with open(pkg.location / "setup.py", "wb") as f:
                memberfile = g.extractfile(member)
                assert memberfile is not None
                f.write(memberfile.read())

            exec(
                [self.python_path(pkg), "setup.py", "bdist_egg"],
                cwd=pkg.location,
            )

    def get_fixed_version_pkgs(self):
        return self.fixed_version_pkgs

    def compute_pkg_hash(self, pkg: Package) -> str:
        """Compute hash of the content of the package"""
        self.build(pkg)
        whl_path = self.wheel_path(pkg)
        assert whl_path is not None
        output = exec([self.pip_path(pkg), "hash", whl_path])[1]
        output = output[output.find("--hash=") + len("--hash=") :]
        assert output.startswith("sha256:")
        return output[len("sha256:") :]

    def install_dependency(
        self,
        pkg: Package,
        dependency: Package,
        editable: bool = False,
        skip_dep_deps: Optional[List[str]] = None,
    ):
        assert dependency.name not in self.cfg.phantom_packages, dependency.name
        skip_dep_deps = skip_dep_deps or []
        exec([self.pip_path(pkg), "uninstall", "-y", dependency.name])

        if editable:
            self.build_editable(dependency, skip_deps=skip_dep_deps)
            exec(
                [self.python_path(pkg), "setup.py", "develop"], cwd=dependency.location
            )
            (dependency.location / "setup.py").unlink()  # remove the setup.py file
        else:
            self.build(
                dependency,
                skip_deps=skip_dep_deps,
            )
            whl_path = self.wheel_path(dependency)
            assert whl_path is not None
            exec([self.pip_path(pkg), "install", whl_path])

    @cache_func()
    def env_path(self, name: str, dir: Path) -> Path:
        """Get environment path of the package, create it if doesn't exist"""
        output = exec(
            "poetry env list --full-path", cwd=dir, **self.exec_options("env.fetch")
        )

        if len(output) == 0:
            # environment doesn't exist, create it
            exec(
                "poetry run python -m __hello__",
                cwd=dir,
                **self.exec_options("env.create"),
            )
            output = exec(
                "poetry env list --full-path", cwd=dir, **self.exec_options("env.fetch")
            )

        if len(output) > 1:
            logger.warning(
                "There are multiple virtual environments for package {}, and we pick the first one (maybe incorrect). List of environments: \n{}",
                name,
                "\n".join(["\t- " + x for x in output]),
            )

        assert len(output) > 0
        if output[0].endswith(" (Activated)"):
            path = output[0].split(" ")[0]
        else:
            path = output[0]

        if not Path(path).exists():
            raise Exception(f"Environment path {path} doesn't exist")
        return Path(path)

    def tar_path(self, pkg: Package) -> Optional[Path]:
        tar_file = pkg.location / "dist" / f"{pkg.name}-{pkg.version}.tar.gz"
        if tar_file.exists():
            return tar_file
        return None

    def wheel_path(self, pkg: Package) -> Optional[Path]:
        whl_files = glob.glob(
            str(pkg.location / f"dist/{pkg.name.replace('-', '_')}*.whl")
        )
        if len(whl_files) == 0:
            return None
        return Path(whl_files[0])

    def pip_path(self, pkg: Package) -> Path:
        return self.env_path(pkg.name, pkg.location) / "bin/pip"  # type: ignore

    def python_path(self, pkg: Package) -> Path:
        return self.env_path(pkg.name, pkg.location) / "bin/python"  # type: ignore

    def exec_options(
        self,
        cmd: Literal[
            "publish",
            "install",
            "build",
            "env.remove",
            "env.create",
            "env.fetch",
        ],
    ) -> dict:
        return {"env": ["PATH"]}

    def parse_dep_spec(self, spec: Union[str, dict]) -> DepConstraint:
        if isinstance(spec, str):
            constraint = f"python=* markers="
            return DepConstraint(version_spec=spec, constraint=constraint)
        elif isinstance(spec, dict):
            if "version" not in spec:
                if "url" in spec:
                    # try to figure out the version from the URL if possible, otherwise, use 1.0.0
                    m = re.search(r"\d+.\d+.\d+", spec["url"])
                    if m is not None:
                        version_spec = f"=={m.group()}"
                    else:
                        version_spec = "==1.0.0"
                else:
                    raise NotImplementedError(
                        f"Not support specify dependency outside of Pypi yet. But found spec {spec}"
                    )
            else:
                version_spec = spec["version"]

            constraint = (
                f"python={spec.get('python', '*')} markers={spec.get('markers', '')}"
            )
            origin_spec = spec.copy()
            if "version" in origin_spec:
                origin_spec.pop("version")

            return DepConstraint(
                version_spec=version_spec,
                constraint=constraint,
                version_spec_field="version",
                origin_spec=origin_spec,
            )

    def serialize_dep_specs(self, specs: DepConstraints):
        items = []
        for spec in specs:
            if spec.origin_spec is None:
                item = spec.version_spec
            else:
                item = inline_table()
                item[cast(str, spec.version_spec_field)] = spec.version_spec
                for k, v in spec.origin_spec.items():
                    item[k] = v
            items.append(item)

        if len(items) == 1:
            return items[0]
        return Array(items, Trivia(), multiline=True)
