import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import router as api_router
from app.core.config import settings
from app.core.database import engine

logger = logging.getLogger(__name__)

_scheduler_tasks: list[asyncio.Task] = []
_scheduler_executor: ThreadPoolExecutor | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Migrations are applied at deploy time via `make migrate` or `alembic upgrade head`.
    # Start the native asyncio scheduler (replaces Celery + Redis).
    from app.core.scheduler import start_scheduler
    global _scheduler_tasks, _scheduler_executor
    _scheduler_tasks, _scheduler_executor = await start_scheduler()
    yield
    # Shutdown: cancel all background tasks
    for task in _scheduler_tasks:
        task.cancel()
    if _scheduler_tasks:
        await asyncio.gather(*_scheduler_tasks, return_exceptions=True)
    if _scheduler_executor:
        _scheduler_executor.shutdown(wait=True)
    await engine.dispose()


app = FastAPI(title="DeepOdds API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning(
        "422 on %s %s — body=%r errors=%s",
        request.method, request.url.path, exc.body, exc.errors(),
    )
    return JSONResponse(status_code=422, content={"detail": exc.errors(), "body": exc.body})


app.include_router(api_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
