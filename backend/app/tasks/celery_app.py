from celery import Celery

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
)

# Tasks will be registered in Days 4-8 (plan, apply_edit, run_experiment, score, decide, loop).
# Beat schedule for stale-review scan registered in Days 7-8.
