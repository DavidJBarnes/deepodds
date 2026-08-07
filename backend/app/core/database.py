from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

engine = create_async_engine(settings.DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession]:
    async with async_session() as session:
        yield session


# ---------------------------------------------------------------------------
# Verbatim — a second database on the same RDS instance.
#
# Deliberately its own DeclarativeBase: sharing `Base` would put Verbatim's 11
# tables into the trading metadata, and `alembic revision --autogenerate` against
# the trading DB would then cheerfully emit DROP TABLE for every one of them.
# Separate metadata makes that mistake impossible rather than merely unlikely.
#
# The engine is built lazily so an unconfigured environment (local dev, CI) can
# import this module without a Verbatim database existing.
# ---------------------------------------------------------------------------
class VerbatimBase(DeclarativeBase):
    pass


_verbatim_engine = None
_verbatim_session = None


def verbatim_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Session factory for the Verbatim DB. Raises if it isn't configured."""
    global _verbatim_engine, _verbatim_session
    if _verbatim_session is None:
        if not settings.verbatim_enabled:
            raise RuntimeError("VERBATIM_DATABASE_URL is not configured")
        # pool_pre_ping: RDS drops idle connections, and the Verbatim tables are
        # written in bursts (a stream goes live after hours of silence), so stale
        # pooled connections are the expected case here, not an edge case.
        _verbatim_engine = create_async_engine(
            settings.VERBATIM_DATABASE_URL, echo=False, pool_pre_ping=True, pool_size=5
        )
        _verbatim_session = async_sessionmaker(
            _verbatim_engine, class_=AsyncSession, expire_on_commit=False
        )
    return _verbatim_session


async def get_verbatim_db() -> AsyncGenerator[AsyncSession]:
    async with verbatim_sessionmaker()() as session:
        yield session
