from app.models.history import History
from app.models.user import User

# NOTE: app.models.verbatim is deliberately NOT imported here.
#
# alembic/env.py does `from app.models import *` and migrates the TRADING
# database. Verbatim's models live on a separate DeclarativeBase in a separate
# database with its own Alembic tree (alembic_verbatim/). Re-exporting them here
# is harmless today (different metadata) but is one refactor away from letting a
# trading autogenerate emit DROP TABLE for every Verbatim table. Import them
# from app.models.verbatim explicitly instead.

__all__ = [
    "History",
    "User",
]
