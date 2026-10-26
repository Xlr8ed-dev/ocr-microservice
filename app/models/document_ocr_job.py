from datetime import datetime
from enum import Enum

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
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

class DocumentFileType(str, Enum):
    PDF_TEXT = "pdf_text"  # PDF with a selectable text layer
    PDF_SCAN = "pdf_scan"  # PDF that is a stack of page images
    DOCX = "docx"
    # DOC = "doc"  # legacy .doc
    TXT = "txt"


class DocumentOCRStatus(str, Enum):
    PENDING = "pending"
    EXTRACTING = "extracting"  # downloading + text extraction + heading detection
    STRUCTURING = "structuring"  # AI chunk processing
    COMPLETED = "completed"
    FAILED = "failed"


# =========================================================
# MODEL
# =========================================================

class DocumentOCRJob(Base):
    __tablename__ = "document_ocr_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # --- identity -------------------------------------------------
    job_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)

    admin_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int] = mapped_column(Integer)

    # --- input ----------------------------------------------------
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    file_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_type: Mapped[DocumentFileType] = mapped_column(
        SAEnum(DocumentFileType, name="document_file_type"),
        nullable=False,
        index=True,
    )
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- processing state ----------------------------------------
    status: Mapped[DocumentOCRStatus] = mapped_column(
        SAEnum(DocumentOCRStatus, name="document_ocr_status"),
        default=DocumentOCRStatus.PENDING,
        index=True,
    )
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0..100

    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_calls: Mapped[int] = mapped_column(Integer, default=0)
    ai_tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    ai_tokens_out: Mapped[int] = mapped_column(Integer, default=0)

    # --- output ---------------------------------------------------
    # Shape: { title, blocks: [...], metadata: {...} }
    output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Raw AI responses per chunk, for debugging. Prune after N days.
    raw_chunks: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- cost (for future billing at ₹1/page) ---------------------
    cost_estimate: Mapped[float | None] = mapped_column(nullable=True)

    # --- timestamps ----------------------------------------------
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
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
        Index("ix_document_jobs_admin_created", "admin_id", "created_at"),
        Index("ix_document_jobs_status_created", "status", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<DocumentOCRJob {self.job_id} {self.file_type} {self.status}>"
