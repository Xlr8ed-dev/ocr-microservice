from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.admin import setup_admin
from app.clients.http import clients
from app.config import settings
from app.routers import events, internal, visitors, workflows, flows, documents, images, analysis, templates, \
    extractions, stats, batch

import app.tasks.celery_app  # noqa: F401
import app.tasks.ocr_tasks  # noqa: F401
import app.tasks.workflow_tasks  # noqa: F401
import app.tasks.document_tasks  # noqa: F401
import app.tasks.image_tasks  # noqa: F401
import app.tasks.analysis_tasks  # noqa: F401
import app.tasks.extraction_tasks  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    await clients.startup()
    yield
    await clients.shutdown()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
    lifespan=lifespan,
)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.ADMIN_SECRET_KEY,
    session_cookie="ocr_admin_session",
    max_age=3600,
)

# --- API routers ---------------------------------------------------
app.include_router(events.router)
app.include_router(visitors.router)
app.include_router(workflows.router)
app.include_router(internal.router)
app.include_router(flows.router)
app.include_router(documents.router)
app.include_router(images.router)
app.include_router(analysis.router)
app.include_router(templates.router)
app.include_router(extractions.router)
app.include_router(stats.router)
app.include_router(batch.router)

# --- Admin ---------------------------------------------------------
setup_admin(app)


# --- Health --------------------------------------------------------
@app.get("/healthz", tags=["Health"])
async def healthz() -> dict:
    return {"status": "ok"}


@app.get("/readyz", tags=["Health"])
async def readyz() -> dict:
    return {"status": "ok"}
