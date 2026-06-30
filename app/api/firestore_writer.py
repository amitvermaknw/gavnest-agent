"""
Firestore writer — the ONLY module allowed to write user data to Firestore.
See CLAUDE.md "Firestore data model — EXACT paths" for the canonical schema.

gavnest/agent/users/{uid}/
  profile/data    ← merged document, all profile fields (update_profile)
  phases/data     ← currentPhase + phases array (advance_phase)
  actions/{id}    ← write_action
  insights/{id}   ← write_insight
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import firebase_admin

logger = logging.getLogger(__name__)

#Firestore client - built from firebase_admin's already-resolved credentials,
#so it can only exist once app.main has initialized the Firebase app. No
#try/except here: if init never happened or credentials are bad, this raises
#immediately instead of letting callers silently no-op.
_db = None

def _get_db():
    global _db
    if _db is None:
        from google.cloud import firestore
        app = firebase_admin.get_app()  # raises ValueError if not yet initialized
        _db = firestore.AsyncClient(
            project=app.project_id,
            credentials=app.credential.get_credential(),
        )
    return _db

async def update_profile(uid: str, fields: dict) -> None:
    """Merge fields into gavnest/agent/users/{uid}/profile/data. Raises on failure."""
    try:
        db = _get_db()
        ref = db.collection("gavnest/agent/users").document(uid).collection("profile").document("data")
        await ref.set(fields, merge=True)
    except Exception as e:
        logger.error(f"update_profile failed for uid={uid}: {e}", exc_info=True)
        raise

async def advance_phase(uid: str, current_phase: int) -> None:
    """Mark current_phase done and current_phase+1 active in gavnest/agent/users/{uid}/phases/data. Raises on failure."""
    if current_phase >= 6:
        return

    try:
        db = _get_db()
        phase_ref = db.collection("gavnest/agent/users").document(uid).collection("phases").document("data")
        snap = await phase_ref.get()
        if not snap.exists:
            raise RuntimeError(f"phases/data does not exist for uid={uid}")

        data = snap.to_dict()
        updated_phases = []
        for p in data["phases"]:
            if p["num"] == current_phase:
                p["status"], p["state"] = "Completed", "done"
            elif p["num"] == current_phase + 1:
                p["status"], p["state"] = "In progress", "active"
            updated_phases.append(p)

        # update() not set() — keeps any other fields on the document intact
        await phase_ref.update({"currentPhase": current_phase + 1, "phases": updated_phases})
        logger.info(f"advance_phase succeeded for uid={uid}: currentPhase {current_phase} -> {current_phase + 1}")
    except Exception as e:
        logger.error(f"advance_phase failed for uid={uid}: {e}", exc_info=True)
        raise

async def write_insight(uid: str, phase: int, message: str) -> None:
    """Write Gavvy's proactive insight to gavnest/agent/users/{uid}/insights — shows in the dashboard 'Gavvy's take' card. Raises on failure."""
    try:
        db = _get_db()
        await db.collection("gavnest/agent/users").document(uid).collection("insights").add({
            "message":   message,
            "phase":     phase,
            "read":      False,
            "createdAt": datetime.now(timezone.utc),
        })
    except Exception as e:
        logger.error(f"write_insight failed for uid={uid}: {e}", exc_info=True)
        raise

async def write_action(uid: str, phase: int, action: dict) -> None:
    """Write one Gavvy-generated action to gavnest/agent/users/{uid}/actions. action = {title, description, urgency}. Raises on failure."""
    try:
        db = _get_db()
        await db.collection("gavnest/agent/users").document(uid).collection("actions").add({
            **action,
            "phase":     phase,
            "completed": False,
            "createdAt": datetime.now(timezone.utc),
        })
    except Exception as e:
        logger.error(f"write_action failed for uid={uid}: {e}", exc_info=True)
        raise
