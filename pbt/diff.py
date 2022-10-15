import os
import shutil
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Dict, Generator, List, Optional
from uuid import uuid4

import orjson
import semver
from loguru import logger
from hugedict.prelude import RocksDBDict, RocksDBOptions
from pbt.config import PBTConfig
from pbt.vcs.git import Git, GitFileStatus
from pbt.package.manager.manager import PkgManager
from pbt.package.package import Package

# file size limit
SOFT_SIZE_LIMIT = (1024**2) * 1  # 1MB
HARD_SIZE_LIMIT = (1024**2) * 100  # 100MBs
DIFF_DB_CACHE = {}


@contextmanager
def diff_db(
    pkg: Package, cfg: PBTConfig, new_connection: bool = False
) -> Generator["RocksDBDict[bytes, bytes]", None, None]:
    global DIFF_DB_CACHE
    db_file = str(cfg.pkg_cache_dir(pkg) / "diff.db")
    if new_connection:
        # client = DB(db_file, Options(create_if_missing=True))
        client = RocksDBDict(
            db_file,
            RocksDBOptions(create_if_missing=True),
            deser_key=bytes,
            deser_value=bytes,
            ser_value=lambda x: x,
        )
        try:
            yield client
        finally:
            del client
    else:
        if db_file not in DIFF_DB_CACHE:
            DIFF_DB_CACHE[db_file] = RocksDBDict(
                db_file,
                RocksDBOptions(create_if_missing=True),
                deser_key=bytes,
                deser_value=bytes,
                ser_value=lambda x: x,
            )
        yield DIFF_DB_CACHE[db_file]


def remove_diff_db(pkg: Package, cfg: PBTConfig):
    db_file = cfg.pkg_cache_dir(pkg) / "diff.db"
    if db_file.exists():
        shutil.rmtree(db_file)


@dataclass(eq=True)
class Diff:
    id: str
    commit_id: str
    changed_files: List[GitFileStatus]
    # content of the changed files, serving as a cache, does not guarantee to have
    # all of the non-deleted files, if the content of a changed file is None, it's
    # mean the value does not change since the last snapshot
    changed_files_content: Dict[str, Optional[bytes]]

    @staticmethod
    def from_local(
        db: "RocksDBDict[bytes, bytes]", manager: PkgManager, pkg: Package
    ) -> "Diff":
        """Compute diff of a current package, i.e., which files of a package have been modified"""
        commit_id = Git.get_current_commit(pkg.location)

        # TODO: make this code to get changed files more efficient
        changed_files = Git.get_new_modified_deleted_files(pkg.location)
        include_files = set(
            manager.filter_included_files(pkg, [file.fpath for file in changed_files])
        )
        changed_files = sorted(
            [file for file in changed_files if file.fpath in include_files]
        )

        return Diff(
            id=str(uuid4()),
            commit_id=commit_id,
            changed_files=changed_files,
            changed_files_content={},
        )

    def is_modified(self, db: "RocksDBDict[bytes, bytes]") -> bool:
        """Check if the package's content has been updated since the last snapshot"""
        prev_commit_id = db.get(b"commit_id")
        if prev_commit_id != self.commit_id.encode():
            return True

        prev_changed_files = orjson.loads(db[b"changed_files"])
        prev_changed_files = [GitFileStatus(*x) for x in prev_changed_files]
        if prev_changed_files != self.changed_files:
            return True

        for file in self.changed_files:
            if file.is_deleted:
                continue
            file_key = b"content:%s" % file.fpath.encode()
            prev_file_content = db.get(file_key)
            if file.fpath not in self.changed_files_content:
                file_content = read_file(file.fpath)
            else:
                file_content = self.changed_files_content[file.fpath]

            if prev_file_content != file_content:
                self.changed_files_content[file.fpath] = file_content
                return True
            self.changed_files_content[file.fpath] = None
        return False

    def save(self, db: "RocksDBDict[bytes, bytes]"):
        """Snapshot the current changes to the DB so that we can detect changes between commits"""
        db[b"commit_id"] = self.commit_id.encode()
        db[b"changed_files"] = orjson.dumps([tuple(x) for x in self.changed_files])

        prev_changed_files = db.get(b"changed_files")
        if prev_changed_files is not None:
            prev_changed_files = {
                GitFileStatus(*x).fpath for x in orjson.loads(prev_changed_files)
            }
            for file in prev_changed_files.difference(
                (x.fpath for x in self.changed_files)
            ):
                del db[b"content:%s" % file.encode()]

        for file in self.changed_files:
            if file.is_deleted:
                del db[b"content:%s" % file.fpath.encode()]
                continue

            if file.fpath not in self.changed_files_content:
                file_content = read_file(file.fpath)
            else:
                file_content = self.changed_files_content[file.fpath]
                if file_content is None:
                    # does not change the value since last snapshot, skip it
                    continue
            db[b"content:%s" % file.fpath.encode()] = file_content


@dataclass(eq=True)
class RemoteDiff:
    is_version_diff: bool
    is_content_changed: bool

    @staticmethod
    def from_pkg(
        manager: PkgManager,
        pkg: Package,
        remote_version: Optional[str] = None,
        remote_version_hash: Optional[str] = None,
    ) -> "RemoteDiff":
        """Detect if content of the current package is different from the remote package."""
        if pkg.version != remote_version:
            pkg_ver = semver.VersionInfo.parse(pkg.version)
            if remote_version is not None:
                remote_ver = semver.VersionInfo.parse(remote_version)
                if pkg_ver < remote_ver:
                    raise Exception(
                        "Current package version is outdated compared to the remote version"
                    )
            return RemoteDiff(is_version_diff=True, is_content_changed=True)

        # TODO: replace the approximation algorithm (checking hash) with exact algorithm
        # that determine if the content is the same
        pkg_hash = manager.compute_pkg_hash(pkg)
        return RemoteDiff(
            is_version_diff=False, is_content_changed=pkg_hash != remote_version_hash
        )


def read_file(fpath: str) -> bytes:
    fsize = os.path.getsize(fpath)
    if fsize > HARD_SIZE_LIMIT:
        raise Exception(
            f"File {fpath} is bigger than the hard limit ({format_size(fsize)} > {format_size(HARD_SIZE_LIMIT)})"
        )

    if fsize > SOFT_SIZE_LIMIT:
        logger.warning(
            "File {} is quite big ({} > {}). Consider ignore or commit it to speed up the process",
            fpath,
            format_size(fsize),
            format_size(SOFT_SIZE_LIMIT),
        )

    with open(fpath, "rb") as f:
        return f.read()


def format_size(n_bytes: int) -> str:
    if n_bytes < 1024:
        size = n_bytes
        unit = "Bs"
    elif n_bytes >= 1024 and n_bytes < (1024**2):
        size = round(n_bytes / 1024, 2)
        unit = "KBs"
    elif n_bytes >= (1024**2) and n_bytes < (1024**3):
        size = round(n_bytes / (1024**2), 2)
        unit = "MBs"
    else:
        assert n_bytes >= (1024**3)
        size = round(n_bytes / (1024**3), 2)
        unit = "GBs"
    return f"{size}{unit}"
