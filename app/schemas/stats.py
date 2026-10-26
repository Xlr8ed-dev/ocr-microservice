"""Schemas for the stats/overview endpoint.

Feeds the Home screen: "182 items extracted", plus template usage counts
and status counts for the sidebar badge.
"""

from pydantic import BaseModel, Field


class TemplateUsageItem(BaseModel):
    template_id: str
    template_name: str
    category: str
    count: int


class StatusCountItem(BaseModel):
    status: str
    count: int


class StatsOverviewOut(BaseModel):
    # Headline numbers
    total_extractions: int = Field(
        ..., description="Total extractions for this user's scope",
    )
    total_this_month: int = Field(
        ..., description="Total extractions in the current calendar month",
    )
    needs_review_count: int = Field(
        ..., description="Extractions with review_needed=true",
    )
    failed_count: int = Field(
        ..., description="Extractions in status=failed",
    )
    in_progress_count: int = Field(
        ..., description="Extractions in pending/ocr_running/extracting",
    )

    # Breakdowns
    by_status: list[StatusCountItem]
    by_template: list[TemplateUsageItem] = Field(
        ..., description="Top templates by usage (up to 10)",
    )


class NeedsReviewCountOut(BaseModel):
    count: int = Field(
        ..., description="Number of extractions with review_needed=true",
    )
