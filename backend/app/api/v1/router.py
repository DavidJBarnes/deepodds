from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.calibration import router as calibration_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.history import router as history_router
from app.api.v1.model_training import router as model_training_router
from app.api.v1.settings import router as settings_router
from app.api.v1.signals import router as signals_router

router = APIRouter(prefix="/api/v1")
router.include_router(auth_router)
router.include_router(calibration_router)
router.include_router(dashboard_router)
router.include_router(history_router)
router.include_router(model_training_router)
router.include_router(settings_router)
router.include_router(signals_router)
