"""
FRED API tool — fetches the current 30-year fixed mortgage rate.
 
Data source: Federal Reserve Economic Data (FRED)
Series used: MORTGAGE30US — Freddie Mac Primary Mortgage Market Survey
API docs: https://fred.stlouisfed.org/docs/api/fred/
 
Why FRED:
- Free, no quota limits for reasonable use
- Authoritative — this is the industry-standard benchmark
- Weekly data, updated every Thursday
- No API key required for public series (key optional, increases rate limits)
 
Returns a dict so the node can include it in tool_results and sources.
"""

from __future__ import annotations
import httpx
from datetime import datetime
from app.config import get_setting

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
SERIES_ID = "MORTGAGE30US"

def _headers()-> dict:
    """FRED V2 auth key in auth header"""
    settings = get_setting()
    return settings.fred_api_key

async def get_current_30yr_rate() -> dict:
    """
    Fetches the most recent 30-year fixed mortgage rate from FRED.
 
    Returns:
        {
            "rate": 6.87,              # float, percent
            "date": "2025-05-01",      # date of the observation
            "source": "FRED / Freddie Mac PMMS",
            "url": "https://fred.stlouisfed.org/series/MORTGAGE30US"
        }
 
    Raises:
        RuntimeError: if FRED is unreachable or returns no data
    """

    params = {
        "series_id": SERIES_ID,
        "api_key": _headers(),
        "sort_order": "desc",
        "limit": 1,
        "file_type": "json"
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(FRED_BASE, params=params)
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise RuntimeError(f"FRED API unreachable: {e}") from e
        
        
    data = response.json()
    observations = data.get("observations", [])

    if not observations:
        raise RuntimeError("FRED returned no observations for MORTGAGE30US")
    
    latest = observations[0]
    rate_str = latest.get("value", "")

    #FRED uses "." to indicate missing data
    if rate_str == "." or not rate_str:
        raise RuntimeError("FRED latest observation has no value")
    
    return {
        "rate": float(rate_str),
        "date": latest.get("date", "unknown"),
        "source": "FRED / Freddie Mac PMMS",
        "url": "https://fred.stlouisfed.org/series/MORTGAGE30US",
    }

async def get_rate_history(limit: int = 52) -> list[dict]:
    """
    Fetches the last N weekly observations (default 52 = 1 year).
    Used by the readiness agent to show rate trend context.
 
    Returns list of {"date": "...", "rate": 6.87} sorted oldest → newest.
    """
    params = {
        "series_id": SERIES_ID,
        "api_key": _headers(),
        "sort_order": "desc",
        "limit": limit,
        "file_type": "json",
    }
 
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(FRED_BASE, params=params)
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise RuntimeError(f"FRED API unreachable: {e}") from e
 
    data = response.json()
    observations = data.get("observations", [])
 
    history = []
    for obs in reversed(observations):   # oldest → newest
        val = obs.get("value", ".")
        if val != ".":
            history.append({
                "date": obs["date"],
                "rate": float(val),
            })
 
    return history