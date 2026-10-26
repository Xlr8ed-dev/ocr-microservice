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


class WorkflowStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"     # some steps succeeded, some failed
    FAILED = "failed"


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    txn_id: Mapped[str] = mapped_column(String(100), index=True)
    admin_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int] = mapped_column(Integer)

    flow_name: Mapped[str] = mapped_column(String(100), nullable=False)

    # steps shape:
    #   {
    #     "ocr":            {"status": "...", "result": {...}, "error": null},
    #     "whatsapp":       {"status": "...", "result": {...}},
    #     "email_generate": {...},
    #     "email_send":     {...}
    #   }
    steps: Mapped[dict] = mapped_column(JSONB, default=dict)

    status: Mapped[WorkflowStatus] = mapped_column(
        SAEnum(WorkflowStatus, name="workflow_status"),
        default=WorkflowStatus.PENDING,
        index=True,
    )
    current_step: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    __table_args__ = (
        Index("ix_workflow_runs_status_created", "status", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<WorkflowRun {self.run_id} {self.flow_name} {self.status}>"