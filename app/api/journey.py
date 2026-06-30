"""
GET  /api/journey            — return user's journey state from Firestore
POST /api/journey/phase      — advance or update a phase
POST /api/journey/next-step  — guided wizard step for a phase (e.g. readiness check)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.firestore_writer import advance_phase, update_profile, write_insight
from app.auth import FirebaseUser, get_current_user
from app.services.readiness import compute_readiness

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")

class PhaseUpdate(BaseModel):
    phase_id: str
    status: str


class NextStepRequest(BaseModel):
    phase_id: str
    answers:  dict = Field(default_factory=dict)


class NextStepResponse(BaseModel):
    done:        bool
    question_id: str | None
    label:       str | None
    helper:      str | None
    input_type:  str | None
    placeholder: str | None
    choices:     list[str] | None
    progress:    dict
    summary:     dict | None


# ── Guided wizard questions ──────────────────────────────────────────────
# One question per Firestore profile field collected by the readiness flow
# (see gavnest-web CLAUDE.md "Firestore data model" — grossMonthlyIncome,
# monthlyDebts, liquidSavings, employmentStatus).
READINESS_QUESTIONS = [
    {
        "question_id": "gross_monthly_income",
        "label":       "What's your gross monthly income?",
        "helper":      "Before taxes, including all reliable income sources.",
        "input_type":  "currency",
        "placeholder": "8000",
        "choices":     None,
    },
    {
        "question_id": "monthly_debts",
        "label":       "How much do you pay monthly toward debts?",
        "helper":      "Car loans, credit cards, student loans (not rent/mortgage)",
        "input_type":  "currency",
        "placeholder": "500",
        "choices":     None,
    },
    {
        "question_id": "liquid_savings",
        "label":       "How much do you have saved for a down payment and closing costs?",
        "helper":      "Cash, checking/savings, or investments you could access soon.",
        "input_type":  "currency",
        "placeholder": "20000",
        "choices":     None,
    },
    {
        "question_id": "employment_status",
        "label":       "What's your employment status?",
        "helper":      "This affects how lenders evaluate your income stability.",
        "input_type":  "choice",
        "placeholder": None,
        "choices":     ["W-2 employee", "Self-employed", "1099 contractor", "Retired", "Other"],
    },
]

PHASE_QUESTIONS = {
    "readiness": READINESS_QUESTIONS,
}

READINESS_PHASE_NUM = 1  # "readiness" is phase 1 in phases/data (see gavvy-web lib/firestore.ts)

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


@router.post("/journey/next-step", response_model=NextStepResponse)
async def next_step(body: NextStepRequest, user: FirebaseUser = Depends(get_current_user)) -> NextStepResponse:
    """
    Stateless wizard step for a guided phase flow. The client resends every
    answer collected so far on each call; this looks up the next unanswered
    question for body.phase_id with no LLM call. Once every question has been
    answered it runs compute_readiness() once, persists the result to
    Firestore, advances the phase, and returns the summary.
    """
    questions = PHASE_QUESTIONS.get(body.phase_id)
    if questions is None:
        raise HTTPException(status_code=404, detail=f"Unknown phase_id: {body.phase_id!r}")

    next_question = next((q for q in questions if q["question_id"] not in body.answers), None)

    if next_question is not None:
        current = questions.index(next_question) + 1
        return NextStepResponse(
            done=False,
            question_id=next_question["question_id"],
            label=next_question["label"],
            helper=next_question["helper"],
            input_type=next_question["input_type"],
            placeholder=next_question["placeholder"],
            choices=next_question["choices"],
            progress={"current": current, "total": len(questions)},
            summary=None,
        )

    try:
        result = await compute_readiness(body.answers)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    try:
        await update_profile(user.uid, {
            "grossMonthlyIncome": body.answers.get("gross_monthly_income"),
            "monthlyDebts":       body.answers.get("monthly_debts"),
            "liquidSavings":      body.answers.get("liquid_savings"),
            "employmentStatus":   body.answers.get("employment_status"),
            "trueBudget":         result["true_budget"],
            "dti":                result["dti"],
            "estimatedPayment":   result["estimated_payment"],
            "readinessVerdict":   result["verdict"],
        })
    except Exception as e:
        logger.error(f"update_profile failed for {user.uid}: {e}", exc_info=True)
        # Do not raise — we still return the summary to the user

    try:
        await advance_phase(user.uid, READINESS_PHASE_NUM)
    except Exception as e:
        logger.error(f"advance_phase failed for {user.uid}: {e}", exc_info=True)
        # Do not raise — we still return the summary to the user

    try:
        await write_insight(user.uid, READINESS_PHASE_NUM, result["summary"])
    except Exception as e:
        logger.error(f"write_insight failed for {user.uid}: {e}", exc_info=True)
        # Do not raise — we still return the summary to the user

    return NextStepResponse(
        done=True,
        question_id=None,
        label=None,
        helper=None,
        input_type=None,
        placeholder=None,
        choices=None,
        progress={"current": len(questions), "total": len(questions)},
        summary=result,
    )