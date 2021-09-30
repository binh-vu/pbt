import os
import shutil

from tests.conftest import setup_dir

from pbt.diff import diff_db, Diff, RemoteDiff
from pbt.pypi import PyPI


def test_local_diff(repo1):
    lib0 = repo1.packages["lib0"]

    with diff_db(lib0, repo1.cfg) as db:
        diff = Diff.from_local(db, lib0)
        assert diff.is_modified(
            db
        ), "If we have no info about the package before. Then it's modified"

    with diff_db(lib0, repo1.cfg) as db:
        diff2 = Diff.from_local(db, lib0)
        assert diff.is_modified(db) == diff2.is_modified(
            db
        ), "Repeated call doesn't change the result"

    with diff_db(lib0, repo1.cfg) as db:
        diff.save(db)
        diff3 = Diff.from_local(db, lib0)
        assert not diff3.is_modified(
            db
        ), "After save changes, the package should not be considered as modified"

    # add new files should change the status
    setup_dir(
        {
            "lib0": {
                "module_a": {"__init__.py": "", "func.py": "print('module_a.func')"}
            }
        },
        lib0.dir,
    )

    with diff_db(lib0, repo1.cfg) as db:
        assert Diff.from_local(db, lib0).is_modified(
            db
        ), "Add new files should change to modified status"

    # remove new files should go back to not modified
    shutil.rmtree(lib0.dir / "lib0/module_a")
    with diff_db(lib0, repo1.cfg) as db:
        assert not Diff.from_local(db, lib0).is_modified(
            db
        ), "Remove new files should go back to normal"

    setup_dir({"lib0": {"main.py": "print('lib0 changed')"}}, lib0.dir)
    with diff_db(lib0, repo1.cfg) as db:
        diff = Diff.from_local(db, lib0)
        assert diff.is_modified(
            db
        ), "Edit existing files should change to modified status"
        diff.save(db)
        assert not Diff.from_local(db, lib0).is_modified(db)

    # modify the same file should mark as modified
    setup_dir({"lib0": {"main.py": "print('lib0 changed again')"}}, lib0.dir)
    with diff_db(lib0, repo1.cfg) as db:
        assert Diff.from_local(db, lib0).is_modified(db)
        Diff.from_local(db, lib0).save(db)
        assert not Diff.from_local(db, lib0).is_modified(db)

    # delete a file should change to modified
    os.remove(lib0.dir / "lib0/main.py")
    with diff_db(lib0, repo1.cfg) as db:
        assert Diff.from_local(db, lib0).is_modified(db)
        Diff.from_local(db, lib0).save(db)
        assert not Diff.from_local(db, lib0).is_modified(db)


def test_remote_diff(repo1):
    pbt_lib = repo1.packages["polyrepo-bt"]

    pkg = PyPI.get_instance().fetch_pkg_info(pbt_lib.name)
    pkg_version = pbt_lib.version
    (pkg_hash,) = [
        release["digests"]["sha256"]
        for release in pkg["releases"][pkg_version]
        if release["filename"].endswith(".whl")
    ]
    diff = RemoteDiff(is_version_diff=False, is_content_changed=False)
    assert RemoteDiff.from_pkg(pbt_lib, repo1.cfg, pkg_version, pkg_hash) == diff
    assert (
        RemoteDiff.from_pkg(pbt_lib, repo1.cfg, pkg_version, pkg_hash) == diff
    ), "Call again should return the same result"

    setup_dir({"pbt": {"newfile.py": "print('new file')"}}, pbt_lib.dir)
    assert RemoteDiff.from_pkg(pbt_lib, repo1.cfg, pkg_version, pkg_hash) == RemoteDiff(
        is_version_diff=False, is_content_changed=True
    )

    pbt_lib.next_version("patch")
    assert RemoteDiff.from_pkg(pbt_lib, repo1.cfg, pkg_version, pkg_hash) == RemoteDiff(
        is_version_diff=True, is_content_changed=True
    )
