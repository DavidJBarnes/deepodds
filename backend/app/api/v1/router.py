from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.settings import router as settings_router
from app.api.v1.signals import router as signals_router
from app.api.v1.spot import router as spot_router

router = APIRouter(prefix="/api/v1")
router.include_router(auth_router)
router.include_router(dashboard_router)
router.include_router(settings_router)
router.include_router(signals_router)
router.include_router(spot_router)
