import glob
from operator import attrgetter
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, List, Literal, Union, cast

from loguru import logger
from pbt.misc import cache_func, exec
from pbt.package.manager.manager import PkgManager
from pbt.package.package import DepConstraint, DepConstraints, Package, PackageType
from tomlkit.api import document, dumps, inline_table, key, loads, nl, table
from tomlkit.items import Key, KeyType


class Poetry(PkgManager):
    def __init__(self) -> None:
        super().__init__()

    def is_package_directory(self, dir: Path) -> bool:
        return (dir / "pyproject.toml").exists()

    def glob_query(self, root: Path) -> str:
        return glob(root.absolute() / "**/pyproject.toml")

    @contextmanager  # type: ignore
    def mask(self, pkg: Package, deps: List[str]):
        with open(pkg.location / "pyproject.toml", "r") as f:
            doc = cast(dict, loads(f.read()))

        for dep in deps:
            if dep in doc["tool"]["poetry"]["dependencies"]:
                doc["tool"]["poetry"]["dependencies"].pop(dep)
            elif dep in doc["tool"]["poetry"]["dev-dependencies"]:
                doc["tool"]["poetry"]["dev-dependencies"].pop(dep)

        try:
            os.rename(
                pkg.location / "pyproject.toml",
                pkg.location / "pyproject.toml.backup",
            )
            with open(pkg.location / "pyproject.toml", "w") as f:
                f.write(dumps(cast(Any, doc)))
            yield None
        finally:
            os.rename(
                pkg.location / "pyproject.toml.backup",
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
                doc.add(Key("tool.poetry", t=KeyType.Bare), tbl)

                tbl = table()
                for dep, specs in pkg.dependencies.items():
                    items = []
                    for spec in specs:
                        if spec.origin_spec is None:
                            item = spec.version_spec
                        else:
                            item = inline_table()
                            item[cast(str, spec.version_spec_field)] = spec.version_spec
                            for k, v in spec.origin_spec.items():
                                item[k] = v
                    tbl.add(dep, items)
                doc.add(nl())
                doc.add(Key("tool.poetry.dependencies", t=KeyType.Bare), tbl)

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
                        items = []
                        for spec in specs:
                            if spec.origin_spec is None:
                                item = spec.version_spec
                            else:
                                item = inline_table()
                                item[
                                    cast(str, spec.version_spec_field)
                                ] = spec.version_spec
                                for k, v in spec.origin_spec.items():
                                    item[k] = v
                        doc["tool"]["poetry"][corr_key][dep] = items
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
        raise NotImplementedError()

    def publish(self, pkg: Package):
        exec("poetry publish --build", cwd=pkg.location, **self.exec_options("publish"))

    def install(self, pkg: Package, skip_deps: List[str] = None):
        if skip_deps is None:
            skip_deps = []

        if len(skip_deps) > 0:
            with self.mask(pkg, skip_deps):
                exec("poetry install", cwd=pkg.location, **self.exec_options("install"))
        else:
            exec("poetry install", cwd=pkg.location, **self.exec_options("install"))

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
                "There are multiple virtual environments for package {}, and we pick the first one (maybe incorrect)",
                name,
            )

        if output[0].rstrip().endswith(" (Activated)"):
            path = output[0].split(" ")[0]
        else:
            path = output[0]

        return Path(path)

    def pip_path(self, pkg: Package) -> Path:
        return self.env_path(pkg.name, pkg.location) / "bin/pip"  # type: ignore

    def python_path(self) -> Path:
        return self.env_path(pkg.name, pkg.location) / "bin/python"  # type: ignore

    def exec_options(
        self, cmd: Literal["publish", "install", "env.create", "env.fetch"]
    ) -> dict:
        if cmd in {"publish", "install"}:
            return {}
        return {}

    def parse_dep_spec(self, spec: Union[str, dict]) -> DepConstraint:
        if isinstance(spec, str):
            return DepConstraint(version_spec=spec)
        elif isinstance(spec, dict):
            if "version" not in spec:
                raise NotImplementedError(
                    f"Not support specify dependency outside of Pypi yet. But found spec {spec}"
                )

            constraint = (
                f"python={spec.get('python', '*')} markers={spec.get('markers', '')}"
            )
            origin_spec = spec.copy()
            origin_spec.pop("version")

            return DepConstraint(
                version_spec=spec["version"],
                constraint=constraint,
                version_spec_field="version",
                origin_spec=origin_spec,
            )