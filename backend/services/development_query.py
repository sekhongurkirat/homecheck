"""
services/development_query.py
------------------------------
PostGIS-backed future-development proximity queries.

Queries the `future_development` table for MUD districts and bond issuances
near a given coordinate and returns classified DevelopmentFlag objects.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

import databases

from models import DevelopmentFlag

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Risk classification thresholds
# ---------------------------------------------------------------------------

# Red: very close AND very recent
_RED_DISTANCE_M = 500
_RED_MUD_AGE_YEARS = 3

# Yellow: somewhat close OR moderately recent
_YELLOW_DISTANCE_M = 1500
_YELLOW_MUD_AGE_YEARS = 7


def _classify(
    dev_type: str,
    distance_m: float,
    formed_year: int | None,
    last_bond_year: int | None,
    current_year: int | None = None,
) -> str:
    """
    Return 'red', 'yellow', or 'green' based on proximity and recency.

    Red rules
    ---------
    - MUD district formed within 3 years AND within 500 m
    - Active bond issuance within 500 m

    Yellow rules
    ------------
    - MUD district formed within 7 years AND within 1 500 m
    - Any bond issuance within 1 500 m

    Green
    -----
    - Everything else within the search radius
    """
    if current_year is None:
        current_year = datetime.now().year

    if dev_type == "mud_district":
        age = (current_year - formed_year) if formed_year is not None else 9999
        if age <= _RED_MUD_AGE_YEARS and distance_m <= _RED_DISTANCE_M:
            return "red"
        if age <= _YELLOW_MUD_AGE_YEARS and distance_m <= _YELLOW_DISTANCE_M:
            return "yellow"

    elif dev_type == "bond_issuance":
        if distance_m <= _RED_DISTANCE_M:
            return "red"
        if distance_m <= _YELLOW_DISTANCE_M:
            return "yellow"

    return "green"


def _build_summary(flag: DevelopmentFlag) -> str:
    """Return a one-sentence human-readable summary for a single flag."""
    parts: list[str] = []

    if flag.name:
        parts.append(flag.name)
    elif flag.dev_type == "mud_district":
        parts.append("Utility district")
    else:
        parts.append("Bond issuance")

    if flag.formed_year:
        parts[-1] += f" formed {flag.formed_year}"

    dist_str = (
        f"{flag.distance_m / 1000:.1f} km"
        if flag.distance_m >= 1000
        else f"{round(flag.distance_m)} m"
    )
    parts.append(f"{dist_str} away")

    if flag.bond_amount_usd:
        amount = flag.bond_amount_usd
        if amount >= 1_000_000:
            amount_str = f"${amount / 1_000_000:.0f}M"
        else:
            amount_str = f"${amount:,}"
        parts.append(f"Active bond issuance: {amount_str}")

    return ". ".join(parts) + "."


# ---------------------------------------------------------------------------
# Main query
# ---------------------------------------------------------------------------

async def query_development(
    db: databases.Database,
    lat: float,
    lng: float,
    radius_m: int = 3000,
) -> list[DevelopmentFlag]:
    """
    Find all future_development features within *radius_m* metres of (lat, lng).

    Parameters
    ----------
    db       : async databases.Database connection
    lat, lng : WGS-84 coordinates of the subject property
    radius_m : search radius in metres (default 3 000 m)

    Returns
    -------
    list[DevelopmentFlag] sorted by distance ascending
    """
    query = """
        SELECT
            dev_type,
            name,
            status,
            formed_year,
            last_bond_year,
            bond_amount_usd,
            ST_AsGeoJSON(geom)::text                    AS geojson,
            ST_Distance(
                geom::geography,
                ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography
            )                                           AS distance_m
        FROM future_development
        WHERE
            ST_DWithin(
                geom::geography,
                ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                :radius_m
            )
        ORDER BY distance_m ASC
        LIMIT 100
    """

    rows = await db.fetch_all(
        query,
        values={"lat": lat, "lng": lng, "radius_m": radius_m},
    )

    flags: list[DevelopmentFlag] = []
    for row in rows:
        dist = float(row["distance_m"])
        dev_type: str = row["dev_type"]
        formed_year: int | None = row["formed_year"]
        last_bond_year: int | None = row["last_bond_year"]
        bond_amount: int | None = row["bond_amount_usd"]

        risk = _classify(dev_type, dist, formed_year, last_bond_year)

        # Build a partial flag first so _build_summary can use it
        flag = DevelopmentFlag(
            dev_type=dev_type,
            status=risk,
            distance_m=round(dist, 1),
            name=row["name"],
            formed_year=formed_year,
            last_bond_year=last_bond_year,
            bond_amount_usd=bond_amount,
            summary="",  # filled below
            geojson=json.loads(row["geojson"]),
        )
        flag.summary = _build_summary(flag)
        flags.append(flag)

    return flags


# ---------------------------------------------------------------------------
# Aggregate summary
# ---------------------------------------------------------------------------

def generate_development_summary(flags: list[DevelopmentFlag]) -> str:
    """
    Return a concise human-readable summary of a collection of DevelopmentFlags.

    Examples
    --------
    "2 active development districts within 1.5 km — construction likely within 2–5 years."
    "No nearby development activity detected."
    """
    if not flags:
        return "No nearby development activity detected."

    mud_flags = [f for f in flags if f.dev_type == "mud_district"]
    bond_flags = [f for f in flags if f.dev_type == "bond_issuance"]
    red_flags = [f for f in flags if f.status == "red"]
    yellow_flags = [f for f in flags if f.status == "yellow"]

    parts: list[str] = []

    total = len(flags)
    max_dist = max(f.distance_m for f in flags)
    max_dist_str = (
        f"{max_dist / 1000:.1f} km" if max_dist >= 1000 else f"{round(max_dist)} m"
    )

    if mud_flags:
        parts.append(
            f"{len(mud_flags)} utility district{'s' if len(mud_flags) > 1 else ''}"
        )
    if bond_flags:
        parts.append(
            f"{len(bond_flags)} bond issuance{'s' if len(bond_flags) > 1 else ''}"
        )

    summary = ", ".join(parts) if parts else f"{total} development feature(s)"
    summary += f" within {max_dist_str}"

    if red_flags:
        summary += " — imminent development likely within 1–3 years"
    elif yellow_flags:
        summary += " — construction likely within 2–5 years"
    else:
        summary += " — low near-term impact expected"

    return summary + "."
