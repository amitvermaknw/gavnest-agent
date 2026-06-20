"""
Closing cost calculator — state-by-state buyer closing cost estimates.

Primary source: Firestore  closing_costs/2025/states/{state_code}
Fallback: same values hardcoded below if Firestore unreachable

Data source: LodeStar 2026 Purchase Mortgage Closing Cost Data Report
             + state transfer tax schedules

Closing costs categorized into:
  Fixed fees       — origination, credit check, appraisal (similar nationally ~$1,500-2,500)
  Title insurance  — varies by state regulation, % of purchase price
  Transfer taxes   — state-imposed, biggest source of variance
  Recording fees   — local government, varies by state
  Prepaids         — first year insurance + tax escrow

Annual update: edit values in seed_closing_costs.py, re-run.
"""
from __future__ import annotations

# ── Fallback state data
# All percentages applied to purchase price. Fixed fees are flat $ amounts.
# Source: LodeStar 2026 Closing Cost Data Report (national averages by state)
# Keep in sync with seed_closing_costs.py

_FALLBACK_STATES = {
    # state_code: { transfer_tax_pct, title_insurance_pct, recording_fees_flat, total_pct_estimate }
    "AL": {"transfer_tax_pct": 0.10, "title_insurance_pct": 0.55, "recording_fees": 200, "total_pct": 1.10, "name": "Alabama"},
    "AK": {"transfer_tax_pct": 0.00, "title_insurance_pct": 0.50, "recording_fees": 200, "total_pct": 1.05, "name": "Alaska"},
    "AZ": {"transfer_tax_pct": 0.00, "title_insurance_pct": 0.55, "recording_fees": 150, "total_pct": 0.90, "name": "Arizona"},
    "AR": {"transfer_tax_pct": 0.33, "title_insurance_pct": 0.45, "recording_fees": 200, "total_pct": 1.25, "name": "Arkansas"},
    "CA": {"transfer_tax_pct": 0.11, "title_insurance_pct": 0.50, "recording_fees": 350, "total_pct": 1.05, "name": "California"},
    "CO": {"transfer_tax_pct": 0.01, "title_insurance_pct": 0.50, "recording_fees": 200, "total_pct": 0.85, "name": "Colorado"},
    "CT": {"transfer_tax_pct": 1.25, "title_insurance_pct": 0.55, "recording_fees": 250, "total_pct": 2.35, "name": "Connecticut"},
    "DE": {"transfer_tax_pct": 2.50, "title_insurance_pct": 0.50, "recording_fees": 300, "total_pct": 3.55, "name": "Delaware"},
    "DC": {"transfer_tax_pct": 1.45, "title_insurance_pct": 0.55, "recording_fees": 400, "total_pct": 2.85, "name": "District of Columbia"},
    "FL": {"transfer_tax_pct": 0.70, "title_insurance_pct": 0.58, "recording_fees": 250, "total_pct": 1.85, "name": "Florida"},
    "GA": {"transfer_tax_pct": 0.10, "title_insurance_pct": 0.50, "recording_fees": 200, "total_pct": 1.10, "name": "Georgia"},
    "HI": {"transfer_tax_pct": 0.10, "title_insurance_pct": 0.60, "recording_fees": 250, "total_pct": 1.15, "name": "Hawaii"},
    "ID": {"transfer_tax_pct": 0.00, "title_insurance_pct": 0.50, "recording_fees": 150, "total_pct": 0.85, "name": "Idaho"},
    "IL": {"transfer_tax_pct": 0.10, "title_insurance_pct": 0.55, "recording_fees": 250, "total_pct": 1.20, "name": "Illinois"},
    "IN": {"transfer_tax_pct": 0.00, "title_insurance_pct": 0.45, "recording_fees": 200, "total_pct": 0.85, "name": "Indiana"},
    "IA": {"transfer_tax_pct": 0.16, "title_insurance_pct": 0.45, "recording_fees": 200, "total_pct": 1.05, "name": "Iowa"},
    "KS": {"transfer_tax_pct": 0.00, "title_insurance_pct": 0.50, "recording_fees": 200, "total_pct": 0.95, "name": "Kansas"},
    "KY": {"transfer_tax_pct": 0.10, "title_insurance_pct": 0.50, "recording_fees": 200, "total_pct": 1.10, "name": "Kentucky"},
    "LA": {"transfer_tax_pct": 0.00, "title_insurance_pct": 0.55, "recording_fees": 200, "total_pct": 1.00, "name": "Louisiana"},
    "ME": {"transfer_tax_pct": 0.44, "title_insurance_pct": 0.50, "recording_fees": 200, "total_pct": 1.45, "name": "Maine"},
    "MD": {"transfer_tax_pct": 1.40, "title_insurance_pct": 0.55, "recording_fees": 350, "total_pct": 2.65, "name": "Maryland"},
    "MA": {"transfer_tax_pct": 0.46, "title_insurance_pct": 0.55, "recording_fees": 250, "total_pct": 1.55, "name": "Massachusetts"},
    "MI": {"transfer_tax_pct": 0.86, "title_insurance_pct": 0.50, "recording_fees": 200, "total_pct": 1.85, "name": "Michigan"},
    "MN": {"transfer_tax_pct": 0.33, "title_insurance_pct": 0.50, "recording_fees": 250, "total_pct": 1.30, "name": "Minnesota"},
    "MS": {"transfer_tax_pct": 0.00, "title_insurance_pct": 0.55, "recording_fees": 150, "total_pct": 0.95, "name": "Mississippi"},
    "MO": {"transfer_tax_pct": 0.00, "title_insurance_pct": 0.50, "recording_fees": 150, "total_pct": 0.80, "name": "Missouri"},
    "MT": {"transfer_tax_pct": 0.00, "title_insurance_pct": 0.50, "recording_fees": 200, "total_pct": 0.85, "name": "Montana"},
    "NE": {"transfer_tax_pct": 0.23, "title_insurance_pct": 0.45, "recording_fees": 200, "total_pct": 1.10, "name": "Nebraska"},
    "NV": {"transfer_tax_pct": 0.51, "title_insurance_pct": 0.55, "recording_fees": 250, "total_pct": 1.60, "name": "Nevada"},
    "NH": {"transfer_tax_pct": 1.50, "title_insurance_pct": 0.55, "recording_fees": 200, "total_pct": 2.45, "name": "New Hampshire"},
    "NJ": {"transfer_tax_pct": 1.00, "title_insurance_pct": 0.55, "recording_fees": 250, "total_pct": 2.05, "name": "New Jersey"},
    "NM": {"transfer_tax_pct": 0.00, "title_insurance_pct": 0.55, "recording_fees": 200, "total_pct": 1.00, "name": "New Mexico"},
    "NY": {"transfer_tax_pct": 1.83, "title_insurance_pct": 0.55, "recording_fees": 400, "total_pct": 2.95, "name": "New York"},
    "NC": {"transfer_tax_pct": 0.20, "title_insurance_pct": 0.50, "recording_fees": 200, "total_pct": 1.20, "name": "North Carolina"},
    "ND": {"transfer_tax_pct": 0.00, "title_insurance_pct": 0.45, "recording_fees": 150, "total_pct": 0.80, "name": "North Dakota"},
    "OH": {"transfer_tax_pct": 0.40, "title_insurance_pct": 0.50, "recording_fees": 250, "total_pct": 1.35, "name": "Ohio"},
    "OK": {"transfer_tax_pct": 0.15, "title_insurance_pct": 0.50, "recording_fees": 200, "total_pct": 1.10, "name": "Oklahoma"},
    "OR": {"transfer_tax_pct": 0.00, "title_insurance_pct": 0.50, "recording_fees": 200, "total_pct": 0.95, "name": "Oregon"},
    "PA": {"transfer_tax_pct": 2.00, "title_insurance_pct": 0.55, "recording_fees": 300, "total_pct": 3.10, "name": "Pennsylvania"},
    "RI": {"transfer_tax_pct": 0.46, "title_insurance_pct": 0.55, "recording_fees": 250, "total_pct": 1.55, "name": "Rhode Island"},
    "SC": {"transfer_tax_pct": 0.37, "title_insurance_pct": 0.50, "recording_fees": 200, "total_pct": 1.40, "name": "South Carolina"},
    "SD": {"transfer_tax_pct": 0.10, "title_insurance_pct": 0.40, "recording_fees": 150, "total_pct": 0.75, "name": "South Dakota"},
    "TN": {"transfer_tax_pct": 0.37, "title_insurance_pct": 0.50, "recording_fees": 200, "total_pct": 1.35, "name": "Tennessee"},
    "TX": {"transfer_tax_pct": 0.00, "title_insurance_pct": 0.55, "recording_fees": 200, "total_pct": 0.95, "name": "Texas"},
    "UT": {"transfer_tax_pct": 0.00, "title_insurance_pct": 0.50, "recording_fees": 200, "total_pct": 0.90, "name": "Utah"},
    "VT": {"transfer_tax_pct": 1.25, "title_insurance_pct": 0.55, "recording_fees": 200, "total_pct": 2.15, "name": "Vermont"},
    "VA": {"transfer_tax_pct": 0.33, "title_insurance_pct": 0.50, "recording_fees": 250, "total_pct": 1.30, "name": "Virginia"},
    "WA": {"transfer_tax_pct": 1.28, "title_insurance_pct": 0.55, "recording_fees": 300, "total_pct": 2.30, "name": "Washington"},
    "WV": {"transfer_tax_pct": 0.44, "title_insurance_pct": 0.50, "recording_fees": 200, "total_pct": 1.40, "name": "West Virginia"},
    "WI": {"transfer_tax_pct": 0.30, "title_insurance_pct": 0.50, "recording_fees": 200, "total_pct": 1.25, "name": "Wisconsin"},
    "WY": {"transfer_tax_pct": 0.00, "title_insurance_pct": 0.50, "recording_fees": 150, "total_pct": 0.85, "name": "Wyoming"},
}

# Fixed lender fees — relatively consistent nationally
_LENDER_FEES = {
    "loan_origination": 1200,  # 0.5-1% of loan, capped here for fixed estimate
    "credit_check":     50,
    "appraisal":        600,
    "underwriting":     400,
    "processing":       400,
}

_SOURCE = "LodeStar 2026 Purchase Mortgage Closing Cost Report + state transfer tax schedules"
_SOURCE_URL = "https://lodestarss.com/"
_FIRESTORE_YEAR = 2025


# ── Firestore read 

async def _read_state_from_firestore(state_code: str) -> dict | None:
    """Read closing cost data for one state from Firestore."""
    try:
        from google.cloud import firestore
        db = firestore.AsyncClient()
        ref = (
            db.collection("closing_costs")
              .document(str(_FIRESTORE_YEAR))
              .collection("states")
              .document(state_code.upper())
        )
        doc = await ref.get()
        if doc.exists:
            return doc.to_dict()
    except Exception as e:
        print(f"[CLOSING_COSTS] Firestore read failed for {state_code}: {e}")
    return None


# ── Public API 

async def calculate_closing_costs(
    purchase_price: float,
    state_code: str,
    loan_amount: float | None = None,
) -> dict:
    """
    Calculate buyer closing costs for a purchase.

    Args:
        purchase_price: Property purchase price in USD
        state_code:     2-letter state code (e.g. "AZ", "NY", "CA")
        loan_amount:    Loan amount (defaults to 80% of purchase price)

    Returns:
        {
            "state": "Arizona",
            "state_code": "AZ",
            "purchase_price": 400000,
            "loan_amount": 320000,
            "breakdown": {
                "loan_origination": 1200,
                "title_insurance":  2200,
                "transfer_tax":     0,
                "recording_fees":   150,
                "prepaid_interest": 1097,
                "homeowners_insurance": 1200,
                "property_tax_escrow": 1333,
                ...
            },
            "total_closing_costs": 7180,
            "pct_of_purchase":     1.80,
            "source": "LodeStar..."
        }
    """
    state_code = state_code.upper().strip()

    # Look up state data — Firestore first, then fallback
    state_data = await _read_state_from_firestore(state_code) or _FALLBACK_STATES.get(state_code)

    if not state_data:
        # Unknown state — used national average ~1.6%
        return {
            "state":      "Unknown",
            "state_code": state_code,
            "purchase_price": purchase_price,
            "error":      f"State code '{state_code}' not recognized. Returning national average estimate.",
            "total_closing_costs": purchase_price * 0.016,
            "pct_of_purchase":     1.6,
            "source": _SOURCE,
            "source_url": _SOURCE_URL,
        }

    if loan_amount is None:
        loan_amount = purchase_price * 0.80

    # ── Lender fees (fixed) 
    loan_origination = _LENDER_FEES["loan_origination"]
    credit_check     = _LENDER_FEES["credit_check"]
    appraisal        = _LENDER_FEES["appraisal"]
    underwriting     = _LENDER_FEES["underwriting"]
    processing       = _LENDER_FEES["processing"]

    # ── State-driven fees 
    title_insurance  = purchase_price * (state_data["title_insurance_pct"] / 100)
    transfer_tax     = purchase_price * (state_data["transfer_tax_pct"]    / 100)
    recording_fees   = state_data["recording_fees"]

    # ── Prepaids (typical first-year estimates) 
    # Mortgage interest for ~15 days at 6.5%
    prepaid_interest      = (loan_amount * 0.065 / 365) * 15
    # Homeowners insurance ~0.3% of purchase annually
    homeowners_insurance  = purchase_price * 0.003
    # Property tax escrow ~2 months at ~1% annually
    property_tax_escrow   = (purchase_price * 0.01) / 12 * 2

    breakdown = {
        "loan_origination":     round(loan_origination, 0),
        "credit_check":         round(credit_check, 0),
        "appraisal":            round(appraisal, 0),
        "underwriting":         round(underwriting, 0),
        "processing":           round(processing, 0),
        "title_insurance":      round(title_insurance, 0),
        "transfer_tax":         round(transfer_tax, 0),
        "recording_fees":       round(recording_fees, 0),
        "prepaid_interest":     round(prepaid_interest, 0),
        "homeowners_insurance": round(homeowners_insurance, 0),
        "property_tax_escrow":  round(property_tax_escrow, 0),
    }

    total = sum(breakdown.values())
    pct_of_purchase = round((total / purchase_price) * 100, 2)

    return {
        "state":            state_data.get("name", state_code),
        "state_code":       state_code,
        "purchase_price":   purchase_price,
        "loan_amount":      loan_amount,
        "breakdown":        breakdown,
        "total_closing_costs": round(total, 0),
        "pct_of_purchase":  pct_of_purchase,
        "transfer_tax_rate": state_data["transfer_tax_pct"],
        "source":           state_data.get("source", _SOURCE),
        "source_url":       _SOURCE_URL,
    }


def extract_state_code(location_string: str) -> str:
    """
    Extract a 2-letter state code from a location string.
    Returns 'XX' if not found.

    Examples:
      "Phoenix AZ"           → "AZ"
      "Washington DC 20500"  → "DC"
      "New York, NY"         → "NY"
    """
    if not location_string:
        return "XX"

    # Try matching any 2-letter state code as a standalone word
    import re
    tokens = re.findall(r"\b([A-Z]{2})\b", location_string.upper())
    for token in tokens:
        if token in _FALLBACK_STATES:
            return token

    return "XX"