"""
pipeline/ingest/usda_fsis_ingest.py
-------------------------------------
Download USDA FSIS establishment directory, filter for meat/poultry/slaughter
facilities, geocode addresses via Nominatim (rate-limited), and upsert into
hazard_features with category='meat_processing'.

Data source
-----------
https://www.fsis.usda.gov/sites/default/files/media_file/documents/MPI_Directory_by_Establishment_Number.xlsx
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import time
from typing import Any

import asyncpg
import httpx
import openpyxl
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

FSIS_URL = (
    "https://www.fsis.usda.gov/sites/default/files/media_file/documents/"
    "MPI_Directory_by_Establishment_Number.xlsx"
)

NOMINATIM_SEARCH = "https://nominatim.openstreetmap.org/search"
NOMINATIM_HEADERS = {
    "User-Agent": "HomeCheck-FSIS-Ingest/0.1 (homecheck-app; contact@example.com)",
}

# Nominatim rate limit — max 1 request/second (be conservative)
GEOCODE_DELAY_S = 1.1

# Activities that indicate meat / poultry / slaughter
MEAT_ACTIVITIES = {
    "Slaughter",
    "Poultry Slaughter",
    "Swine Slaughter",
    "Cattle Slaughter",
    "Sheep Slaughter",
    "Goat Slaughter",
    "Poultry Processing",
    "Meat Processing",
    "Meat Food Product",
    "Poultry Food Product",
}


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

async def _download_xlsx() -> bytes:
    logger.info("Downloading USDA FSIS xlsx from %s …", FSIS_URL)
    async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
        resp = await client.get(FSIS_URL)
        resp.raise_for_status()
    logger.info("Downloaded %d bytes.", len(resp.content))
    return resp.content


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------

def _parse_xlsx(content: bytes) -> list[dict[str, Any]]:
    """
    Parse the FSIS xlsx.  Column headers vary by year; we search case-insensitively.
    Returns a list of facility dicts with keys:
        est_number, name, street, city, state, zip, activities
    """
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []

    # First non-empty row → headers
    header_row = rows[0]
    headers = [str(h).strip().lower() if h else "" for h in header_row]

    def _col(name_fragments: list[str]) -> int | None:
        """Return column index for the first header containing any fragment."""
        for frag in name_fragments:
            for i, h in enumerate(headers):
                if frag.lower() in h:
                    return i
        return None

    idx_est = _col(["establishment number", "est number", "est. number"])
    idx_name = _col(["establishment name", "est name"])
    idx_street = _col(["street", "address"])
    idx_city = _col(["city"])
    idx_state = _col(["state"])
    idx_zip = _col(["zip"])
    idx_activities = _col(["activities", "grant"])

    if idx_name is None or idx_city is None or idx_state is None:
        logger.error("Could not find required columns in FSIS xlsx. Headers: %s", headers)
        return []

    facilities: list[dict] = []
    for row in rows[1:]:
        if not row or all(v is None for v in row):
            continue

        activities_raw = str(row[idx_activities] or "") if idx_activities is not None else ""
        # Check whether any meat activity is present
        acts = set(a.strip() for a in activities_raw.split(","))
        if not acts.intersection(MEAT_ACTIVITIES):
            continue

        name = str(row[idx_name] or "").strip()
        street = str(row[idx_street] or "").strip() if idx_street is not None else ""
        city = str(row[idx_city] or "").strip()
        state = str(row[idx_state] or "").strip()
        zip_code = str(row[idx_zip] or "").strip() if idx_zip is not None else ""
        est_number = str(row[idx_est] or "").strip() if idx_est is not None else ""

        if not city or not state:
            continue

        # Build a geocodeable address string
        parts = [p for p in [street, city, state, zip_code] if p]
        address_str = ", ".join(parts)

        # Determine best meat_processing subcategory
        if acts.intersection({"Poultry Slaughter", "Poultry Processing", "Poultry Food Product"}):
            subcategory = "poultry_processing"
        elif acts.intersection({"Slaughter", "Cattle Slaughter", "Swine Slaughter",
                                "Sheep Slaughter", "Goat Slaughter"}):
            subcategory = "slaughterhouse"
        elif acts.intersection({"Meat Processing", "Meat Food Product"}):
            subcategory = "meat_processing"
        else:
            subcategory = "meatpacking"

        facilities.append({
            "est_number": est_number,
            "name": name,
            "address": address_str,
            "city": city,
            "state": state,
            "subcategory": subcategory,
            "activities": activities_raw,
        })

    logger.info("Parsed %d meat/poultry facilities from FSIS xlsx.", len(facilities))
    return facilities


# ---------------------------------------------------------------------------
# Nominatim geocoding (rate-limited)
# ---------------------------------------------------------------------------

async def _geocode_batch(
    facilities: list[dict],
    client: httpx.AsyncClient,
) -> list[dict]:
    """
    Geocode each facility's address string, adding lat/lng keys.
    Skips facilities that cannot be geocoded.
    """
    geocoded: list[dict] = []
    total = len(facilities)
    for i, fac in enumerate(facilities):
        address = fac["address"]
        try:
            resp = await client.get(
                NOMINATIM_SEARCH,
                params={"q": address, "format": "json", "limit": 1, "addressdetails": 0},
                headers=NOMINATIM_HEADERS,
                timeout=15.0,
            )
            resp.raise_for_status()
            results = resp.json()
            if results:
                fac["lat"] = float(results[0]["lat"])
                fac["lng"] = float(results[0]["lon"])
                geocoded.append(fac)
            else:
                logger.debug("No geocode result for: %s", address)
        except Exception as exc:
            logger.warning("Geocoding failed for %r: %s", address, exc)

        if (i + 1) % 50 == 0:
            logger.info("Geocoded %d / %d facilities …", i + 1, total)

        # Respect Nominatim's usage policy: 1 req/second
        await asyncio.sleep(GEOCODE_DELAY_S)

    logger.info("Geocoding complete: %d / %d facilities have coordinates.", len(geocoded), total)
    return geocoded


# ---------------------------------------------------------------------------
# PostGIS upsert
# ---------------------------------------------------------------------------

async def _upsert_fsis(
    conn: asyncpg.Connection,
    facilities: list[dict],
) -> int:
    if not facilities:
        return 0

    records: list[tuple] = []
    for f in facilities:
        props = json.dumps({
            "est_number": f.get("est_number"),
            "city": f.get("city"),
            "state": f.get("state"),
            "activities": f.get("activities"),
        })
        geom_json = json.dumps({
            "type": "Point",
            "coordinates": [f["lng"], f["lat"]],
        })
        records.append((
            "usda_fsis",
            "meat_processing",
            f["subcategory"],
            f["name"] or None,
            props,
            geom_json,
        ))

    await conn.execute("""
        CREATE TEMP TABLE IF NOT EXISTS _tmp_fsis (
            source      TEXT,
            category    TEXT,
            subcategory TEXT,
            name        TEXT,
            properties  JSONB,
            geom_json   TEXT
        ) ON COMMIT DROP
    """)

    await conn.copy_records_to_table(
        "_tmp_fsis",
        records=records,
        columns=["source", "category", "subcategory", "name", "properties", "geom_json"],
    )

    result = await conn.execute("""
        INSERT INTO hazard_features (source, category, subcategory, name, properties, geom)
        SELECT
            source, category, subcategory, name, properties,
            ST_SetSRID(ST_GeomFromGeoJSON(geom_json), 4326)
        FROM _tmp_fsis
        WHERE geom_json IS NOT NULL
        ON CONFLICT DO NOTHING
    """)

    await conn.execute("DROP TABLE IF EXISTS _tmp_fsis")
    return int(result.split()[-1]) if result else 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def run() -> None:
    """Full USDA FSIS ingest: download → parse → geocode → upsert."""
    db_url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    logger.info("USDA FSIS ingest starting …")

    raw = await _download_xlsx()
    facilities = _parse_xlsx(raw)
    if not facilities:
        logger.warning("No meat/poultry facilities parsed — check xlsx format.")
        return

    async with httpx.AsyncClient() as client:
        facilities = await _geocode_batch(facilities, client)

    conn: asyncpg.Connection = await asyncpg.connect(db_url)
    try:
        inserted = await _upsert_fsis(conn, facilities)
        logger.info("USDA FSIS ingest complete. Inserted %d facilities.", inserted)
    finally:
        await conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
