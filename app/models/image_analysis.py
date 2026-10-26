"""Image analysis: summary + tags on demand.

Same structure as DocumentAnalysis but no classification fields — the
image_type already tells us what the image is.
"""

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


class ImageAnalysisStatus(str, Enum):
    PENDING    = "pending"
    PROCESSING = "processing"
    COMPLETED  = "completed"
    FAILED     = "failed"


class ImageAnalysis(Base):
    __tablename__ = "image_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analysis_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)

    # --- parent job -----------------------------------------------
    job_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("image_ocr_jobs.job_id", ondelete="CASCADE"),
        index=True,
    )

    # --- ownership ------------------------------------------------
    admin_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int] = mapped_column(Integer)

    # --- result ---------------------------------------------------
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # --- execution ------------------------------------------------
    status: Mapped[ImageAnalysisStatus] = mapped_column(
        SAEnum(ImageAnalysisStatus, name="image_analysis_status"),
        default=ImageAnalysisStatus.PENDING,
        index=True,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- AI usage ------------------------------------------------
    ai_calls: Mapped[int] = mapped_column(Integer, default=0)
    ai_tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    ai_tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_estimate: Mapped[float | None] = mapped_column(nullable=True)

    # --- config ---------------------------------------------------
    prompt_version: Mapped[str] = mapped_column(String(32), default="v1")
    max_words_used: Mapped[int | None] = mapped_column(Integer, nullable=True)

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

    __table_args__ = (
        Index("ix_img_analyses_job_created", "job_id", "created_at"),
        Index("ix_img_analyses_admin_created", "admin_id", "created_at"),
        Index("ix_img_analyses_status_created", "status", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<ImageAnalysis {self.analysis_id} job={self.job_id} {self.status}>"