from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
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


class Visitor(Base):
    __tablename__ = "visitors"

    # --- identity -------------------------------------------------
    txn_Id: Mapped[str] = mapped_column(
        String(100), primary_key=True,
    )

    # --- ownership ------------------------------------------------
    admin_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    agent_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_by_user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by_role: Mapped[str] = mapped_column(String(20), nullable=False)

    # --- event ----------------------------------------------------
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_name: Mapped[str] = mapped_column(String(255), nullable=False)
    admin_company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # --- core identity -------------------------------------------
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str] = mapped_column(Text, nullable=False, default="")
    visitor_email: Mapped[str | None] = mapped_column(Text, nullable=True)
    image: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- meeting context -----------------------------------------
    interest: Mapped[int | None] = mapped_column(Integer, nullable=True)
    date: Mapped[str | None] = mapped_column(Text, nullable=True)
    meet_time: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- meta / sync ---------------------------------------------
    created_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    sync_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    sync_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True,
    )

    # --- card files (URLs) ---------------------------------------
    visiting_card_primary: Mapped[list | None] = mapped_column(
        JSONB, nullable=True, default=list,
    )
    visiting_card_secondary: Mapped[list | None] = mapped_column(
        JSONB, nullable=True, default=list,
    )

    # --- user-entered extras -------------------------------------
    products: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=list)
    voice_notes: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=list)

    # --- OCR outputs ---------------------------------------------
    visiting_card_primary_ocr: Mapped[str | None] = mapped_column(Text, nullable=True)
    visiting_card_secondary_ocr: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_status: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True,
    )

    # --- AI outputs (summaries, STT) -----------------------------
    notes_summarize: Mapped[str | None] = mapped_column(Text, nullable=True)
    email_notes_summarize: Mapped[str | None] = mapped_column(Text, nullable=True)
    voice_notes_to_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- extra OCR-derived fields --------------------------------
    visitor_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    visitor_designation: Mapped[str | None] = mapped_column(Text, nullable=True)
    visitor_websites: Mapped[str | None] = mapped_column(Text, nullable=True)
    visitor_category: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- duplicate flags -----------------------------------------
    is_duplicate: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True,
    )
    duplicate_of: Mapped[str | None] = mapped_column(String(100), nullable=True)
    related_event_ids: Mapped[list | None] = mapped_column(
        JSONB, nullable=True, default=list,
    )

    # --- suppression ---------------------------------------------
    is_stopped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_stopped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    __table_args__ = (
        Index("ix_visitors_admin_sync", "admin_id", "sync_at"),
        Index("ix_visitors_agent_sync", "agent_id", "sync_at"),
        Index("ix_visitors_event_sync", "event_id", "sync_at"),
    )

    def __repr__(self) -> str:
        return f"<Visitor {self.txn_Id} {self.name}>"