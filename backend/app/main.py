import logging
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The API serves auth + the longshot status surface. The longshot-short
    # strategy runs in its own container (backend/longshot/, deepodds-longshot).
    # No scanner / scheduler here.
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
