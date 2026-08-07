from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.explorer import router as explorer_router
from app.api.v1.longshot import router as longshot_router
from app.api.v1.verbatim import router as verbatim_router

router = APIRouter(prefix="/api/v1")
router.include_router(auth_router)
router.include_router(longshot_router)
router.include_router(explorer_router)
router.include_router(verbatim_router)
