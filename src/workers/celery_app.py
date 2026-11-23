"""Celery application configuration and distributed task queue setup."""

from celery import Celery

from src.config import get_settings

settings = get_settings()

celery_app = Celery(
    "cloud_workflow_orchestrator",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["src.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_default_queue=settings.CELERY_TASK_DEFAULT_QUEUE,
    task_time_limit=settings.CELERY_TASK_TIME_LIMIT,
    task_soft_time_limit=settings.CELERY_TASK_TIME_LIMIT - 60,
    worker_concurrency=settings.WORKER_CONCURRENCY,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    result_expires=86400,  # 24 hours
    beat_schedule={
        "reclaim-zombie-tasks-every-60s": {
            "task": "src.workers.tasks.reclaim_zombie_tasks",
            "schedule": 60.0,
        },
        "trigger-pending-schedules-every-60s": {
            "task": "src.workers.tasks.trigger_pending_schedules",
            "schedule": 60.0,
        },
    },
)
