from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

_settings = get_settings()

celery_app = Celery(
    "autoresearch",
    broker=_settings.redis_url,
    backend=_settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    imports=(
        "app.tasks.plan",
        "app.tasks.apply_edit",
        "app.tasks.run_experiment",
        "app.tasks.score",
        "app.tasks.decide",
        "app.tasks.loop",
        "app.tasks.stale_reviews",
    ),
    beat_schedule={
        "stale-reviews-hourly": {
            "task": "autoresearch.stale_reviews",
            "schedule": crontab(minute=0),
        },
    },
)
