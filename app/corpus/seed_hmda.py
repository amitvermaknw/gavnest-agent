"""
Run this once to seed HMDA rate tier data into Firestore.

Usage:
  python -m app.corpus.seed_hmda

Requirements:
  - DEV_MODE=false OR GOOGLE_APPLICATION_CREDENTIALS set
  - Firestore enabled in your Firebase project

Command to Run: python -m app.corpus.seed_hmda
"""
import asyncio
from datetime import datetime, timezone
from google.cloud import firestore


TIERS = [
    {
        "id": "Excellent",
        "tier": "Excellent",
        "score_range": "760+",
        "avg_rate": 6.82,
        "rate_low": 6.50,
        "rate_high": 7.10,
    },
    {
        "id": "Good",
        "tier": "Good",
        "score_range": "720-759",
        "avg_rate": 6.94,
        "rate_low": 6.65,
        "rate_high": 7.25,
    },
    {
        "id": "Fair",
        "tier": "Fair",
        "score_range": "660-719",
        "avg_rate": 7.18,
        "rate_low": 6.90,
        "rate_high": 7.55,
    },
    {
        "id": "Poor",
        "tier": "Poor",
        "score_range": "620-659",
        "avg_rate": 7.65,
        "rate_low": 7.20,
        "rate_high": 8.10,
    },
]


async def seed():
    db = firestore.AsyncClient()

    # ── Write parent document: hmda_rates/2023 ────────────────────────────────
    year_ref = db.collection("gavnest/agent/hmda_rates").document("2023")
    await year_ref.set({
        "year": 2023,
        "source": "FHFA National Mortgage Database 2023",
        "source_url": "https://www.fhfa.gov/data/national-mortgage-database",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    print("✓ Written: hmda_rates/2023")

    # ── Write each tier: hmda_rates/2023/tiers/{tier} ─────────────────────────
    for tier in TIERS:
        tier_id = tier.pop("id")
        ref = year_ref.collection("tiers").document(tier_id)
        await ref.set(tier)
        print(f"✓ Written: hmda_rates/2023/tiers/{tier_id}  →  avg_rate={tier['avg_rate']}%")

    print("\n✅ Firestore seed complete.")
    print("   Path: hmda_rates/2023/tiers/{Excellent|Good|Fair|Poor}")
    print("   To update next year: edit TIERS above and re-run with --year 2024")


if __name__ == "__main__":
    asyncio.run(seed())
