"""Alembic environment.

Uses the synchronous psycopg driver: migrations are a one-shot operation and the async
engine adds nothing but complexity here.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from spilltrace.config import get_settings
from spilltrace.db import models  # noqa: F401  (import registers every table)
from spilltrace.db.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().sync_database_url)
target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to) -> bool:
    """Only manage objects this application declares.

    A PostGIS database contains extension-owned tables (spatial_ref_sys, and whatever
    else the base image installed).  Without this filter, autogenerate reflects them and
    proposes dropping every one — which would destroy the extensions.
    """
    managed = set(target_metadata.tables)
    if type_ == "table":
        return name in managed
    if type_ in ("index", "unique_constraint", "foreign_key_constraint", "column"):
        table_name = getattr(getattr(obj, "table", None), "name", None)
        if reflected and table_name is not None and table_name not in managed:
            return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
