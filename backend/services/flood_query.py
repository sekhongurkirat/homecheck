"""
flood_query.py
--------------
PostGIS point-in-polygon query for FEMA flood zone data.
"""

from __future__ import annotations

import logging

import databases

from models import FloodZone

logger = logging.getLogger(__name__)

# Human-readable labels for FEMA flood zone codes
FLOOD_ZONE_LABELS: dict[str, str] = {
    "A":   "100-year flood zone (no BFE determined)",
    "AE":  "100-year flood zone (BFE determined)",
    "AH":  "100-year shallow flooding (ponding)",
    "AO":  "100-year shallow flooding (sheet flow)",
    "AR":  "Special flood hazard area — levee being restored",
    "A99": "100-year flood zone — federal project under construction",
    "VE":  "Coastal 100-year flood zone with wave action",
    "V":   "Coastal 100-year flood zone (no BFE)",
    "X":   "Outside 100-year floodplain (minimal risk)",
    "D":   "Possible but undetermined flood hazard",
}


async def query_flood_zone(
    db: databases.Database,
    lat: float,
    lng: float,
) -> FloodZone | None:
    """
    Determine whether (lat, lng) falls inside a mapped FEMA flood zone.

    Returns a FloodZone with in_zone=True if the point is inside a high-risk
    zone (anything except 'X'), or FloodZone(zone_code='X', in_zone=False) if
    it is outside all flood zone polygons or only within zone X.

    Returns None only when the flood_zones table is completely empty (i.e. no
    data has been ingested yet).
    """
    query = """
        SELECT zone_code, flood_label
        FROM flood_zones
        WHERE ST_Contains(
            geom,
            ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)
        )
        ORDER BY
            -- Prefer high-risk zones first so the worst-case is surfaced
            CASE
                WHEN zone_code IN ('AE','A','AH','AO','AR','A99','VE','V') THEN 0
                ELSE 1
            END
        LIMIT 1
    """

    row = await db.fetch_one(
        query,
        values={"lat": lat, "lng": lng},
    )

    if row is None:
        # Check whether the table has any data at all
        count_row = await db.fetch_one("SELECT COUNT(*) AS cnt FROM flood_zones")
        if count_row and count_row["cnt"] == 0:
            logger.warning("flood_zones table is empty — flood data not yet ingested.")
            return None

        # Point is not inside any polygon → outside all flood zones
        return FloodZone(
            zone_code="X",
            flood_label=FLOOD_ZONE_LABELS["X"],
            in_zone=False,
        )

    zone_code: str = row["zone_code"]
    flood_label: str = row["flood_label"] or FLOOD_ZONE_LABELS.get(zone_code, zone_code)
    in_zone: bool = zone_code not in ("X", "D")

    logger.info("Flood zone at (%.6f, %.6f): %s (%s)", lat, lng, zone_code, flood_label)

    return FloodZone(
        zone_code=zone_code,
        flood_label=flood_label,
        in_zone=in_zone,
    )
