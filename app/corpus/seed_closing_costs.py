"""
Seed Firestore with state-by-state closing cost data.

Run once using below:
  python -m app.corpus.seed_closing_costs

Annual update:
  Edit STATES below, re-run.
"""
import asyncio
from datetime import datetime, timezone
from google.cloud import firestore

from app.tools.closing_cost import _FALLBACK_STATES, _SOURCE, _SOURCE_URL



async def seed():
    db = firestore.AsyncClient()

    # ── Parent document: closing_costs/2025 
    year_ref = db.collection("gavnest/agent/closing_costs").document("2025")
    await year_ref.set({
        "year":       2025,
        "source":     _SOURCE,
        "source_url": _SOURCE_URL,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    print("✓ Written: closing_costs/2025")

    # ── State documents: closing_costs/2025/states/{state_code} 
    for state_code, data in _FALLBACK_STATES.items():
        ref = year_ref.collection("states").document(state_code)
        await ref.set({
            **data,
            "state_code": state_code,
            "source":     _SOURCE,
        })
        print(f"✓ Written: {state_code} — transfer tax {data['transfer_tax_pct']}%, total ~{data['total_pct']}%")

    print(f"\n✅ Seeded {len(_FALLBACK_STATES)} states.")
    print("   Path: closing_costs/2025/states/{state_code}")


if __name__ == "__main__":
    asyncio.run(seed())