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
            "schedule": 30.0,
        },
        "settle-signals": {
            "task": "settle_signals",
            "schedule": 300.0,
        },
        "sync-live-orders": {
            "task": "sync_live_orders",
            "schedule": 60.0,
        },
        "check-spot-signals": {
            "task": "check_spot_signals",
            "schedule": 10.0,
        },
    },
)
celery.autodiscover_tasks(["app.tasks"])

from celery.signals import worker_ready  # noqa: E402


@worker_ready.connect
def _start_binance_stream(**kwargs):
    from app.tasks.spot import start_binance_stream_task
    start_binance_stream_task.delay()
