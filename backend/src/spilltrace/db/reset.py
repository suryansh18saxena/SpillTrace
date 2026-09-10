"""Drop every application table.  Destructive; development only."""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from spilltrace.config import get_settings
from spilltrace.db.session import dispose_engine, get_engine


async def reset() -> None:
    settings = get_settings()
    if settings.is_production:
        raise SystemExit("Refusing to reset a production database.")
    engine = get_engine()
    async with engine.begin() as connection:
        # Recreating the schema is faster and more thorough than dropping tables one by
        # one, and it also clears the Alembic version table.
        await connection.execute(text("DROP SCHEMA public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))
        await connection.execute(
            text(f"GRANT ALL ON SCHEMA public TO {settings.postgres_user}, public")
        )
        for extension in (
            "postgis",
            "postgis_raster",
            "pgcrypto",
            "btree_gist",
            "citext",
            "pg_trgm",
        ):
            await connection.execute(text(f"CREATE EXTENSION IF NOT EXISTS {extension}"))
    await dispose_engine()
    print("Database schema reset. Run migrations next.")


if __name__ == "__main__":
    asyncio.run(reset())
