"""
pipeline/ingest/epa_tri_ingest.py
----------------------------------
Download EPA Toxics Release Inventory (TRI) facility data, map SIC codes to
subcategories, and upsert into hazard_features.

Data source
-----------
EPA TRI Basic Data Files (CSV) — one row per facility-chemical combination.
We de-duplicate on TRIFID (facility identifier) so each plant appears once.

URL pattern  (year can be parameterised):
    https://www.epa.gov/sites/default/files/2020-10/tri_basic_data_files_calendar_year_2019_0.zip

For robustness we also try the direct CSV download endpoint:
    https://data.epa.gov/efservice/downloads/tri/mv_tri_basic_download/{year}/US/csv
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import os
import zipfile
from typing import Any

import asyncpg
import httpx
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SIC code → subcategory mapping
# ---------------------------------------------------------------------------
# SIC major groups: https://www.osha.gov/data/sic-manual
SIC_TO_SUBCATEGORY: dict[str, str] = {
    # 20xx — Food processing
    "20": "food_processing",
    "2011": "meat_packing",
    "2013": "sausages_and_prepared_meats",
    "2048": "feed_manufacturing",
    # 26xx — Paper
    "26": "paper_mill",
    "2611": "pulp_mill",
    "2621": "paper_mill",
    # 28xx — Chemicals
    "28": "chemical",
    "2812": "alkali_chlorine",
    "2816": "inorganic_pigments",
    "2819": "industrial_inorganic_chemicals",
    "2821": "plastics_materials",
    "2865": "cyclic_crudes_and_intermediates",
    "2869": "industrial_organic_chemicals",
    "2879": "agricultural_chemicals",
    "2911": "petroleum_refining",
    # 29xx — Petroleum
    "29": "refinery",
    # 33xx — Primary metals
    "33": "metal_smelting",
    "3312": "steel_works",
    "3317": "steel_pipe_and_tubes",
    "3325": "steel_foundries",
    "3334": "aluminum_smelting",
    "3339": "primary_nonferrous_metals",
    # 34xx — Fabricated metals
    "34": "metal_fabrication",
    # 36xx — Electronics / semiconductors
    "36": "electronics",
    "3674": "semiconductors",
    # 37xx — Transportation equipment
    "37": "auto_manufacturing",
    # 49xx — Utilities
    "49": "power_plant",
    "4911": "electric_services",
    "4931": "electric_and_gas",
    "4941": "water_supply",
    "4952": "sewerage_systems",
    # Default
    "default": "industrial",
}


def _sic_to_subcategory(sic_code: str) -> str:
    """Map a 4-digit SIC code to a canonical subcategory string."""
    if not sic_code:
        return "industrial"
    sic4 = sic_code.strip().zfill(4)
    sic2 = sic4[:2]
    return (
        SIC_TO_SUBCATEGORY.get(sic4)
        or SIC_TO_SUBCATEGORY.get(sic2)
        or "industrial"
    )


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------

TRI_ZIP_URL = (
    "https://www.epa.gov/sites/default/files/2020-10/"
    "tri_basic_data_files_calendar_year_2019_0.zip"
)
TRI_CSV_DIRECT = (
    "https://data.epa.gov/efservice/downloads/tri/mv_tri_basic_download/2019/US/csv"
)


async def _download_tri_csv(year: int = 2019) -> list[dict]:
    """
    Try zip first, fall back to direct CSV endpoint.
    Returns a list of row dicts keyed by column header.
    """
    async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
        # Attempt 1: zip archive
        logger.info("Downloading TRI zip from %s …", TRI_ZIP_URL)
        try:
            resp = await client.get(TRI_ZIP_URL)
            resp.raise_for_status()
            buf = io.BytesIO(resp.content)
            with zipfile.ZipFile(buf) as zf:
                csv_names = [n for n in zf.namelist() if n.endswith(".csv")]
                if not csv_names:
                    raise ValueError("No CSV found in zip")
                # TRI basic file naming: US_{year}_v*.csv or similar
                # Pick first CSV
                with zf.open(csv_names[0]) as f:
                    content = f.read().decode("latin-1")
            logger.info("Downloaded TRI zip; using file %s", csv_names[0])
        except Exception as exc:
            logger.warning("Zip download failed (%s), trying direct CSV …", exc)
            try:
                resp = await client.get(TRI_CSV_DIRECT)
                resp.raise_for_status()
                content = resp.text
            except Exception as exc2:
                logger.error("TRI CSV download failed: %s", exc2)
                return []

    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)
    logger.info("TRI CSV: %d raw rows", len(rows))
    return rows


# ---------------------------------------------------------------------------
# Parse & de-duplicate
# ---------------------------------------------------------------------------

def _normalise_column(row: dict, *candidates: str) -> str:
    """Return the first non-empty value among candidate column names."""
    for col in candidates:
        v = row.get(col, "").strip()
        if v:
            return v
        # Case-insensitive fallback
        for k, val in row.items():
            if k.strip().lower() == col.lower() and val.strip():
                return val.strip()
    return ""


def _parse_facilities(rows: list[dict]) -> list[dict[str, Any]]:
    """
    De-duplicate by TRIFID and return one dict per unique facility.
    """
    seen: dict[str, dict] = {}
    for row in rows:
        trifid = _normalise_column(row, "TRIFID", "TRI FACILITY ID", "4. TRIFID")
        if not trifid:
            continue
        if trifid in seen:
            continue

        lat_str = _normalise_column(row, "LATITUDE", "LATUTIDE", "12. LATITUDE")
        lng_str = _normalise_column(row, "LONGITUDE", "LONGITUDE", "13. LONGITUDE")
        try:
            lat = float(lat_str)
            lng = float(lng_str)
        except (ValueError, TypeError):
            continue  # Skip facilities with no coordinates

        name = _normalise_column(row, "FACILITY NAME", "FACILITY_NAME", "4. FACILITY NAME")
        sic = _normalise_column(row, "PRIMARY SIC CODE", "SIC CODE", "22. PRIMARY SIC CODE")
        city = _normalise_column(row, "CITY", "BIA CITY")
        state = _normalise_column(row, "ST", "STATE", "STATE ABBR")
        address = _normalise_column(row, "STREET ADDRESS", "ADDRESS")

        seen[trifid] = {
            "trifid": trifid,
            "name": name,
            "lat": lat,
            "lng": lng,
            "sic": sic,
            "city": city,
            "state": state,
            "address": address,
        }

    facilities = list(seen.values())
    logger.info("Parsed %d unique TRI facilities with coordinates.", len(facilities))
    return facilities


# ---------------------------------------------------------------------------
# PostGIS upsert
# ---------------------------------------------------------------------------

async def _upsert_facilities(
    conn: asyncpg.Connection,
    facilities: list[dict],
) -> int:
    if not facilities:
        return 0

    records: list[tuple] = []
    for f in facilities:
        subcategory = _sic_to_subcategory(f["sic"])
        props = json.dumps({
            "trifid": f["trifid"],
            "sic": f["sic"],
            "city": f["city"],
            "state": f["state"],
            "address": f["address"],
        })
        geom_json = json.dumps({
            "type": "Point",
            "coordinates": [f["lng"], f["lat"]],
        })
        records.append((
            "epa_tri",
            "industrial",
            subcategory,
            f["name"] or None,
            props,
            geom_json,
        ))

    await conn.execute("""
        CREATE TEMP TABLE IF NOT EXISTS _tmp_tri (
            source      TEXT,
            category    TEXT,
            subcategory TEXT,
            name        TEXT,
            properties  JSONB,
            geom_json   TEXT
        ) ON COMMIT DROP
    """)

    await conn.copy_records_to_table(
        "_tmp_tri",
        records=records,
        columns=["source", "category", "subcategory", "name", "properties", "geom_json"],
    )

    result = await conn.execute("""
        INSERT INTO hazard_features (source, category, subcategory, name, properties, geom)
        SELECT
            source, category, subcategory, name, properties,
            ST_SetSRID(ST_GeomFromGeoJSON(geom_json), 4326)
        FROM _tmp_tri
        WHERE geom_json IS NOT NULL
        ON CONFLICT DO NOTHING
    """)

    await conn.execute("DROP TABLE IF EXISTS _tmp_tri")
    return int(result.split()[-1]) if result else 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def run(year: int = 2019) -> None:
    """Download and ingest EPA TRI data for *year*."""
    db_url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    logger.info("EPA TRI ingest starting (year=%d) …", year)

    rows = await _download_tri_csv(year)
    if not rows:
        logger.error("No TRI data downloaded — aborting.")
        return

    facilities = _parse_facilities(rows)

    conn: asyncpg.Connection = await asyncpg.connect(db_url)
    try:
        inserted = await _upsert_facilities(conn, facilities)
        logger.info("EPA TRI ingest complete. Inserted %d facilities.", inserted)
    finally:
        await conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
