import os

from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from starlette.requests import Request

from app.database import engine
from app.models import (
    Event,
    Visitor,
    OCRJob,
    OpenAIUsageLog,
    WorkflowRun, DocumentOCRJob, ImageOCRJob, Template, Extraction,
)


# =========================================================
# AUTH BACKEND
# =========================================================
# Simple username/password auth for Phase 0.
# Later: swap to SSO — verify a Bearer token from the
# sso service and check role == ADMIN.

class AdminAuth(AuthenticationBackend):
    async def login(self, request: Request) -> bool:
        form = await request.form()
        username = form.get("username")
        password = form.get("password")

        expected_user = os.getenv("ADMIN_USERNAME", "admin")
        expected_pass = os.getenv("ADMIN_PASSWORD", "admin")

        if username == expected_user and password == expected_pass:
            request.session.update({"admin_user": username})
            return True
        return False

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        return "admin_user" in request.session


# =========================================================
# EVENT
# =========================================================

class EventAdmin(ModelView, model=Event):
    name = "Event"
    name_plural = "Events"
    icon = "fa-solid fa-calendar"

    column_list = [
        Event.id,
        Event.event_name,
        Event.admin_id,
        Event.start_date,
        Event.end_date,
        Event.venue,
        Event.created_at,
    ]
    column_searchable_list = [Event.event_name, Event.venue]
    column_sortable_list = [Event.event_name, Event.created_at]
    column_default_sort = [(Event.created_at, True)]  # True = descending
    page_size = 50


# =========================================================
# VISITOR
# =========================================================

class VisitorAdmin(ModelView, model=Visitor):
    name = "Visitor"
    name_plural = "Visitors"
    icon = "fa-solid fa-id-card"

    column_list = [
        Visitor.txn_Id,
        Visitor.name,
        Visitor.company_name,
        Visitor.phone,
        Visitor.visitor_email,
        Visitor.admin_id,
        Visitor.agent_id,
        Visitor.event_name,
        Visitor.ocr_status,
        Visitor.is_duplicate,
        Visitor.is_stopped,
        Visitor.sync_at,
    ]
    column_searchable_list = [
        Visitor.txn_Id,
        Visitor.name,
        Visitor.company_name,
        Visitor.phone,
        Visitor.visitor_email,
    ]
    column_sortable_list = [
        Visitor.name,
        Visitor.sync_at,
        Visitor.ocr_status,
        Visitor.is_duplicate,
    ]
    column_default_sort = [(Visitor.sync_at, True)]
    page_size = 50

    # Read-only fields that shouldn't be edited by hand
    form_excluded_columns = [
        Visitor.sync_at,
        Visitor.sync_updated_at,
        Visitor.deleted_at,
        Visitor.visiting_card_primary_ocr,
        Visitor.visiting_card_secondary_ocr,
        Visitor.related_event_ids,
    ]


# =========================================================
# OCR JOB
# =========================================================

class OCRJobAdmin(ModelView, model=OCRJob):
    name = "OCR Job"
    name_plural = "OCR Jobs"
    icon = "fa-solid fa-image"

    column_list = [
        OCRJob.job_id,
        OCRJob.txn_id,
        OCRJob.job_type,
        OCRJob.status,
        OCRJob.webhook_status,
        OCRJob.attempts,
        OCRJob.admin_id,
        OCRJob.created_at,
        OCRJob.completed_at,
    ]
    column_searchable_list = [OCRJob.txn_id, OCRJob.job_id]
    column_sortable_list = [
        OCRJob.created_at,
        OCRJob.status,
        OCRJob.job_type,
    ]
    column_default_sort = [(OCRJob.created_at, True)]
    page_size = 50

    # These are written by the worker only — not by hand
    form_excluded_columns = [
        OCRJob.job_id,
        OCRJob.result,
        OCRJob.error,
        OCRJob.celery_task_id,
        OCRJob.webhook_status,
        OCRJob.webhook_attempts,
        OCRJob.webhook_last_error,
        OCRJob.started_at,
        OCRJob.completed_at,
    ]


# =========================================================
# OPENAI USAGE LOG
# =========================================================

class OpenAIUsageLogAdmin(ModelView, model=OpenAIUsageLog):
    name = "OpenAI Usage"
    name_plural = "OpenAI Usage Logs"
    icon = "fa-solid fa-coins"

    column_list = [
        OpenAIUsageLog.id,
        OpenAIUsageLog.job_id,
        OpenAIUsageLog.txn_id,
        OpenAIUsageLog.task_name,
        OpenAIUsageLog.api_call_type,
        OpenAIUsageLog.model,
        OpenAIUsageLog.prompt_tokens,
        OpenAIUsageLog.completion_tokens,
        OpenAIUsageLog.total_tokens,
        OpenAIUsageLog.created_at,
    ]
    column_searchable_list = [
        OpenAIUsageLog.txn_id,
        OpenAIUsageLog.job_id,
        OpenAIUsageLog.model,
    ]
    column_sortable_list = [OpenAIUsageLog.created_at]
    column_default_sort = [(OpenAIUsageLog.created_at, True)]
    page_size = 100

    # Usage logs are append-only — no create/edit/delete from admin
    can_create = False
    can_edit = False
    can_delete = False


# =========================================================
# WORKFLOW RUN
# =========================================================

class WorkflowRunAdmin(ModelView, model=WorkflowRun):
    name = "Workflow Run"
    name_plural = "Workflow Runs"
    icon = "fa-solid fa-diagram-project"

    column_list = [
        WorkflowRun.run_id,
        WorkflowRun.txn_id,
        WorkflowRun.flow_name,
        WorkflowRun.status,
        WorkflowRun.current_step,
        WorkflowRun.admin_id,
        WorkflowRun.user_id,
        WorkflowRun.created_at,
        WorkflowRun.completed_at,
    ]
    column_searchable_list = [
        WorkflowRun.run_id,
        WorkflowRun.txn_id,
        WorkflowRun.flow_name,
    ]
    column_sortable_list = [
        WorkflowRun.created_at,
        WorkflowRun.status,
        WorkflowRun.flow_name,
    ]
    column_default_sort = [(WorkflowRun.created_at, True)]
    page_size = 50

    form_excluded_columns = [
        WorkflowRun.run_id,
        WorkflowRun.steps,
        WorkflowRun.status,
        WorkflowRun.current_step,
        WorkflowRun.error,
        WorkflowRun.started_at,
        WorkflowRun.completed_at,
    ]


# =========================================================
# TEMPLATE
# =========================================================

class TemplateAdmin(ModelView, model=Template):
    name = "Template"
    name_plural = "Templates"
    icon = "fa-solid fa-file-lines"

    column_list = [
        Template.id,
        Template.name,
        Template.category,
        Template.is_active,
        Template.created_at,
        Template.updated_at,
    ]
    column_searchable_list = [Template.id, Template.name, Template.category]
    column_sortable_list = [
        Template.category,
        Template.name,
        Template.created_at,
    ]
    column_default_sort = [(Template.category, False), (Template.name, False)]
    page_size = 50

    # Fields are managed by seed scripts — don't allow inline editing.
    can_create = False
    can_edit = False
    can_delete = False

    form_excluded_columns = [
        Template.fields,
        Template.sample_doc_url,
        Template.created_at,
        Template.updated_at,
    ]


# =========================================================
# EXTRACTION
# =========================================================

class ExtractionAdmin(ModelView, model=Extraction):
    name = "Extraction"
    name_plural = "Extractions"
    icon = "fa-solid fa-file-import"

    column_list = [
        Extraction.id,
        Extraction.template_id,
        Extraction.file_name,
        Extraction.file_type,
        Extraction.status,
        Extraction.review_needed,
        Extraction.admin_id,
        Extraction.user_id,
        Extraction.created_at,
    ]
    column_searchable_list = [
        Extraction.id,
        Extraction.file_name,
        Extraction.template_id,
    ]
    column_sortable_list = [
        Extraction.created_at,
        Extraction.status,
        Extraction.review_needed,
    ]
    column_default_sort = [(Extraction.created_at, True)]
    page_size = 50

    # Extractions are created via API and edited by end users.
    # Admin is for inspection only.
    can_create = False
    can_edit = False
    can_delete = True

    form_excluded_columns = [
        Extraction.id,
        Extraction.result,
        Extraction.min_confidence,
        Extraction.review_needed,
        Extraction.error,
        Extraction.ai_calls,
        Extraction.ai_tokens_in,
        Extraction.ai_tokens_out,
        Extraction.cost_estimate,
        Extraction.started_at,
        Extraction.completed_at,
        Extraction.updated_at,
    ]


class DocumentOCRJobAdmin(ModelView, model=DocumentOCRJob):
    name = "Document OCR Job"
    name_plural = "Document OCR Jobs"
    icon = "fa-solid fa-file-lines"

    column_list = [
        DocumentOCRJob.job_id,
        DocumentOCRJob.file_name,
        DocumentOCRJob.file_type,
        DocumentOCRJob.status,
        DocumentOCRJob.page_count,
        DocumentOCRJob.progress,
        DocumentOCRJob.admin_id,
        DocumentOCRJob.created_at,
    ]
    column_searchable_list = [DocumentOCRJob.job_id, DocumentOCRJob.file_name]
    column_sortable_list = [DocumentOCRJob.created_at, DocumentOCRJob.status]
    column_default_sort = [(DocumentOCRJob.created_at, True)]
    page_size = 50

    form_excluded_columns = [
        DocumentOCRJob.job_id,
        DocumentOCRJob.output,
        DocumentOCRJob.raw_chunks,
        DocumentOCRJob.error,
        DocumentOCRJob.progress,
        DocumentOCRJob.started_at,
        DocumentOCRJob.completed_at,
    ]


class ImageOCRJobAdmin(ModelView, model=ImageOCRJob):
    name = "Image OCR Job"
    name_plural = "Image OCR Jobs"
    icon = "fa-solid fa-image"

    column_list = [
        ImageOCRJob.job_id,
        ImageOCRJob.image_type,
        ImageOCRJob.status,
        ImageOCRJob.admin_id,
        ImageOCRJob.created_at,
        ImageOCRJob.completed_at,
    ]
    column_searchable_list = [ImageOCRJob.job_id]
    column_sortable_list = [ImageOCRJob.created_at, ImageOCRJob.status, ImageOCRJob.image_type]
    column_default_sort = [(ImageOCRJob.created_at, True)]
    page_size = 50

    form_excluded_columns = [
        ImageOCRJob.job_id,
        ImageOCRJob.output,
        ImageOCRJob.raw_response,
        ImageOCRJob.error,
        ImageOCRJob.started_at,
        ImageOCRJob.completed_at,
    ]


# =========================================================
# SETUP
# =========================================================

def setup_admin(app) -> Admin:
    admin = Admin(
        app,
        engine,
        title="OCR Service Admin",
        base_url="/admin",
        authentication_backend=AdminAuth(
            secret_key=os.getenv("ADMIN_SECRET_KEY", "change-me-in-production"),
        ),
    )

    admin.add_view(EventAdmin)
    admin.add_view(VisitorAdmin)
    admin.add_view(OCRJobAdmin)
    admin.add_view(OpenAIUsageLogAdmin)
    admin.add_view(WorkflowRunAdmin)
    admin.add_view(DocumentOCRJobAdmin)
    admin.add_view(ImageOCRJobAdmin)
    admin.add_view(TemplateAdmin)
    admin.add_view(ExtractionAdmin)

    return admin
