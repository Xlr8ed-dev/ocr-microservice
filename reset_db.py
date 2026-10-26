import asyncio
import asyncpg


async def main() -> None:
    conn = await asyncpg.connect("postgresql://postgres:12345@localhost:5432/postgres")
    # Kick everyone off the target DB so DROP can proceed
    await conn.execute(
        """
        SELECT pg_terminate_backend(pg_stat_activity.pid)
        FROM pg_stat_activity
        WHERE pg_stat_activity.datname = 'ocr-service-local'
          AND pid <> pg_backend_pid()
        """
    )
    await conn.execute('DROP DATABASE IF EXISTS "ocr-service-local"')
    await conn.execute('CREATE DATABASE "ocr-service-local"')
    await conn.close()
    print("done")


if __name__ == "__main__":
    asyncio.run(main())