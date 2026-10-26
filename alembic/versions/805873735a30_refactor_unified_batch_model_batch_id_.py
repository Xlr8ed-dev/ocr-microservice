"""refactor: unified batch model, batch_id FKs

Revision ID: 805873735a30
Revises: 4e4826e67b79
Create Date: 2026-10-26 16:09:50.952025

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "805873735a30"
down_revision: Union[str, Sequence[str], None] = "4e4826e67b79"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # =========================================================
    # Drop everything using raw SQL with CASCADE.
    # This drops tables AND their indexes AND their FK constraints
    # in one shot, without having to know exact index names.
    # =========================================================

    # Drop dependent tables first (foreign keys flow upward)
    op.execute("DROP TABLE IF EXISTS image_analyses CASCADE")
    op.execute("DROP TABLE IF EXISTS document_analyses CASCADE")
    op.execute("DROP TABLE IF EXISTS extractions CASCADE")
    op.execute("DROP TABLE IF EXISTS image_ocr_jobs CASCADE")
    op.execute("DROP TABLE IF EXISTS document_ocr_jobs CASCADE")
    op.execute("DROP TABLE IF EXISTS batches CASCADE")

    # Drop all related enum types
    for enum_name in [
        "batch_kind",
        "batch_status",
        "batch_status_v2",
        "extraction_ocr_job_type",
        "extraction_status",
        "document_ocr_status",
        "document_file_type",
        "image_ocr_status",
        "image_ocr_type",
        "analysis_status",
        "image_analysis_status",
    ]:
        op.execute(f"DROP TYPE IF EXISTS {enum_name} CASCADE")

    # =========================================================
    # Recreate in dependency order:
    #   1. batches (parent)
    #   2. document_ocr_jobs, image_ocr_jobs, extractions (children)
    #   3. document_analyses, image_analyses (grandchildren)
    # =========================================================

    # --- batches --------------------------------------------------
    op.create_table(
        "batches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("admin_id", sa.Integer, nullable=False),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column(
            "kind",
            sa.Enum("document", "image", "extraction", name="batch_kind"),
            nullable=False,
        ),
        sa.Column("template_id", sa.String(64), nullable=True),
        sa.Column("label", sa.Text, nullable=True),
        sa.Column("total_files", sa.Integer, nullable=False, server_default="0"),
        sa.Column("pending_files", sa.Integer, nullable=False, server_default="0"),
        sa.Column("in_progress_files", sa.Integer, nullable=False, server_default="0"),
        sa.Column("completed_files", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failed_files", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "processing", "completed",
                "partially_failed", "failed", "cancelled",
                name="batch_status_v2",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_index("ix_batches_admin_id", "batches", ["admin_id"])
    op.create_index("ix_batches_template_id", "batches", ["template_id"])
    op.create_index("ix_batches_kind", "batches", ["kind"])
    op.create_index("ix_batches_status", "batches", ["status"])
    op.create_index("ix_batches_created_at", "batches", ["created_at"])
    op.create_index("ix_batches_admin_created", "batches", ["admin_id", "created_at"])
    op.create_index("ix_batches_status_created", "batches", ["status", "created_at"])
    op.create_index("ix_batches_kind_created", "batches", ["kind", "created_at"])

    # --- document_ocr_jobs ----------------------------------------
    op.create_table(
        "document_ocr_jobs",
        sa.Column("id", sa.Integer, autoincrement=True, primary_key=True),
        sa.Column("job_id", sa.String(36), unique=True, nullable=False),
        sa.Column(
            "batch_id", sa.String(36),
            sa.ForeignKey("batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("admin_id", sa.Integer, nullable=False),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("source_url", sa.Text, nullable=False),
        sa.Column("file_name", sa.Text, nullable=True),
        sa.Column(
            "file_type",
            sa.Enum(
                "pdf_text", "pdf_scan", "docx", "txt",
                name="document_file_type",
            ),
            nullable=False,
        ),
        sa.Column("file_size_bytes", sa.Integer, nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "extracting", "structuring", "completed", "failed",
                name="document_ocr_status",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("progress", sa.Integer, nullable=False, server_default="0"),
        sa.Column("page_count", sa.Integer, nullable=True),
        sa.Column("chunk_count", sa.Integer, nullable=True),
        sa.Column("ai_calls", sa.Integer, nullable=False, server_default="0"),
        sa.Column("ai_tokens_in", sa.Integer, nullable=False, server_default="0"),
        sa.Column("ai_tokens_out", sa.Integer, nullable=False, server_default="0"),
        sa.Column("output", postgresql.JSONB, nullable=True),
        sa.Column("raw_chunks", postgresql.JSONB, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("cost_estimate", sa.Float, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_index("ix_document_ocr_jobs_job_id", "document_ocr_jobs", ["job_id"])
    op.create_index("ix_document_ocr_jobs_batch_id", "document_ocr_jobs", ["batch_id"])
    op.create_index("ix_document_ocr_jobs_admin_id", "document_ocr_jobs", ["admin_id"])
    op.create_index("ix_document_ocr_jobs_file_type", "document_ocr_jobs", ["file_type"])
    op.create_index("ix_document_ocr_jobs_status", "document_ocr_jobs", ["status"])
    op.create_index("ix_document_jobs_admin_created", "document_ocr_jobs", ["admin_id", "created_at"])
    op.create_index("ix_document_jobs_status_created", "document_ocr_jobs", ["status", "created_at"])

    # --- image_ocr_jobs -------------------------------------------
    op.create_table(
        "image_ocr_jobs",
        sa.Column("id", sa.Integer, autoincrement=True, primary_key=True),
        sa.Column("job_id", sa.String(36), unique=True, nullable=False),
        sa.Column(
            "batch_id", sa.String(36),
            sa.ForeignKey("batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("admin_id", sa.Integer, nullable=False),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("source_url", sa.Text, nullable=False),
        sa.Column(
            "image_type",
            sa.Enum(
                "invoice", "receipt", "visiting_card", "hotel_menu",
                "id_card", "handwritten", "generic",
                name="image_ocr_type",
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "processing", "completed", "failed",
                name="image_ocr_status",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("output", postgresql.JSONB, nullable=True),
        sa.Column("raw_response", postgresql.JSONB, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("cost_estimate", sa.Float, nullable=True),
        sa.Column("ai_calls", sa.Integer, nullable=False, server_default="0"),
        sa.Column("ai_tokens_in", sa.Integer, nullable=False, server_default="0"),
        sa.Column("ai_tokens_out", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_index("ix_image_ocr_jobs_job_id", "image_ocr_jobs", ["job_id"])
    op.create_index("ix_image_ocr_jobs_batch_id", "image_ocr_jobs", ["batch_id"])
    op.create_index("ix_image_ocr_jobs_admin_id", "image_ocr_jobs", ["admin_id"])
    op.create_index("ix_image_ocr_jobs_image_type", "image_ocr_jobs", ["image_type"])
    op.create_index("ix_image_ocr_jobs_status", "image_ocr_jobs", ["status"])
    op.create_index("ix_image_jobs_admin_created", "image_ocr_jobs", ["admin_id", "created_at"])
    op.create_index("ix_image_jobs_type_status", "image_ocr_jobs", ["image_type", "status"])

    # --- extractions ----------------------------------------------
    op.create_table(
        "extractions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "batch_id", sa.String(36),
            sa.ForeignKey("batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("admin_id", sa.Integer, nullable=False),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("template_id", sa.String(64), nullable=False),
        sa.Column("template_version", sa.String(16), nullable=False),
        sa.Column("file_name", sa.Text, nullable=False),
        sa.Column("file_url", sa.Text, nullable=False),
        sa.Column("file_type", sa.String(32), nullable=False),
        sa.Column("file_size_bytes", sa.Integer, nullable=True),
        sa.Column(
            "ocr_job_type",
            sa.Enum("document", "image", name="extraction_ocr_job_type"),
            nullable=False,
        ),
        sa.Column("ocr_job_id", sa.String(36), nullable=True),
        sa.Column("ocr_status", sa.String(32), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "ocr_running", "extracting", "completed",
                "needs_review", "blurry", "failed",
                name="extraction_status",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("result", postgresql.JSONB, nullable=True),
        sa.Column("min_confidence", sa.Float, nullable=True),
        sa.Column("review_needed", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("ai_calls", sa.Integer, nullable=False, server_default="0"),
        sa.Column("ai_tokens_in", sa.Integer, nullable=False, server_default="0"),
        sa.Column("ai_tokens_out", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cost_estimate", sa.Float, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_index("ix_extractions_batch_id", "extractions", ["batch_id"])
    op.create_index("ix_extractions_admin_id", "extractions", ["admin_id"])
    op.create_index("ix_extractions_template_id", "extractions", ["template_id"])
    op.create_index("ix_extractions_status", "extractions", ["status"])
    op.create_index("ix_extractions_created_at", "extractions", ["created_at"])
    op.create_index("ix_extractions_ocr_job_id", "extractions", ["ocr_job_id"])
    op.create_index("ix_extractions_review_needed", "extractions", ["review_needed"])
    op.create_index("ix_extractions_admin_created", "extractions", ["admin_id", "created_at"])
    op.create_index("ix_extractions_batch_created", "extractions", ["batch_id", "created_at"])
    op.create_index("ix_extractions_template_created", "extractions", ["template_id", "created_at"])
    op.create_index("ix_extractions_status_created", "extractions", ["status", "created_at"])

    # --- document_analyses ----------------------------------------
    op.create_table(
        "document_analyses",
        sa.Column("id", sa.Integer, autoincrement=True, primary_key=True),
        sa.Column("analysis_id", sa.String(36), unique=True, nullable=False),
        sa.Column(
            "job_id", sa.String(36),
            sa.ForeignKey("document_ocr_jobs.job_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("admin_id", sa.Integer, nullable=False),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("category", sa.String(64), nullable=True),
        sa.Column("subcategory", sa.String(64), nullable=True),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("tags", postgresql.JSONB, nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "processing", "completed", "failed",
                name="analysis_status",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("ai_calls", sa.Integer, nullable=False, server_default="0"),
        sa.Column("ai_tokens_in", sa.Integer, nullable=False, server_default="0"),
        sa.Column("ai_tokens_out", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cost_estimate", sa.Float, nullable=True),
        sa.Column("prompt_version", sa.String(32), nullable=False, server_default="v1"),
        sa.Column("categories_used", postgresql.JSONB, nullable=True),
        sa.Column("max_words_used", sa.Integer, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_document_analyses_analysis_id", "document_analyses", ["analysis_id"])
    op.create_index("ix_document_analyses_job_id", "document_analyses", ["job_id"])
    op.create_index("ix_document_analyses_admin_id", "document_analyses", ["admin_id"])
    op.create_index("ix_document_analyses_status", "document_analyses", ["status"])
    op.create_index("ix_doc_analyses_job_created", "document_analyses", ["job_id", "created_at"])
    op.create_index("ix_doc_analyses_admin_created", "document_analyses", ["admin_id", "created_at"])
    op.create_index("ix_doc_analyses_status_created", "document_analyses", ["status", "created_at"])

    # --- image_analyses -------------------------------------------
    op.create_table(
        "image_analyses",
        sa.Column("id", sa.Integer, autoincrement=True, primary_key=True),
        sa.Column("analysis_id", sa.String(36), unique=True, nullable=False),
        sa.Column(
            "job_id", sa.String(36),
            sa.ForeignKey("image_ocr_jobs.job_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("admin_id", sa.Integer, nullable=False),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("tags", postgresql.JSONB, nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "processing", "completed", "failed",
                name="image_analysis_status",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("ai_calls", sa.Integer, nullable=False, server_default="0"),
        sa.Column("ai_tokens_in", sa.Integer, nullable=False, server_default="0"),
        sa.Column("ai_tokens_out", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cost_estimate", sa.Float, nullable=True),
        sa.Column("prompt_version", sa.String(32), nullable=False, server_default="v1"),
        sa.Column("max_words_used", sa.Integer, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_image_analyses_analysis_id", "image_analyses", ["analysis_id"])
    op.create_index("ix_image_analyses_job_id", "image_analyses", ["job_id"])
    op.create_index("ix_image_analyses_admin_id", "image_analyses", ["admin_id"])
    op.create_index("ix_image_analyses_status", "image_analyses", ["status"])
    op.create_index("ix_img_analyses_job_created", "image_analyses", ["job_id", "created_at"])
    op.create_index("ix_img_analyses_admin_created", "image_analyses", ["admin_id", "created_at"])
    op.create_index("ix_img_analyses_status_created", "image_analyses", ["status", "created_at"])


def downgrade() -> None:
    raise NotImplementedError(
        "Refactor migration is one-way. Restore from backup if needed."
    )
