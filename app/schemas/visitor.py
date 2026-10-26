from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


# =========================================================
# CARD INPUT / OUTPUT SHAPES
# =========================================================

class VisitingCardPrimary(BaseModel):
    front: str | None = None
    back: str | None = None


class VisitingCardSecondary(BaseModel):
    id: int | None = None
    front: str | None = None
    back: str | None = None


class VisitingCardInput(BaseModel):
    primary: VisitingCardPrimary = Field(default_factory=VisitingCardPrimary)
    secondary: list[VisitingCardSecondary] = Field(default_factory=list)


class VisitingCardOut(BaseModel):
    """Matches monolith `get_visiting_card` output."""
    primary: VisitingCardPrimary = Field(default_factory=VisitingCardPrimary)
    secondary: list[VisitingCardSecondary] = Field(default_factory=list)


# =========================================================
# FLOW OPTIONS (client picks flow in request body)
# =========================================================

class FlowOptions(BaseModel):
    name: str = "ocr_only"        # ocr_only | visitor_quick_scan | visitor_full
    send_whatsapp: bool = False
    send_email: bool = False
    email_template_id: int | None = None
    email_sender: str | None = None


# =========================================================
# CREATE / UPDATE
# =========================================================

class VisitorCreate(BaseModel):
    txn_Id: str = Field(..., min_length=1, max_length=100)
    event_id: int
    agent_id: int | None = None

    # basic
    name: str = Field(default="", max_length=255)
    company_name: str | None = Field(default=None, max_length=255)
    phone: str = Field(default="")
    visitor_email: str | None = None
    image: str | None = None

    # meeting
    interest: int | None = Field(default=None, ge=0, le=5)
    date: str | None = None
    meet_time: str | None = None
    created_at: str | None = None      # mobile-supplied ISO string

    # extras
    visitor_address: str | None = None
    visitor_designation: str | None = None
    visitor_websites: str | None = None
    visitor_category: str | None = None

    # user-entered
    products: str | None = None
    notes: list[str] = Field(default_factory=list)
    voice_notes: list[str] = Field(default_factory=list)

    # card urls
    visiting_card: VisitingCardInput = Field(default_factory=VisitingCardInput)

    # workflow choice
    flow: FlowOptions | None = None

    @field_validator("visiting_card")
    @classmethod
    def _require_at_least_one_image(cls, v: VisitingCardInput) -> VisitingCardInput:
        has_primary = bool(v.primary.front or v.primary.back)
        has_secondary = any(c.front or c.back for c in v.secondary)
        if not has_primary and not has_secondary:
            raise ValueError(
                "At least one card image (primary front/back or secondary) is required"
            )
        return v


class VisitorUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    company_name: str | None = Field(default=None, max_length=255)
    phone: str | None = None
    visitor_email: str | None = None
    image: str | None = None

    interest: int | None = Field(default=None, ge=0, le=5)
    date: str | None = None
    meet_time: str | None = None

    visitor_address: str | None = None
    visitor_designation: str | None = None
    visitor_websites: str | None = None
    visitor_category: str | None = None

    products: str | None = None
    notes: list[str] | None = None
    voice_notes: list[str] | None = None

    is_stopped: bool | None = None


# =========================================================
# RESPONSE SHAPES
# =========================================================

class AddressOut(BaseModel):
    id: int
    address: str = ""
    state: str = ""
    country: str = ""


class SecondaryOCROut(BaseModel):
    id: str
    name: str = ""
    designation: str = ""
    company: str = ""
    emails: str = ""
    phones: str = ""
    address: str = ""
    websites: str = ""


class EventInfo(BaseModel):
    event_name: str
    start_date: str | None = None
    end_date: str | None = None
    venue: str | None = None


class EventDetails(BaseModel):
    event: EventInfo | None = None
    related_event_map: list[EventInfo] = Field(default_factory=list)
    message: str | None = None


class VisitorOut(BaseModel):
    """Matches monolith `VisitorSerializer` shape 1:1."""

    model_config = ConfigDict(from_attributes=True)

    txn_Id: str
    name: str
    company_name: str | None = None
    phone: str
    visitor_email: str | None = None
    image: str | None = None

    interest: int | None = None
    date: str | None = None
    meet_time: str | None = None
    created_at: str | None = None
    sync_at: datetime
    sync_updated_at: datetime | None = None

    # ownership (new for microservices, populated by service layer)
    admin_id: int
    agent_id: int | None = None
    agent_name: str | None = None
    admin_company_name: str | None = None

    # event
    event: int
    event_details: list[EventDetails] = Field(default_factory=list)

    # extras
    visitor_address: list[AddressOut] | str | None = None
    visitor_designation: str | None = None
    visitor_websites: str | None = None
    visitor_category: str | None = None

    # cards + OCR
    visiting_card: VisitingCardOut = Field(default_factory=VisitingCardOut)
    visiting_card_secondary_ocr: list[SecondaryOCROut] = Field(default_factory=list)

    # free-form
    products: str | None = None
    notes: list[str] = Field(default_factory=list)
    voice_notes: list[str] = Field(default_factory=list)
    notes_summarize: str | None = None

    # duplicate flags
    is_duplicate: bool = False
    duplicate_of: str | None = None
    related_event_ids: list[int] = Field(default_factory=list)

    # suppression
    is_stopped: bool = False
    is_stopped_at: datetime | None = None

    # ocr state
    ocr_status: bool = False


class VisitorListOut(BaseModel):
    """Lighter shape for list endpoints (no nested OCR blobs)."""

    model_config = ConfigDict(from_attributes=True)

    txn_Id: str
    name: str
    company_name: str | None = None
    phone: str
    visitor_email: str | None = None
    admin_id: int
    agent_id: int | None = None
    agent_name: str | None = None
    event_name: str
    interest: int | None = None
    is_duplicate: bool = False
    duplicate_of: str | None = None
    ocr_status: bool = False
    sync_at: datetime
    deleted_at: datetime | None = None


class VisitorAccepted(BaseModel):
    """202 response when a visitor + OCR job are queued."""

    status: str = "success"
    txn_Id: str
    ocr_status: str                           # pending | ready | failed
    workflow_run_id: str | None = None
    message: str | None = None


class DuplicateInfo(BaseModel):
    is_duplicate: bool
    duplicate_of: str | None = None
    related_txn_ids: list[str] = Field(default_factory=list)