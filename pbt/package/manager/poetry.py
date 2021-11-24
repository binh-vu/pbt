import glob
import os
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, List, Literal, cast

from loguru import logger
from pbt.misc import exec
from pbt.package.manager.manager import PkgManager
from pbt.package.package import Package, PackageType
from tomlkit.api import document, dumps, inline_table, key, loads, nl, table
from tomlkit.items import Key, KeyType


class Poetry(PkgManager):
    def __init__(self) -> None:
        super().__init__()

    def is_package_directory(self, dir: Path) -> bool:
        return (dir / "pyproject.toml").exists()

    def iter_package(self, root: Path) -> Iterable[Package]:
        return [
            self.load(os.path.dirname(fpath))
            for fpath in glob(root.absolute() / "**/pyproject.toml")
        ]

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
                for k, v in project_cfg["tool"]["poetry"]["dependencies"].items():
                    if isinstance(v, str):
                        dependencies[k] = {"version": v}
                    else:
                        assert isinstance(v, dict)
                        assert "version" in v
                        dependencies[k] = v

                dev_dependencies = {}
                for k, v in project_cfg["tool"]["poetry"]["dev-dependencies"].items():
                    if isinstance(v, str):
                        dev_dependencies[k] = {"version": v}
                    else:
                        assert isinstance(v, dict)
                        assert "version" in v
                        dev_dependencies[k] = v

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
                for dep, info in pkg.dependencies.items():
                    if len(info) > 1:
                        x = inline_table()
                        for k, v in info.items():
                            x[k] = v
                        tbl.add(dep, x)
                    else:
                        tbl.add(dep, info["version"])
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
                for dep, version in dependencies.items():
                    is_dep_modified = False
                    if dep not in doc["tool"]["poetry"][corr_key]:
                        is_dep_modified = True
                    else:
                        other_ver = doc["tool"]["poetry"][corr_key][dep]
                        if isinstance(other_ver, str):
                            other_ver = {"version": other_ver}
                        if other_ver != version:
                            is_dep_modified = True

                    if is_dep_modified:
                        if len(version) > 1:
                            x = inline_table()
                            for k, v in version.items():
                                x[k] = v
                            doc["tool"]["poetry"][corr_key][dep] = x
                        else:
                            doc["tool"]["poetry"][corr_key][dep] = version["version"]
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

    @lru_cache(maxsize=None)
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
                **self.exec_options("env.create")
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
