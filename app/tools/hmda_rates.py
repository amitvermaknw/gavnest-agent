"""
HMDA rates tool — reads base rate data from Firestore, adjusts to live FRED rate.
 
Primary source: Firestore hmda_rates/2023/tiers/{tier}
Fallback: same values hardcoded below (only used if Firestore unreachable)
 
Rate adjustment logic:
  Firestore stores 2023 absolute rates. FRED gives us the current rate.
  We calculate the delta from the stored Excellent tier avg to current FRED,
  then apply that delta to all tiers — preserving real spreads between tiers.
 
  Example:
    Firestore Excellent avg = 6.82 (2023 base)
    Current FRED            = 6.37
    Delta                   = 6.37 - 6.82 = -0.45
    Adjusted Excellent      = 6.82 - 0.45 = 6.37
    Adjusted Good           = 6.94 - 0.45 = 6.49  (spread of +0.12% preserved)
    Adjusted Fair           = 7.18 - 0.45 = 6.73  (spread of +0.36% preserved)
    Adjusted Poor           = 7.65 - 0.45 = 7.20  (spread of +0.83% preserved)
 
Annual update: edit values in Firestore, re-run seed_hmda.py. No code change needed.
"""

from __future__ import annotations

# Keep in sync with what seed_hmda.py writes to Firestore.
_FALLBACK = {
    "Excellent": {"score_range": "760+",    "avg_rate": 6.82, "rate_low": 6.50, "rate_high": 7.10},
    "Good":      {"score_range": "720-759", "avg_rate": 6.94, "rate_low": 6.65, "rate_high": 7.25},
    "Fair":      {"score_range": "660-719", "avg_rate": 7.18, "rate_low": 6.90, "rate_high": 7.55},
    "Poor":      {"score_range": "620-659", "avg_rate": 7.65, "rate_low": 7.20, "rate_high": 8.10},
}
 
_SOURCE = "FHFA National Mortgage Database 2023"
_SOURCE_URL = "https://www.fhfa.gov/data/national-mortgage-database"
_FIRESTORE_YEAR = 2023

async def _read_all_tiers_from_firestore() -> dict | None:
    """
    Reads all four tier documents from Firestore concurrently.
    Returns dict keyed by tier name, or None if unavailable.
    """
    try:
        import asyncio
        from google.cloud import firestore

        db=firestore.AsyncClient()
        tiers = list(_FALLBACK.keys())

        refs = [
            db.collection("gavnest")
                .document("agent")
                .collection("hmda_rates")
                .document(str(_FIRESTORE_YEAR))
                .collection("tiers")
                .document(tier)
            for tier in tiers
        ]

        docs = await asyncio.gather(*[ref.get() for ref in refs])

        result = {}

        for tier, doc in zip(tiers, doc):
            if doc.existes:
                result[tier] = doc.to_dict()

        if len(result) == 4:
            print(f"[HMDA_TOOL] Loaded tier data from Firestore ({_FIRESTORE_YEAR})")
            return result
        
        print(f"[HMDA_TOOL] Firestore return {len(result)}/4 tiers using fallback ")

    except Exception as e:
        print(f"[HMDA_TOOL] Firestore unavaiable, using fallaback: {e}")
        return None
    
def _adjust_tiers(base: dict, current_30yr_rate: float) -> dict[str, dict]:
    """
    Adjusts stored rates to current FRED rate.
    Uses the Excellent tier avg_rate from base data as the anchor —
    so next year when Firestore is updated, the math stays correct automatically.
    """
    # Anchor comes from Firestore data, not a hardcoded constant
    excellent_base = base["Excellent"]["avg_rate"]
    delta = current_30yr_rate - excellent_base

    result = {}
    
    for tier, data in base.items():
        adj_mid = round(data["avg_rate"] + delta, 2)
        adj_low = round(data["rate_low"] + delta, 2)
        adj_high = round(data["rate_high"] + delta, 2)


        result[tier] = {
            "tier": tier,
            "score_rage": data["score_range"],
            "rate_mide": adj_mid,
            "rate_low": adj_low,
            "rate_high": adj_high,
            "monthly_payment_300k": _monthly_payment(300_000, adj_mid, 30),
            "source": data.get("source", _SOURCE),
            "source_url": _SOURCE_URL
        }

    return result

async def get_all_tiers(current_30yr_rate: float) -> dict[str, dict]:
    """
    Returns rate data for all four tiers adjusted to the current FRED rate.
    Reads from Firestore, falls back to hardcoded values if unavailable.
    """
    base = await _read_all_tiers_from_firestore() or _FALLBACK
    return _adjust_tiers(base, current_30yr_rate)

 
def get_cost_difference(
    excellent_rate: float,
    user_rate: float,
    loan_amount: float = 300_000,
) -> dict:
    """
    30-year total cost difference between Excellent tier and user's tier.
    Pass rate_mid values from  get_all_tiers().
    """
    monthly_excellent = _monthly_payment(loan_amount, excellent_rate, 30)
    monthly_user      = _monthly_payment(loan_amount, user_rate, 30)
    monthly_diff      = monthly_user - monthly_excellent
    return {
        "monthly_difference":     abs(monthly_diff),
        "total_30yr_difference":  abs(monthly_diff) * 360,
        "loan_amount":            loan_amount,
    }
 
 
def _monthly_payment(principal: float, annual_rate_pct: float, years: int) -> int:
    """Standard fixed-rate mortgage monthly payment formula."""
    r = (annual_rate_pct / 100) / 12
    n = years * 12
    if r == 0:
        return int(principal / n)
    return int(principal * (r * (1 + r) ** n) / ((1 + r) ** n - 1))
