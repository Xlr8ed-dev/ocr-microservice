"""Print the DB values of batch_kind and batch_status_v2."""

import asyncio
import asyncpg

from app.config import settings


async def main() -> None:
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            """
            SELECT t.typname, e.enumlabel
            FROM pg_type t
            JOIN pg_enum e ON t.oid = e.enumtypid
            WHERE t.typname IN ('batch_kind', 'batch_status_v2')
            ORDER BY t.typname, e.enumsortorder
            """
        )
        for r in rows:
            print(f"{r['typname']} → {r['enumlabel']}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())