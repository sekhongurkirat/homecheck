import asyncio
import logging
import os

import databases
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DATABASE_URL: str = os.environ["DATABASE_URL"]

# Use the `databases` async wrapper around asyncpg.
database = databases.Database(DATABASE_URL)


async def connect() -> None:
    """Connect to the database with retries for container startup timing."""
    for attempt in range(1, 11):
        try:
            await database.connect()
            logger.info("databases: connected to %s", DATABASE_URL.split("@")[-1])
            return
        except Exception as exc:
            logger.warning("DB connect attempt %d/10 failed: %s", attempt, exc)
            if attempt == 10:
                raise
            await asyncio.sleep(attempt * 2)  # 2s, 4s, 6s … back-off


async def disconnect() -> None:
    """Disconnect from the database. Called during application shutdown."""
    await database.disconnect()
    logger.info("databases: disconnected.")


async def get_db() -> databases.Database:
    """
    FastAPI dependency that yields the shared database connection.

    Usage::

        @router.get("/example")
        async def example(db: databases.Database = Depends(get_db)):
            rows = await db.fetch_all("SELECT 1")
    """
    return database
