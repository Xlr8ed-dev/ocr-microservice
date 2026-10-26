"""Extraction model.

One row per (file × template). A single upload can produce many extractions
(one per file). Extractions with the same batch_id were uploaded together.

The underlying OCR is delegated to DocumentOCRJob or ImageOCRJob — this
model references whichever one ran, so the OCR engine stays independent
of the product layer.
"""

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    Float,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


# =========================================================
# ENUMS
# =========================================================

class ExtractionStatus(str, Enum):
    PENDING = "pending"
    OCR_RUNNING = "ocr_running"
    EXTRACTING = "extracting"
    COMPLETED = "completed"
    NEEDS_REVIEW = "needs_review"
    BLURRY = "blurry"
    FAILED = "failed"


class ExtractionJobType(str, Enum):
    DOCUMENT = "document"
    IMAGE = "image"


# =========================================================
# MODEL
# =========================================================

class Extraction(Base):
    __tablename__ = "extractions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # UUID; the primary identifier the FE sees

    # --- batch (nullable for single-file uploads) -----------------
    batch_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True,
    )

    # --- ownership ------------------------------------------------
    admin_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)

    # --- template -------------------------------------------------
    template_id: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
    )
    template_version: Mapped[str] = mapped_column(
        String(16), nullable=False, default="v1",
    )

    # --- source file ----------------------------------------------
    file_name: Mapped[str] = mapped_column(Text, nullable=False)
    file_url: Mapped[str] = mapped_column(Text, nullable=False)
    file_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # "pdf" | "docx" | "txt" | "jpg" | "png" | ...
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- underlying OCR job ---------------------------------------
    ocr_job_type: Mapped[ExtractionJobType] = mapped_column(
        SAEnum(ExtractionJobType, name="extraction_ocr_job_type"),
        nullable=False,
    )
    ocr_job_id: Mapped[str] = mapped_column(String(36), nullable=True, index=True)
    # null until the worker dispatches the OCR job

    ocr_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # mirrors the underlying OCR job's status for quick reads

    # --- status ---------------------------------------------------
    status: Mapped[ExtractionStatus] = mapped_column(
        SAEnum(ExtractionStatus, name="extraction_status"),
        nullable=False,
        default=ExtractionStatus.PENDING,
        index=True,
    )

    # --- result ---------------------------------------------------
    # Shape:
    # {
    #   "full_name":      {"value": "Priya Nair", "confidence": 0.98},
    #   "email":          {"value": "priya@...",  "confidence": 0.95},
    #   "line_items":     {"value": [...],        "confidence": 0.82},
    # }
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    min_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_needed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True,
    )

    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- AI usage ------------------------------------------------
    ai_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ai_tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ai_tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- timestamps ----------------------------------------------
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
        index=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_extractions_admin_created", "admin_id", "created_at"),
        Index("ix_extractions_batch_created", "batch_id", "created_at"),
        Index("ix_extractions_template_created", "template_id", "created_at"),
        Index("ix_extractions_status_created", "status", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Extraction {self.id} {self.template_id} {self.status}>"
