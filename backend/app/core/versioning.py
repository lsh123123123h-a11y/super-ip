import re
from typing import Any


_SEMVER = re.compile(
    r"^v?(?P<major>0|[1-9]\d*)\."
    r"(?P<minor>0|[1-9]\d*)\."
    r"(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>[0-9A-Za-z.-]+))?"
    r"(?:\+[0-9A-Za-z.-]+)?$"
)


def version_sort_key(value: str) -> tuple[Any, ...]:
    """Return a deterministic ordering key for implementation version strings.

    Registries only need to choose an administrative default. Runtime resume
    always resolves an exact persisted version and never silently falls back.
    """

    normalized = value.strip().lower()
    match = _SEMVER.fullmatch(normalized)
    if match:
        prerelease = match.group("prerelease")
        prerelease_key = tuple(
            (0, int(part)) if part.isdigit() else (1, part)
            for part in (prerelease or "").split(".")
            if part
        )
        return (
            1,
            int(match.group("major")),
            int(match.group("minor")),
            int(match.group("patch")),
            1 if prerelease is None else 0,
            prerelease_key,
        )
    natural = tuple(
        (0, int(part)) if part.isdigit() else (1, part)
        for part in re.split(r"[._+-]", normalized)
        if part
    )
    return (0, 0, 0, 0, 0, natural)
