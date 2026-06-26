from datetime import datetime, timezone

#Firestore client - initialized lazily so local dev without
#GCP credentials doesn't crash the whole app
_db = None

def _get_db():
    global _db
    if _db is None:
        try:
            from google.cloud import firestore
            _db = firestore.AsyncClient()
        except Exception as e:
            print(f"[FIRESTORE_WRITE_SKIPPED] No Firestore credentials available, writes are no-ops: {e}")
            _db = None
    return _db

async def write_actions_for_phase(uid: str, phase: int, actions: list[dict]) -> None:
    """
    Write Gavvy-generated actions to Firestore.
    Called by agent nodes after generating a response.

    Non-blocking — errors are swallowed so a write failure never crashes
    the agent (the chat reply has usually already streamed to the user).

    Each action dict:
    {
        "title":       "Provide your gross monthly income",
        "description": "Gavvy needs this to calculate your DTI ratio accurately",
        "urgency":     None   # or "Complete before next session"
    }
    """
    db = _get_db()
    if db is None:
        return

    try:
        actions_ref = db.collection('gavnest/agent/users').document(uid).collection('actions')
        for action in actions:
            await actions_ref.add({
                **action,
                "phase": phase,
                "completed": False,
                "createdAt": datetime.now(timezone.utc)
            })
    except Exception as e:
        print(f"[FIRESTORE_WRITE_ERROR] Failed to write actions for uid={uid}: {e}")

async def write_insight(uid: str, phase: int, message: str) -> None:
    """
    Write Gavvy's proactive insight to Firestore.
    Shows in the dashboard 'Gavvy's take' card.

    Non-blocking — errors are swallowed so a write failure never crashes
    the agent (the chat reply has usually already streamed to the user).
    """
    db = _get_db()
    if db is None:
        return

    try:
        await db.collection('gavnest/agent/users').document(uid) \
            .collection('insights').add({
                "message":   message,
                "phase":     phase,
                "read":      False,
                "createdAt": datetime.now(timezone.utc)
            })
    except Exception as e:
        print(f"[FIRESTORE_WRITE_ERROR] Failed to write insight for uid={uid}: {e}")
