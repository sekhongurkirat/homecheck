"""
hazard_query.py
---------------
PostGIS-backed hazard proximity queries and buffer geometry helpers.
"""

from __future__ import annotations

import json
import logging
import math
from typing import Any

import databases
from shapely.geometry import mapping, Point
from shapely.ops import transform
import pyproj

from models import HazardFlag, Priority

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Priority → subcategory mapping
# ---------------------------------------------------------------------------
PRIORITY_SUBCATEGORIES: dict[str, list[str]] = {
    Priority.highway: ["motorway", "trunk", "primary"],
    Priority.rail: ["rail", "subway", "tram", "light_rail", "narrow_gauge"],
    Priority.industrial: [
        "industrial",
        "works",
        "factory",
        "chemical",
        "metal_smelting",
        "refinery",
        "power_plant",
    ],
    Priority.meat_processing: [
        "slaughterhouse",
        "meat_processing",
        "poultry_processing",
        "meatpacking",
    ],
    Priority.landfill: ["landfill", "waste_transfer_station", "recycling"],
    Priority.airport: ["aerodrome", "airport", "airstrip", "helipad"],
}


def _status(distance_m: float, threshold_m: int) -> str:
    """Return red / yellow / green based on distance vs threshold."""
    if distance_m <= threshold_m:
        return "red"
    if distance_m <= threshold_m * 1.5:
        return "yellow"
    return "green"


async def query_hazards(
    db: databases.Database,
    lat: float,
    lng: float,
    priorities: list[str],
    thresholds: dict[str, int],
) -> list[HazardFlag]:
    """
    Find hazard features within the maximum threshold distance of (lat, lng).

    Parameters
    ----------
    db          : async databases.Database connection
    lat, lng    : WGS-84 coordinates of the subject property
    priorities  : list of Priority enum values (strings) to check
    thresholds  : mapping of priority → distance in metres

    Returns
    -------
    list[HazardFlag] sorted by distance ascending
    """
    if not priorities or not thresholds:
        return []

    max_radius_m: int = max(thresholds.get(p, 500) for p in priorities)

    # Build the subcategory filter
    subcategory_list: list[str] = []
    for p in priorities:
        subcategory_list.extend(PRIORITY_SUBCATEGORIES.get(p, []))

    if not subcategory_list:
        return []

    # Parameterised query — ST_DWithin on geography casts gives metres
    query = """
        SELECT
            id,
            source,
            category,
            subcategory,
            name,
            properties,
            ST_AsGeoJSON(geom)::text               AS geojson,
            ST_Distance(
                geom::geography,
                ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography
            )                                       AS distance_m
        FROM hazard_features
        WHERE
            subcategory = ANY(:subcategories)
            AND ST_DWithin(
                geom::geography,
                ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                :radius_m
            )
        ORDER BY distance_m ASC
        LIMIT 200
    """

    rows = await db.fetch_all(
        query,
        values={
            "lat": lat,
            "lng": lng,
            "subcategories": subcategory_list,
            "radius_m": max_radius_m,
        },
    )

    flags: list[HazardFlag] = []
    # Deduplicate: keep only the closest segment per (priority, name).
    # Long roads appear as many OSM way segments — we only want the nearest one.
    seen: set[tuple] = set()
    for row in rows:
        priority_for_row = _subcategory_to_priority(row["subcategory"], priorities)
        if priority_for_row is None:
            continue
        dedup_key = (priority_for_row, row["name"] or row["subcategory"])
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        threshold_m = thresholds.get(priority_for_row, 500)
        dist = float(row["distance_m"])
        flags.append(
            HazardFlag(
                priority=priority_for_row,
                status=_status(dist, threshold_m),
                distance_m=round(dist, 1),
                threshold_m=threshold_m,
                name=row["name"],
                subcategory=row["subcategory"],
                source=row["source"],
                geojson=json.loads(row["geojson"]),
            )
        )

    return flags


def _subcategory_to_priority(subcategory: str, priorities: list[str]) -> str | None:
    """Return the first matching priority for a given subcategory."""
    for p in priorities:
        if subcategory in PRIORITY_SUBCATEGORIES.get(p, []):
            return p
    return None


# ---------------------------------------------------------------------------
# Buffer helper
# ---------------------------------------------------------------------------

def generate_buffer_geojson(lat: float, lng: float, radius_m: float) -> dict[str, Any]:
    """
    Return a GeoJSON Polygon representing a geodesic circle of *radius_m* metres
    centred on (lat, lng).  Uses an azimuthal equidistant projection so the
    buffer is accurate regardless of latitude.
    """
    # Project to a CRS centred on the point
    aeqd = pyproj.CRS(
        proj="aeqd",
        ellps="WGS84",
        datum="WGS84",
        lat_0=lat,
        lon_0=lng,
        units="m",
    )
    wgs84 = pyproj.CRS("EPSG:4326")

    project_fwd = pyproj.Transformer.from_crs(wgs84, aeqd, always_xy=True).transform
    project_inv = pyproj.Transformer.from_crs(aeqd, wgs84, always_xy=True).transform

    # Create circle in projected space then reproject back
    point_proj = transform(project_fwd, Point(lng, lat))
    circle_proj = point_proj.buffer(radius_m, resolution=64)
    circle_wgs84 = transform(project_inv, circle_proj)

    return {
        "type": "Feature",
        "geometry": mapping(circle_wgs84),
        "properties": {"radius_m": radius_m},
    }
