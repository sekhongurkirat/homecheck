"""
pipeline/ingest/osm_ingest.py
-----------------------------
Download hazard features from the OpenStreetMap Overpass API and upsert them
into the hazard_features PostGIS table.

Supported categories
--------------------
- highway  : motorway / trunk / primary roads
- rail     : rail / subway / tram lines
- industrial: industrial land-use, factories, works
- landfill : landfill / waste transfer stations
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

import asyncpg
import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Bounding box: contiguous USA (south, west, north, east)
USA_BBOX = "24.396308,-125.000000,49.384358,-66.934570"

# Overpass QL query templates — {{bbox}} is replaced at runtime.
QUERIES: list[dict[str, Any]] = [
    {
        "category": "highway",
        "subcategory_field": "highway",
        "subcategory_values": ["motorway", "trunk", "primary"],
        "overpass_ql": """
[out:json][timeout:180];
(
  way["highway"~"^(motorway|trunk|primary)$"]({{bbox}});
);
out geom qt;
""",
    },
    {
        "category": "rail",
        "subcategory_field": "railway",
        "subcategory_values": ["rail", "subway", "tram", "light_rail", "narrow_gauge"],
        "overpass_ql": """
[out:json][timeout:180];
(
  way["railway"~"^(rail|subway|tram|light_rail|narrow_gauge)$"]({{bbox}});
);
out geom qt;
""",
    },
    {
        "category": "industrial",
        "subcategory_field": None,
        "subcategory_values": [],
        "overpass_ql": """
[out:json][timeout:180];
(
  node["landuse"="industrial"]({{bbox}});
  way["landuse"="industrial"]({{bbox}});
  node["man_made"~"^(works|factory)$"]({{bbox}});
  way["man_made"~"^(works|factory)$"]({{bbox}});
);
out geom qt;
""",
    },
    {
        "category": "landfill",
        "subcategory_field": None,
        "subcategory_values": [],
        "overpass_ql": """
[out:json][timeout:180];
(
  node["landuse"="landfill"]({{bbox}});
  way["landuse"="landfill"]({{bbox}});
  node["amenity"="waste_transfer_station"]({{bbox}});
  way["amenity"="waste_transfer_station"]({{bbox}});
);
out geom qt;
""",
    },
]


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _nodes_to_linestring(nodes: list[dict]) -> dict | None:
    """Convert an Overpass way's geometry array to a GeoJSON LineString."""
    coords = [(n["lon"], n["lat"]) for n in nodes if "lon" in n and "lat" in n]
    if len(coords) < 2:
        return None
    return {"type": "LineString", "coordinates": coords}


def _nodes_to_polygon(nodes: list[dict]) -> dict | None:
    """Convert an Overpass closed way to a GeoJSON Polygon."""
    coords = [(n["lon"], n["lat"]) for n in nodes if "lon" in n and "lat" in n]
    if len(coords) < 4:
        return None
    # Close the ring if needed
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    return {"type": "Polygon", "coordinates": [coords]}


def _element_to_geojson(element: dict) -> dict | None:
    """
    Return a GeoJSON geometry dict for an Overpass node or way element.
    Returns None if geometry cannot be extracted.
    """
    etype = element.get("type")

    if etype == "node":
        lat = element.get("lat")
        lon = element.get("lon")
        if lat is None or lon is None:
            return None
        return {"type": "Point", "coordinates": [lon, lat]}

    if etype == "way":
        geometry = element.get("geometry", [])
        if not geometry:
            return None
        # Closed way (first == last node_id) → Polygon, otherwise LineString
        node_refs = element.get("nodes", [])
        is_closed = len(node_refs) >= 4 and node_refs[0] == node_refs[-1]
        if is_closed:
            return _nodes_to_polygon(geometry)
        return _nodes_to_linestring(geometry)

    return None


def _derive_subcategory(element: dict, spec: dict) -> str:
    """
    For categories with a known tag field (highway, rail) read directly.
    For others (industrial, landfill) map tags to canonical subcategories.
    """
    tags: dict = element.get("tags", {})
    field = spec.get("subcategory_field")

    if field:
        return tags.get(field, spec["category"])

    # Industrial
    if spec["category"] == "industrial":
        landuse = tags.get("landuse", "")
        man_made = tags.get("man_made", "")
        if man_made in ("works", "factory"):
            return man_made
        if landuse == "industrial":
            return "industrial"
        return "industrial"

    # Landfill
    if spec["category"] == "landfill":
        amenity = tags.get("amenity", "")
        if amenity == "waste_transfer_station":
            return "waste_transfer_station"
        return "landfill"

    return spec["category"]


# ---------------------------------------------------------------------------
# Overpass download
# ---------------------------------------------------------------------------

async def _fetch_overpass(ql: str, bbox: str, client: httpx.AsyncClient) -> list[dict]:
    """POST a query to Overpass and return the elements list."""
    payload = ql.replace("{{bbox}}", bbox).strip()
    logger.info("Sending Overpass query (%d chars) …", len(payload))

    for attempt in range(1, 4):
        try:
            resp = await client.post(
                OVERPASS_URL,
                data={"data": payload},
                timeout=240.0,
            )
            resp.raise_for_status()
            return resp.json().get("elements", [])
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            logger.warning("Overpass attempt %d failed: %s", attempt, exc)
            if attempt < 3:
                await asyncio.sleep(10 * attempt)
    logger.error("All Overpass attempts failed for query.")
    return []


# ---------------------------------------------------------------------------
# PostGIS upsert
# ---------------------------------------------------------------------------

async def _upsert_features(
    conn: asyncpg.Connection,
    records: list[tuple],
) -> int:
    """
    Bulk-upsert records into hazard_features.
    Each record: (source, category, subcategory, name, properties_json, geojson_str)
    Returns the number of rows inserted/updated.
    """
    if not records:
        return 0

    # Wrap in a transaction so the temp table survives until the INSERT completes.
    async with conn.transaction():
        await conn.execute("""
            CREATE TEMP TABLE IF NOT EXISTS _tmp_hazard (
                source      TEXT,
                category    TEXT,
                subcategory TEXT,
                name        TEXT,
                properties  JSONB,
                geom_json   TEXT
            )
        """)

        await conn.copy_records_to_table(
            "_tmp_hazard",
            records=records,
            columns=["source", "category", "subcategory", "name", "properties", "geom_json"],
        )

        result = await conn.execute("""
            INSERT INTO hazard_features (source, category, subcategory, name, properties, geom)
            SELECT
                source, category, subcategory, name, properties,
                ST_SetSRID(ST_GeomFromGeoJSON(geom_json), 4326)
            FROM _tmp_hazard
            WHERE geom_json IS NOT NULL
            ON CONFLICT DO NOTHING
        """)

        await conn.execute("DROP TABLE IF EXISTS _tmp_hazard")

    # asyncpg returns "INSERT 0 N"
    inserted = int(result.split()[-1]) if result else 0
    return inserted


# ---------------------------------------------------------------------------
# Main ingest logic
# ---------------------------------------------------------------------------

async def _ingest_query(spec: dict, bbox: str, conn: asyncpg.Connection) -> int:
    """Run one Overpass query spec and upsert results. Returns insert count."""
    async with httpx.AsyncClient() as client:
        elements = await _fetch_overpass(spec["overpass_ql"], bbox, client)

    logger.info("[%s] Fetched %d elements from Overpass.", spec["category"], len(elements))

    records: list[tuple] = []
    skipped = 0
    for el in elements:
        geom = _element_to_geojson(el)
        if geom is None:
            skipped += 1
            continue
        tags: dict = el.get("tags", {})
        subcategory = _derive_subcategory(el, spec)
        name = tags.get("name") or tags.get("ref")
        properties = {k: v for k, v in tags.items() if k not in ("name", "ref")}
        records.append((
            "osm",
            spec["category"],
            subcategory,
            name,
            json.dumps(properties),
            json.dumps(geom),
        ))

    if skipped:
        logger.info("[%s] Skipped %d elements with no geometry.", spec["category"], skipped)

    inserted = await _upsert_features(conn, records)
    logger.info("[%s] Upserted %d / %d features.", spec["category"], inserted, len(records))
    return inserted


async def run(bbox: str = USA_BBOX) -> None:
    """
    Full OSM ingest run.

    Parameters
    ----------
    bbox : Overpass bounding box string  "south,west,north,east"
    """
    db_url = os.environ["DATABASE_URL"]
    # asyncpg uses a slightly different DSN format (no +asyncpg driver prefix)
    dsn = db_url.replace("postgresql+asyncpg://", "postgresql://")

    logger.info("OSM ingest starting (bbox=%s) …", bbox)
    conn: asyncpg.Connection = await asyncpg.connect(dsn)
    try:
        total = 0
        for spec in QUERIES:
            count = await _ingest_query(spec, bbox, conn)
            total += count
            # Be polite to the public Overpass instance
            await asyncio.sleep(5)
        logger.info("OSM ingest complete. Total upserted: %d", total)
    finally:
        await conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
