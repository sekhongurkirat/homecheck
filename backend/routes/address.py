"""
routes/address.py
-----------------
Address autocomplete / suggestion endpoint using Mapbox Geocoding API.
"""

from __future__ import annotations

import logging
import os
import urllib.parse

import httpx
from fastapi import APIRouter, Query

logger = logging.getLogger(__name__)

router = APIRouter(tags=["address"])

MAPBOX_TOKEN = os.getenv("MAPBOX_TOKEN", "")
MAPBOX_GEOCODE_URL = "https://api.mapbox.com/geocoding/v5/mapbox.places/{query}.json"

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_HEADERS = {"User-Agent": "HomeCheck/0.1 (homecheck-app)"}


@router.get("/address/suggest")
async def suggest_addresses(
    q: str = Query(..., min_length=3, description="Partial address to autocomplete"),
) -> list[dict]:
    """
    Return up to 5 address suggestions for a partial query string.
    Uses Mapbox if token is available, otherwise falls back to Nominatim.
    """
    if MAPBOX_TOKEN and not MAPBOX_TOKEN.startswith("pk.your_"):
        return await _suggest_mapbox(q)
    return await _suggest_nominatim(q)


async def _suggest_mapbox(query: str) -> list[dict]:
    url = MAPBOX_GEOCODE_URL.format(query=urllib.parse.quote(query))
    params = {
        "access_token": MAPBOX_TOKEN,
        "autocomplete": "true",
        "limit": 5,
        "types": "address,place,postcode",
        "country": "US",
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        logger.warning("Mapbox suggest error: %s", exc)
        return []

    features = r.json().get("features", [])
    return [
        {
            "address": feat["place_name"],
            "lat": feat["geometry"]["coordinates"][1],
            "lng": feat["geometry"]["coordinates"][0],
        }
        for feat in features
    ]


async def _suggest_nominatim(query: str) -> list[dict]:
    params = {
        "q": query,
        "format": "json",
        "limit": 5,
        "countrycodes": "us",
        "addressdetails": 1,
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                NOMINATIM_URL, params=params, headers=NOMINATIM_HEADERS
            )
            r.raise_for_status()
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        logger.warning("Nominatim suggest error: %s", exc)
        return []

    return [
        {
            "address": item["display_name"],
            "lat": float(item["lat"]),
            "lng": float(item["lon"]),
        }
        for item in r.json()
    ]
