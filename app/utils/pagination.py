from dataclasses import dataclass
from math import ceil

from app.schemas.common import PaginationMeta


DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


@dataclass(frozen=True)
class Page:
    page: int
    items: int
    offset: int
    limit: int


def parse_page(page: int = 1, items: int = DEFAULT_PAGE_SIZE) -> Page:
    page = max(1, page)
    items = max(1, min(items, MAX_PAGE_SIZE))
    return Page(
        page=page,
        items=items,
        offset=(page - 1) * items,
        limit=items,
    )


def build_meta(total: int, page: Page) -> PaginationMeta:
    total_pages = ceil(total / page.items) if total > 0 else 0
    return PaginationMeta(
        total_entries=total,
        page=page.page,
        items=page.items,
        total_pages=total_pages,
        has_next=page.page < total_pages,
        has_previous=page.page > 1,
    )