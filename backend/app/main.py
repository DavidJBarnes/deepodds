import logging
from contextlib import asynccontextmanager

from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import router as api_router
from app.core.config import settings
from app.core.database import engine

logger = logging.getLogger(__name__)


def _run_migrations():
    """Apply any pending Alembic migrations at startup."""
    alembic_cfg = Config("alembic.ini")
    # Alembic's env.py reads DATABASE_URL_SYNC from settings, so we don't
    # need to override sqlalchemy.url here — env.py sets it at runtime.
    command.upgrade(alembic_cfg, "head")
    logger.info("Database migrations applied")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _run_migrations()
    yield
    await engine.dispose()


app = FastAPI(title="DeepOdds API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(api_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
