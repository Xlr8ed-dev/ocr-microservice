from datetime import datetime
from enum import Enum

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.enum_helpers import _enum_values


class ImageOCRType(str, Enum):
    INVOICE = "invoice"
    RECEIPT = "receipt"
    VISITING_CARD = "visiting_card"
    HOTEL_MENU = "hotel_menu"
    ID_CARD = "id_card"
    HANDWRITTEN = "handwritten"
    GENERIC = "generic"


class ImageOCRStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ImageOCRJob(Base):
    __tablename__ = "image_ocr_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    batch_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    admin_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int] = mapped_column(Integer)

    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    image_type: Mapped[ImageOCRType] = mapped_column(
        SAEnum(
            ImageOCRType,
            name="image_ocr_type",
            values_callable=_enum_values,
        ),
        nullable=False,
        index=True,
    )

    status: Mapped[ImageOCRStatus] = mapped_column(
        SAEnum(
            ImageOCRStatus,
            name="image_ocr_status",
            values_callable=_enum_values,
        ),
        default=ImageOCRStatus.PENDING,
        index=True,
    )

    output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    raw_response: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_estimate: Mapped[float | None] = mapped_column(nullable=True)

    ai_calls: Mapped[int] = mapped_column(Integer, default=0)
    ai_tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    ai_tokens_out: Mapped[int] = mapped_column(Integer, default=0)

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
        Index("ix_image_jobs_admin_created", "admin_id", "created_at"),
        Index("ix_image_jobs_type_status", "image_type", "status"),
    )

    def __repr__(self) -> str:
        return f"<ImageOCRJob {self.job_id} {self.image_type} {self.status}>"
