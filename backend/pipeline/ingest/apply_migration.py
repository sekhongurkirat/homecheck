"""
pipeline/ingest/apply_migration.py
------------------------------------
Apply the mud_migration.sql DDL to the homecheck database.

Reads `mud_migration.sql` from the same directory and executes it via asyncpg.
Safe to run multiple times (all statements use IF NOT EXISTS).

Usage
-----
    python -m pipeline.ingest.apply_migration
    # or from run_ingest.sh:
    asyncio.run(run())
"""

from __future__ import annotations

import asyncio
import logging
import os
import pathlib

import asyncpg
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_MIGRATION_FILE = pathlib.Path(__file__).parent / "mud_migration.sql"


async def run() -> None:
    """
    Connect to the database and execute mud_migration.sql.

    DATABASE_URL env var is used for the connection string.
    Defaults to the Docker-internal DSN when not set.
    """
    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://homecheck:homecheck_secret@db:5432/homecheck",
    )
    dsn = db_url.replace("postgresql+asyncpg://", "postgresql://")

    sql = _MIGRATION_FILE.read_text(encoding="utf-8")

    logger.info("Applying migration: %s", _MIGRATION_FILE.name)
    conn: asyncpg.Connection = await asyncpg.connect(dsn)
    try:
        async with conn.transaction():
            await conn.execute(sql)
        logger.info("Migration applied successfully.")
    except Exception as exc:
        logger.error("Migration failed: %s", exc)
        raise
    finally:
        await conn.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )
    asyncio.run(run())
