from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class EventCreate(BaseModel):
    event_name: str = Field(..., min_length=1, max_length=255)
    start_date: date | None = None
    end_date: date | None = None
    venue: str | None = Field(default=None, max_length=255)
    campaign_id: str | None = Field(default=None, max_length=64)


class EventUpdate(BaseModel):
    event_name: str | None = Field(default=None, min_length=1, max_length=255)
    start_date: date | None = None
    end_date: date | None = None
    venue: str | None = Field(default=None, max_length=255)
    campaign_id: str | None = Field(default=None, max_length=64)


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_name: str
    start_date: date | None = None
    end_date: date | None = None
    venue: str | None = None
    admin_id: int
    campaign_id: str | None = None
    created_at: datetime
    updated_at: datetime
