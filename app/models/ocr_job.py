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
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class JobType(str, Enum):
    OCR_PRIMARY = "ocr_primary"
    OCR_SECONDARY = "ocr_secondary"


class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class WebhookStatus(str, Enum):
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"
    NOT_REQUIRED = "not_required"


class OCRJob(Base):
    __tablename__ = "ocr_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    txn_id: Mapped[str] = mapped_column(String(100), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(150), unique=True)

    admin_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int] = mapped_column(Integer)

    job_type: Mapped[JobType] = mapped_column(
        SAEnum(JobType, name="ocr_job_type"), index=True,
    )

    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    callback_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[JobStatus] = mapped_column(
        SAEnum(JobStatus, name="ocr_job_status"),
        default=JobStatus.PENDING,
        index=True,
    )
    celery_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)

    webhook_status: Mapped[WebhookStatus] = mapped_column(
        SAEnum(WebhookStatus, name="ocr_webhook_status"),
        default=WebhookStatus.PENDING,
    )
    webhook_attempts: Mapped[int] = mapped_column(Integer, default=0)
    webhook_last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
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
    )

    usage_logs: Mapped[list["OpenAIUsageLog"]] = relationship(
        back_populates="job", cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("txn_id", "job_type", name="uq_ocr_job_txn_type"),
        Index("ix_ocr_jobs_status_created", "status", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<OCRJob {self.job_id} {self.txn_id} {self.job_type} {self.status}>"


class OpenAIUsageLog(Base):
    __tablename__ = "openai_usage_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("ocr_jobs.job_id", ondelete="CASCADE"),
        index=True,
    )
    txn_id: Mapped[str] = mapped_column(String(100), index=True)
    admin_id: Mapped[int] = mapped_column(Integer, index=True)

    task_name: Mapped[str] = mapped_column(String(100))
    api_call_type: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(64))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    job: Mapped[OCRJob] = relationship(back_populates="usage_logs")