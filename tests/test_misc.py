from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Dict, cast
from pbt.config import PBTConfig
from pbt.misc import exec
from pbt.package.manager.poetry import Poetry
from pbt.package.package import Package, PackageType

from pbt.package.manager.manager import PkgManager


def test_exec():
    assert exec(["echo", "hello world"]) == ["hello world"]
    assert exec("echo") == [""]

    # test command that output nothing
    with TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        (tmpdir / ".cache").mkdir(parents=True, exist_ok=True)

        cfg = PBTConfig(
            cwd=tmpdir,
            cache_dir=tmpdir / ".cache",
        )

        poetry = Poetry(cfg)

        pkg = Package(
            name="test",
            version="0.0.1",
            type=PackageType.Poetry,
            location=Path(tmpdir),
            include=[],
            exclude=[],
            dependencies={},
            dev_dependencies={},
        )
        poetry.save(pkg)
        assert exec("poetry env list --full-path", cwd=tmpdir) == []
