"""
FEMA flood zone tool — lookup by address.

Flow:
  1. Geocode address → lat/lng using Census Geocoder (free, no key)
  2. Query FEMA NFHL ArcGIS REST API with lat/lng (free, no key)
  3. Return flood zone, SFHA status, and plain-English risk summary

Data source:
  FEMA National Flood Hazard Layer (NFHL)
  https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer
  The authoritative federal database used by banks and insurance companies.

Flood zone reference:
  High risk (SFHA — flood insurance required for federally-backed mortgages):
    A, AE, AH, AO, AR, A99  → 1% annual flood chance (100-year floodplain)
    V, VE                    → coastal high hazard

  Moderate risk:
    X (shaded)               → 0.2% annual flood chance (500-year floodplain)

  Low risk:
    X (unshaded)             → minimal flood hazard
    D                        → undetermined risk
"""
from __future__ import annotations

import httpx

# FEMA NFHL ArcGIS REST endpoint 
# Layer 28 = S_FLD_HAZ_AR (Special Flood Hazard Areas)
NFHL_URL = (
    "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query"
)

# Census Geocoder — free, no key required
CENSUS_GEOCODER_URL = (
    "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
)

# High-risk zones where flood insurance is federally required
SFHA_ZONES = {"A", "AE", "AH", "AO", "AR", "A99", "V", "VE"}

ZONE_DESCRIPTIONS = {
    "AE":  "High risk — 1% annual flood chance. Base Flood Elevation determined.",
    "A":   "High risk — 1% annual flood chance. No Base Flood Elevation determined.",
    "AH":  "High risk — shallow flooding (ponding), 1% annual chance.",
    "AO":  "High risk — shallow sheet-flow flooding, 1% annual chance.",
    "VE":  "Coastal high hazard — wave action + 1% annual flood chance.",
    "V":   "Coastal high hazard — wave action + 1% annual flood chance.",
    "X":   "Moderate to low risk. Outside the Special Flood Hazard Area.",
    "D":   "Undetermined flood risk. No flood analysis conducted.",
}


async def get_flood_zone(address: str) -> dict:
    """
    Looks up the FEMA flood zone for a US address.

    Args:
        address: full US address e.g. "123 Main St, Phoenix AZ 85001"

    Returns:
        {
            "address":      "123 Main St, Phoenix AZ 85001",
            "flood_zone":   "X",
            "sfha":         False,
            "risk_level":   "low",
            "description":  "Moderate to low risk...",
            "insurance_required": False,
            "source":       "FEMA NFHL",
            "source_url":   "https://msc.fema.gov/portal/home",
            "lat":          33.448,
            "lng":          -112.074,
        }

    Raises:
        RuntimeError: if geocoding fails or FEMA API is unreachable
    """
    # ── Step 1: geocode address → lat/lng
    lat, lng = await _geocode_address(address)

    # ── Step 2: query FEMA NFHL with lat/lng
    flood_data = await _query_nfhl(lat, lng)

    flood_zone = flood_data.get("flood_zone", "X")
    sfha = flood_zone.rstrip("0123456789") in SFHA_ZONES

    if sfha:
        risk_level = "high"
    elif flood_zone.startswith("X"):
        risk_level = "low"
    else:
        risk_level = "undetermined"

    return {
        "address":            address,
        "flood_zone":         flood_zone,
        "sfha":               sfha,
        "risk_level":         risk_level,
        "description":        ZONE_DESCRIPTIONS.get(flood_zone, f"Zone {flood_zone}"),
        "insurance_required": sfha,
        "firm_panel":         flood_data.get("firm_panel", ""),
        "source":             "FEMA National Flood Hazard Layer",
        "source_url":         "https://msc.fema.gov/portal/home",
        "lat":                lat,
        "lng":                lng,
    }


async def _geocode_address(address: str) -> tuple[float, float]:
    """
    Geocodes a US address using the Census Geocoder.
    Returns (lat, lng). Free, no key required.
    """
    params = {
        "address":   address,
        "benchmark": "Public_AR_Current",
        "format":    "json",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(CENSUS_GEOCODER_URL, params=params)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise RuntimeError(f"Census geocoder unreachable: {e}") from e

    data = resp.json()
    matches = data.get("result", {}).get("addressMatches", [])

    if not matches:
        raise RuntimeError(
            f"Could not geocode address: '{address}'. "
            "Try adding city, state, and ZIP code."
        )

    coords = matches[0]["coordinates"]
    return float(coords["y"]), float(coords["x"])   # lat, lng


async def _query_nfhl(lat: float, lng: float) -> dict:
    """
    Queries FEMA NFHL ArcGIS REST API with coordinates.
    Returns flood zone and FIRM panel data.
    """
    params = {
        "geometry":       f"{lng},{lat}",
        "geometryType":   "esriGeometryPoint",
        "inSR":           "4326",
        "spatialRel":     "esriSpatialRelIntersects",
        "outFields":      "FLD_ZONE,FIRM_PANEL,ZONE_SUBTY",
        "returnGeometry": "false",
        "f":              "json",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(NFHL_URL, params=params)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise RuntimeError(f"FEMA NFHL API unreachable: {e}") from e

    data = resp.json()
    features = data.get("features", [])

    if not features:
        # No NFHL data for this location — likely unmapped area, treat as low risk
        return {"flood_zone": "X", "firm_panel": ""}

    attrs = features[0].get("attributes", {})
    return {
        "flood_zone": attrs.get("FLD_ZONE", "X"),
        "firm_panel": attrs.get("FIRM_PANEL", ""),
        "zone_subtype": attrs.get("ZONE_SUBTY", ""),
    }