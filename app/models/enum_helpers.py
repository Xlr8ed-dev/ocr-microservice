"""Shared helpers for SQLAlchemy Enum columns.

SQLAlchemy's Enum() by default sends the Python enum's `.name` to the
database (e.g., `TXT`), not its `.value` (e.g., `txt`). For enums
where those differ, this causes "invalid input value" errors at insert
time.

We always want to send `.value` because:
  - `.value` is what the API returns to the FE
  - `.value` is what the migration created in the DB
  - `.value` is what's in the seed data

`values_callable=_enum_values` fixes this everywhere consistently.
"""

from enum import Enum


def _enum_values(enum_cls: type[Enum]) -> list[str]:
    """SQLAlchemy `values_callable` — sends `.value` to the DB."""
    return [e.value for e in enum_cls]