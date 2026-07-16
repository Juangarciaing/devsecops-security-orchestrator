import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import AsyncEngine, async_engine_from_config

from alembic import context
from orchestrator.infrastructure.db import models  # noqa: F401 -- registers ORM metadata
from orchestrator.infrastructure.db.base import Base
from orchestrator.infrastructure.db.engine import resolve_database_url

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override the `sqlalchemy.url` placeholder from alembic.ini with the
# normalized DSN from Settings (Module 1's `get_settings().database_url`,
# via PR3's `resolve_database_url()` — same normalization the application's
# runtime engine uses, so migrations and the app always target the same
# database with the same asyncpg-driver scheme).
config.set_main_option("sqlalchemy.url", resolve_database_url())

# `Base.metadata` registers every ORM model imported above (`infrastructure.db.models`)
# for 'autogenerate' support.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: object) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)  # type: ignore[arg-type]

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode against the async engine.

    Creates an `AsyncEngine` from the alembic config section and associates
    a connection with the context via `run_sync`, since Alembic's migration
    context itself is synchronous.
    """
    connectable: AsyncEngine = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
