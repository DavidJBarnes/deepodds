from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

from app.core.config import settings
from app.core.database import Base
from app.models import *  # noqa: F401, F403

config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL_SYNC)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


STALE_REVISIONS = {
    "l4m5n6o7p8q9": "k4e5f6g7h8i9",
    "n6o7p8q9r0s1": "m5n6o7p8q9r0",
}


def _fix_stale_revisions(connection):
    """Patch alembic_version if it points to a deleted migration."""
    try:
        row = connection.execute(text("SELECT version_num FROM alembic_version")).first()
        if row and row[0] in STALE_REVISIONS:
            target = STALE_REVISIONS[row[0]]
            connection.execute(
                text("UPDATE alembic_version SET version_num = :v"),
                {"v": target},
            )
            connection.commit()
    except Exception:
        pass


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        _fix_stale_revisions(connection)
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
