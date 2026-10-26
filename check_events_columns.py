import asyncio
from sqlalchemy import text
from app.database import AsyncSessionLocal


async def main() -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            text(
                "SELECT column_name, data_type "
                "FROM information_schema.columns "
                "WHERE table_name = 'events' "
                "ORDER BY ordinal_position"
            )
        )
        for row in result:
            print(f"{row[0]:30s} {row[1]}")


if __name__ == "__main__":
    asyncio.run(main())
