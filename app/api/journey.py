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
from app.config import READINESS_QUESTIONS, MORTGAGE_QUESTIONS

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


PHASE_QUESTIONS = {
    "readiness": READINESS_QUESTIONS,
    "mortgage": MORTGAGE_QUESTIONS
}

READINESS_PHASE_NUM = 1  # "readiness" is phase 1 in phases/data (see gavvy-web lib/firestore.ts)
MORTGAGE_PHASE_NUM = 2

PHASE_NUM_MAP = {
    "readiness": READINESS_PHASE_NUM,
    "mortgage":  MORTGAGE_PHASE_NUM,
}


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

    #Get the right summary function for this phase
    summary_fn = PHASE_SUMMARY_FN.get(body.phase_id)
    if not summary_fn:
        raise HTTPException(status_code=400, detail=f"No summary handler for: {body.phase_id!r}")

    try:
        result = await summary_fn(body.answers)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    #Get phase number for Firestore writes
    phase_num = PHASE_NUM_MAP.get(body.phase_id, 1)

    #Write profile fields
    try:
        fields_fn = PHASE_PROFILE_FIELDS.get(body.phase_id)
        if fields_fn:
            await update_profile(user.uid, fields_fn(body.answers, result))
    except Exception as e:
        logger.error(f"update_profile failed for {user.uid}: {e}", exc_info=True)

    #Advance phase
    try:
        await advance_phase(user.uid, phase_num)
    except Exception as e:
        logger.error(f"advance_phase failed for {user.uid}: {e}", exc_info=True)

    #Write insight
    try:
        await write_insight(user.uid, phase_num, result["summary"])
    except Exception as e:
        logger.error(f"write_insight failed for {user.uid}: {e}", exc_info=True)

    return NextStepResponse(
        done        = True,
        question_id = None,
        label       = None,
        helper      = None,
        input_type  = None,
        placeholder = None,
        choices     = None,
        progress    = {"current": len(questions), "total": len(questions)},
        summary     = result,
    )


async def compute_mortgage_summary(answers: dict) -> dict:
    """
    One LLM call at the end of Phase 2.
    Uses existing mortgage_agent logic to return guidance.
    """
    from app.graph.nodes.mortgage import compute_mortgage  # extract this (see Step 3)
    return await compute_mortgage(answers)


# Map phase_id → summary function
PHASE_SUMMARY_FN = {
    "readiness": compute_readiness,
    "mortgage":  compute_mortgage_summary,
}

# Map phase_id → Firestore fields to write after summary
PHASE_PROFILE_FIELDS = {
    "readiness": lambda answers, result: {
        "grossMonthlyIncome": answers.get("gross_monthly_income"),
        "monthlyDebts":       answers.get("monthly_debts"),
        "liquidSavings":      answers.get("liquid_savings"),
        "employmentStatus":   answers.get("employment_status"),
        "trueBudget":         result.get("true_budget"),
        "dti":                result.get("dti"),
        "estimatedPayment":   result.get("estimated_payment"),
        "readinessVerdict":   result.get("verdict"),
    },
    "mortgage": lambda answers, result: {
        "targetHomePrice":    answers.get("target_home_price"),
        "downPaymentAmount":  answers.get("down_payment_amount"),
        "hasExistingLender":  answers.get("has_existing_lender"),
        "loanTypePreference": answers.get("loan_type_preference"),
        "recommendedLoan":    result.get("recommended_loan_type"),
        "estimatedRate":      result.get("estimated_rate"),
        "mortgageVerdict":    result.get("verdict"),
    },
}