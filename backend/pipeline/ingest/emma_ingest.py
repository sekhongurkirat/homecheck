"""
pipeline/ingest/emma_ingest.py
-------------------------------
Download municipal bond issuances from MSRB EMMA for a given state and
upsert them into the future_development PostGIS table.

EMMA's public API is subject to occasional 403 / rate-limiting responses.
All network errors are handled gracefully — the ingestor logs a warning and
continues rather than crashing.

Geocoding falls back through Nominatim (no API key required) to place each
issuer at an approximate point geometry.  If geocoding fails the record is
still stored using a fallback centroid for the state (Texas: 31.0,-100.0).

Usage
-----
    python -m pipeline.ingest.emma_ingest
    asyncio.run(run("TX"))
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import re
from typing import Any

import asyncpg
import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# EMMA endpoints
# ---------------------------------------------------------------------------
EMMA_ISSUER_URL = (
    "https://emma.msrb.org/IssuerView/GetIssuersByStateAndType"
)
EMMA_SEARCH_URL = (
    "https://emma.msrb.org/SecurityView/GetSecuritySearchResults"
)

# State centroids used as fallback when geocoding fails
STATE_CENTROIDS: dict[str, tuple[float, float]] = {
    "TX": (31.0, -100.0),
    "CA": (36.7, -119.4),
    "FL": (27.7, -81.6),
    "NY": (42.9, -75.5),
}
DEFAULT_CENTROID = (39.5, -98.4)  # USA geographic centre

# Nominatim geocoder
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_HEADERS = {"User-Agent": "HomeCheck/0.1 (homecheck-app)"}

# Page size for EMMA pagination
PAGE_SIZE = 100

CURRENT_YEAR = datetime.date.today().year
CURRENT_DATE_STR = datetime.date.today().isoformat()


# ---------------------------------------------------------------------------
# Standalone geocoder (no FastAPI dependency)
# ---------------------------------------------------------------------------

async def _geocode(query: str, state: str) -> tuple[float, float]:
    """
    Geocode *query* string to (lat, lng) using Nominatim.

    Falls back to the state centroid if geocoding fails or returns no results.
    """
    fallback = STATE_CENTROIDS.get(state, DEFAULT_CENTROID)
    if not query or not query.strip():
        return fallback

    params = {
        "q": query,
        "format": "json",
        "limit": 1,
        "countrycodes": "us",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                NOMINATIM_URL, params=params, headers=NOMINATIM_HEADERS
            )
            resp.raise_for_status()
            results = resp.json()
            if results:
                return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("Geocoding failed for %r: %s", query, exc)

    return fallback


# ---------------------------------------------------------------------------
# EMMA API helpers
# ---------------------------------------------------------------------------

def _make_headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (compatible; HomeCheck/0.1; +https://homecheck.app)"
        ),
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://emma.msrb.org/",
        "X-Requested-With": "XMLHttpRequest",
    }


async def _fetch_issuers_page(
    client: httpx.AsyncClient,
    state: str,
    page_num: int,
) -> list[dict]:
    """
    Fetch one page from EMMA's GetIssuersByStateAndType endpoint.
    Returns an empty list on any error.
    """
    params = {
        "stateId": state,
        "issuerTypeId": "MUD",
        "pageSize": PAGE_SIZE,
        "pageNum": page_num,
    }
    try:
        resp = await client.get(
            EMMA_ISSUER_URL,
            params=params,
            headers=_make_headers(),
            timeout=30.0,
        )
        if resp.status_code in (403, 429):
            logger.warning(
                "EMMA issuers endpoint returned %d — skipping page %d.",
                resp.status_code,
                page_num,
            )
            return []
        resp.raise_for_status()
        data = resp.json()

        # EMMA may return the list under various keys
        if isinstance(data, list):
            return data
        for key in ("issuers", "Issuers", "results", "Results", "data", "Data"):
            if isinstance(data.get(key), list):
                return data[key]
        return []
    except httpx.HTTPStatusError as exc:
        logger.warning("EMMA issuers HTTP error page %d: %s", page_num, exc)
        return []
    except Exception as exc:  # noqa: BLE001
        logger.warning("EMMA issuers request error page %d: %s", page_num, exc)
        return []


async def _fetch_securities_page(
    client: httpx.AsyncClient,
    state: str,
    page_num: int,
) -> list[dict]:
    """
    POST to EMMA's security search endpoint with a broad date range.
    Returns an empty list on any error.
    """
    form_data = {
        "stateId": state,
        "dateRangeType": "custom",
        "startDate": "2020-01-01",
        "endDate": CURRENT_DATE_STR,
        "primaryPurposeOfIssue": "GENERAL OBLIGATION",
        "pageSize": str(PAGE_SIZE),
        "pageNum": str(page_num),
    }
    try:
        resp = await client.post(
            EMMA_SEARCH_URL,
            data=form_data,
            headers=_make_headers(),
            timeout=30.0,
        )
        if resp.status_code in (403, 429):
            logger.warning(
                "EMMA securities endpoint returned %d — skipping page %d.",
                resp.status_code,
                page_num,
            )
            return []
        resp.raise_for_status()
        data = resp.json()

        if isinstance(data, list):
            return data
        for key in ("securities", "Securities", "results", "Results", "data", "Data"):
            if isinstance(data.get(key), list):
                return data[key]
        return []
    except httpx.HTTPStatusError as exc:
        logger.warning("EMMA securities HTTP error page %d: %s", page_num, exc)
        return []
    except Exception as exc:  # noqa: BLE001
        logger.warning("EMMA securities request error page %d: %s", page_num, exc)
        return []


async def _fetch_all_emma(state: str) -> list[dict]:
    """
    Pull all available issuers + bond securities from EMMA for *state*.

    Combines results from both endpoints; deduplicates by issuer name.
    Fails gracefully — always returns a (possibly empty) list.
    """
    combined: list[dict] = []

    async with httpx.AsyncClient() as client:
        # --- Issuers endpoint ---
        logger.info("Fetching EMMA issuers for state=%s …", state)
        page = 1
        while True:
            items = await _fetch_issuers_page(client, state, page)
            combined.extend(items)
            logger.info(
                "  EMMA issuers page %d → %d items (total so far: %d)",
                page,
                len(items),
                len(combined),
            )
            if len(items) < PAGE_SIZE:
                break
            page += 1
            await asyncio.sleep(1)

        # --- Securities endpoint ---
        logger.info("Fetching EMMA securities for state=%s …", state)
        page = 1
        while True:
            items = await _fetch_securities_page(client, state, page)
            combined.extend(items)
            logger.info(
                "  EMMA securities page %d → %d items (total so far: %d)",
                page,
                len(items),
                len(combined),
            )
            if len(items) < PAGE_SIZE:
                break
            page += 1
            await asyncio.sleep(1)

    logger.info("EMMA total raw items: %d", len(combined))
    return combined


# ---------------------------------------------------------------------------
# Record building
# ---------------------------------------------------------------------------

def _extract_bond_amount(item: dict) -> int | None:
    """Try several common field names for principal / par amount."""
    for key in (
        "principalAmount",
        "principal_amount",
        "PrincipalAmount",
        "parAmount",
        "par_amount",
        "ParAmount",
        "amount",
        "Amount",
        "totalAmount",
        "TotalAmount",
    ):
        val = item.get(key)
        if val is not None:
            try:
                return int(float(str(val).replace(",", "").replace("$", "")))
            except (ValueError, TypeError):
                continue
    return None


def _extract_issue_year(item: dict) -> int | None:
    """Try several common field names for the issue / dated date."""
    for key in (
        "datedDate",
        "dated_date",
        "DatedDate",
        "issueDate",
        "issue_date",
        "IssueDate",
        "closingDate",
        "closing_date",
        "ClosingDate",
    ):
        val = item.get(key)
        if val is None:
            continue
        # May be epoch-ms or a date string
        if isinstance(val, (int, float)):
            try:
                return datetime.datetime.utcfromtimestamp(val / 1000).year
            except Exception:  # noqa: BLE001
                continue
        if isinstance(val, str):
            val = val.strip()
            for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
                try:
                    return datetime.datetime.strptime(val, fmt).year
                except ValueError:
                    continue
            m = re.search(r"\b(19|20)\d{2}\b", val)
            if m:
                return int(m.group(0))
    return None


def _extract_name(item: dict) -> str | None:
    for key in (
        "issuerName",
        "issuer_name",
        "IssuerName",
        "name",
        "Name",
        "description",
        "Description",
        "issueName",
        "issue_name",
    ):
        val = item.get(key)
        if val and isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _extract_location_query(item: dict, state: str) -> str:
    """Build a geocoding query from available location fields."""
    parts: list[str] = []
    for key in ("county", "County", "countyName", "county_name", "CountyName"):
        val = item.get(key)
        if val and isinstance(val, str) and val.strip():
            parts.append(val.strip())
            break
    for key in ("city", "City", "cityName", "city_name"):
        val = item.get(key)
        if val and isinstance(val, str) and val.strip():
            parts.append(val.strip())
            break
    parts.append(state)
    parts.append("USA")
    return ", ".join(parts)


async def _build_record(item: dict, state: str) -> tuple | None:
    """
    Convert an EMMA API item into a DB record tuple (with geocoding).

    Returns
    -------
    (source, dev_type, name, description, formed_year, last_bond_year,
     bond_amount_usd, status, properties_json, geom_json)
    or None if a minimum required field is absent.
    """
    name = _extract_name(item)
    if not name:
        return None

    issue_year = _extract_issue_year(item)
    bond_amount = _extract_bond_amount(item)

    # Geocode the issuer to get a point geometry
    location_query = _extract_location_query(item, state)
    lat, lng = await _geocode(location_query, state)

    geom = {"type": "Point", "coordinates": [lng, lat]}

    description_parts = []
    if issue_year:
        description_parts.append(f"Bond issued {issue_year}")
    if bond_amount:
        description_parts.append(f"${bond_amount:,}")
    description = " — ".join(description_parts) if description_parts else "EMMA bond issuance"

    # Serialise the full raw item as extra properties (drop nulls)
    extra_props = {k: v for k, v in item.items() if v is not None}

    return (
        "emma",                        # source
        "bond_issuance",               # dev_type
        name,                          # name
        description,                   # description
        None,                          # formed_year (not applicable for bonds)
        issue_year,                    # last_bond_year
        bond_amount,                   # bond_amount_usd
        "active",                      # status
        json.dumps(extra_props),       # properties
        json.dumps(geom),              # geom_json
    )


# ---------------------------------------------------------------------------
# PostGIS upsert
# ---------------------------------------------------------------------------

async def _upsert_records(conn: asyncpg.Connection, records: list[tuple]) -> int:
    if not records:
        return 0

    async with conn.transaction():
        await conn.execute("""
            CREATE TEMP TABLE IF NOT EXISTS _tmp_emma_dev (
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
            "_tmp_emma_dev",
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
            FROM _tmp_emma_dev
            WHERE geom_json IS NOT NULL
            ON CONFLICT (source, dev_type, name)
            DO UPDATE SET
                description     = EXCLUDED.description,
                last_bond_year  = EXCLUDED.last_bond_year,
                bond_amount_usd = EXCLUDED.bond_amount_usd,
                status          = EXCLUDED.status,
                properties      = EXCLUDED.properties,
                geom            = EXCLUDED.geom
        """)

        return int(result.split()[-1]) if result else 0


async def _ensure_schema(conn: asyncpg.Connection) -> None:
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

async def run(state: str = "TX") -> None:
    """
    Full EMMA bond-issuance ingest for *state*.

    All network errors are handled gracefully — the function will not raise
    even if EMMA is entirely unavailable.
    """
    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://homecheck:homecheck_secret@127.0.0.1:5432/homecheck",
    )
    dsn = db_url.replace("postgresql+asyncpg://", "postgresql://")

    logger.info("EMMA ingest starting (state=%s) …", state)

    raw_items = await _fetch_all_emma(state)
    if not raw_items:
        logger.warning("No EMMA data returned — nothing to upsert.")
        return

    conn: asyncpg.Connection = await asyncpg.connect(dsn)
    try:
        await _ensure_schema(conn)

        records: list[tuple] = []
        skipped = 0
        for item in raw_items:
            try:
                rec = await _build_record(item, state)
                if rec is None:
                    skipped += 1
                    continue
                records.append(rec)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Skipping EMMA item due to error: %s", exc)
                skipped += 1
                continue

        if skipped:
            logger.info("Skipped %d EMMA items.", skipped)

        inserted = await _upsert_records(conn, records)
        logger.info(
            "EMMA ingest complete. Upserted %d / %d records.",
            inserted,
            len(records),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("EMMA ingest failed with unexpected error: %s", exc)
    finally:
        await conn.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )
    asyncio.run(run())
