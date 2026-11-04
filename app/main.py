from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.admin import setup_admin
from app.clients.http import clients
from app.config import settings
from app.routers import events, internal, visitors, workflows, flows, documents, images, analysis, templates, \
    extractions, stats, batch, uploads, files, auth

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


# --- Authorize dialog: bearer + user_id + device fingerprint ----------
#
# The dependencies declare the bearer via HTTPBearer (which becomes a security
# requirement automatically) but read X-User-Id and X-Device-Fingerprint as
# plain headers. Without the post-processing below Swagger shows those two as
# per-endpoint input fields instead of letting users fill them once in the
# "Available authorizations" dialog. Three security schemes bound together
# (AND) means every protected request is sent with all three values.

def _install_openapi_authorizations() -> None:
    if settings.AUTH_MODE != "auth_service":
        return

    _original_openapi = app.openapi

    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema

        schema = _original_openapi()
        components = schema.setdefault("components", {})
        schemes = components.setdefault("securitySchemes", {})
        schemes["XDeviceFingerprint"] = {
            "type": "apiKey",
            "in": "header",
            "name": "X-Device-Fingerprint",
            "description": (
                "The device fingerprint the access token was bound to at "
                "login. Must be the same value for every request."
            ),
        }
        schemes["XUserId"] = {
            "type": "apiKey",
            "in": "header",
            "name": "X-User-Id",
            "description": (
                "The auth-service user UUID (auth_user_id from /auth/me). "
                "Verified against the token's subject; a mismatch is a 401."
            ),
        }

        # One requirement object whose map has all three schemes = ALL three
        # must be supplied (AND). Keeping HTTPBearer in the same object is what
        # makes Swagger's Authorize dialog store and attach all of them at
        # once.
        requirement = [
            {"HTTPBearer": [], "XDeviceFingerprint": [], "XUserId": []},
        ]

        for operations in schema.get("paths", {}).values():
            for method, operation in operations.items():
                if method not in ("get", "post", "put", "patch", "delete"):
                    continue
                if not operation.get("security"):
                    continue  # public or service-token routes stay untouched

                operation["security"] = requirement
                # Drop the now-redundant per-endpoint header fields.
                operation["parameters"] = [
                    parameter
                    for parameter in operation.get("parameters", [])
                    if not (
                        parameter.get("in") == "header"
                        and parameter.get("name")
                        in ("X-User-Id", "X-Device-Fingerprint")
                    )
                ]

        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi


# --- API routers ---------------------------------------------------
app.include_router(auth.router)
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
app.include_router(uploads.router)
app.include_router(files.router)

# Must run AFTER all routers are included so the first /openapi.json build
# sees every route.
_install_openapi_authorizations()

# --- Admin ---------------------------------------------------------
setup_admin(app)


# --- Health --------------------------------------------------------
@app.get("/healthz", tags=["Health"])
async def healthz() -> dict:
    return {"status": "ok"}


@app.get("/readyz", tags=["Health"])
async def readyz() -> dict:
    return {"status": "ok"}
