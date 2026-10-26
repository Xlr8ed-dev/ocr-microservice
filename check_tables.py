"""Quick DB table check.

Run:  python check_tables.py

Connects using the same settings the app uses, lists every table in the
public schema, and prints them sorted alphabetically.
"""

import asyncio

import asyncpg

from app.config import settings


async def main() -> None:
    # Build a plain asyncpg connection URL from settings.
    # settings.database_url is "postgresql+asyncpg://..." — strip the
    # SQLAlchemy driver prefix so asyncpg can parse it.
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")

    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            """
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'public'
            ORDER BY tablename
            """
        )
    finally:
        await conn.close()

    if not rows:
        print("(no tables found in public schema)")
        return

    for r in rows:
        print(r["tablename"])


if __name__ == "__main__":
    asyncio.run(main())