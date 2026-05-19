from celery import Celery

from app.core.config import settings

celery = Celery("deepodds", broker=settings.REDIS_URL, backend=settings.REDIS_URL)
celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    task_track_started=True,
    beat_schedule={
        "scan-crypto-markets": {
            "task": "scan_markets",
            "schedule": 60.0,
        },
        "settle-signals": {
            "task": "settle_signals",
            "schedule": 300.0,
        },
    },
)
celery.autodiscover_tasks(["app.tasks"])
