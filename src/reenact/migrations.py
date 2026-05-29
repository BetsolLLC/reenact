"""Schema migrations stub.

When SCHEMA_VERSION bumps, add a migration function here:

    def migrate_1_0_to_1_1(data: dict) -> dict:
        ...
        return data

Then register it in MIGRATIONS.
"""

from __future__ import annotations

from collections.abc import Callable

MIGRATIONS: dict[tuple[str, str], Callable[[dict[str, object]], dict[str, object]]] = {}


def migrate(data: dict[str, object]) -> dict[str, object]:
    """Apply all applicable migrations in version order."""
    version: str = str(data.get("version", "1.0"))
    while True:
        keys = [k for k in MIGRATIONS if k[0] == version]
        if not keys:
            break
        key = sorted(keys)[0]
        data = MIGRATIONS[key](data)
        version = key[1]
        data["version"] = version
    return data
