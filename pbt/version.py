import re

import semver


def parse_version(version: str) -> semver.VersionInfo:
    m = re.match(r"^\d+(?P<minor>\.\d+)?$", version)
    if m is not None:
        if m.group("minor") is None:
            version += ".0.0"
        else:
            version += ".0"
    return semver.VersionInfo.parse(version)
