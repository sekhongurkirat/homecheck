"""
routes/report.py
----------------
Report generation endpoint and priority metadata endpoint.
"""

from __future__ import annotations

import asyncio
import logging

import databases
from fastapi import APIRouter, Depends, HTTPException

from database import get_db
from models import (
    DEFAULT_THRESHOLDS,
    HazardFlag,
    Priority,
    ReportRequest,
    ReportResponse,
)
from services.development_query import query_development
from services.flood_query import query_flood_zone
from services.geocoder import geocode
from services.hazard_query import query_hazards

logger = logging.getLogger(__name__)

router = APIRouter(tags=["report"])

# Labels shown to end users
PRIORITY_LABELS: dict[str, str] = {
    Priority.highway: "Highways & Major Roads",
    Priority.rail: "Rail Lines",
    Priority.industrial: "Industrial Facilities",
    Priority.meat_processing: "Meat Processing Plants",
    Priority.landfill: "Landfills & Transfer Stations",
    Priority.airport: "Airports & Airstrips",
}


@router.post("/report", response_model=ReportResponse)
async def create_report(
    req: ReportRequest,
    db: databases.Database = Depends(get_db),
) -> ReportResponse:
    """
    Generate a full hazard report for the given address.

    Steps:
    1. Geocode the address via Nominatim.
    2. Run hazard proximity query and flood zone lookup in parallel.
    3. Return the combined ReportResponse.
    """
    # ── 1. Geocode ────────────────────────────────────────────────────────────
    lat, lng = await geocode(req.address)

    # Build effective priorities & thresholds (merge defaults with user overrides)
    priorities = [p.value if hasattr(p, "value") else p for p in (req.priorities or list(Priority))]
    thresholds: dict[str, int] = {
        p.value if hasattr(p, "value") else p: DEFAULT_THRESHOLDS.get(p, 500)
        for p in Priority
    }
    # Apply user-supplied overrides
    for k, v in (req.thresholds or {}).items():
        key = k.value if hasattr(k, "value") else k
        thresholds[key] = v

    # ── 2. Parallel queries ───────────────────────────────────────────────────
    hazards_task = query_hazards(db, lat, lng, priorities, thresholds)
    flood_task = query_flood_zone(db, lat, lng)
    development_task = query_development(db, lat, lng, radius_m=3000)

    flags, flood_zone, development = await asyncio.gather(
        hazards_task, flood_task, development_task
    )

    logger.info(
        "Report for %r: %d flags, flood_zone=%s, %d development features",
        req.address,
        len(flags),
        flood_zone.zone_code if flood_zone else "N/A",
        len(development),
    )

    return ReportResponse(
        address=req.address,
        lat=lat,
        lng=lng,
        flags=flags,
        flood_zone=flood_zone,
        school=None,  # School lookup not yet implemented
        development=development,
    )


@router.get("/report/priorities")
async def list_priorities() -> list[dict]:
    """
    Return available priority categories with labels and default thresholds.
    """
    return [
        {
            "value": p.value,
            "label": PRIORITY_LABELS[p],
            "default_threshold_m": DEFAULT_THRESHOLDS[p],
        }
        for p in Priority
    ]
