from pathlib import Path
from tempfile import TemporaryDirectory
from pbt.misc import exec
from pbt.package import Package, PackageType
from tests.conftest import setup_poetry

def test_exec():
    assert exec(["echo", "hello world"]) == ["hello world\n"]
    assert exec("echo") == ["\n"]

    # test command that output nothing
    with TemporaryDirectory() as tmpdir:
        pkg = Package(
            name="test",
            type=PackageType.Poetry,
            dir=Path(tmpdir),
            version="0.0.1",
            include=[],
            exclude=[],
            dependencies={},
            inter_dependencies=[],
            invert_inter_dependencies=[],
        )
        setup_poetry(pkg)
        assert exec("poetry env list --full-path", cwd=tmpdir) == []

