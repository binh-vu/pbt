from pbt.package.manager.manager import build_cache


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
