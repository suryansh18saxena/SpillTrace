#!/usr/bin/env python3
"""Post-process an Alembic autogenerate output.

GeoAlchemy2 attaches DDL listeners that create a spatial index automatically for every
``Geometry`` column whose ``spatial_index`` is true (the default).  Alembic autogenerate
*also* emits an explicit ``op.create_index(..., postgresql_using='gist')`` for the same
column, so the migration tries to create each spatial index twice and fails with
``relation "idx_<table>_<column>" already exists``.

Keeping the explicit statements is the better half of the trade: they are visible,
reviewable and reversible.  So this script turns the implicit creation off by setting
``spatial_index=False`` on every ``Geometry(...)`` in the migration.

Run automatically by ``make makemigration``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

GEOMETRY_CALL = re.compile(r"geoalchemy2\.types\.Geometry\((?![^)]*spatial_index)")


def postprocess(path: Path) -> int:
    source = path.read_text()
    patched, count = GEOMETRY_CALL.subn("geoalchemy2.types.Geometry(spatial_index=False, ", source)
    if "from sqlalchemy.dialects import postgresql" not in patched:
        patched = patched.replace(
            "import sqlalchemy as sa",
            "import sqlalchemy as sa\nfrom sqlalchemy.dialects import postgresql",
            1,
        )
    if patched != source:
        path.write_text(patched)
    return count


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: postprocess_migration.py <migration.py> [...]", file=sys.stderr)
        return 2
    for name in argv[1:]:
        path = Path(name)
        if not path.is_file():
            print(f"skip (not a file): {path}", file=sys.stderr)
            continue
        count = postprocess(path)
        print(f"{path.name}: disabled implicit spatial_index on {count} Geometry column(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
