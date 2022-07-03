from pathlib import Path
from pbt.config import PBTConfig
from pbt.package.manager.manager import PkgManager, build_cache
from pbt.package.manager.poetry import Poetry
from pbt.package.package import VersionSpec
from semver import VersionInfo


def test_build_cache():
    with build_cache() as cache:
        assert cache == {}

        # nested call share the same dictionary
        with build_cache() as cache2:
            cache2["xxx"] = 1
            assert cache["xxx"] == 1
        assert cache["xxx"] == 1
        with build_cache() as cache3:
            assert cache3["xxx"] == 1
            assert cache["xxx"] == 1

    # when we go out of the with block, the cache is cleared
    with build_cache() as cache:
        assert cache == {}


def test_parse_version_spec():
    vs = PkgManager.parse_version_spec(">=2.0.0-alpha.15")
    assert vs == VersionSpec(VersionInfo.parse("2.0.0-alpha.15"), None, True, False)

    vs = PkgManager.parse_version_spec(">2.0.0-alpha.15")
    assert vs == VersionSpec(VersionInfo.parse("2.0.0-alpha.15"), None, False, False)

    vs = PkgManager.parse_version_spec(">2.0.0-alpha.15, <=5.2.1")
    assert vs == VersionSpec(
        VersionInfo.parse("2.0.0-alpha.15"), VersionInfo.parse("5.2.1"), False, True
    )
