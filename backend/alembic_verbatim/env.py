"""Alembic environment for the Verbatim database.

Points at VERBATIM_DATABASE_URL and targets VerbatimBase.metadata ONLY. The
trading models are never imported here, so an autogenerate in this tree cannot
see — or drop — a trading table, and vice versa.
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings
from app.core.database import VerbatimBase
import app.models.verbatim  # noqa: F401  — registers the tables on VerbatimBase

config = context.config

# No Verbatim database configured (local dev, CI, or a deployment that has not
# opted in) -> exit cleanly rather than fail the deploy. The guard lives here
# rather than in the deploy shell because $VERBATIM_DATABASE_URL only exists
# inside the container, and quoting it through SSM -> docker -> sh is exactly
# the kind of thing that silently evaluates to empty and skips real migrations.
if not settings.VERBATIM_DATABASE_URL:
    print("alembic_verbatim: VERBATIM_DATABASE_URL unset — skipping")
    raise SystemExit(0)

# Escape % for ConfigParser interpolation — URL-encoded passwords would
# otherwise raise ValueError("invalid interpolation syntax").
config.set_main_option(
    "sqlalchemy.url", settings.VERBATIM_DATABASE_URL_SYNC.replace("%", "%%")
)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = VerbatimBase.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        version_table="alembic_version_verbatim",
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
            version_table="alembic_version_verbatim",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
