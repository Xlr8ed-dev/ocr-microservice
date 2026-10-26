"""Schemas for the template catalog.

The FE reads these to render:
  - The Templates library screen (list + categories)
  - The Template overview modal (detail with fields)
  - The upload dropdown (which template to use)
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# =========================================================
# FIELD SCHEMA (as stored in Template.fields)
# =========================================================

class TemplateField(BaseModel):
    key: str = Field(..., description="Machine-readable field identifier, e.g. 'full_name'")
    label: str = Field(..., description="Human-readable label, e.g. 'Full name'")
    type: str = Field(
        ...,
        description="string | email | phone | date | number | list | object | table",
    )
    required: bool = False
    description: str | None = Field(
        default=None,
        description="Hint for the AI about what to extract into this field",
    )


# =========================================================
# LIST ITEM (lightweight — used in GET /templates)
# =========================================================

class TemplateListItem(BaseModel):
    """List item for the Templates library screen.

    Includes `field_count` (a cheap summary) but not the full field list,
    because the FE only renders the field list in the detail modal.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    category: str
    description: str
    field_count: int
    sample_doc_url: str | None = None


# =========================================================
# DETAIL (full — used in GET /templates/{id})
# =========================================================

class TemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    category: str
    description: str
    fields: list[TemplateField]
    sample_doc_url: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


# =========================================================
# CATEGORY TABS (used in GET /templates/categories)
# =========================================================

class TemplateCategoryOut(BaseModel):
    key: str
    label: str
    count: int


class TemplateCategoryListOut(BaseModel):
    status: str = "success"
    data: list[TemplateCategoryOut]