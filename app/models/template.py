"""Template model.

A template is a structured field schema. The AI uses the fields when
extracting data from a document or image. Templates are seed-only in v1.

Field schema format:
    {
        "key": "full_name",
        "label": "Full name",
        "type": "string",       # string | email | phone | date | number
                                # | list | object | table
        "required": true,
        "description": "The person's name as printed"
    }
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Template(Base):
    __tablename__ = "templates"

    # --- identity -------------------------------------------------
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Human-friendly slug, e.g. "resume_screener"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # --- field schema ---------------------------------------------
    fields: Mapped[list] = mapped_column(JSONB, nullable=False)

    # --- extras ---------------------------------------------------
    sample_doc_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # --- meta -----------------------------------------------------
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_templates_category_active", "category", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<Template {self.id} {self.name}>"