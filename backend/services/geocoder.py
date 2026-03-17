import logging
import os
import urllib.parse

import httpx
from fastapi import HTTPException

logger = logging.getLogger(__name__)

MAPBOX_TOKEN = os.getenv("MAPBOX_TOKEN", "")
MAPBOX_URL = "https://api.mapbox.com/geocoding/v5/mapbox.places/{query}.json"

# Fallback: Nominatim (works from host network, may 403 from some container IPs)
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_HEADERS = {"User-Agent": "HomeCheck/0.1 (homecheck-app)"}


async def geocode(address: str) -> tuple[float, float]:
    """
    Geocode *address* to (latitude, longitude).

    Uses Mapbox Geocoding if MAPBOX_TOKEN is set, otherwise falls back to Nominatim.
    """
    if MAPBOX_TOKEN and not MAPBOX_TOKEN.startswith("pk.your_"):
        return await _geocode_mapbox(address)
    return await _geocode_nominatim(address)


async def _geocode_mapbox(address: str) -> tuple[float, float]:
    url = MAPBOX_URL.format(query=urllib.parse.quote(address))
    params = {"access_token": MAPBOX_TOKEN, "limit": 1, "types": "address,place"}
    logger.info("Geocoding via Mapbox: %r", address)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.error("Mapbox geocoding error: %s", exc)
        raise HTTPException(status_code=502, detail="Geocoding service returned an error.")
    except httpx.RequestError as exc:
        logger.error("Mapbox request error: %s", exc)
        raise HTTPException(status_code=502, detail="Could not reach geocoding service.")

    features = r.json().get("features", [])
    if not features:
        raise HTTPException(status_code=404, detail=f"Address not found: {address!r}")

    lng, lat = features[0]["geometry"]["coordinates"]
    logger.info("Geocoded %r → (%.6f, %.6f)", address, lat, lng)
    return float(lat), float(lng)


async def _geocode_nominatim(address: str) -> tuple[float, float]:
    params = {"q": address, "format": "json", "limit": 1}
    logger.info("Geocoding via Nominatim: %r", address)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(NOMINATIM_URL, params=params, headers=NOMINATIM_HEADERS)
            r.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.error("Nominatim error: %s", exc)
        raise HTTPException(status_code=502, detail="Geocoding service returned an error.")
    except httpx.RequestError as exc:
        logger.error("Nominatim request error: %s", exc)
        raise HTTPException(status_code=502, detail="Could not reach geocoding service.")

    results = r.json()
    if not results:
        raise HTTPException(status_code=404, detail=f"Address not found: {address!r}")

    return float(results[0]["lat"]), float(results[0]["lon"])
