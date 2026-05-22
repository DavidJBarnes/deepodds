import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import router as api_router
from app.core.config import settings
from app.core.database import engine

logger = logging.getLogger(__name__)

_scheduler_tasks: list[asyncio.Task] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Migrations are applied at deploy time via `make migrate` or `alembic upgrade head`.
    # Start the native asyncio scheduler (replaces Celery + Redis).
    from app.core.scheduler import start_scheduler
    global _scheduler_tasks
    _scheduler_tasks = await start_scheduler()
    yield
    # Shutdown: cancel all background tasks
    for task in _scheduler_tasks:
        task.cancel()
    if _scheduler_tasks:
        await asyncio.gather(*_scheduler_tasks, return_exceptions=True)
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
