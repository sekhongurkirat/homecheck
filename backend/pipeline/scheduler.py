"""
pipeline/scheduler.py
---------------------
Simple asyncio-based scheduler for data pipeline jobs.

Schedule
--------
- OSM ingest     : monthly
- EPA TRI ingest : monthly
- USDA FSIS ingest: quarterly (every 3 months)

Run via:
    python -m pipeline.scheduler
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from pipeline.ingest import osm_ingest, epa_tri_ingest, usda_fsis_ingest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("pipeline.scheduler")

# Job intervals
MONTHLY_SECONDS = 30 * 24 * 60 * 60       # ~30 days
QUARTERLY_SECONDS = 90 * 24 * 60 * 60     # ~90 days


async def _run_job(name: str, coro_factory) -> None:
    """Execute a coroutine job with timing and exception logging."""
    logger.info("=== JOB START: %s ===", name)
    start = datetime.utcnow()
    try:
        await coro_factory()
        elapsed = (datetime.utcnow() - start).total_seconds()
        logger.info("=== JOB DONE:  %s (%.1fs) ===", name, elapsed)
    except Exception:
        elapsed = (datetime.utcnow() - start).total_seconds()
        logger.exception("=== JOB FAILED: %s (%.1fs) ===", name, elapsed)


async def _loop_monthly(name: str, coro_factory) -> None:
    """Run *coro_factory* once immediately, then every MONTHLY_SECONDS."""
    while True:
        await _run_job(name, coro_factory)
        next_run = datetime.utcnow() + timedelta(seconds=MONTHLY_SECONDS)
        logger.info("[%s] Next run scheduled at %s", name, next_run.isoformat())
        await asyncio.sleep(MONTHLY_SECONDS)


async def _loop_quarterly(name: str, coro_factory) -> None:
    """Run *coro_factory* once immediately, then every QUARTERLY_SECONDS."""
    while True:
        await _run_job(name, coro_factory)
        next_run = datetime.utcnow() + timedelta(seconds=QUARTERLY_SECONDS)
        logger.info("[%s] Next run scheduled at %s", name, next_run.isoformat())
        await asyncio.sleep(QUARTERLY_SECONDS)


async def main() -> None:
    logger.info("HomeCheck pipeline scheduler starting …")
    logger.info(
        "Schedule: OSM=monthly, EPA TRI=monthly, USDA FSIS=quarterly"
    )

    # Stagger initial runs by a few minutes so they don't all slam resources at once.
    async def osm():
        # Austin TX
        await osm_ingest.run("30.098,-97.938,30.516,-97.474")
        # Atlanta GA
        await osm_ingest.run("33.55,-84.65,34.05,-84.15")

    async def epa():
        await asyncio.sleep(5 * 60)   # start 5 min after OSM
        await epa_tri_ingest.run()

    async def fsis():
        await asyncio.sleep(10 * 60)  # start 10 min after OSM
        await usda_fsis_ingest.run()

    await asyncio.gather(
        _loop_monthly("osm_ingest", osm),
        _loop_monthly("epa_tri_ingest", epa),
        _loop_quarterly("usda_fsis_ingest", fsis),
    )


if __name__ == "__main__":
    asyncio.run(main())
