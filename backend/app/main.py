import asyncio
import logging
import os
import subprocess
import sys
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
_scanner_proc: subprocess.Popen | None = None


def _start_scanner_subprocess() -> subprocess.Popen | None:
    """Launch the scanner as a subprocess using fork+exec for a clean slate."""
    try:
        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env = os.environ.copy()
        env.setdefault("DATABASE_URL_SYNC", settings.DATABASE_URL_SYNC)
        env.setdefault("PYTHONPATH", backend_dir)
        proc = subprocess.Popen(
            [sys.executable, "-m", "scanner.main"],
            env=env,
            cwd=backend_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logger.info("Scanner subprocess started (pid=%d)", proc.pid)
        return proc
    except Exception:
        logger.exception("Failed to start scanner subprocess")
        return None


def _stop_scanner_subprocess(proc: subprocess.Popen | None) -> None:
    """Terminate the scanner subprocess gracefully."""
    if proc is None:
        return
    try:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
    except Exception:
        logger.exception("Failed to stop scanner subprocess")


async def _monitor_scanner():
    """Watchdog: restart the scanner subprocess if it dies."""
    global _scanner_proc
    while True:
        await asyncio.sleep(30)
        if _scanner_proc is not None:
            poll = _scanner_proc.poll()
            if poll is not None:
                logger.error("Scanner subprocess died (exit=%s), restarting...", poll)
                _scanner_proc = _start_scanner_subprocess()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Migrations are applied at deploy time via `make migrate` or `alembic upgrade head`.
    # Start the native asyncio scheduler (replaces Celery + Redis).
    # Start the standalone scanner subprocess.
    from app.core.scheduler import start_scheduler
    global _scheduler_tasks, _scheduler_executor, _scanner_proc

    _scheduler_tasks, _scheduler_executor = await start_scheduler()

    # The scanner runs as a separate OS process for full isolation.
    # Start it manually with:  python -m scanner.main
    # or let the deployment entrypoint script handle it.
    # _scanner_proc = _start_scanner_subprocess()
    # monitor_task = asyncio.create_task(_monitor_scanner(), name="scanner_watchdog")

    yield

    # monitor_task.cancel()
    # try:
    #     await monitor_task
    # except asyncio.CancelledError:
    #     pass

    # Shutdown: cancel all background tasks
    for task in _scheduler_tasks:
        task.cancel()
    if _scheduler_tasks:
        await asyncio.gather(*_scheduler_tasks, return_exceptions=True)
    if _scheduler_executor:
        _scheduler_executor.shutdown(wait=True)

    # _stop_scanner_subprocess(_scanner_proc)

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
