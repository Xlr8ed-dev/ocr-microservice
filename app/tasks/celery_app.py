from celery import Celery

from app.config import settings

celery_app = Celery(
    "ocr_visitor_service",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,

    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_time_limit=600,
    task_soft_time_limit=540,

    task_default_retry_delay=10,
    task_default_max_retries=3,

    task_always_eager=settings.CELERY_TASK_ALWAYS_EAGER,
    task_eager_propagates=True,
)

celery_app.set_default()


# ---------------------------------------------------------
# Register task modules.
# Safe to import here because each task module imports
# celery_app from this file (no circular import at task
# registration time).
# ---------------------------------------------------------
import app.tasks.ocr_tasks        # noqa: E402,F401
import app.tasks.workflow_tasks   # noqa: E402,F401
import app.tasks.document_tasks   # noqa: E402,F401
import app.tasks.image_tasks   # noqa: E402,F401
import app.tasks.analysis_tasks   # noqa: E402,F401
import app.tasks.extraction_tasks   # noqa: E402,F401

