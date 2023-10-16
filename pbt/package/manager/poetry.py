import os
import re
import shutil
from contextlib import contextmanager
from dataclasses import dataclass
from operator import attrgetter
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union, cast

import semver
from loguru import logger
from tomlkit.api import document, dumps, inline_table, loads, nl, table
from tomlkit.items import Array, KeyType, SingleKey, Trivia

from pbt.config import PBTConfig
from pbt.misc import ExecProcessError, NewEnvVar, cache_method, exec
from pbt.package.manager.python import Pep518PkgManager, PythonPackage
from pbt.package.package import DepConstraint, DepConstraints, Package, PackageType


@dataclass
class PoetryPackage(PythonPackage):
    def get_all_dependency_specs(self) -> dict[str, DepConstraints]:
        """Get all dependency specifications for project specification manipulation purposes such as saving pyproject.toml.

        The reason we have a dedicated function is that optional dependencies in pyproject.toml is removed from the `dependencies`
        attribute and put into the `extra_dependencies` as by default, they are not installed without specifying the extra explicitly.
        """
        deps = self.dependencies.copy()
        for extra, extra_deps in self.extra_dependencies.items():
            if extra != "dev":
                # duplicated should always have the same specs
                deps.update(extra_deps)
        return deps


class Poetry(Pep518PkgManager[PoetryPackage]):
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
        pkg: PoetryPackage,
        skip_deps: List[str],
        additional_deps: dict[str, DepConstraints],
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
            if (pkg.location / "poetry.lock").exists():
                os.rename(
                    pkg.location / "poetry.lock",
                    self.cfg.pkg_cache_dir(pkg) / "poetry.modified.lock",
                )
            if (self.cfg.pkg_cache_dir(pkg) / "poetry.origin.lock").exists():
                os.rename(
                    self.cfg.pkg_cache_dir(pkg) / "poetry.origin.lock",
                    pkg.location / "poetry.lock",
                )

    def load(self, dir: Path) -> PoetryPackage:
        try:
            project_cfg = self.parse_pyproject(dir / "pyproject.toml")
            name = project_cfg["tool"]["poetry"]["name"]
            version = project_cfg["tool"]["poetry"]["version"]

            dependencies: dict[str, DepConstraints] = {}
            dev_dependencies: dict[str, DepConstraints] = {}

            # the optional dependencies are put into the extra_dependencies
            # as they are not install by default
            optional_deps: dict[str, DepConstraints] = {}
            tmp: Sequence[tuple[dict[str, DepConstraints], str]] = [
                (dependencies, "dependencies"),
                (dev_dependencies, "dev-dependencies"),
            ]
            for deps, cfg_key in tmp:
                deps: dict[str, DepConstraints]
                for k, vs in project_cfg["tool"]["poetry"].get(cfg_key, {}).items():
                    if not isinstance(vs, list):
                        vs = [vs]

                    deps[k] = sorted(
                        (self.parse_dep_spec(v) for v in vs),
                        key=attrgetter("constraint"),
                    )

                    if any(
                        (v.origin_spec or {}).get("optional", False) for v in deps[k]
                    ):
                        assert all(
                            (v.origin_spec or {}).get("optional", False)
                            for v in deps[k]
                        )
                        assert (
                            k not in optional_deps
                        ), f"Dependency {k} should not be specified twice"
                        assert (
                            cfg_key == "dependencies"
                        ), f"Optional dependency {k} should be specified in dependencies"
                        optional_deps[k] = deps.pop(k)

            extra_dependencies = {
                "dev": dev_dependencies,
            }

            assert "dev" not in project_cfg["tool"]["poetry"].get(
                "extras", {}
            ), "in poetry we reserve the dev extra for dev dependencies"
            for extra, vs in project_cfg["tool"]["poetry"].get("extras", {}).items():
                if not isinstance(vs, list):
                    vs = [vs]
                extra_dependencies[extra] = {k: optional_deps[k] for k in vs}

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

        return PythonPackage(
            name=name,
            version=version,
            dependencies=dependencies,
            extra_dependencies=extra_dependencies,
            extra_self_reference_deps={},
            type=PackageType.Poetry,
            location=dir,
            include=include,
            exclude=exclude,
        )

    def save(self, pkg: PoetryPackage, poetry_file: Optional[Path] = None):
        poetry_file = poetry_file or pkg.location / "pyproject.toml"
        if not poetry_file.exists():
            with open(poetry_file, "w") as f:
                doc = document()

                tbl = table()
                tbl.add("name", pkg.name)
                tbl.add("version", pkg.version)
                tbl.add("description", "")
                tbl.add("authors", [])

                if len(pkg.exclude) > 0:
                    tbl.add("exclude", pkg.exclude)
                if sum(int(x != pkg.name) for x in pkg.include) > 0:
                    tbl.add("packages", [{"include": x} for x in pkg.include])

                doc.add(SingleKey("tool.poetry", t=KeyType.Bare), tbl)

                tbl = table()
                for dep, specs in pkg.get_all_dependency_specs().items():
                    tbl.add(dep, self.serialize_dep_specs(specs))
                doc.add(nl())
                doc.add(SingleKey("tool.poetry.dependencies", t=KeyType.Bare), tbl)

                tbl = table()
                # always have extra_dependencies[dev]
                for dep, specs in pkg.extra_dependencies["dev"].items():
                    tbl.add(dep, self.serialize_dep_specs(specs))
                doc.add(nl())
                doc.add(SingleKey("tool.poetry.dev-dependencies", t=KeyType.Bare), tbl)

                if any(
                    len(dep_specs) > 0
                    for extra, dep_specs in pkg.extra_dependencies.items()
                    if extra != "dev"
                ):
                    tbl = table()
                    for extra, dep_specs in pkg.extra_dependencies.items():
                        if extra != "dev":
                            tbl.add(extra, [dep for dep in dep_specs])
                    doc.add(nl())
                    doc.add(SingleKey("tool.poetry.extras", t=KeyType.Bare), tbl)

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

            if pkg.exclude != doc["tool"]["poetry"].get("exclude", []):
                doc["tool"]["poetry"]["exclude"] = pkg.exclude
                is_modified = True

            include = doc["tool"]["poetry"].get("include", [])
            include.append(pkg.name)
            for pkg_cfg in doc["tool"]["poetry"].get("packages", []):
                include.append(
                    os.path.join(pkg_cfg.get("from", ""), pkg_cfg["include"])
                )
            include = sorted(set(include))
            if pkg.include != include:
                doc["tool"]["poetry"]["packages"] = [
                    {"include": x} for x in pkg.include
                ]
                is_modified = True

            for dependencies, corr_key in [
                (pkg.get_all_dependency_specs(), "dependencies"),
                (pkg.extra_dependencies["dev"], "dev-dependencies"),
            ]:
                dependencies: dict[str, DepConstraints]
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

            for extra, dep_specs in pkg.extra_dependencies.items():
                if extra == "dev":
                    continue
                if extra not in doc["tool"]["poetry"].get("extras", {}):
                    doc["tool"]["poetry"]["extras"][extra] = [dep for dep in dep_specs]
                    is_modified = True
                else:
                    other_deps = doc["tool"]["poetry"]["extras"][extra]
                    assert isinstance(other_deps, list)
                    if set(other_deps) != set(dep_specs):
                        doc["tool"]["poetry"]["extras"][extra] = [
                            dep for dep in dep_specs
                        ]
                        is_modified = True

            return is_modified

        self.update_pyproject(poetry_file, update_fn)

    def install(
        self,
        package: PoetryPackage,
        include_dev: bool = False,
        skip_deps: Optional[List[str]] = None,
        additional_deps: Optional[dict[str, DepConstraints]] = None,
        virtualenv: Optional[Path] = None,
    ):
        skip_deps = skip_deps or []
        additional_deps = additional_deps or {}

        if "python" in skip_deps:
            # we cannot skip python requirements
            skip_deps.remove("python")

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
            if (package.location / "poetry.lock").exists():
                try:
                    exec("poetry lock --check", cwd=package.location, env=env)
                except ExecProcessError:
                    logger.debug(
                        "poetry.lock is inconsistent with pyproject.toml, updating lock file..."
                    )
                    exec(
                        "poetry lock --no-update",
                        cwd=package.location,
                        capture_stdout=False,
                        env=env,
                    )

            exec(
                f"poetry install {options}",
                cwd=package.location,
                capture_stdout=False,
                env=env,
            )

    def _build_command(self, pkg: PoetryPackage, release: bool):
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
