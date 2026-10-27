"""Batch model — unified across documents, images, and template extractions.

Every upload creates exactly one batch. Even a single-file upload goes
through a batch. This gives the FE a uniform contract: always get back
a batch_id, always poll GET /batch/{id}, always see per-file status.

The `kind` field discriminates which child table to look at when
computing per-file state:
  - "document"   → DocumentOCRJob (via batch_id)
  - "image"      → ImageOCRJob (via batch_id)
  - "extraction" → Extraction (via batch_id)
"""

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
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


# =========================================================
# ENUMS
# =========================================================

class BatchKind(str, Enum):
    DOCUMENT = "document"
    IMAGE = "image"
    EXTRACTION = "extraction"


class BatchStatus(str, Enum):
    PENDING = "pending"  # none of the files started yet
    PROCESSING = "processing"  # at least one file started, not all terminal
    COMPLETED = "completed"  # all files finished with success
    PARTIALLY_FAILED = "partially_failed"  # all finished, some succeeded some failed
    FAILED = "failed"  # all files failed
    CANCELLED = "cancelled"  # user cancelled remaining work


# =========================================================
# MODEL
# =========================================================

class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)

    # --- ownership ------------------------------------------------
    admin_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)

    # --- kind discriminator ---------------------------------------
    kind: Mapped[BatchKind] = mapped_column(
        SAEnum(
            BatchKind,
            name="batch_kind",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        index=True,
    )

    # --- template (only for kind='extraction') --------------------
    template_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True,
    )

    # --- optional user-supplied label for the batch --------------
    label: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- aggregate counters (maintained by worker on child change) -
    total_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pending_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    in_progress_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # --- status ---------------------------------------------------
    status: Mapped[BatchStatus] = mapped_column(
        SAEnum(
            BatchStatus,
            name="batch_status_v2",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        default=BatchStatus.PENDING,
        index=True,
    )

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
        Index("ix_batches_admin_created", "admin_id", "created_at"),
        Index("ix_batches_status_created", "status", "created_at"),
        Index("ix_batches_kind_created", "kind", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<Batch {self.id} kind={self.kind} "
            f"{self.completed_files}/{self.total_files}>"
        )
