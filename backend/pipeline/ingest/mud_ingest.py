"""
pipeline/ingest/mud_ingest.py
------------------------------
Download Texas Municipal Utility District (MUD) boundaries from the TWDB
ArcGIS REST API and upsert them into the future_development PostGIS table.

The TWDB Water Districts layer exposes district polygons for all types:
MUD, WCID, FWSD, SWSD, CISD, LID, etc.

Usage
-----
    python -m pipeline.ingest.mud_ingest
    # or inside the pipeline shell script:
    asyncio.run(run('30.098,-97.938,30.516,-97.474'))
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
from typing import Any

import asyncpg
import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# TCEQ IWUD ArcGIS REST endpoint (authoritative source for Texas MUD boundaries)
# Layer 6 = Municipal Utility Districts specifically
# Layer 0 = All water district types combined
# ---------------------------------------------------------------------------
TWDB_URL = (
    "https://gisweb.tceq.texas.gov/arcgis/rest/services/"
    "iwud/WaterDistricts_PRD/MapServer/6/query"
)

OUT_FIELDS = "OBJECTID,NAME,DISTRICT_ID,COUNTY,STATUS,COGO_ACRES"
PAGE_SIZE = 1000

# Austin TX default bbox (south,west,north,east  — OSM convention)
DEFAULT_BBOX = "30.098,-97.938,30.516,-97.474"

CURRENT_YEAR = datetime.date.today().year


# ---------------------------------------------------------------------------
# Status classification
# ---------------------------------------------------------------------------

def _classify_status(formed_year: int | None) -> str:
    """
    Classify a district based on how recently it was organised.

    - active      : formed within the last 5 years
    - established : formed within the last 10 years
    - mature      : older than 10 years (or unknown)
    """
    if formed_year is None:
        return "mature"
    age = CURRENT_YEAR - formed_year
    if age <= 5:
        return "active"
    if age <= 10:
        return "established"
    return "mature"


# ---------------------------------------------------------------------------
# ORG_DATE parser
# ---------------------------------------------------------------------------

def _parse_year(org_date: Any) -> int | None:
    """
    Parse the ORG_DATE field returned by the TWDB API.

    The field may be:
    - An integer Unix epoch in milliseconds (ArcGIS default for date fields)
    - A string like "2019/01/15" or "2019-01-15" or "01/15/2019"
    - None / null
    """
    if org_date is None:
        return None

    # ArcGIS date fields come back as epoch-milliseconds integers
    if isinstance(org_date, (int, float)):
        try:
            dt = datetime.datetime.utcfromtimestamp(org_date / 1000)
            return dt.year
        except (OSError, OverflowError, ValueError):
            return None

    if isinstance(org_date, str):
        org_date = org_date.strip()
        if not org_date:
            return None
        # Try several common formats
        for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"):
            try:
                return datetime.datetime.strptime(org_date, fmt).year
            except ValueError:
                continue
        # Last-ditch: grab a 4-digit year anywhere in the string
        import re
        m = re.search(r"\b(19|20)\d{2}\b", org_date)
        if m:
            return int(m.group(0))

    return None


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _geojson_from_feature(feature: dict) -> dict | None:
    """Return the GeoJSON geometry dict from an ArcGIS GeoJSON feature."""
    geom = feature.get("geometry")
    if not geom:
        return None
    gtype = geom.get("type")
    if gtype not in (
        "Point",
        "MultiPoint",
        "LineString",
        "MultiLineString",
        "Polygon",
        "MultiPolygon",
    ):
        return None
    return geom


# ---------------------------------------------------------------------------
# TWDB API fetch (with pagination)
# ---------------------------------------------------------------------------

async def _fetch_page(
    client: httpx.AsyncClient,
    bbox_str: str,
    offset: int,
) -> list[dict]:
    """Fetch one page of features from the TWDB ArcGIS REST endpoint."""
    # bbox_str is south,west,north,east; ArcGIS wants west,south,east,north
    parts = bbox_str.split(",")
    if len(parts) == 4:
        south, west, north, east = parts
        geometry_param = f"{west},{south},{east},{north}"
    else:
        geometry_param = bbox_str

    params = {
        "where": "1=1",
        "geometry": geometry_param,
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "outSR": "4326",
        "outFields": OUT_FIELDS,
        "returnGeometry": "true",
        "f": "geojson",
        "resultRecordCount": PAGE_SIZE,
        "resultOffset": offset,
    }

    for attempt in range(1, 4):
        try:
            resp = await client.get(TWDB_URL, params=params, timeout=60.0)
            resp.raise_for_status()
            data = resp.json()
            features = data.get("features", [])
            logger.info(
                "TWDB page offset=%d → %d features (attempt %d)",
                offset,
                len(features),
                attempt,
            )
            return features
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            logger.warning("TWDB request attempt %d failed: %s", attempt, exc)
            if attempt < 3:
                await asyncio.sleep(5 * attempt)

    logger.error("All TWDB fetch attempts failed for offset=%d", offset)
    return []


async def _fetch_all_features(bbox_str: str) -> list[dict]:
    """Paginate through the TWDB API and return all features."""
    all_features: list[dict] = []
    offset = 0

    async with httpx.AsyncClient(
        headers={"User-Agent": "HomeCheck/0.1 (homecheck-app)"}
    ) as client:
        while True:
            page = await _fetch_page(client, bbox_str, offset)
            all_features.extend(page)
            if len(page) < PAGE_SIZE:
                # Last page — no more records
                break
            offset += PAGE_SIZE
            await asyncio.sleep(1)  # be polite to the public API

    logger.info("TWDB total features fetched: %d", len(all_features))
    return all_features


# ---------------------------------------------------------------------------
# Record building
# ---------------------------------------------------------------------------

def _build_record(feature: dict) -> tuple | None:
    """
    Convert an ArcGIS GeoJSON feature into a DB record tuple.

    Returns
    -------
    (source, dev_type, name, description, formed_year, last_bond_year,
     bond_amount_usd, status, properties_json, geom_json)
    or None if the feature should be skipped.
    """
    props: dict = feature.get("properties") or {}
    geom = _geojson_from_feature(feature)
    if geom is None:
        return None

    # TCEQ IWUD field names
    dist_name: str | None = (
        props.get("NAME") or props.get("DIST_NAME") or props.get("name")
    )
    district_id: Any = props.get("DISTRICT_ID") or props.get("dist_num")
    cnty_name: str | None = props.get("COUNTY") or props.get("CNTY_NAME")
    dist_status: str | None = props.get("STATUS")
    acres: Any = props.get("COGO_ACRES")

    # TCEQ doesn't expose formation date — use district status for classification
    formed_year = None
    status = "active" if dist_status in ("Active", "ACTIVE") else "established"

    # Build a human-readable description
    county_label = f", {cnty_name} County" if cnty_name else ""
    description = f"Municipal Utility District{county_label}"
    if district_id:
        description += f" #{district_id}"
    if acres:
        description += f" ({acres:.0f} acres)"

    extra_props = {k: v for k, v in props.items() if v is not None}

    return (
        "twdb_mud",            # source
        "mud_district",        # dev_type
        dist_name,             # name
        description,           # description
        formed_year,           # formed_year
        None,                  # last_bond_year
        None,                  # bond_amount_usd
        status,                # status
        json.dumps(extra_props),  # properties
        json.dumps(geom),      # geom_json (WGS-84 GeoJSON text)
    )


# ---------------------------------------------------------------------------
# PostGIS upsert
# ---------------------------------------------------------------------------

async def _upsert_records(conn: asyncpg.Connection, records: list[tuple]) -> int:
    """
    Bulk-upsert records into future_development.

    Each tuple:
      (source, dev_type, name, description, formed_year, last_bond_year,
       bond_amount_usd, status, properties_json, geom_json)

    Matches on (source, dev_type, name) — duplicate district names from the
    same source are updated rather than duplicated.
    """
    if not records:
        return 0

    inserted_total = 0

    async with conn.transaction():
        await conn.execute("""
            CREATE TEMP TABLE IF NOT EXISTS _tmp_future_dev (
                source          TEXT,
                dev_type        TEXT,
                name            TEXT,
                description     TEXT,
                formed_year     INT,
                last_bond_year  INT,
                bond_amount_usd BIGINT,
                status          TEXT,
                properties      JSONB,
                geom_json       TEXT
            ) ON COMMIT DROP
        """)

        await conn.copy_records_to_table(
            "_tmp_future_dev",
            records=records,
            columns=[
                "source",
                "dev_type",
                "name",
                "description",
                "formed_year",
                "last_bond_year",
                "bond_amount_usd",
                "status",
                "properties",
                "geom_json",
            ],
        )

        result = await conn.execute("""
            INSERT INTO future_development
                (source, dev_type, name, description, formed_year,
                 last_bond_year, bond_amount_usd, status, properties, geom)
            SELECT
                source, dev_type, name, description, formed_year,
                last_bond_year, bond_amount_usd, status,
                properties::jsonb,
                ST_SetSRID(ST_GeomFromGeoJSON(geom_json), 4326)
            FROM _tmp_future_dev
            WHERE geom_json IS NOT NULL
            ON CONFLICT (source, dev_type, name)
            DO UPDATE SET
                description     = EXCLUDED.description,
                formed_year     = EXCLUDED.formed_year,
                status          = EXCLUDED.status,
                properties      = EXCLUDED.properties,
                geom            = EXCLUDED.geom
        """)

        inserted_total = int(result.split()[-1]) if result else 0

    return inserted_total


# ---------------------------------------------------------------------------
# Ensure unique constraint exists so ON CONFLICT works
# ---------------------------------------------------------------------------

async def _ensure_schema(conn: asyncpg.Connection) -> None:
    """
    Idempotently ensure the unique constraint required for upsert exists.
    This is separate from the migration SQL so the ingestor can be run
    standalone without re-running the full migration.
    """
    await conn.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_future_dev_source_type_name'
            ) THEN
                ALTER TABLE future_development
                ADD CONSTRAINT uq_future_dev_source_type_name
                UNIQUE (source, dev_type, name);
            END IF;
        END
        $$;
    """)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def run(bbox: str = DEFAULT_BBOX) -> None:
    """
    Full MUD ingest run.

    Parameters
    ----------
    bbox : str
        Bounding box in *south,west,north,east* order (OSM convention).
        Default covers the Austin, TX metro area.
    """
    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://homecheck:homecheck_secret@127.0.0.1:5432/homecheck",
    )
    dsn = db_url.replace("postgresql+asyncpg://", "postgresql://")

    logger.info("MUD ingest starting (bbox=%s) …", bbox)

    conn: asyncpg.Connection = await asyncpg.connect(dsn)
    try:
        await _ensure_schema(conn)

        features = await _fetch_all_features(bbox)
        if not features:
            logger.warning("No features returned from TWDB — nothing to upsert.")
            return

        records: list[tuple] = []
        skipped = 0
        for feat in features:
            rec = _build_record(feat)
            if rec is None:
                skipped += 1
                continue
            records.append(rec)

        if skipped:
            logger.info("Skipped %d features with no usable geometry.", skipped)

        inserted = await _upsert_records(conn, records)
        logger.info(
            "MUD ingest complete. Upserted %d / %d records.",
            inserted,
            len(records),
        )
    finally:
        await conn.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )
    asyncio.run(run())
