"""
GET  /api/journey       — return user's journey state from Firestore
POST /api/journey/phase — advance or update a phase
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import FirebaseUser, get_current_user

router = APIRouter(prefix="/api/v1")

class PhaseUpdate(BaseModel):
    phase_id: str
    status: str

@router.get("/journey")
async def get_journey(user: FirebaseUser=Depends(get_current_user)):
    """
    Returns journey + phase state for the authenticated user.
    Reads from Firestore — Firestore client will be wired in Weekend 1.
    """
    # TODO Weekend 1: wire Firestore client
    # journey_ref = db.collection("journeys").document(user.uid)
    # phases_ref  = db.collection("phases").document(user.uid).collections()
    return {
        "uid": user.uid,
        "currentPhase": "readiness",
        "phases": [],
    }


@router.post("/journey/phase")
async def update_phase(body: PhaseUpdate, user: FirebaseUser = Depends(get_current_user),):
    """Advance a phase status. Called by Next.js when user completes a phase."""
    # TODO Weekend 1: write to Firestore
    return {"uid": user.uid, "phase_id": body.phase_id, "status": body.status}