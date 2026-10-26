from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class StatusResponse(BaseModel):
    status: str = "success"
    message: str | None = None


class ErrorResponse(BaseModel):
    status: str = "error"
    errors: str | dict | list | None = None
    message: str | None = None


class PaginationMeta(BaseModel):
    total_entries: int
    page: int
    items: int
    total_pages: int
    has_next: bool
    has_previous: bool


class PaginatedResponse(BaseModel, Generic[T]):
    status: str = "success"
    data: list[T]
    pagination: PaginationMeta
    message: str | None = None