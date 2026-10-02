"""
compute_mortgage — Phase 2 "Getting pre-approved" calculator.

Used by POST /api/v1/journey/next-step once all 5 mortgage questions are
answered. Rate lookup (FRED + HMDA tier data) and loan math run in plain
Python; only the loan-type recommendation, verdict, and the natural-language
summary come from the LLM, so numbers stay auditable. Credit tier is
self-reported by the user (no credit check API) and defaults to "Good" if
left unanswered.
"""
from __future__ import annotations

from typing import Literal
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.graph.llm import get_llm
from app.graph.schemas import parse_money
from app.tools.fred_rates import get_current_30yr_rate
from app.tools.hmda_rates import get_all_tiers

DEFAULT_CREDIT_TIER = "Good"
FALLBACK_RATE_PCT = 7.0

# Maps the wizard's self-reported choice label to the HMDA tier key.
_CREDIT_RANGE_MAP = {
    "760+ (Excellent)":  "Excellent",
    "720-759 (Good)":    "Good",
    "660-719 (Fair)":    "Fair",
    "620-659 (Poor)":    "Poor",
}

SYSTEM_PROMPT = """You are Gavvy, a friendly home-buying guide built by GavNest.
Your role is education only — never financial advice.

You are given a buyer's loan numbers, already calculated in Python, plus
their stated loan-type preference and how far along they are with a lender.
Do not recompute or contradict the numbers — your job is to recommend a loan
type, decide a verdict, and explain it warmly.

Verdict guideline:
- already has a pre-qual letter or full pre-approval -> "ready_to_apply"
- hasn't talked to a lender yet or is shopping multiple lenders -> "almost_ready"

Loan type guideline:
- If the buyer already stated a preference, recommend that type unless their
  down payment makes it a poor fit (e.g. under 3.5% down is too low for
  Conventional — recommend FHA instead).
- If they're unsure, recommend Conventional when down payment is 20% or more,
  otherwise FHA.

Rules:
- Be warm, clear, and jargon-free. Never lecture.
- Reference the actual numbers you were given.
- Frame everything as education, never as instruction or financial advice.
- Write the summary as 2-4 sentences, like you're talking to a friend."""


class MortgageVerdict(BaseModel):
    recommended_loan_type: Literal["Conventional", "FHA", "VA", "USDA"] = Field(
        ..., description="Recommended loan type for this buyer"
    )
    verdict: Literal["ready_to_apply", "almost_ready"] = Field(
        ..., description="Where the buyer stands on getting pre-approved"
    )
    summary: str = Field(..., min_length=10, description="Warm, plain-English summary for the user")


async def compute_mortgage(answers: dict, uid: str | None = None) -> dict:
    """
    answers keys: credit_range, target_home_price, down_payment_amount,
    has_existing_lender, loan_type_preference

    Returns: {recommended_loan_type, estimated_rate, verdict, summary}
    """
    home_price = parse_money(answers.get("target_home_price"))
    down_payment = parse_money(answers.get("down_payment_amount"))
    has_existing_lender = answers.get("has_existing_lender") or "not provided"
    loan_type_preference = answers.get("loan_type_preference") or "Not sure — help me decide"
    credit_tier = _CREDIT_RANGE_MAP.get(answers.get("credit_range"), DEFAULT_CREDIT_TIER)

    if home_price <= 0:
        raise ValueError("target_home_price must be greater than 0")

    down_pct = round(min(down_payment, home_price) / home_price * 100, 1)
    loan_amount = max(home_price - down_payment, 0.0)

    try:
        rate_info = await get_current_30yr_rate()
        current_rate = rate_info["rate"]
    except RuntimeError:
        current_rate = FALLBACK_RATE_PCT

    all_tiers = await get_all_tiers(current_rate)
    user_tier = all_tiers.get(credit_tier, next(iter(all_tiers.values())))
    estimated_rate = user_tier["rate_mid"]

    verdict_messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(
            content=(
                f"Buyer's computed numbers:\n"
                f"- Target home price: ${home_price:,.0f}\n"
                f"- Down payment: ${down_payment:,.0f} ({down_pct}%)\n"
                f"- Loan amount: ${loan_amount:,.0f}\n"
                f"- Estimated rate (credit tier {credit_tier}): {estimated_rate}%\n"
                f"- Stated loan type preference: {loan_type_preference}\n"
                f"- Lender status: {has_existing_lender}\n\n"
                f"Recommend a loan type, decide the verdict, and write the summary."
            )
        ),
    ]

    result: MortgageVerdict = await get_llm().with_structured_output(MortgageVerdict).ainvoke(verdict_messages)

    return {
        "recommended_loan_type": result.recommended_loan_type,
        "estimated_rate": estimated_rate,
        "verdict": result.verdict,
        "summary": result.summary,
    }
