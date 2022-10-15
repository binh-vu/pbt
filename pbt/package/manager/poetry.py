import re
import os
import shutil
import semver
from contextlib import contextmanager
from operator import attrgetter
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, cast

from loguru import logger
from pbt.config import PBTConfig
from pbt.misc import ExecProcessError, NewEnvVar, cache_method, exec
from pbt.package.manager.python import Pep518PkgManager
from pbt.package.package import DepConstraint, DepConstraints, Package, PackageType
from tomlkit.api import document, dumps, inline_table, loads, nl, table
from tomlkit.items import Array, KeyType, Trivia, SingleKey


class Poetry(Pep518PkgManager):
    def __init__(self, cfg: PBTConfig) -> None:
        super().__init__(
            cfg, pkg_type=PackageType.Poetry, backend="poetry.core.masonry.api"
        )
        self.passthrough_envs = self.passthrough_envs + ["POETRY_VIRTUALENVS_PATH"]

    @cache_method()
    def get_poetry_version(self, path: str) -> str:
        """Get current poetry version"""
        out = exec("poetry --version", env={"PATH": path})
        m = re.match(r"^Poetry \(?version ([^)]+)\)?$", out[0].strip())
        if m is None:
            raise ValueError(
                "Cannot parse Poetry version. Please report if after updating Poetry, you still encounter this error."
            )
        return m.group(1)

    @contextmanager  # type: ignore
    def change_dependencies(
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
            if dep in doc["tool"]["poetry"].get("dependencies", {}):
                r = doc["tool"]["poetry"]["dependencies"].remove(dep)
            elif dep in doc["tool"]["poetry"].get("dev-dependencies", {}):
                doc["tool"]["poetry"]["dev-dependencies"].remove(dep)

        for dep, specs in additional_deps.items():
            if dep not in doc["tool"]["poetry"]["dependencies"]:
                doc["tool"]["poetry"]["dependencies"][dep] = self.serialize_dep_specs(
                    specs
                )

        with open(self.cfg.pkg_cache_dir(pkg) / "pyproject.modified.toml", "w") as f:
            f.write(dumps(cast(Any, doc)))

        try:
            os.rename(
                pkg.location / "pyproject.toml",
                self.cfg.pkg_cache_dir(pkg) / "pyproject.origin.toml",
            )
            if (pkg.location / "poetry.lock").exists():
                os.rename(
                    pkg.location / "poetry.lock",
                    self.cfg.pkg_cache_dir(pkg) / "poetry.origin.lock",
                )
            shutil.copy(
                self.cfg.pkg_cache_dir(pkg) / "pyproject.modified.toml",
                pkg.location / "pyproject.toml",
            )
            if (self.cfg.pkg_cache_dir(pkg) / "poetry.modified.lock").exists():
                shutil.copy(
                    self.cfg.pkg_cache_dir(pkg) / "poetry.modified.lock",
                    pkg.location / "poetry.lock",
                )
            yield None
        finally:
            os.rename(
                self.cfg.pkg_cache_dir(pkg) / "pyproject.origin.toml",
                pkg.location / "pyproject.toml",
            )
            os.rename(
                pkg.location / "poetry.lock",
                self.cfg.pkg_cache_dir(pkg) / "poetry.modified.lock",
            )
            if (self.cfg.pkg_cache_dir(pkg) / "poetry.origin.lock").exists():
                os.rename(
                    self.cfg.pkg_cache_dir(pkg) / "poetry.origin.lock",
                    pkg.location / "poetry.lock",
                )

    def load(self, dir: Path) -> Package:
        try:
            project_cfg = self.parse_pyproject(dir / "pyproject.toml")
            name = project_cfg["tool"]["poetry"]["name"]
            version = project_cfg["tool"]["poetry"]["version"]

            dependencies = {}
            dev_dependencies = {}

            for deps, cfg_key in [
                (dependencies, "dependencies"),
                (dev_dependencies, "dev-dependencies"),
            ]:
                for k, vs in project_cfg["tool"]["poetry"].get(cfg_key, {}).items():
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
            with open(poetry_file, "w") as f:
                doc = document()

                tbl = table()
                tbl.add("name", pkg.name)
                tbl.add("version", pkg.version)
                tbl.add("description", "")
                tbl.add("authors", [])

                doc.add(SingleKey("tool.poetry", t=KeyType.Bare), tbl)

                tbl = table()
                for dep, specs in pkg.dependencies.items():
                    tbl.add(dep, self.serialize_dep_specs(specs))
                doc.add(nl())
                doc.add(SingleKey("tool.poetry.dependencies", t=KeyType.Bare), tbl)

                tbl = table()
                for dep, specs in pkg.dev_dependencies.items():
                    tbl.add(dep, self.serialize_dep_specs(specs))
                doc.add(nl())
                doc.add(SingleKey("tool.poetry.dev-dependencies", t=KeyType.Bare), tbl)

                tbl = table()
                tbl.add("requires", ["poetry-core>=1.0.0"])
                tbl.add("build-backend", "poetry.core.masonry.api")
                doc.add(nl())
                doc.add("build-system", tbl)

                f.write(dumps(doc))
            return

        doc = self.parse_pyproject(poetry_file)

        def update_fn(doc: dict):
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
            return is_modified

        self.update_pyproject(poetry_file, update_fn)

    def install(
        self,
        package: Package,
        include_dev: bool = False,
        skip_deps: Optional[List[str]] = None,
        additional_deps: Optional[Dict[str, DepConstraints]] = None,
        virtualenv: Optional[Path] = None,
    ):
        skip_deps = skip_deps or []
        additional_deps = additional_deps or {}

        if virtualenv is None:
            virtualenv = self.venv_path(package.name, package.location)

        path = os.environ.get("PATH", "")
        env: List[Union[str, NewEnvVar]] = [
            x for x in self.passthrough_envs if x != "PATH"
        ]
        for k, v in self.get_virtualenv_environment_variables(virtualenv).items():
            env.append({"name": k, "value": v})
            if k == "PATH":
                path = v

        options = ""
        if not include_dev:
            ver = self.parse_version(self.get_poetry_version(path))

            if semver.VersionInfo(
                major=ver.major, minor=ver.minor
            ) < semver.VersionInfo(major=1, minor=2):
                options = "--no-dev"
            else:
                options = "--only=main"

        with self.change_dependencies(package, skip_deps, additional_deps):
            try:
                exec(
                    f"poetry install {options}",
                    cwd=package.location,
                    env=env,
                )
            except ExecProcessError as e:
                if any(
                    str(e).find(s) != -1
                    for s in [
                        "Warning: The lock file is not up to date with the latest changes in pyproject.toml. You may be getting outdated dependencies. Run update to update them.",
                        "Warning: poetry.lock is not consistent with pyproject.toml. You may be getting improper dependencies.",
                    ]
                ):
                    # try to update the lock file without upgrade previous packages, and retry
                    logger.info("Updating lock file for package: {}", package.name)
                    exec(
                        "poetry lock",
                        cwd=package.location,
                        env=env,
                    )
                    logger.info("Re-install package: {}", package.name)
                    exec(
                        f"poetry install {options}",
                        cwd=package.location,
                        env=env,
                    )

    def _build_command(self, pkg: Package, release: bool):
        exec(
            "poetry build",
            cwd=pkg.location,
            env=self.passthrough_envs,
        )

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
